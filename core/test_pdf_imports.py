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
from core.services import interest_statements as it
from core.services import pdf_imports, pdf_text
from core.services.rates import FakeRateProvider

from .test_pdf_support import (
    ACCEPTED, BONUS_SHARE_PLAN, DISAGREEING_NET, EXPECT_FUND, INCONSISTENT, MUFG_STYLE, NO_PAYMENT_DATE, REINVESTED, SCHEME_PAYMENT,
    UNKNOWN_LAYOUT, fund_statement, make_pdf)

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

    def test_company_name_is_used_when_the_statement_prints_it_otherwise_only_the_code(self):
        names = {name: parsed(lines).issuer for name, (lines, _e) in ACCEPTED.items()}
        self.assertEqual(names['mufg'], 'Acme Mining Limited')              # printed in capitals above the ABN line
        self.assertEqual(names['computershare'], 'Zed Resources Limited')
        self.assertEqual(names['label_first_net'], 'Quick Pharma Limited')   # on the same line as the ABN
        self.assertEqual(names['payment_then_record'], 'Hubb Limited')
        self.assertEqual(names['value_per_line'], '')                       # no name next to the ABN: the code alone is used

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


def fund(**kw):
    return it.parse(pdf_text.extract_pages(make_pdf([fund_statement(**kw)])))


class FundStatementTests(SimpleTestCase):
    def test_monthly_return_fees_and_net_are_worked_out_by_hand(self):
        r = fund()
        self.assertEqual((r.payment_date, r.currency, r.gross, r.expenses, r.net), EXPECT_FUND)   # 1.5000 - 0.5400 = 0.9600
        self.assertEqual(r.days, 3)
        self.assertEqual(r.evidence['gross_amount'], (1, 'Total Earned Return 1.5000'))

    def test_daily_lines_must_add_up_to_the_summary(self):
        with self.assertRaisesRegex(ds.UnsupportedStatement, 'do not add up'):
            fund(earned='1.6000')
        with self.assertRaisesRegex(ds.UnsupportedStatement, 'do not add up'):
            fund(total_fees='-0.5300')

    def test_other_problems_are_refused(self):
        with self.assertRaisesRegex(ds.UnsupportedStatement, 'no return was earned|nothing to import'):
            fund(returns=('0', '0', '0'), earned='0', fees=('0', '0', '0'), total_fees='0')
        with self.assertRaisesRegex(ds.UnsupportedStatement, 'single month'):
            fund(period='Period Jan 1, 2025 - Jun 30, 2025')
        with self.assertRaisesRegex(ds.UnsupportedStatement, 'period'):
            fund(period='Between June and July')

    def test_the_ordinary_revolut_account_statement_is_still_not_recognised(self):
        lines = ['EUR Statement', 'Generated on the Oct 16, 2026', 'Balance summary',
                 'Account (Current Account) \u20ac4.63 \u20ac2,677.43 \u20ac2,676.09 \u20ac3.29', 'Sep 1, 2026 To EUR Flexible Cash Funds \u20ac100.00 \u20ac819.63']
        pages = pdf_text.extract_pages(make_pdf([lines]))
        self.assertFalse(it.recognises(pages))
        with self.assertRaisesRegex(ds.UnsupportedStatement, 'not recognised'):
            ds.parse(pages)


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
                         ('2025-05-12', 'Acme Mining Limited (ACM)', 'Dividends', 'AUD', '50.00', '50.00', '0.00', 'one_off'))
        self.assertEqual(row.status, 'valid')
        self.assertEqual((Payment.objects.count(), Organisation.objects.count()), (0, 0))
        self.assertEqual((row.rate, row.rate_provider), (D('0.6'), 'fake'))                 # proposed conversion, not applied

    def test_organisation_is_name_and_code_when_available_else_the_code(self):
        named = self.stage(('n.pdf', MUFG_STYLE)).rows.get()
        self.assertEqual(named.data['organisation'], 'Acme Mining Limited (ACM)')
        unnamed = self.stage(('u.pdf', ACCEPTED['value_per_line'][0])).rows.get()
        self.assertEqual(unnamed.data['organisation'], 'RTO')
        self.assertEqual(named.data['comment'], 'Dividend (PDF import).')

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

    def test_fund_statements_stage_as_interest_with_fees_as_expenses_and_commit_at_rate_one(self):
        batch = pdf_imports.stage_pdf_batch([('jun.pdf', make_pdf([fund_statement()]))], PROVIDER)
        row = batch.rows.get()
        self.assertEqual((row.data['payment_date'], row.data['organisation'], row.data['category'], row.data['currency'],
                          row.data['gross_amount'], row.data['expenses'], row.data['net_amount'], row.data['withholding_tax'],
                          row.data['frequency']),
                         ('2025-06-30', 'Revolut Securities Europe UAB (Flexible Cash Funds)', 'Interest', 'EUR',
                          '1.5000', '0.5400', '0.9600', '0', 'monthly'))
        self.assertEqual((row.status, row.rate, row.rate_provider), ('valid', D('1'), 'identity'))
        self.assertEqual(row.provenance['expenses'], {'page': 1, 'text': 'Total Fees -0.5400'})
        svc.commit_batch(batch)
        p = Payment.objects.get()
        self.assertEqual((p.gross_amount, p.expenses, p.net_amount, p.withholding_tax, p.unallocated, p.gross_eur, p.expenses_eur),
                         (D('1.5'), D('0.54'), D('0.96'), D('0'), D('0'), D('1.5'), D('0.54')))

    def test_dividends_and_fund_statements_can_be_uploaded_together(self):
        batch = self.stage(('a.pdf', MUFG_STYLE), ('z-fund.pdf', fund_statement()))
        self.assertEqual([r.data['category'] for r in batch.rows.all()], ['Dividends', 'Interest'])

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
                          p.expenses, p.gross_eur, p.rate), ('Acme Mining Limited (ACM)', 'Dividends', 'AUD', D('50'), D('50'), D('0'), D('0'), D('30'), D('0.6')))
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

    def test_a_whole_folder_with_hidden_files_is_staged_and_the_counts_are_reported(self):
        files = [('a.pdf', make_pdf([MUFG_STYLE])), ('b.pdf', make_pdf([ACCEPTED['computershare'][0]])),
                 ('nab.pdf', make_pdf([BONUS_SHARE_PLAN])), ('.DS_Store', b'\x00\x00junk'), ('.hidden.pdf', make_pdf([UNKNOWN_LAYOUT]))]
        r = self.client.post(reverse('import_upload'), {'folder': [SimpleUploadedFile(n, raw) for n, raw in files]}, follow=True)
        batch = ImportBatch.objects.get()
        self.assertEqual(batch.rows.count(), 2)
        self.assertContains(r, '2 of 3 PDF files read and staged as 2 rows; 0 recognised with no income or not imported; 1 not staged')
        self.assertContains(r, 'nab.pdf')                                 # listed with its reason
        self.assertContains(r, 'bonus share plan')

    def test_nothing_usable_in_the_selection_is_an_error(self):
        r = self.client.post(reverse('import_upload'), {'folder': [SimpleUploadedFile('.DS_Store', b'junk')]})
        self.assertContains(r, 'No usable file was selected')
        self.assertEqual(ImportBatch.objects.count(), 0)

    def test_the_form_offers_a_folder_picker_and_many_files_are_allowed(self):
        page = self.client.get(reverse('import_list')).content.decode()
        self.assertIn('webkitdirectory', page)
        self.assertGreaterEqual(settings.DATA_UPLOAD_MAX_NUMBER_FILES, 300)                    # Django's default is 100
        self.assertGreaterEqual(pdf_imports.MAX_FILES, 300)

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


FUNDS = Path(settings.BASE_DIR) / 'local' / 'samples' / 'Statements' / 'Revolut'


@skipUnless(any(FUNDS.glob('savings-statement*.pdf')) if FUNDS.is_dir() else False, 'owner-supplied Revolut statements are not present')
class LocalFundSampleTests(SimpleTestCase):
    def test_every_real_savings_statement_reconciles(self):
        for path in sorted(FUNDS.glob('savings-statement*.pdf')):
            r = it.parse(pdf_text.extract_pages(path.read_bytes()))      # raises unless the daily lines add up to the summary
            self.assertEqual(r.net, r.gross - r.expenses, path.name)
            self.assertEqual(r.currency, 'EUR')
