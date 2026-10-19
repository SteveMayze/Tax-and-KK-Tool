"""Phase 14: PDF statements read into the import staging. Synthetic PDFs only; the figures below were worked out by hand.

The real statements the owner supplied live in the git-ignored local/samples; one optional test reads them when they
exist (never printing or asserting private amounts)."""
import hashlib
import io
import shutil
import tempfile
import zipfile
from decimal import Decimal as D
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from core.models import ImportBatch, ImportRow, Organisation, Payment
from core.services import dividend_statements as ds
from core.services import imports as svc
from core.services import pdf_imports, pdf_text
from core.services.rates import FakeRateProvider

from .test_pdf_support import (
    ACCEPTED, BONUS_SHARE_PLAN, DISAGREEING_NET, INCONSISTENT, MUFG_STYLE, NO_PAYMENT_DATE, REINVESTED, SCHEME_PAYMENT,
    UNKNOWN_LAYOUT, make_pdf)

import datetime

PROVIDER = FakeRateProvider({('AUD', datetime.date(2025, 5, 12)): D('0.6')})


def parsed(lines):
    return ds.parse(pdf_text.extract_pages(make_pdf([lines])))


class ExtractionTests(SimpleTestCase):
    def test_every_layout_gives_the_hand_worked_figures(self):
        for name, (lines, expected) in ACCEPTED.items():
            d = parsed(lines)
            got = (d.code, d.payment_date, d.record_date, d.gross, d.net, d.withholding, d.reinvested)
            self.assertEqual(got, expected, name)

    def test_gross_equals_net_plus_withholding_always(self):
        for name, (lines, _e) in ACCEPTED.items():
            d = parsed(lines)
            self.assertEqual(d.gross, d.net + d.withholding, name)

    def test_withholding_is_only_accepted_when_a_line_explains_it(self):
        d = parsed(ACCEPTED['withholding'][0])
        self.assertEqual((d.gross, d.withholding, d.net), (D('100.00'), D('15.00'), D('85.00')))
        with self.assertRaisesRegex(ds.UnsupportedStatement, 'no withholding-tax line explains'):
            parsed(INCONSISTENT)

    def test_every_value_comes_with_its_source_line(self):
        d = parsed(MUFG_STYLE)
        self.assertEqual(set(d.evidence), {'payment_date', 'organisation', 'gross_amount', 'net_amount', 'withholding_tax'})
        page, text = d.evidence['net_amount']
        self.assertEqual((page, text), (1, 'Net Amount AUD 50.00'))
        self.assertEqual(d.evidence['payment_date'], (1, 'Payment Date: 12 May 2025'))

    def test_statements_that_are_not_dividends_are_refused_with_a_reason(self):
        for lines, text in ((SCHEME_PAYMENT, 'scheme of arrangement'), (BONUS_SHARE_PLAN, 'bonus share plan'),
                            (UNKNOWN_LAYOUT, 'not recognised as a dividend')):
            with self.assertRaisesRegex(ds.UnsupportedStatement, text):
                parsed(lines)

    def test_ambiguous_or_missing_figures_are_refused_never_guessed(self):
        with self.assertRaisesRegex(ds.UnsupportedStatement, 'Several different amounts'):
            parsed(DISAGREEING_NET)
        with self.assertRaisesRegex(ds.UnsupportedStatement, 'payment date'):
            parsed(NO_PAYMENT_DATE)

    def test_franking_details_are_not_read(self):
        self.assertFalse(hasattr(parsed(MUFG_STYLE), 'franking_credit'))

    def test_pdf_problems_have_clear_messages(self):
        with self.assertRaisesRegex(pdf_text.PdfError, 'not a PDF'):
            pdf_text.extract_pages(b'hello')
        with self.assertRaisesRegex(pdf_text.PdfError, 'no text layer'):
            pdf_text.extract_pages(make_pdf([[]]))
        with self.assertRaisesRegex(pdf_text.PdfError, 'could not be read'):
            pdf_text.extract_pages(b'%PDF-1.4\nthis is damaged')
        with self.assertRaisesRegex(pdf_text.PdfError, 'larger than'):
            pdf_text.extract_pages(b'%PDF-' + b'0' * (pdf_text.MAX_PDF_BYTES + 1))


class UploadDirMixin:
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.mkdtemp()
        self._ov = override_settings(UPLOAD_DIR=self._tmp)
        self._ov.enable()
        self.addCleanup(self._ov.disable)
        self.addCleanup(shutil.rmtree, self._tmp, True)


class StagingTests(UploadDirMixin, TestCase):
    def stage(self, *named_lines):
        return pdf_imports.stage_pdf_batch([(n, make_pdf([l])) for n, l in named_lines], PROVIDER)

    def test_preview_rows_match_the_hand_worked_figures_and_nothing_is_saved(self):
        batch = self.stage(('acme.pdf', MUFG_STYLE))
        row = batch.rows.get()
        self.assertEqual((batch.kind, batch.status), ('pdf', 'preview'))
        self.assertEqual((row.data['payment_date'], row.data['organisation'], row.data['category'], row.data['currency'],
                          row.data['gross_amount'], row.data['net_amount'], row.data['withholding_tax'], row.data['frequency']),
                         ('2025-05-12', 'ACM', 'Dividends', 'AUD', '50.00', '50.00', '0.00', 'one_off'))
        self.assertEqual(row.status, 'valid')
        self.assertEqual((Payment.objects.count(), Organisation.objects.count()), (0, 0))
        self.assertEqual((row.rate, row.rate_provider), (D('0.6'), 'fake'))                 # proposed conversion, not applied

    def test_each_value_shows_where_it_was_read(self):
        row = self.stage(('acme.pdf', MUFG_STYLE)).rows.get()
        self.assertEqual(row.source_name, 'acme.pdf')
        self.assertEqual(row.provenance['net_amount'], {'page': 1, 'text': 'Net Amount AUD 50.00'})
        self.assertEqual(row.provenance['organisation']['text'], 'ACM - ORDINARY SHARES $0.10 500 $0.00 $50.00 $50.00 $21.43')

    def test_long_reference_numbers_are_hidden_in_the_evidence(self):
        lines = [l for l in MUFG_STYLE if not l.startswith('ACM - ')] + ['T 0123456789 000 ACM']
        row = self.stage(('x.pdf', lines)).rows.get()
        self.assertEqual(row.provenance['organisation']['text'], 'T ###### 000 ACM')

    def test_unknown_layout_gives_an_error_and_no_staged_rows(self):
        with self.assertRaisesRegex(svc.ImportFileError, 'not recognised, so nothing was staged'):
            self.stage(('letter.pdf', UNKNOWN_LAYOUT))
        self.assertEqual((ImportBatch.objects.count(), ImportRow.objects.count()), (0, 0))
        self.assertFalse(any(Path(self._tmp).rglob('*.pdf')))                                   # no file kept either

    def test_scan_and_garbage_are_refused_without_staging(self):
        for raw in (make_pdf([[]]), b'%PDF-1.4 damaged'):
            with self.assertRaises(svc.ImportFileError):
                pdf_imports.stage_pdf_batch([('x.pdf', raw)], PROVIDER)
        self.assertEqual(ImportBatch.objects.count(), 0)

    def test_several_statements_one_batch_and_unreadable_ones_are_listed(self):
        batch = self.stage(('a-acme.pdf', MUFG_STYLE), ('b-zed.pdf', ACCEPTED['computershare'][0]), ('c-letter.pdf', UNKNOWN_LAYOUT))
        self.assertEqual([r.source_name for r in batch.rows.all()], ['a-acme.pdf', 'b-zed.pdf'])
        self.assertEqual(batch.file_name, '2 PDF statements')
        self.assertTrue(any('c-letter.pdf' in w and 'Not staged' in w for w in batch.warnings))
        archive = zipfile.ZipFile(io.BytesIO(svc.upload_path(batch).read_bytes()))
        self.assertEqual(len(archive.namelist()), 2)

    def test_same_statement_twice_in_one_upload_is_staged_once(self):
        batch = self.stage(('one.pdf', MUFG_STYLE), ('two.pdf', MUFG_STYLE))
        self.assertEqual(batch.rows.count(), 1)
        self.assertTrue(any('selected twice' in w for w in batch.warnings))

    def test_a_statement_already_imported_is_flagged_as_duplicate(self):
        svc.commit_batch(self.stage(('a.pdf', MUFG_STYLE)))
        again = self.stage(('b.pdf', MUFG_STYLE))
        self.assertEqual(again.rows.get().status, 'duplicate')

    def test_withholding_reinvestment_and_edit_flow(self):
        batch = self.stage(('w.pdf', ACCEPTED['withholding'][0]), ('r.pdf', REINVESTED))
        reinvested, withheld = batch.rows.all()               # sorted by file name: r.pdf, w.pdf
        self.assertEqual((withheld.data['gross_amount'], withheld.data['withholding_tax'], withheld.data['net_amount']), ('100.00', '15.00', '85.00'))
        self.assertIn('Reinvested under a dividend reinvestment plan', reinvested.data['comment'])
        self.assertIn('reinvested', reinvested.provenance)
        # per-row exclude and edit work as for CSV rows
        svc.set_excluded(reinvested, True, PROVIDER)
        svc.update_row(withheld, {**withheld.data, 'organisation': 'Acme Mining'}, PROVIDER)
        self.assertEqual(batch.rows.get(line_number=2).data['organisation'], 'Acme Mining')

    def test_commit_creates_a_converted_payment_once(self):
        batch = self.stage(('a.pdf', MUFG_STYLE))
        svc.commit_batch(batch)
        p = Payment.objects.get()
        self.assertEqual((p.organisation.name, p.category.name, p.currency, p.gross_amount, p.net_amount, p.withholding_tax,
                          p.expenses, p.gross_eur, p.rate), ('ACM', 'Dividends', 'AUD', D('50'), D('50'), D('0'), D('0'), D('30'), D('0.6')))
        self.assertEqual(p.source_document.description, 'PDF import #%d' % batch.pk)
        with self.assertRaises(svc.ImportStateError):
            svc.commit_batch(batch)                                                           # a double submit is harmless
        self.assertEqual(Payment.objects.count(), 1)


@override_settings(RATE_PROVIDER='core.services.rates.ManualOnlyProvider')
class ViewTests(UploadDirMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user('pdf', password='pw-for-tests-123')
        self.client.force_login(self.user)

    def upload(self, *files):
        return self.client.post(reverse('import_upload'), {'file': [SimpleUploadedFile(n, raw) for n, raw in files]})

    def test_upload_review_confirm_and_double_submit(self):
        r = self.upload(('a.pdf', make_pdf([MUFG_STYLE])), ('b.pdf', make_pdf([ACCEPTED['computershare'][0]])))
        batch = ImportBatch.objects.get()
        self.assertRedirects(r, reverse('import_preview', args=[batch.pk]))
        page = self.client.get(reverse('import_preview', args=[batch.pk])).content.decode()
        self.assertIn('Where each value was read', page)
        self.assertIn('Net Amount AUD 50.00', page)
        self.assertIn('a.pdf', page)
        self.assertEqual(Payment.objects.count(), 0)                  # nothing saved before the owner confirms
        url = reverse('import_commit', args=[batch.pk])
        self.client.post(url)
        self.client.post(url, follow=True)                            # the second submit is refused politely
        self.assertEqual(Payment.objects.count(), 2)

    def test_unknown_layout_upload_shows_the_reason_and_creates_nothing(self):
        r = self.upload(('letter.pdf', make_pdf([UNKNOWN_LAYOUT])))
        self.assertContains(r, 'not recognised, so nothing was staged')
        self.assertContains(r, 'Enter the payment manually')
        self.assertEqual((ImportBatch.objects.count(), ImportRow.objects.count()), (0, 0))

    def test_csv_and_pdf_cannot_be_mixed_and_several_csvs_are_refused(self):
        r = self.upload(('a.pdf', make_pdf([MUFG_STYLE])), ('b.csv', b'payment_date\n'))
        self.assertContains(r, 'not both together')
        r = self.upload(('a.csv', b'x'), ('b.csv', b'y'))
        self.assertContains(r, 'one CSV file at a time')
        self.assertEqual(ImportBatch.objects.count(), 0)

    def test_original_pdf_download_is_protected_and_is_the_file(self):
        raw = make_pdf([MUFG_STYLE])
        self.upload(('a.pdf', raw))
        batch = ImportBatch.objects.get()
        url = reverse('import_file', args=[batch.pk])
        r = self.client.get(url)
        self.assertEqual((r['Content-Type'], r['X-Content-Type-Options']), ('application/pdf', 'nosniff'))
        self.assertIn(f'import-{batch.pk}.pdf', r['Content-Disposition'])
        self.assertEqual(b''.join(r.streaming_content), raw)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)
        self.assertFalse(str(settings.STATIC_URL) in str(svc.upload_path(batch)))               # never under the static files

    def test_import_page_describes_the_pdf_support(self):
        page = self.client.get(reverse('import_list')).content.decode()
        self.assertIn('multiple', page)
        self.assertIn('Expected PDF statements', page)


SAMPLES = Path(settings.BASE_DIR) / 'local' / 'samples' / 'Statements' / 'Securities'


@skipUnless(SAMPLES.is_dir(), 'owner-supplied sample PDFs are not present (they are never committed)')
class LocalSampleTests(SimpleTestCase):
    """Reads the owner's real statements if they are on this machine. Nothing private is printed or asserted: every file
    must either parse with gross = net + withholding and a plausible date, or be refused with UnsupportedStatement."""

    def test_every_real_statement_is_read_consistently_or_refused_cleanly(self):
        files = sorted(SAMPLES.rglob('*.pdf'))
        self.assertTrue(files)
        parsed_count = 0
        for path in files:
            try:
                d = ds.parse(pdf_text.extract_pages(path.read_bytes()))
            except ds.UnsupportedStatement:
                continue
            parsed_count += 1
            self.assertEqual(d.gross, d.net + d.withholding, path.name)
            self.assertTrue(datetime.date(2020, 1, 1) < d.payment_date < datetime.date(2030, 1, 1), path.name)
            self.assertRegex(d.code, r'^[A-Z][A-Z0-9]{1,4}$', path.name)
        self.assertGreater(parsed_count, len(files) // 2)
