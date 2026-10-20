"""Phase 22: MECU statements (AUD) and the tolerant opening of damaged PDFs. Synthetic PDFs only: invented holder, accounts and
figures, worked out by hand in the comments."""
import datetime
import tempfile
from decimal import Decimal as D
from pathlib import Path
from unittest import mock, skipUnless

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.models import Payment
from core.services import imports as svc
from core.services import mecu_account, pdf_imports, pdf_inventory, pdf_text
from core.services import statement_readers as sr
from core.services.rates import FakeRateProvider

from .test_pdf_imports import UploadDirMixin
from .test_pdf_support import make_pdf

COLUMNS = 'Effective Posted Description Debit Credit Balance'


def statement(number='12', date='31 March 2025', sections=None, extra=()):
    sections = sections if sections is not None else default_sections()
    lines = ['Statement of Account', 'Statement Number ' + number, 'Statement Date ' + date, 'Account summary',
             'Account Number Account Opening Balance Total Debits Total Credits Closing Balance', '11111111 1,000.00 200.00 588.00 1,388.00 Everyday Access',
             *extra]
    for section in sections:
        lines += section
    lines += ['Bank Example Limited ABN 00 000 000 000 Australian Credit Licence Number 000000']
    return [lines]


def memo(day, tax, gross):
    return [f'{day} Mar {day} Mar Overseas Withholding Tax (${tax})', f'{day} Mar {day} Mar Gross Interest. (${gross})']


def savings(rows=None, closing='1,388.00', header='Account: 11111111 Everyday Access TFN Overseas'):
    """1,000.00 +500.00 -200.00 +80.00 (receiving credit of a term-deposit payment) +8.00 (bonus interest) = 1,388.00"""
    rows = rows if rows is not None else [
        '5 Mar 5 Mar Direct Credit EXAMPLE EMPLOYER 500.00 1,500.00',
        '10 Mar 10 Mar BPAY Payment To EXAMPLE BILLER 200.00 1,300.00',
        '15 Mar 15 Mar Interest Credit 33333333 Transfer 80.00 1,380.00',
        '31 Mar 31 Mar Bonus Interest 8.00 1,388.00', *memo(31, '2.00', '10.00')]
    return [header, 'Account Name: EXAMPLE HOLDER', COLUMNS, '1 Mar Opening Balance 1,000.00', *rows, f'31 Mar Closing Balance {closing}']


def td_maturing(net='300.00', closing='10,300.00', tax='100.00', gross='400.00'):
    return ['Account: 22222222 Term Deposit 6 months TFN Overseas', 'Interest rate 4.00% p.a. maturing 31 Mar 2025', 'Account Name: EXAMPLE HOLDER', COLUMNS,
            '1 Mar Opening Balance 10,000.00', f'31 Mar 31 Mar Interest Credit {net} {closing}', *memo(31, tax, gross), f'31 Mar Closing Balance {closing}']


def td_paying_out():
    return ['Account: 33333333 Term Deposit 12 months TFN Overseas', 'Account Name: EXAMPLE HOLDER', COLUMNS, '1 Mar Opening Balance 20,000.00',
            '15 Mar 15 Mar Interest Payment 33333333 Transfer ($80.00)', *memo(15, '20.00', '100.00'), '31 Mar Closing Balance 20,000.00']


def default_sections():
    return [savings(), td_maturing(), td_paying_out()]


def read(pages):
    return sr.read_statement(make_pdf(pages))


class MecuReaderTests(SimpleTestCase):
    def test_multi_account_statement_stages_interest_once_with_memo_figures(self):        # M1, M3, M4, M5
        outcome = read(statement())
        self.assertEqual(outcome.reader_id, 'mecu_account', outcome.error)
        rows = {(r.data['payment_date'], r.data['gross_amount']): r.data for r in outcome.result.rows}
        # bonus interest 10.00 gross - 2.00 withheld = 8.00; maturing deposit 400.00 - 100.00 = 300.00; paid-out deposit 100.00 - 20.00 = 80.00
        self.assertEqual(sorted((k, v['withholding_tax'], v['net_amount']) for k, v in rows.items()),
                         [(('2025-03-15', '100.00'), '20.00', '80.00'), (('2025-03-31', '10.00'), '2.00', '8.00'),
                          (('2025-03-31', '400.00'), '100.00', '300.00')])
        for d in rows.values():
            self.assertEqual((d['currency'], d['category'], d['frequency'], d['organisation'], d['expenses']), ('AUD', 'Interest', 'monthly', 'MECU', '0'))
            self.assertEqual(D(d['gross_amount']) - D(d['withholding_tax']), D(d['net_amount']))
        self.assertEqual(len(outcome.result.rows), 3)                 # the receiving credit of the paid-out deposit is a transfer, not a fourth row

    def test_comment_names_the_kind_and_the_account_type_but_no_account_number(self):
        comments = sorted(r.data['comment'] for r in read(statement()).result.rows)
        self.assertEqual(comments, ['Bonus interest (savings account), posted 2025-03-31 (PDF import).',
                                    'Term-deposit interest (term deposit), posted 2025-03-15 (PDF import).',
                                    'Term-deposit interest (term deposit), posted 2025-03-31 (PDF import).'])

    def test_provenance_cites_the_credit_and_its_memo_lines(self):
        row = next(r for r in read(statement()).result.rows if r.data['gross_amount'] == '10.00')
        self.assertIn('Overseas Withholding Tax ($2.00)', row.provenance['withholding_tax'][1])
        self.assertIn('Gross Interest. ($10.00)', row.provenance['gross_amount'][1])

    def test_a_memo_line_that_does_not_agree_with_the_credit_is_refused(self):           # M4
        sections = [savings(rows=['31 Mar 31 Mar Bonus Interest 8.00 1,008.00', *memo(31, '2.50', '10.00')], closing='1,008.00')]
        outcome = read(statement(sections=sections))
        self.assertIsNone(outcome.result)
        self.assertIn('do not agree with the amount credited', outcome.error)

    def test_an_interest_credit_by_transfer_without_a_partner_is_refused(self):           # M5
        outcome = read(statement(sections=[savings(), td_maturing()]))                   # the paid-out deposit section is missing
        self.assertIn('no matching term-deposit', outcome.error)

    def test_the_year_comes_from_the_statement_date_across_a_year_boundary(self):          # M2
        rows = ['20 Dec 20 Dec Bonus Interest 8.00 1,008.00', *memo(20, '2.00', '10.00').__class__(
            [x.replace('Mar', 'Dec') for x in memo(20, '2.00', '10.00')]),
            '2 Jan 2 Jan Bonus Interest 8.00 1,016.00', *[x.replace('Mar', 'Jan') for x in memo(2, '2.00', '10.00')]]
        section = ['Account: 11111111 Everyday Access TFN Overseas', COLUMNS, '15 Dec Opening Balance 1,000.00', *rows, '15 Jan Closing Balance 1,016.00']
        outcome = read(statement(date='15 January 2025', sections=[section]))
        self.assertEqual(outcome.error, '')
        self.assertEqual(sorted(r.data['payment_date'] for r in outcome.result.rows), ['2024-12-20', '2025-01-02'])
        self.assertEqual(outcome.result.period, (datetime.date(2024, 12, 15), datetime.date(2025, 1, 15)))

    def test_a_date_outside_the_statement_period_is_refused(self):                        # M2
        rows = ['5 Feb 5 Feb Bonus Interest 8.00 1,008.00']
        outcome = read(statement(sections=[savings(rows=rows, closing='1,008.00')]))
        self.assertIn('outside the statement period', outcome.error)

    def test_the_running_balance_of_every_row_and_account_must_add_up(self):               # M9, G9
        rows = ['5 Mar 5 Mar Direct Credit EXAMPLE EMPLOYER 500.00 1,501.00']
        self.assertIn('running balance', read(statement(sections=[savings(rows=rows, closing='1,501.00')])).error)
        rows = ['5 Mar 5 Mar Direct Credit EXAMPLE EMPLOYER 500.00 1,500.00']
        self.assertIn('closing balance', read(statement(sections=[savings(rows=rows, closing='1,499.00')])).error)

    def test_a_wrapped_row_and_a_page_continuation_of_an_account_are_one_account(self):
        rows = ['5 Mar 5 Mar Transfer To 22222222 To EXAMPLE PERSON - 7 Acc No.: 0000000000,', '200.00 800.00']
        cont = ['Account: 11111111 Everyday Access TFN Overseas - continued', COLUMNS, '31 Mar 31 Mar Bonus Interest 8.00 808.00', *memo(31, '2.00', '10.00'),
                '31 Mar Closing Balance 808.00']
        section = savings(rows=rows, closing='808.00')[:-1]
        outcome = read(statement(sections=[section, cont]))
        self.assertEqual(outcome.error, '')
        self.assertEqual([r.data['net_amount'] for r in outcome.result.rows], ['8.00'])

    def test_a_fee_or_other_unknown_booking_is_refused_naming_its_first_words(self):        # G12
        rows = ['5 Mar 5 Mar Account Keeping Fee 5.00 995.00']
        outcome = read(statement(sections=[savings(rows=rows, closing='995.00')]))
        self.assertIsNone(outcome.result)
        self.assertIn('Account Keeping', outcome.error)
        self.assertNotIn('5.00', outcome.error)

    def test_rows_that_only_restate_the_balance_are_accepted_only_when_the_figure_is_the_balance(self):
        ok = ['5 Mar 5 Mar Balance Enquiry #123456 - EXAMPLE ATM', 'EXAMPLE BRANCH 1,000.00']
        self.assertEqual(read(statement(sections=[savings(rows=ok, closing='1,000.00')])).error, '')
        bad = ['5 Mar 5 Mar Balance Enquiry #123456 - EXAMPLE ATM', 'EXAMPLE BRANCH 999.00']
        self.assertIn('could not be read', read(statement(sections=[savings(rows=bad, closing='1,000.00')])).error)

    def test_other_documents_are_not_claimed(self):
        self.assertIsNone(read([['A letter about nothing']]).reader_id)

    def test_fingerprint_is_number_period_end_and_the_sum_of_closing_balances(self):         # G7
        a, b = read(statement()).result, read(statement(extra=('Printed again',))).result
        self.assertEqual(a.fingerprint, b.fingerprint)
        self.assertNotEqual(a.fingerprint, read(statement(number='13')).result.fingerprint)
        self.assertNotEqual(a.fingerprint, read(statement(sections=[savings(), td_maturing(closing='10,301.00', net='301.00', gross='401.00'), td_paying_out()])).result.fingerprint)


class MecuAnnualSummaryTests(SimpleTestCase):
    @staticmethod
    def year(summary_withheld='24.00', summary_interest='120.00', months=12):
        """Twelve statements July 2024 to June 2025, each with one bonus interest 10.00 gross / 2.00 withheld (120.00 and 24.00 a year);
        the June statement carries the annual Payment Summary."""
        items = []
        for k in range(months):
            month = (6 + k) % 12 + 1
            year = 2024 + (6 + k) // 12
            last = (datetime.date(year + (month == 12), month % 12 + 1, 1) - datetime.timedelta(days=1)).day
            name = datetime.date(year, month, 1).strftime('%B')
            mon = datetime.date(year, month, 1).strftime('%b')
            section = ['Account: 11111111 Everyday Access TFN Overseas', COLUMNS, f'1 {mon} Opening Balance 1,000.00',
                       f'{last} {mon} {last} {mon} Bonus Interest 8.00 1,008.00', f'{last} {mon} {last} {mon} Overseas Withholding Tax ($2.00)',
                       f'{last} {mon} {last} {mon} Gross Interest. ($10.00)', f'{last} {mon} Closing Balance 1,008.00']
            extra = ()
            if month == 6:
                extra = ('Payment Summary for Withholding Tax 1/7/24 - 30/6/25', 'Account Number Interest Resident Non-resident',
                         f'11111111 {summary_interest} 0.00 {summary_withheld} Everyday Access', 'Account summary')
            items.append((f'm{k:02d}.pdf', statement(number=str(100 + k), date=f'{last} {name} {year}', sections=[section], extra=extra)))
        return items

    def results(self, items):
        return [(n, sr.read_statement(make_pdf(p)).result) for n, p in items]

    def test_a_summary_that_agrees_gives_no_warning(self):
        self.assertEqual(sr.reader_by_id('mecu_account').settle(self.results(self.year())), [])

    def test_a_summary_that_disagrees_by_one_unit_is_a_warning_and_the_rows_still_stage(self):      # M6
        items = self.results(self.year(summary_withheld='24.01'))
        warnings = sr.reader_by_id('mecu_account').settle(items)
        self.assertEqual(len(warnings), 1)
        self.assertIn('does not agree', warnings[0])
        self.assertEqual(sum(len(r.rows) for _n, r in items), 12)

    def test_a_partial_year_is_not_compared(self):
        warnings = sr.reader_by_id('mecu_account').settle(self.results(self.year()[5:]))
        self.assertTrue(any('not compared' in w for w in warnings), warnings)


class MecuStagingTests(UploadDirMixin, TestCase):
    PROVIDER = FakeRateProvider({('AUD', datetime.date(2025, 3, 31)): D('0.6'), ('AUD', datetime.date(2025, 3, 15)): D('0.6')})

    def test_real_chain_from_a_damaged_pdf_to_payments_and_the_original_is_kept(self):
        raw = make_pdf(statement(), short_xref=True)
        with self.assertRaises(Exception):
            import pypdf, io
            pypdf.PdfReader(io.BytesIO(raw)).pages[0].extract_text()          # pypdf alone cannot read it (M10)
        batch = pdf_imports.stage_pdf_batch([('stmt.pdf', raw)], self.PROVIDER)
        self.assertEqual(batch.rows.count(), 3)
        self.assertEqual(svc.upload_path(batch).read_bytes(), raw)           # the stored original is the uploaded, unrepaired file
        user = get_user_model().objects.create_user('u', password='p')
        self.client.force_login(user)
        self.assertIn(self.client.post(reverse('import_commit', args=[batch.pk])).status_code, (200, 302))
        self.assertEqual(Payment.objects.count(), 3)
        self.assertEqual(sorted(p.withholding_tax for p in Payment.objects.all()), [D('2.00'), D('20.00'), D('100.00')])

    def test_a_barcode_only_page_does_not_refuse_the_file(self):                           # M7
        pages = statement()
        outcome = read([pages[0], []])                                                  # a second page without any text
        self.assertEqual(outcome.error, '')
        self.assertEqual(len(outcome.result.rows), 3)

    def test_a_reissued_statement_is_staged_once(self):
        a, b = statement(), statement(extra=('Reprinted',))
        batch = pdf_imports.stage_pdf_batch([('one.pdf', make_pdf(a)), ('two.pdf', make_pdf(b))], self.PROVIDER)
        self.assertEqual(batch.rows.count(), 3)
        self.assertTrue(any('same statement as one.pdf' in w for w in batch.warnings))

    def test_a_swapped_file_name_does_not_change_the_period_read(self):                     # M8
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / '2401-001.pdf').write_bytes(make_pdf(statement()))          # named for January 2024, holds March 2025
            (entry,) = pdf_inventory.inventory(tmp)
        self.assertEqual(entry.period, (datetime.date(2025, 3, 1), datetime.date(2025, 3, 31)))
        self.assertIn('file name period differs from the period read', entry.flags)


class TolerantOpeningTests(SimpleTestCase):
    def test_a_short_cross_reference_header_is_repaired_in_memory(self):
        raw = make_pdf([['Hello 12.50']], short_xref=True)
        self.assertEqual(pdf_text.extract_pages(raw), ['Hello 12.50'])
        self.assertIn(b'xref\n0 5\n', raw)                                   # the uploaded bytes still carry the defect

    def test_a_truly_corrupt_pdf_is_still_refused(self):
        for raw in (b'%PDF-1.4\nthis is damaged', b'%PDF-1.4\n1 0 obj\n<< >>\nendobj\nxref\n0 1\ngarbage here\ntrailer\n<< >>\nstartxref\n10\n%%EOF'):
            with self.assertRaisesRegex(pdf_text.PdfError, 'could not be read'):
                pdf_text.extract_pages(raw)

    def test_an_undamaged_file_never_goes_through_the_repair(self):
        with mock.patch.object(pdf_text, 'repair_xref_counts', wraps=pdf_text.repair_xref_counts) as spy:
            pdf_text.extract_pages(make_pdf([['Hello 12.50']]))
        spy.assert_not_called()

    def test_repair_changes_only_the_count_and_returns_none_when_nothing_is_wrong(self):
        raw = make_pdf([['x']], short_xref=True)
        fixed = pdf_text.repair_xref_counts(raw)
        self.assertEqual(len(fixed), len(raw))
        self.assertEqual(sum(1 for a, b in zip(raw, fixed) if a != b), 1)
        self.assertIsNone(pdf_text.repair_xref_counts(make_pdf([['x']])))

    def test_the_size_limit_still_applies(self):
        with self.assertRaisesRegex(pdf_text.PdfError, 'larger than'):
            pdf_text.extract_pages(b'%PDF-' + b'0' * (pdf_text.MAX_PDF_BYTES + 1))


SAMPLES = Path(__file__).resolve().parent.parent / 'local' / 'samples'


@skipUnless((SAMPLES / 'MECU').is_dir(), 'owner-supplied MECU statements are not present (they are never committed)')
class LocalMecuTests(SimpleTestCase):
    """Reads the owner's real statements; prints counts only. If local/samples/expected/mecu.csv exists
    (payment_date,gross_amount,withholding_tax,net_amount,kind) the rows must equal it."""

    def test_all_files_open_none_is_refused_and_the_rows_match_the_owner_checked_file(self):
        files = sorted((SAMPLES / 'MECU').glob('*.pdf'))
        items, rows = [], []
        for path in files:
            outcome = sr.read_statement(path.read_bytes())
            self.assertEqual((outcome.reader_id, outcome.error), ('mecu_account', ''), path.name[:7])
            items.append((path.name[:7], outcome.result))
            rows += [(r.data['payment_date'], r.data['gross_amount'], r.data['withholding_tax'], r.data['net_amount'], r.data['comment'].split(' (')[0])
                     for r in outcome.result.rows]
        warnings = sr.reader_by_id('mecu_account').settle(items)
        print(f'\nMECU: {len(files)} files opened, {len(rows)} rows, annual-summary warnings: {warnings}')
        expected_file = SAMPLES / 'expected' / 'mecu.csv'
        if expected_file.is_file():
            expected = [tuple(l.split(',')) for l in expected_file.read_text().splitlines()[1:] if l.strip()]
            self.assertEqual(sorted(rows), sorted(expected))
        else:
            print('MECU: no expected file (local/samples/expected/mecu.csv); rows not compared')
