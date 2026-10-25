"""PDF export of reports (Phase 33, ADR 0034). Inspected with pypdf; the dataset is the synthetic one of test_reports."""
import io

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from pypdf import PdfReader

from core.models import Payment
from core.services import report_csv, reports
from core.services.policies.sbk import PolicyUnavailable

from .test_helpers import make_payment
from .test_reports import BASE_KEYS, build_dataset, d

ALL_KEYS = BASE_KEYS + ['cross', 'tax_summary', 'tax_checks', 'sbk']
EN_NOTICE = 'must not be used on its own'
DE_NOTICE = 'nicht für sich allein verwendet'


def read(response):
    return PdfReader(io.BytesIO(response.content))


def text(reader):
    return '\n'.join(p.extract_text() for p in reader.pages)


class PdfBase(TestCase):
    def setUp(self):
        self.p = build_dataset()
        self.client.force_login(get_user_model().objects.create_user('t', password='pw-for-tests-123'))

    def pdf(self, key, query='?year=2024'):
        return self.client.get(reverse('report_pdf', args=[key]) + query)

    def set_language(self, code):
        self.client.post(reverse('set_language'), {'language': code, 'next': reverse('report_index')})


class PdfRouteTests(PdfBase):
    def test_every_report_is_a_landscape_a4_pdf(self):
        for key in ALL_KEYS:
            r = self.pdf(key)
            if r.status_code == 302:     # a policy report with no policy for the year: same message as the CSV route
                self.assertIn(key, ('sbk', 'tax_checks'), key)
                continue
            self.assertEqual(r.status_code, 200, key)
            self.assertEqual(r['Content-Type'], 'application/pdf')
            self.assertEqual(r['Content-Disposition'], f'attachment; filename="report-{key}-2024.pdf"')
            self.assertEqual(r['Cache-Control'], 'no-store')
            self.assertEqual(r['X-Content-Type-Options'], 'nosniff')
            self.assertTrue(r.content.startswith(b'%PDF'), key)
            box = read(r).pages[0].mediabox
            self.assertAlmostEqual(float(box.width), 841.89, delta=0.1)
            self.assertAlmostEqual(float(box.height), 595.28, delta=0.1)

    def test_login_required_and_get_only(self):
        self.client.logout()
        for key in ALL_KEYS:
            r = self.pdf(key)
            self.assertEqual(r.status_code, 302)
            self.assertTrue(r.url.startswith(reverse('login')), key)
        self.client.force_login(get_user_model().objects.get(username='t'))
        self.assertEqual(self.client.post(reverse('report_pdf', args=['annual'])).status_code, 405)
        self.assertEqual(self.pdf('nope').status_code, 404)

    def test_bad_parameters_behave_like_csv(self):
        for q in ('?year=1999', '?year=abc', '?year=2024&organisation=x', '?year=2024&category=99999'):
            a = self.client.get(reverse('report_pdf', args=['annual']) + q, follow=True)
            b = self.client.get(reverse('report_csv', args=['annual']) + q, follow=True)
            self.assertEqual(a.redirect_chain, b.redirect_chain, q)
            self.assertEqual([str(m) for m in a.context['messages']], [str(m) for m in b.context['messages']], q)
        a = self.client.get(reverse('report_pdf', args=['monthly']) + '?year=all', follow=True)
        self.assertRedirects(a, reverse('report_index'))

    def test_filtered_file_name_and_basis(self):
        org = self.p[1].organisation_id
        r = self.pdf('payments', f'?year=2024&organisation={org}')
        self.assertEqual(r['Content-Disposition'], 'attachment; filename="report-payments-2024-filtered.pdf"')
        self.assertIn('Filter', text(read(r)))
        self.assertEqual(self.pdf('annual', '?year=all')['Content-Disposition'], 'attachment; filename="report-annual-all.pdf"')
        # Not applied to whole-person reports: the name does not claim a filter
        r = self.pdf('tax_checks', f'?year=2024&organisation={org}')
        if r.status_code == 200:
            self.assertNotIn('filtered', r['Content-Disposition'])

    def test_content_matches_the_report(self):
        reader = read(self.pdf('organisation'))
        body = text(reader)
        rep = reports.REPORTS['organisation'].build(2024)
        self.assertIn(rep.title, body)
        for label, _t in rep.basis:
            self.assertIn(str(label).split()[0], body)
        for r in rep.rows:
            self.assertIn(r['organisation'] if 'organisation' in r else str(list(r.values())[0]), body)
        self.assertIn('Page 1 of 1', body)

    def test_empty_result(self):
        Payment.objects.exclude(kind='normal').delete()
        Payment.objects.all().delete()
        r = self.pdf('payments', '?year=all')
        self.assertEqual(r.status_code, 200)
        self.assertIn('No data for this period', text(read(r)))

    def test_many_rows_split_across_pages_with_repeated_header_and_page_numbers(self):
        for i in range(150):
            make_payment(gross='10', date=d(2024, 5, 1 + i % 28), org='Bulk Co', comment=f'bulk-{i}').save()
        reader = read(self.pdf('payments'))
        self.assertGreater(len(reader.pages), 2)
        total = len(reader.pages)
        for n, page in enumerate(reader.pages, 1):
            t = page.extract_text()
            self.assertIn(f'Page {n} of {total}', t)
            self.assertIn('General financial summary, not an official assessment or tax calculation', t)
            if n > 1:
                self.assertIn('Organisation', t)      # header row repeats

    def test_wide_tables_fit(self):
        for key in ('cross', 'payments'):
            reader = read(self.pdf(key))
            for page in reader.pages:
                self.assertTrue(page.extract_text())
            self.assertLess(len(reader.pages), 6, key)

    def test_german(self):
        self.set_language('de')
        r = self.pdf('tax_summary')
        self.assertEqual(r.status_code, 200)
        body = text(read(r))
        self.assertIn(DE_NOTICE, body)
        for term in ('Name', 'Ort', 'Datum', 'Unterschrift', 'Seite 1 von'):
            self.assertIn(term, body)
        self.assertNotIn(EN_NOTICE, body)
        # file name is language independent
        self.assertEqual(r['Content-Disposition'], 'attachment; filename="report-tax_summary-2024.pdf"')

    def test_outputs_unchanged_and_nothing_stored(self):
        import tempfile
        from pathlib import Path
        from django.test import override_settings
        before = self.client.get(reverse('report_csv', args=['annual']) + '?year=2024').content
        with tempfile.TemporaryDirectory() as tmp, override_settings(UPLOAD_DIR=tmp):
            for key in BASE_KEYS:
                self.pdf(key)
            self.assertEqual(list(Path(tmp).rglob('*')), [])
        self.assertEqual(self.client.get(reverse('report_csv', args=['annual']) + '?year=2024').content, before)
        self.assertEqual(report_csv.CSV_FORMAT_VERSION, '2')

    def test_buttons(self):
        self.assertContains(self.client.get(reverse('report_view', args=['annual'])), reverse('report_pdf', args=['annual']))
        r = self.client.get(reverse('report_index'))
        for key in ALL_KEYS:
            self.assertContains(r, reverse('report_pdf', args=[key]))


class TaxSummarySignatureTests(PdfBase):
    def fields(self, reader):
        return {k: v for k, v in (reader.get_fields() or {}).items()}

    def test_disclaimer_labels_and_fillable_fields(self):
        reader = read(self.pdf('tax_summary'))
        body = text(reader)
        self.assertEqual(body.count(EN_NOTICE), 2)                   # near the title and above the signature block
        for s in ('Steuerbescheid', 'Steuererklärung', 'gross income', 'not a tax calculation',
                  'Name', 'Place (Ort)', 'Date (Datum)', 'Signature (Unterschrift)'):
            self.assertIn(s, body)
        fields = self.fields(reader)
        self.assertEqual(set(fields), {'name', 'place', 'date', 'signature'})
        self.assertEqual(fields['signature'].get('/FT'), '/Sig')
        self.assertEqual(fields['place'].get('/FT'), '/Tx')
        self.assertEqual(fields['date'].get('/FT'), '/Tx')
        for name in ('name', 'place', 'date'):                      # nothing pre-filled
            self.assertIn(fields[name].get('/V'), (None, ''))

    def test_block_sits_on_the_last_page_with_the_second_notice(self):
        for i in range(120):
            make_payment(gross='10', date=d(2024, 5, 1 + i % 28), org=f'Org {i:03d}', category='Salary').save()
        reader = read(self.pdf('tax_summary'))
        last = reader.pages[-1].extract_text()
        self.assertGreater(len(reader.pages), 1)
        self.assertIn(EN_NOTICE, last)
        self.assertIn('Signature (Unterschrift)', last)
        self.assertNotIn('Signature (Unterschrift)', '\n'.join(p.extract_text() for p in reader.pages[:-1]))
        annots = reader.pages[-1].get('/Annots')
        self.assertEqual(len(annots), 4)
        for p in reader.pages[:-1]:
            self.assertFalse(p.get('/Annots'))

    def widgets(self, reader):
        """name -> (page index, rect) in the order of the page's annotations."""
        out = {}
        for i, page in enumerate(reader.pages):
            for a in page.get('/Annots') or []:
                a = a.get_object()
                out[a['/T']] = (i, [float(v) for v in a['/Rect']], len(out))
        return out

    def test_layout_one_column_aligned(self):
        from reportlab.pdfbase.pdfmetrics import stringWidth
        from core.services import report_pdf
        for language in ('en', 'de'):
            self.set_language(language)
            reader = read(self.pdf('tax_summary'))
            w = self.widgets(reader)
            self.assertEqual(sorted(w, key=lambda k: w[k][2]), ['name', 'place', 'date', 'signature'], language)  # tab order
            self.assertEqual(len({v[0] for v in w.values()}), 1, language)                      # one page
            r = {k: v[1] for k, v in w.items()}                                                 # x0, y0, x1, y1
            width = {k: v[2] - v[0] for k, v in r.items()}
            usable = float(reader.pages[0].mediabox.width) - 2 * report_pdf.MARGIN
            self.assertLessEqual(width['name'], usable / 3 + 0.5)
            self.assertAlmostEqual(width['name'], width['signature'], delta=0.1)
            self.assertAlmostEqual(width['place'], width['date'], delta=0.1)
            self.assertAlmostEqual(width['place'] + report_pdf.GAP + width['date'], width['name'], delta=0.1)
            # shared left and right edges
            self.assertAlmostEqual(r['name'][0], r['place'][0], delta=0.1)
            self.assertAlmostEqual(r['name'][0], r['signature'][0], delta=0.1)
            self.assertAlmostEqual(r['date'][2], r['name'][2], delta=0.1)
            self.assertAlmostEqual(r['signature'][2], r['name'][2], delta=0.1)
            # rows from top to bottom: Name, Place/Date, Signature
            self.assertAlmostEqual(r['place'][1], r['date'][1], delta=0.1)
            self.assertLess(r['place'][3], r['name'][1])
            self.assertLess(r['signature'][3], r['place'][1])
            self.assertGreaterEqual(r['signature'][3] - r['signature'][1], 12 / 25.4 * 72)      # tall enough to sign in
            for k in ('name', 'place', 'date'):
                self.assertLess(r[k][3] - r[k][1], 12 / 25.4 * 72)
            self.assertGreater(min(v[1] for v in r.values()), 14 / 25.4 * 72)                   # above the page footer
            # typical values fit the narrow fields at the field font size
            for k, sample in (('place', 'Frankfurt am Main'), ('date', '25.10.2026')):
                self.assertLess(stringWidth(sample, report_pdf.FONT, report_pdf.FIELD_FONT), width[k] - 4, k)

    def test_other_reports_have_no_signature_block(self):
        for key in BASE_KEYS + ['cross']:
            reader = read(self.pdf(key))
            body = text(reader)
            self.assertNotIn('Unterschrift', body, key)
            self.assertNotIn(EN_NOTICE, body, key)
            self.assertFalse(reader.get_fields(), key)
            self.assertIn('not an official assessment or tax calculation', body, key)

    def test_no_personal_data_and_empty_year(self):
        reader = read(self.pdf('tax_summary', '?year=2023'))
        self.assertEqual(reader.metadata.get('/Author') or '', '')
