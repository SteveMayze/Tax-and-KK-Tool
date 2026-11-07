"""Phase 41 (ADR 0037): source references in the tax information summary. Synthetic data and files only.

Files are written under a temporary UPLOAD_DIR; the bytes are not real PDFs (the service reads bytes, never text).
"""
import datetime
import hashlib
import io
import re
import shutil
import tempfile
import zipfile
from decimal import Decimal as D
from html import unescape
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfReader

from core.models import ImportBatch, ImportRow, Payment, SourceDocument
from core.services import report_csv, report_sources, reports
from core.services.report_filter import ReportFilter

from .test_adviser_report import add

d = datetime.date
PDF_A, PDF_B, PDF_C = b'%PDF-1.4 EXAMPLE A', b'%PDF-1.4 EXAMPLE B', b'%PDF-1.4 EXAMPLE C'
sha = lambda b: hashlib.sha256(b).hexdigest()


class SourceBase(TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.override = override_settings(UPLOAD_DIR=self.tmp)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.client.force_login(get_user_model().objects.create_user('src', password='pw-for-tests-123'))
        self.n = 0

    def store(self, name, data):
        path = Path(self.tmp) / 'imports' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return f'imports/{name}'

    def batch(self, members, kind='pdf', removed=False, file_name='EXAMPLE statement.pdf'):
        """members: [(file name, bytes)]; one member = single PDF, several = zip named NNN-name."""
        self.n += 1
        if kind == 'csv':
            data, rel = b'a,b\n1,2\n', self.store(f'b{self.n}.csv', b'a,b\n1,2\n')
        elif len(members) == 1:
            data = members[0][1]
            rel = self.store(f'b{self.n}.pdf', data)
        else:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w') as z:
                for i, (name, raw) in enumerate(members, 1):
                    z.writestr(f'{i:03d}-{name}', raw)
            data = buf.getvalue()
            rel = self.store(f'b{self.n}.zip', data)
        b = ImportBatch.objects.create(kind=kind, sha256=sha(data), stored_path=rel, file_name=file_name,
                                       status=ImportBatch.Status.COMMITTED,
                                       original_removed_at=timezone.now() if removed else None)
        return b

    def pay(self, batch, shown, page=2, date=d(2026, 3, 1), org='EXAMPLE BANK', provenance=None, **kw):
        p = add('10', date, org, 'Interest', **kw)
        p.import_batch = batch
        p.save()
        self.n += 1
        ImportRow.objects.create(batch=batch, line_number=self.n, data={}, original={}, source_name=shown,
                                 provenance=provenance if provenance is not None else
                                 {'gross_amount': {'page': page, 'text': 'EXAMPLE LINE TEXT 4711'}}, created_payment=p)
        return p

    def srcs(self, *payments):
        return report_sources.resolve(Payment.objects.filter(pk__in=[p.pk for p in payments]).select_related('organisation'))

    def build(self, **kw):
        return reports.REPORTS['tax_summary'].build(2026, flt=ReportFilter(**kw) if kw else None)

    def table(self, rep, key):
        return {t.key: t for t in rep.tables}[key]


class SourceTests(SourceBase):
    def test_S1_single_pdf(self):
        b = self.batch([('EXAMPLE statement.pdf', PDF_A)])
        p = self.pay(b, 'EXAMPLE statement.pdf', page=3)
        r = self.srcs(p)
        self.assertEqual(r.per_payment[p.pk].text(), 'D01 p.3')
        self.assertEqual((r.documents[0].sha256, r.documents[0].state, r.documents[0].kind), (sha(PDF_A), 'stored', 'pdf'))

    def test_S2_zip_members_and_ambiguity(self):
        b = self.batch([('EXAMPLE one.pdf', PDF_A), ('EXAMPLE two.pdf', PDF_B), ('EXAMPLE acct 11111111.pdf', PDF_C),
                        ('EXAMPLE acct 22222222.pdf', PDF_A + b'2')])
        p1, p2 = self.pay(b, 'EXAMPLE one.pdf'), self.pay(b, 'EXAMPLE two.pdf', page=5)
        amb = self.pay(b, 'EXAMPLE acct ######.pdf')
        r = self.srcs(p1, p2, amb)
        self.assertEqual({r.documents[i].sha256 for i in range(2)}, {sha(PDF_A), sha(PDF_B)})
        self.assertEqual(r.per_payment[p1.pk].ref + r.per_payment[p2.pk].ref, 'D01D02')
        self.assertEqual(r.per_payment[p2.pk].page, 5)
        self.assertEqual(r.per_payment[amb.pk].text(), 'none: ambiguous (two files with the same shown name)')

    def test_S3_csv(self):
        b = self.batch([], kind='csv', file_name='my own file.csv')
        p = self.pay(b, '')
        r = self.srcs(p)
        self.assertEqual((r.documents[0].kind, r.per_payment[p.pk].ref), ('csv', 'D01'))
        rep = self.build()
        self.assertEqual(self.table(rep, 'sources').rows[0]['kind'], 'CSV file (your own import file)')

    def test_S4_hand_entered(self):
        p = add('10', d(2026, 3, 1), 'EXAMPLE BANK', 'Interest')
        r = self.srcs(p)
        self.assertEqual(r.per_payment[p.pk].text(), 'none: entered by hand')
        self.assertIn('1 of 1 payment(s) have no source document (entered by hand: 1)', dict(self.build().basis)['Source documents'])

    def test_S5_removed_and_missing(self):
        gone = self.batch([('EXAMPLE gone.pdf', PDF_A)], removed=True, file_name='EXAMPLE gone.pdf')
        lost = self.batch([('EXAMPLE lost.pdf', PDF_B)], file_name='EXAMPLE lost.pdf')
        Path(self.tmp, lost.stored_path).unlink()
        zipgone = self.batch([('EXAMPLE z1.pdf', PDF_A), ('EXAMPLE z2.pdf', PDF_B)], removed=True)
        p1, p2, p3 = self.pay(gone, 'EXAMPLE gone.pdf'), self.pay(lost, 'EXAMPLE lost.pdf'), self.pay(zipgone, 'EXAMPLE z1.pdf')
        r = self.srcs(p1, p2, p3)
        states = {d.name: d.state for d in r.documents}
        self.assertTrue(states['EXAMPLE gone.pdf'].startswith('removed on '))
        self.assertEqual(states['EXAMPLE lost.pdf'], 'not found')
        self.assertTrue(states['EXAMPLE z1.pdf'].startswith('removed on '))
        self.assertTrue(all(v.ref for v in r.per_payment.values()))
        self.assertEqual(self.get_page().status_code, 200)

    def test_S6_batch_deleted(self):
        b = self.batch([('EXAMPLE x.pdf', PDF_A)])
        p = self.pay(b, 'EXAMPLE x.pdf')
        doc = SourceDocument.objects.create(file_name='x')
        Payment.objects.filter(pk=p.pk).update(source_document=doc)
        b.delete()
        p.refresh_from_db()
        self.assertIsNone(p.import_batch_id)
        self.assertEqual(self.srcs(p).per_payment[p.pk].text(), 'none: batch deleted')

    def test_S7_withholding_settled_across_statements(self):
        b = self.batch([('EXAMPLE f1.pdf', PDF_A), ('EXAMPLE f2.pdf', PDF_B)])
        multi = {'gross_amount': {'page': 1, 'text': 'x'}, 'withholding_tax': {'page': 1, 'text': 'Tax: a / Reversal: b'}}
        p = self.pay(b, 'EXAMPLE f1.pdf', provenance=multi)
        plain = self.pay(b, 'EXAMPLE f2.pdf')
        rep = self.build()
        rows = {r['source'] for r in self.table(rep, 'payments').rows}
        self.assertIn('D01 p.1 *', rows)
        self.assertIn('D02 p.2', rows)
        self.assertIn('settled from another statement of the same upload', self.table(rep, 'payments').note)
        self.assertTrue(self.srcs(plain).any_settled_elsewhere is False)

    def test_S8_shared_documents(self):
        b1 = self.batch([('EXAMPLE s.pdf', PDF_A)])
        b2 = self.batch([('EXAMPLE s.pdf', PDF_A)])
        p1, p2, p3 = self.pay(b1, 'EXAMPLE s.pdf'), self.pay(b1, 'EXAMPLE s.pdf', page=4), self.pay(b2, 'EXAMPLE s.pdf')
        r = self.srcs(p1, p2, p3)
        self.assertEqual(len(r.documents), 1)
        self.assertEqual({v.ref for v in r.per_payment.values()}, {'D01'})
        self.assertEqual(r.documents[0].payments, 3)

    def test_S9_deterministic_numbering_and_index_follows_selection(self):
        b = self.batch([('EXAMPLE late.pdf', PDF_A), ('EXAMPLE early.pdf', PDF_B)])
        self.pay(b, 'EXAMPLE late.pdf', date=d(2026, 9, 1), org='EXAMPLE LATE ORG')
        self.pay(b, 'EXAMPLE early.pdf', date=d(2026, 2, 1), org='EXAMPLE EARLY ORG')
        first = [(r['ref'], r['name']) for r in self.table(self.build(), 'sources').rows]
        self.assertEqual(first, [('D01', 'EXAMPLE early.pdf'), ('D02', 'EXAMPLE late.pdf')])
        self.assertEqual(first, [(r['ref'], r['name']) for r in self.table(self.build(), 'sources').rows])
        from core.models import Organisation
        only_late = self.build(organisation_ids=(Organisation.objects.get(name='EXAMPLE LATE ORG').pk,))
        self.assertEqual([(r['ref'], r['name']) for r in self.table(only_late, 'sources').rows], [('D01', 'EXAMPLE late.pdf')])

    def get_page(self, **q):
        return self.client.get(reverse('report_view', args=['tax_summary']), {'year': '2026', **q})

    def test_S10_privacy(self):
        b = self.batch([('EXAMPLE acct 123456789.pdf', PDF_A), ('EXAMPLE other.pdf', PDF_B)], file_name='EXAMPLE 2 PDF statements')
        self.pay(b, 'EXAMPLE acct ######.pdf', provenance={'gross_amount': {'page': 2, 'text': 'SECRET LINE TEXT'}})
        csv_b = self.batch([], kind='csv', file_name='own 987654321 file.csv')
        self.pay(csv_b, '')
        outputs = [unescape(self.get_page().content.decode()),
                   self.client.get(reverse('report_csv', args=['tax_summary']), {'year': '2026'}).content.decode(),
                   '\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(
                       self.client.get(reverse('report_pdf', args=['tax_summary']), {'year': '2026'}).content)).pages)]
        for text in outputs:
            self.assertNotIn('123456789', text)
            self.assertNotIn('987654321', text)
            self.assertNotIn('SECRET LINE TEXT', text)
            self.assertNotIn(self.tmp, text)
            self.assertNotIn('b1.zip', text)
            self.assertNotIn('b2.pdf', text)
        self.assertIn('EXAMPLE acct ######.pdf', outputs[0])
        self.assertIn('######', outputs[0])

    def test_S11_totals_unchanged_by_sources(self):
        b = self.batch([('EXAMPLE t.pdf', PDF_A)])
        self.pay(b, 'EXAMPLE t.pdf')
        add('5', d(2026, 4, 1), 'EXAMPLE BANK', 'Interest')
        rep = self.build()
        totals = [self.table(rep, k).totals['gross_eur'] for k in ('category_currency', 'organisation', 'payments')]
        self.assertEqual(totals, [D(15)] * 3)

    def test_csv_carries_references_and_full_hash_html_pdf_shorten(self):
        b = self.batch([('EXAMPLE h.pdf', PDF_A)])
        self.pay(b, 'EXAMPLE h.pdf', page=7)
        text = self.client.get(reverse('report_csv', args=['tax_summary']), {'year': '2026'}).content.decode()
        self.assertIn('D01 p.7', text)
        self.assertIn(sha(PDF_A), text)
        html = self.get_page().content.decode()
        self.assertIn(sha(PDF_A)[:12], html)
        self.assertNotIn(sha(PDF_A), html)
        self.assertIn('Documents</th>', html)
        self.assertEqual(report_csv.CSV_FORMAT_VERSION, '3')

    def test_read_only(self):
        b = self.batch([('EXAMPLE r.pdf', PDF_A), ('EXAMPLE q.pdf', PDF_B)])
        self.pay(b, 'EXAMPLE r.pdf')
        files = {p: p.read_bytes() for p in Path(self.tmp).rglob('*') if p.is_file()}
        before = (Payment.objects.count(), ImportBatch.objects.count(), list(ImportBatch.objects.values_list('sha256', 'stored_path')))
        self.get_page()
        self.assertEqual(files, {p: p.read_bytes() for p in Path(self.tmp).rglob('*') if p.is_file()})
        self.assertEqual(before, (Payment.objects.count(), ImportBatch.objects.count(), list(ImportBatch.objects.values_list('sha256', 'stored_path'))))
