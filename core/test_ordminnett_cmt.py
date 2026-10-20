"""Phase 23: Cash Management Trust statements (AUD). Synthetic PDFs only: invented holder, payers and figures, worked out by hand
in the comments. The fixture imitates the structure of the real statements (period line, Date / Description / Debit / Credit /
Balance table with one amount column and a running balance, a taxation summary in the financial-year statements)."""
import datetime
import re
from decimal import Decimal as D
from pathlib import Path
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.models import Payment
from core.services import imports as svc
from core.services import ordminnett_cmt, pdf_imports, pdf_inventory
from core.services import statement_readers as sr
from core.services.rates import FakeRateProvider

from .test_pdf_imports import UploadDirMixin
from .test_pdf_support import make_pdf

HEADER = 'Date Description Debit ($) Credit ($) Balance ($)'


def cmt(period='01 July 2024 to 30 September 2024', rows=(), opening='10,000.00', summary=(), date='30 Sep 2024', title='Cash Management Trust Statement'):
    lines = [title, period, f'Statement Date: {date}', 'Account Number: 0000000', 'Transaction Summary', HEADER,
             f'01 Jul 24 Brought Forward {opening}', *rows]
    if summary:
        lines += ['2024-2025 Taxation Summary', 'Quarter Ended Tax Rate Interest Gross Resident Withholding Tax Non-Resident Withholding Tax', *summary]
    lines += ['Page 1 of 1']
    return [lines]


def read(pages):
    return sr.read_statement(make_pdf(pages))


# 10,000.00 +100.00 dividend -50.00 BPAY +60.00 interest -6.00 withholding = 10,104.00
Q3_ROWS = ['05 Jul 24 Direct Credit (EXAMPLE CORP DIVIDEND ABC24/12345678) 100.00 10,100.00',
           '10 Jul 24 BPay Internet 12ABC34 123456789012345678 TAX 50.00 10,050.00',
           '20 Aug 24 Interest 60.00 10,110.00',
           '30 Sep 24 Overseas Withholding Tax 6.00 10,104.00']


class OrdsReaderTests(SimpleTestCase):
    def test_interest_credit_and_a_later_withholding_debit_of_the_same_quarter_give_one_row(self):    # O2
        outcome = read(cmt(rows=Q3_ROWS))
        self.assertEqual(outcome.reader_id, 'ordminnett_cmt', outcome.error)
        warnings = sr.reader_by_id('ordminnett_cmt').settle([('a.pdf', outcome.result)])
        self.assertEqual(warnings, [])
        (row,) = outcome.result.rows
        d = row.data
        self.assertEqual((d['payment_date'], d['gross_amount'], d['withholding_tax'], d['net_amount'], d['expenses']), ('2024-08-20', '60.00', '6.00', '54.00', '0'))
        self.assertEqual((d['currency'], d['category'], d['frequency'], d['organisation'], d['income_period_start'], d['income_period_end']),
                         ('AUD', 'Interest', 'quarterly', 'Ord Minnett', '2024-07-01', '2024-09-30'))
        self.assertIn('Overseas withholding tax debited on 2024-09-30', d['comment'])
        self.assertEqual(row.provenance['withholding_tax'][1], '30 Sep 24 Overseas Withholding Tax 6.00 10,104.00')

    def test_the_dividend_credit_is_not_staged_and_the_dividend_reader_does_not_claim_the_statement(self):    # O5
        outcome = read(cmt(rows=Q3_ROWS))
        self.assertNotEqual(outcome.reader_id, 'au_dividend_advice')
        self.assertEqual(len(outcome.result.meta['events']), 2)         # only interest and withholding are events

    def test_a_row_whose_direction_cannot_be_proved_is_refused(self):                       # O1
        outcome = read(cmt(rows=['05 Jul 24 Direct Credit (EXAMPLE CORP DIVIDEND ABC24/12345678) 100.00 10,150.00']))
        self.assertIsNone(outcome.result)
        self.assertIn('direction', outcome.error)
        self.assertNotIn('100', outcome.error)

    def test_a_sale_proceeds_transfer_a_scheme_credit_and_a_property_credit_are_notices_with_dates_only(self):     # O6, O7
        rows = ['05 Jul 24 Transferred from a/c 123456 - SELL 100 EXC 5,000.00 15,000.00',
                '06 Jul 24 Direct Credit (EXAMPLE CORP SCHEME ABC24/12345678) 1,000.00 16,000.00',
                '07 Jul 24 Direct Credit (E X EXAMPLE SMITH) 250,000.00 266,000.00',
                '08 Jul 24 Direct Credit (ATO ATO123456789012345) 500.00 266,500.00',
                '09 Jul 24 Direct Debit (EXAMPLE TRANSFER 123456) 100,000.00 166,500.00',
                '10 Jul 24 EXAMPLE HOLDER, BSB 000-000, a/c 123456 (mortgage) 2,000.00 164,500.00']
        outcome = read(cmt(rows=rows))
        self.assertEqual(outcome.error, '')
        self.assertEqual(outcome.result.notices, [
            'Stock-sale proceeds transfer on 2024-07-05 is not imported (sales are not recorded).',
            'Share-scheme consideration credit on 2024-07-06 is not imported.',
            'A large credit on 2024-07-07 (a property sale or similar) is not imported.'])
        for n in outcome.result.notices:
            self.assertFalse(any(ch.isdigit() for ch in re.sub(r'\d{4}-\d{2}-\d{2}', '', n)), n)      # nothing but the date: no amounts, no names

    def test_an_unknown_booking_text_is_refused_naming_it(self):                            # G12
        outcome = read(cmt(rows=['05 Jul 24 Cheque Presented 100.00 9,900.00']))
        self.assertIn('Cheque Presented', outcome.error)

    def test_a_holdings_snapshot_has_nothing_to_import(self):                              # O8
        pages = [['Portfolio Valuation Account Number: 000000', 'Code Description Units Price Value', 'ABC EXAMPLE CORP 100 $10.0000 $1,000.00']]
        outcome = read(pages)
        self.assertEqual((outcome.reader_id, outcome.error, outcome.result.rows), ('ordminnett_valuation', '', []))

    def test_other_documents_are_not_claimed(self):
        self.assertIsNone(read([['A letter about nothing']]).reader_id)

    def test_the_first_row_must_be_the_brought_forward_balance(self):
        lines = cmt(rows=Q3_ROWS)[0]
        lines.remove(next(l for l in lines if 'Brought Forward' in l))
        self.assertIsNone(read([lines]).result)

    def test_fingerprint_is_period_statement_date_and_closing_balance(self):               # G7
        a, b = read(cmt(rows=Q3_ROWS)).result, read(cmt(rows=Q3_ROWS) and [cmt(rows=Q3_ROWS)[0] + ['Reprinted']]).result
        self.assertEqual(a.fingerprint, b.fingerprint)
        self.assertNotEqual(a.fingerprint, read(cmt(rows=Q3_ROWS[:3])).result.fingerprint)


def settle(*pairs):
    return sr.reader_by_id('ordminnett_cmt').settle(list(pairs))


class OrdsBatchTests(SimpleTestCase):
    def r(self, **kw):
        return read(cmt(**kw)).result

    def test_a_financial_year_statement_repeating_monthly_rows_stages_each_once_and_lists_the_repeats(self):   # O3
        monthly = self.r(rows=Q3_ROWS)
        # the financial-year statement repeats the Q3 lines and adds the June quarter (+80.00 interest, -8.00 withholding) that only it holds
        fy_rows = [*Q3_ROWS, '30 Jun 25 Interest 80.00 10,184.00', '30 Jun 25 Overseas Withholding Tax 8.00 10,176.00']
        fy = self.r(period='01 July 2024 to 30 June 2025', rows=fy_rows, date='30 Jun 2025')
        warnings = settle(('a-monthly.pdf', monthly), ('b-fy.pdf', fy))
        rows = [row for res in (monthly, fy) for row in res.rows]
        self.assertEqual(sorted((r.data['payment_date'], r.data['gross_amount'], r.data['withholding_tax']) for r in rows),
                         [('2024-08-20', '60.00', '6.00'), ('2025-06-30', '80.00', '8.00')])
        self.assertEqual(len(monthly.rows), 1)                       # first seen wins
        self.assertEqual(len(fy.rows), 1)                            # the FY-only quarter stages from the FY file
        self.assertTrue(any('2 line(s) repeated' in w and 'b-fy.pdf (also in a-monthly.pdf)' in w for w in warnings), warnings)
        self.assertFalse(any('80.00' in w or '60.00' in w for w in warnings))

    def test_two_identical_lines_inside_one_statement_are_two_payments(self):
        rows = ['20 Aug 24 Interest 60.00 10,060.00', '21 Aug 24 Interest 60.00 10,120.00']
        res = self.r(rows=rows)
        settle(('a.pdf', res))
        self.assertEqual(len(res.rows), 2)

    def test_a_withholding_without_interest_is_a_warning_and_no_row(self):                  # O10
        res = self.r(rows=['30 Sep 24 Overseas Withholding Tax 6.00 9,994.00'])
        warnings = settle(('a.pdf', res))
        self.assertEqual(res.rows, [])
        self.assertTrue(any('no interest credit in their quarter' in w for w in warnings), warnings)

    def test_interest_without_a_withholding_debit_stages_with_zero_and_a_warning(self):
        res = self.r(rows=['20 Aug 24 Interest 60.00 10,060.00'])
        warnings = settle(('a.pdf', res))
        self.assertEqual((res.rows[0].data['withholding_tax'], res.rows[0].data['net_amount']), ('0', '60.00'))
        self.assertTrue(any('no overseas withholding debit' in w for w in warnings))

    def test_the_taxation_summary_is_a_cross_check_with_warnings_only(self):                  # O4
        rows = ['30 Sep 24 Interest 60.00 10,060.00', '30 Sep 24 Overseas Withholding Tax 6.00 10,054.00']
        good = self.r(period='01 July 2024 to 30 June 2025', rows=rows, summary=['30 Sep 2024 0.00 60.00 0.00 6.00'])
        self.assertEqual(settle(('fy.pdf', good)), [])
        bad = self.r(period='01 July 2024 to 30 June 2025', rows=rows, summary=['30 Sep 2024 0.00 60.01 0.00 6.00'])
        warnings = settle(('fy.pdf', bad))
        self.assertTrue(any('does not agree' in w for w in warnings), warnings)
        self.assertEqual(len(bad.rows), 1)                                              # still staged
        missing = self.r(period='01 July 2024 to 30 June 2025', rows=rows, summary=['31 Dec 2024 0.00 70.00 0.00 7.00'])
        self.assertTrue(any('no interest line' in w for w in settle(('fy.pdf', missing))))


class OrdsStagingTests(UploadDirMixin, TestCase):
    PROVIDER = FakeRateProvider({('AUD', datetime.date(2024, 8, 20)): D('0.6'), ('AUD', datetime.date(2025, 6, 30)): D('0.6')})

    def test_real_chain_two_overlapping_statements_to_payments(self):
        fy_rows = [*Q3_ROWS, '30 Jun 25 Interest 80.00 10,184.00', '30 Jun 25 Overseas Withholding Tax 8.00 10,176.00']
        files = [('a-monthly.pdf', make_pdf(cmt(rows=Q3_ROWS))), ('b-fy.pdf', make_pdf(cmt(period='01 July 2024 to 30 June 2025', rows=fy_rows, date='30 Jun 2025')))]
        batch = pdf_imports.stage_pdf_batch(files, self.PROVIDER)
        self.assertEqual(batch.rows.count(), 2)
        self.assertTrue(any('repeated in overlapping statements' in w for w in batch.warnings), batch.warnings)
        user = get_user_model().objects.create_user('u', password='p')
        self.client.force_login(user)
        self.assertIn(self.client.post(reverse('import_commit', args=[batch.pk])).status_code, (200, 302))
        self.assertEqual(sorted((p.gross_amount, p.withholding_tax, p.net_amount) for p in Payment.objects.all()),
                         [(D('60.00'), D('6.00'), D('54.00')), (D('80.00'), D('8.00'), D('72.00'))])

    def test_statements_without_interest_are_nothing_to_import_and_their_notices_survive(self):
        rows = ['05 Jul 24 Transferred from a/c 123456 - SELL 100 EXC 5,000.00 15,000.00']
        with self.assertRaises(pdf_imports.NothingToImport) as ctx:
            pdf_imports.stage_pdf_batch([('a.pdf', make_pdf(cmt(rows=rows)))], self.PROVIDER)
        self.assertIn('1 statement recognised, no income.', str(ctx.exception))
        self.assertIn('Stock-sale proceeds', str(ctx.exception))

    def test_a_refused_statement_stages_nothing(self):
        with self.assertRaisesRegex(svc.ImportFileError, 'Cheque Presented'):
            pdf_imports.stage_pdf_batch([('x.pdf', make_pdf(cmt(rows=['05 Jul 24 Cheque Presented 100.00 9,900.00'])))], self.PROVIDER)

    def test_the_inventory_counts_the_rows_made_by_the_batch_step(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'a.pdf').write_bytes(make_pdf(cmt(rows=Q3_ROWS)))
            (entry,) = pdf_inventory.inventory(tmp)
        self.assertEqual((entry.rows, entry.outcome), (1, 'staged'))


SAMPLES = Path(__file__).resolve().parent.parent / 'local' / 'samples'


@skipUnless((SAMPLES / 'Ords').is_dir(), 'owner-supplied Cash Management Trust statements are not present (they are never committed)')
class LocalOrdsTests(SimpleTestCase):
    """Reads the owner's real statements; prints counts only. If local/samples/expected/ords.csv exists
    (payment_date,income_period_end,gross_amount,withholding_tax,net_amount) the settled rows must equal it."""

    def test_all_files_are_staged_or_nothing_to_import_none_is_refused_and_rows_match(self):
        items = []
        for path in sorted((SAMPLES / 'Ords').glob('*.pdf')):
            outcome = sr.read_statement(path.read_bytes())
            self.assertIsNotNone(outcome.result, outcome.error)
            items.append((path.name[:6] + path.name[-30:-26], outcome))
        warnings = sr.reader_by_id('ordminnett_cmt').settle([(l, o.result) for l, o in items if o.reader_id == 'ordminnett_cmt'])
        rows = [(r.data['payment_date'], r.data['income_period_end'], r.data['gross_amount'], r.data['withholding_tax'], r.data['net_amount'])
                for _l, o in items for r in o.result.rows]
        print(f'\nOrd Minnett: {len(items)} files, {len(rows)} rows, {len(warnings)} warning(s)')
        expected_file = SAMPLES / 'expected' / 'ords.csv'
        if expected_file.is_file():
            expected = [tuple(l.split(',')) for l in expected_file.read_text().splitlines()[1:] if l.strip()]
            self.assertEqual(sorted(rows), sorted(expected))
        else:
            print('Ord Minnett: no expected file (local/samples/expected/ords.csv); rows not compared')
