"""Phase 42 (ADR 0038): the report package (ZIP with the report PDF, the original statements, index.csv, README.txt).
Synthetic data and files only (see test_report_sources)."""
import csv
import hashlib
import io
import zipfile
from pathlib import Path

from django.conf import settings
from django.test import override_settings
from django.urls import reverse
from pypdf import PdfReader

from core.models import ImportBatch, Organisation, Payment
from core.services import report_package

from .test_adviser_report import add
from .test_report_sources import PDF_A, PDF_B, PDF_C, SourceBase, d, sha


class PackageBase(SourceBase):
    def setUp(self):
        super().setUp()
        self.b1 = self.batch([('EXAMPLE one.pdf', PDF_A)], file_name='EXAMPLE one.pdf')
        self.bz = self.batch([('EXAMPLE two.pdf', PDF_B), ('EXAMPLE three.pdf', PDF_C)])
        self.p1 = self.pay(self.b1, 'EXAMPLE one.pdf', org='EXAMPLE ONE ORG', date=d(2026, 1, 5))
        self.p2 = self.pay(self.bz, 'EXAMPLE two.pdf', org='EXAMPLE TWO ORG', date=d(2026, 2, 5), page=4)
        self.p3 = self.pay(self.bz, 'EXAMPLE three.pdf', org='EXAMPLE TWO ORG', date=d(2026, 3, 5))

    def url(self, name='report_package_zip', **q):
        return reverse(name, args=['tax_summary']) + '?' + '&'.join(f'{k}={v}' for k, v in {'year': '2026', **q}.items())

    def package(self, **q):
        r = self.client.get(self.url(**q))
        self.assertEqual(r.status_code, 200)
        data = b''.join(r.streaming_content)
        return r, zipfile.ZipFile(io.BytesIO(data))

    def index(self, z):
        return list(csv.DictReader(io.StringIO(z.read('index.csv').decode())))

    def uploads(self):
        return {p: p.read_bytes() for p in Path(self.tmp).rglob('*') if p.is_file()}


class PackageTests(PackageBase):
    def test_K1_contents_and_byte_identity(self):
        r, z = self.package()
        names = z.namelist()
        self.assertIn('report-tax_summary-2026.pdf', names)
        self.assertIn('index.csv', names)
        self.assertIn('README.txt', names)
        sources = {n: z.read(n) for n in names if n.startswith('sources/')}
        self.assertEqual(sorted(sha(b) for b in sources.values()), sorted(sha(x) for x in (PDF_A, PDF_B, PDF_C)))   # single PDF and zip members
        self.assertEqual(len(sources), 3)
        rows = self.index(z)
        self.assertEqual(sorted(r['SHA-256'] for r in rows), sorted(sha(x) for x in (PDF_A, PDF_B, PDF_C)))
        for row in rows:
            self.assertEqual(sha(z.read(row['File name in the package'])), row['SHA-256'])
            self.assertEqual(row['State'], 'stored')
        self.assertEqual(r['Content-Type'], 'application/zip')
        self.assertEqual(r['Content-Disposition'], 'attachment; filename="report-tax_summary-2026-package.zip"')

    def test_K2_hash_mismatch(self):
        Path(self.tmp, self.b1.stored_path).write_bytes(PDF_A + b' tampered')
        page = self.client.get(self.url('report_package')).content.decode()
        self.assertIn('changed on disk, not included', page)
        r, z = self.package()
        self.assertFalse(any(sha(PDF_A) == sha(z.read(n)) for n in z.namelist() if n.startswith('sources/')))
        self.assertEqual(len([n for n in z.namelist() if n.startswith('sources/')]), 2)
        changed = [row for row in self.index(z) if row['State'].startswith('changed')]
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0]['File name in the package'], '')

    def test_K2_a_changed_member_of_a_stored_zip_is_caught(self):
        path = Path(self.tmp, self.bz.stored_path)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as w:
            w.writestr('001-EXAMPLE two.pdf', PDF_B + b'x')
            w.writestr('002-EXAMPLE three.pdf', PDF_C)
        path.write_bytes(buf.getvalue())
        r, z = self.package()
        self.assertEqual(sum(1 for row in self.index(z) if row['State'].startswith('changed')), 2)   # whole stored file no longer matches
        self.assertEqual(len([n for n in z.namelist() if n.startswith('sources/')]), 1)

    def test_K3_missing_or_removed_original(self):
        Path(self.tmp, self.b1.stored_path).unlink()
        ImportBatch.objects.filter(pk=self.bz.pk).update(original_removed_at=self.bz.created_at)
        page = self.client.get(self.url('report_package')).content.decode()
        self.assertIn('not found', page)
        self.assertEqual(self.client.get(self.url()).status_code, 302)          # nothing left to package
        add('1', d(2026, 5, 5), 'EXAMPLE X', 'Interest')
        b3 = self.batch([('EXAMPLE four.pdf', PDF_A + b'4')], file_name='EXAMPLE four.pdf')
        self.pay(b3, 'EXAMPLE four.pdf')
        r, z = self.package()
        states = {row['Reference']: row['State'] for row in self.index(z)}
        self.assertEqual(len(states), 4)
        self.assertEqual(sorted(s.split(' ')[0] for s in states.values()), ['not', 'removed', 'removed', 'stored'])

    def test_K4_filter_applied_and_pdf_equals_the_route(self):
        org = Organisation.objects.get(name='EXAMPLE ONE ORG').pk
        r, z = self.package(organisation=org)
        self.assertEqual(len([n for n in z.namelist() if n.startswith('sources/')]), 1)
        self.assertEqual(self.index(z)[0]['SHA-256'], sha(PDF_A))
        self.assertEqual(r['Content-Disposition'], 'attachment; filename="report-tax_summary-2026-filtered-package.zip"')
        route = self.client.get(reverse('report_pdf', args=['tax_summary']) + f'?year=2026&organisation={org}')
        inside = z.read('report-tax_summary-2026-filtered.pdf')
        text = lambda b: '\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(b)).pages)
        self.assertEqual(text(inside), text(route.content))

    def test_K5_safe_names(self):
        hostile = ['../../etc/passwd', 'a/b\\c', 'x\x00y\x1b[31m', 'Ä' * 200, '..', '...pdf', '', 'name with  spaces and ######.pdf']
        seen = set()
        for i, name in enumerate(hostile, 1):
            m = report_package.member_name(f'D{i:02d}', name)
            self.assertRegex(m, r'^sources/D\d\d_[A-Za-z0-9._# _-]*\.pdf$')
            self.assertNotIn('..', m.split('/', 1)[1].replace('...', ''))
            self.assertEqual(m.count('/'), 1)
            self.assertLessEqual(len(m), 100)
            seen.add(m)
        self.assertEqual(len(seen), len(hostile))                               # the reference keeps them apart

    def test_K6_size_limit_and_temp_file(self):
        with override_settings(REPORT_PACKAGE_MAX_MB=0):
            page = self.client.get(self.url('report_package')).content.decode()
            self.assertIn('larger than the limit of 0 MB', page)
            self.assertNotIn('Download package', page)
            self.assertIn('Report PDF only', page)
            r = self.client.get(self.url())
            self.assertEqual(r.status_code, 302)
        from unittest import mock
        created, real = [], report_package.tempfile.TemporaryFile

        def spy():
            f = real()
            created.append(f)
            return f
        with mock.patch.object(report_package.tempfile, 'TemporaryFile', spy):
            r = self.client.get(self.url())
            b''.join(r.streaming_content)
            r.close()
            r2 = self.client.get(self.url())
            r2.close()                                                          # interrupted: never read
        self.assertEqual(len(created), 2)
        self.assertTrue(all(f.closed for f in created))                        # anonymous temp files: gone once closed

    def test_K6_a_failing_build_closes_the_temp_file(self):
        from unittest import mock
        from core.services import report_sources
        sources = report_sources.resolve(Payment.objects.select_related('organisation'))
        summary = report_package.inspect(sources)
        created, real = [], report_package.tempfile.TemporaryFile

        def spy():
            f = real()
            created.append(f)
            return f
        with mock.patch.object(report_package.tempfile, 'TemporaryFile', spy), \
                mock.patch.object(report_package, '_open', return_value=None):
            with self.assertRaises(OSError):
                report_package.build(summary, b'%PDF', 'r.pdf', sources)
        self.assertTrue(created and all(f.closed for f in created))

    def test_K7_nothing_to_package(self):
        Payment.objects.all().delete()
        add('1', d(2026, 5, 5), 'EXAMPLE X', 'Interest')
        page = self.client.get(self.url('report_package')).content.decode()
        self.assertIn('nothing to package', page)
        self.assertNotIn('Download package', page)
        self.assertIn('Report PDF only', page)
        r = self.client.get(self.url())
        self.assertEqual(r.status_code, 302)
        self.assertNotEqual(r.get('Content-Type'), 'application/zip')

    def test_K8_confirmation_page(self):
        Path(self.tmp, self.b1.stored_path).unlink()
        page = self.client.get(self.url('report_package')).content.decode()
        for needle in ('Statements included', '>2<', 'Not included', 'account numbers and other personal data', 'no filter',
                       'Download package', 'Report PDF only'):
            self.assertIn(needle, page)
        self.assertNotIn(self.tmp, page)
        self.assertNotIn('EXAMPLE LINE TEXT', page)
        org = Organisation.objects.get(name='EXAMPLE TWO ORG').pk
        self.assertIn('EXAMPLE TWO ORG', self.client.get(self.url('report_package', organisation=org)).content.decode())

    def test_K9_read_only(self):
        before = (self.uploads(), Payment.objects.count(), ImportBatch.objects.count(),
                  list(ImportBatch.objects.values_list('sha256', 'stored_path', 'original_removed_at')))
        self.package()
        self.client.get(self.url('report_package'))
        self.assertEqual(before, (self.uploads(), Payment.objects.count(), ImportBatch.objects.count(),
                                  list(ImportBatch.objects.values_list('sha256', 'stored_path', 'original_removed_at'))))

    def test_K10_language(self):
        self.client.post(reverse('set_language'), {'language': 'de', 'next': '/'})
        page = self.client.get(self.url('report_package')).content.decode()
        self.assertIn('Personenbezogene Daten', page)
        r, z = self.package()
        self.assertIn('keine Steuerberechnung', z.read('README.txt').decode())
        self.assertEqual(list(self.index(z)[0])[:2], ['Reference', 'File name in the package'])
        text = '\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(z.read('report-tax_summary-2026.pdf'))).pages)
        self.assertIn('Wichtiger Hinweis', text)
        self.client.post(reverse('set_language'), {'language': 'en', 'next': '/'})
        r, z = self.package()
        self.assertIn('not a tax calculation', z.read('README.txt').decode())

    def test_K11_basics(self):
        for name in ('report_package', 'report_package_zip'):
            self.assertEqual(self.client.post(self.url(name)).status_code, 405)
            self.assertEqual(self.client.get(reverse(name, args=['annual']) + '?year=2026').status_code, 404)
        r = self.client.get(self.url())
        self.assertEqual((r['Cache-Control'], r['X-Content-Type-Options']), ('no-store', 'nosniff'))
        self.assertTrue(r['Content-Disposition'].startswith('attachment'))
        self.client.logout()
        for name in ('report_package', 'report_package_zip'):
            r = self.client.get(self.url(name))
            self.assertEqual(r.status_code, 302)
            self.assertIn('login', r['Location'])

    def test_report_page_has_the_button_only_for_the_tax_summary(self):
        self.assertIn('PDF with source documents', self.client.get(reverse('report_view', args=['tax_summary']), {'year': '2026'}).content.decode())
        self.assertNotIn('PDF with source documents', self.client.get(reverse('report_view', args=['annual']), {'year': '2026'}).content.decode())

    def test_bad_filter_in_the_package_route_is_the_usual_error(self):
        r = self.client.get(self.url(currency='XX1'), follow=True)
        self.assertRedirects(r, reverse('report_index'))
        self.assertIn('Unknown currency', r.content.decode())
