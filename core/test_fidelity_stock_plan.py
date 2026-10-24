"""Phase 19: Fidelity Stock Plan Services reports (USD). Synthetic PDFs only: invented company ("EXAMPLE CORP"), core fund
("EXAMPLE CASH RESERVES PORTFOLIO") and figures, worked out by hand next to each fixture."""
import datetime
from decimal import Decimal as D
from pathlib import Path
from unittest import skipUnless

from django.test import SimpleTestCase, TestCase

from core.services import organisations, pdf_imports
from core.services import imports as svc
from core.services import statement_readers as sr
from core.services.rates import FakeRateProvider

from .test_pdf_imports import UploadDirMixin
from .test_pdf_support import make_pdf

STOCK_INCOME = 'EXAMPLE CORP 12345A678'
FUND_INCOME = 'EXAMPLE CASH RESERVES 999999999'          # the name wraps: "PORTFOLIO" follows on the next line
FUND_TAX = 'EXAMPLE CASH RESERVES PORTFOLIO CLASS'       # the tax table prints a longer form of the same name
STOCK_TAX = 'EXAMPLE CORP'


def income(day, name_code, amount, wrapped=''):
    lines = [f'{day} {name_code} Dividend Received - - {amount}']
    return lines + ([wrapped] if wrapped else [])


def fund_income(day, amount):
    return income(day, FUND_INCOME, amount, 'PORTFOLIO')


def tax(day, name, desc, amount, flag='', wrapped=''):
    lines = [f'{flag + " " if flag else ""}{day} {name} {desc} {amount}']
    return lines + ([wrapped] if wrapped else [])


def statement(period='January 1, 2025 - January 31, 2025', income_rows=(), tax_rows=(), income_total='0.00', tax_total=None, summary_total=None,
              sections=(), core_rows=('01/31 CASH Reinvestment EXAMPLE CASH RESERVES PORTFOLIO 1.000 1.0000 1.00 100.00',), ending='$10,000.00'):
    lines = ['STOCK PLAN SERVICES REPORT', period, 'Account Summary', f'Ending Account Value as of Jan 31 {ending}',
             'Income Summary', 'This Period Year-to-date', f'Taxable ${income_total} ${income_total}',
             f'Total ${income_total if summary_total is None else summary_total} ${income_total}', 'Activity', *sections]
    lines += ['Dividends, Interest & Other Income', '(Excluding dividend reinvestment)', 'Settlement',
              'Date Security Name Code Description Quantity Price Amount', *income_rows, f'Total Dividends, Interest & Other Income ${income_total}']
    if tax_rows or tax_total is not None:
        lines += ['Taxes Withheld', 'Date Security Description Amount', *tax_rows,
                  f'Total Federal Taxes Withheld {tax_total or "0.00"}', f'Total Taxes Withheld ${tax_total or "0.00"}']
    if core_rows:
        lines += ['Core Fund Activity (Excluding)', 'Settlement Account', 'Date Account Description Quantity Price Amount Balance', *core_rows,
                  'Total Core Fund Activity $1.00']
    return [lines]


def read(pages):
    return sr.read_statement(make_pdf(pages))


def basic():
    # stock 40.00 with 6.00 withheld (posting printed with the event's date), fund 3.00 without: income 43.00; tax lines sum -6.00
    return statement(income_rows=[*income('01/23', STOCK_INCOME, '$40.00'), *fund_income('01/31', '3.00')],
                     tax_rows=tax('01/23', STOCK_TAX, 'Non-Resident Tax', '-6.00'), income_total='43.00', tax_total='6.00')


class FidelityReaderTests(SimpleTestCase):
    def test_a_stock_dividend_with_withholding_and_a_fund_dividend_without_give_two_rows(self):
        outcome = read(basic())
        self.assertEqual(outcome.reader_id, 'fidelity_stock_plan', outcome.error)
        stock, fund = outcome.result.rows
        self.assertEqual((stock.data['payment_date'], stock.data['gross_amount'], stock.data['withholding_tax'], stock.data['net_amount'],
                          stock.data['frequency'], stock.data['organisation']),
                         ('2025-01-23', '40.00', '6.00', '34.00', 'quarterly', 'Fidelity Example Corp'))
        self.assertEqual((fund.data['payment_date'], fund.data['gross_amount'], fund.data['withholding_tax'], fund.data['net_amount'],
                          fund.data['frequency'], fund.data['organisation']),
                         ('2025-01-31', '3.00', '0', '3.00', 'monthly', 'Fidelity Example Cash Reserves Portfolio'))      # the wrapped name is rejoined (F1)
        for r, category in ((stock, 'Dividends'), (fund, 'Interest')):      # Phase 32: fund income is Interest
            self.assertEqual((r.data['currency'], r.data['category'], r.data['expenses']), ('USD', category, '0'))
        self.assertEqual((stock.data['comment'], fund.data['comment']), ('Dividend via Fidelity.', 'Fund dividend via Fidelity.'))
        self.assertEqual(outcome.result.period, (datetime.date(2025, 1, 1), datetime.date(2025, 1, 31)))

    def test_provenance_cites_the_income_line_and_the_wrapped_remainder(self):
        stock, fund = read(basic()).result.rows
        self.assertEqual(fund.provenance['gross_amount'], (1, '01/31 EXAMPLE CASH RESERVES 999999999 Dividend Received - - 3.00 / PORTFOLIO'))

    def test_a_wrapped_tax_name_is_matched_to_its_income_line(self):            # F1
        pages = statement(income_rows=fund_income('01/31', '10.00'), income_total='10.00', tax_total='1.50',
                          tax_rows=tax('01/31', FUND_TAX, 'Non-Resident Tax', '-1.50', wrapped='SHARES MORE'))
        (row,) = read(pages).result.rows
        self.assertEqual((row.data['withholding_tax'], row.data['net_amount']), ('1.50', '8.50'))

    def test_the_printed_federal_total_may_have_either_sign(self):             # F4
        for printed in ('6.00', '-6.00'):
            pages = statement(income_rows=income('01/23', STOCK_INCOME, '$40.00'), income_total='40.00', tax_total=printed,
                              tax_rows=tax('01/23', STOCK_TAX, 'Non-Resident Tax', '-6.00'))
            self.assertEqual(read(pages).error, '', printed)
        refund = statement(income_total='0.00', tax_total='-1.50', tax_rows=tax('01/10', STOCK_TAX, 'Adj Non-Resident Tax', '1.50', flag='A'))
        self.assertEqual(read(refund).error, '')                                # a net refund still reconciles

    def test_a_federal_total_that_does_not_match_the_lines_is_refused(self):
        pages = statement(income_rows=income('01/23', STOCK_INCOME, '$40.00'), income_total='40.00', tax_total='6.01',
                          tax_rows=tax('01/23', STOCK_TAX, 'Non-Resident Tax', '-6.00'))
        self.assertIn('federal taxes withheld', read(pages).error)

    def test_an_income_total_that_does_not_match_is_refused(self):
        pages = statement(income_rows=income('01/23', STOCK_INCOME, '$40.00'), income_total='40.01')
        self.assertIn('total of the income table', read(pages).error)
        self.assertIn('income summary', read(statement(income_rows=income('01/23', STOCK_INCOME, '$40.00'), income_total='40.00', summary_total='39.99')).error)

    def test_an_unknown_income_description_is_refused_naming_it(self):           # G12
        pages = statement(income_rows=['01/23 EXAMPLE CORP 12345A678 Interest Earned - - $1.00'], income_total='1.00')
        outcome = read(pages)
        self.assertIsNone(outcome.result)
        self.assertIn('Interest Earned', outcome.error)

    def test_an_unknown_tax_description_is_refused_naming_it(self):
        pages = statement(income_rows=income('01/23', STOCK_INCOME, '$40.00'), income_total='40.00', tax_total='1.00',
                          tax_rows=tax('01/23', STOCK_TAX, 'Backup Withholding', '-1.00'))
        self.assertIn('Backup Withholding', read(pages).error)

    def test_a_delivery_and_a_sale_are_notices_and_nothing_is_staged_from_them(self):         # F7
        sections = ['Securities Bought & Sold', 'Date Security Name Code Description Quantity Price Cost Basis Cost Amount',
                    '01/10 EXAMPLE CORP RSU1234 12345A678 You Bought 10.000 $50.00000 - -', 'VALUE OF SHARES $500.00',
                    '01/10 EXAMPLE CORP SELL12345 12345A678 You Sold -4.000 50.00000 200.00 - 200.00',
                    'Net Securities Bought & Sold - $200.00']
        outcome = read(statement(income_rows=income('01/23', STOCK_INCOME, '$40.00'), income_total='40.00', tax_total='6.00',
                                 tax_rows=tax('01/23', STOCK_TAX, 'Non-Resident Tax', '-6.00'), sections=sections))
        self.assertEqual(outcome.error, '')
        self.assertEqual(len(outcome.result.rows), 1)
        self.assertEqual(outcome.result.notices, ['Not imported: shares bought (a delivery or purchase) on 01/10.', 'Not imported: shares sold on 01/10.'])
        self.assertFalse(any(ch.isdigit() for n in outcome.result.notices for ch in n.replace('01/10', '')))        # no amounts

    def test_a_month_with_only_core_fund_activity_has_nothing_to_import(self):         # F8
        outcome = read(statement())
        self.assertEqual((outcome.error, outcome.result.rows), ('', []))

    def test_other_documents_are_not_claimed(self):
        self.assertIsNone(read([['A letter about nothing']]).reader_id)

    def test_the_same_company_gets_the_identical_organisation_string_as_from_e_trade(self):
        """Both brokers print the company in capitals; the shared function gives one company string, and the broker is the
        prefix (Phase 32), so the two organisations differ. (The E*TRADE reader's own test uses the same invented company.)"""
        from .test_etrade_client import DEFAULT_ROWS, statement as etrade_statement
        etrade_rows = read(etrade_statement(rows=DEFAULT_ROWS)).result.rows
        fidelity_rows = read(basic()).result.rows
        self.assertEqual(etrade_rows[1].data['organisation'], 'E*Trade Example Corp')
        self.assertEqual(fidelity_rows[0].data['organisation'], 'Fidelity Example Corp')
        self.assertEqual(organisations.tidy_security_name('EXAMPLE CORP'), 'Example Corp')
        self.assertIn('via E*TRADE', etrade_rows[1].data['comment'])
        self.assertIn('via Fidelity', fidelity_rows[0].data['comment'])


def jan_with_original_withholding():
    # fund dividend 10.00 on 01/31 with 1.50 withheld
    return statement(income_rows=fund_income('01/31', '10.00'), income_total='10.00', tax_total='1.50',
                     tax_rows=tax('01/31', FUND_TAX, 'Non-Resident Tax', '-1.50'))


def feb_with_reversal_and_rebooking():
    # February's own dividend 2.00 (nothing withheld); January's event is reversed (+1.50) and re-booked smaller (-0.75): lines sum +0.75
    return statement(period='February 1, 2025 - February 28, 2025', income_rows=fund_income('02/28', '2.00'), income_total='2.00', tax_total='0.75',
                     tax_rows=[*tax('01/31', FUND_TAX, 'Adj Non-Resident Tax', '1.50', flag='A'), *tax('01/31', FUND_TAX, 'Non-Resident Tax', '-0.75', flag='A')],
                     core_rows=('02/28 CASH Reinvestment EXAMPLE CASH RESERVES PORTFOLIO 1.000 1.0000 1.00 100.00',), ending='$10,100.00')


class FidelitySettlementTests(UploadDirMixin, TestCase):
    PROVIDER = FakeRateProvider({('USD', datetime.date(2025, 1, 31)): D('0.9'), ('USD', datetime.date(2025, 2, 28)): D('0.9'),
                                 ('USD', datetime.date(2025, 1, 23)): D('0.9')})

    def stage(self, *named):
        return pdf_imports.stage_pdf_batch([(n, make_pdf(p)) for n, p in named], self.PROVIDER)

    def rows(self, batch):
        return {r.data['payment_date']: r.data for r in batch.rows.all()}

    def test_withholding_is_the_sum_of_original_reversal_and_rebooking_across_statements(self):     # F5
        batch = self.stage(('a-jan.pdf', jan_with_original_withholding()), ('b-feb.pdf', feb_with_reversal_and_rebooking()))
        rows = self.rows(batch)
        january = rows['2025-01-31']
        # -(-1.50 + 1.50 - 0.75) = 0.75 withheld; net 10.00 - 0.75
        self.assertEqual((january['gross_amount'], january['withholding_tax'], january['net_amount']), ('10.00', '0.75', '9.25'))
        self.assertIn('sum of 3 postings (1 reversal(s))', january['comment'])
        self.assertNotIn('may be revised', january['comment'])              # a later statement is in the upload
        self.assertIn('may be revised', rows['2025-02-28']['comment'])      # the latest statement could still be revised
        self.assertEqual(batch.rows.count(), 2)
        prov = batch.rows.get(data__payment_date='2025-01-31').provenance['withholding_tax']['text']
        self.assertEqual(prov.count('Non-Resident Tax'), 3)
        self.assertFalse(any('not in this upload' in w for w in batch.warnings), batch.warnings)

    def test_uploaded_alone_the_january_row_is_marked_as_possibly_revised(self):
        batch = self.stage(('a-jan.pdf', jan_with_original_withholding()))
        row = batch.rows.get().data
        self.assertEqual((row['withholding_tax'], row['net_amount']), ('1.50', '8.50'))
        self.assertIn('Withholding may be revised by a later statement.', row['comment'])

    def test_postings_for_events_outside_the_upload_stage_nothing_and_are_counted(self):          # F3
        pages = statement(period='January 1, 2026 - January 31, 2026', income_total='0.00', tax_total='0.75',
                          tax_rows=[*tax('12/15', FUND_TAX, 'Adj Non-Resident Tax', '1.50', flag='A'), *tax('12/15', FUND_TAX, 'Non-Resident Tax', '-0.75', flag='A')],
                          core_rows=())
        with self.assertRaises(pdf_imports.NothingToImport) as ctx:
            self.stage(('jan.pdf', pages))
        self.assertIn('1 statement recognised, no income.', str(ctx.exception))
        both = self.stage(('x-jan.pdf', pages), ('y-other.pdf', basic()))
        self.assertIn('Tax postings for events not in this upload: 2 (not staged).', both.warnings)
        self.assertEqual(both.rows.count(), 2)

    def test_a_net_refund_larger_than_the_withholding_is_a_warning_with_zero_withholding(self):
        feb = statement(period='February 1, 2025 - February 28, 2025', income_total='0.00', tax_total='2.00', core_rows=(),
                        tax_rows=tax('01/31', FUND_TAX, 'Adj Non-Resident Tax', '2.00', flag='A'))
        batch = self.stage(('a-jan.pdf', jan_with_original_withholding()), ('b-feb.pdf', feb))
        january = batch.rows.get().data
        self.assertEqual((january['withholding_tax'], january['net_amount']), ('0', '10.00'))          # -1.50 + 2.00 = +0.50 refund
        self.assertIn('net refund', january['comment'])
        self.assertTrue(any('net tax refund' in w for w in batch.warnings), batch.warnings)

    def test_the_same_statement_twice_stages_once_and_the_rows_pass_the_normal_review(self):
        batch = self.stage(('one.pdf', basic()), ('two.pdf', basic()))
        self.assertEqual(batch.rows.count(), 2)
        self.assertEqual(set(batch.rows.values_list('status', flat=True)), {'valid'})

    def test_real_chain_without_any_rate_warning_when_the_rate_exists(self):
        batch = self.stage(('basic.pdf', basic()))
        self.assertEqual(batch.rows.first().rate, D('0.9'))


SAMPLES = Path(__file__).resolve().parent.parent / 'local' / 'samples'


@skipUnless((SAMPLES / 'Fidelity').is_dir(), 'owner-supplied Fidelity statements are not present (they are never committed)')
class LocalFidelityTests(SimpleTestCase):
    """Reads the owner's real statements; prints counts only. If local/samples/expected/fidelity.csv exists
    (payment_date,gross_amount,withholding_tax,net_amount,frequency) the settled rows must equal it."""

    def test_all_files_are_staged_without_gaps_and_the_settled_rows_match_the_owner_checked_file(self):
        from core.services import pdf_inventory
        entries = pdf_inventory.inventory(SAMPLES / 'Fidelity')
        self.assertEqual([e.name for e in entries if e.outcome not in ('staged', 'nothing to import')], [])
        self.assertEqual([e.flags for e in entries if e.flags], [])
        items = []
        for path in sorted((SAMPLES / 'Fidelity').glob('*.pdf')):
            items.append((path.name[-12:], sr.read_statement(path.read_bytes()).result))
        warnings = sr.reader_by_id('fidelity_stock_plan').settle(items)
        rows = [(r.data['payment_date'], r.data['gross_amount'], r.data['withholding_tax'], r.data['net_amount'], r.data['frequency'])
                for _l, res in items for r in res.rows]
        print(f'\nFidelity: {len(entries)} files, {len(rows)} rows, warnings: {warnings}')
        expected_file = SAMPLES / 'expected' / 'fidelity.csv'
        if expected_file.is_file():
            expected = [tuple(l.split(',')) for l in expected_file.read_text().splitlines()[1:] if l.strip()]
            self.assertEqual(sorted(rows), sorted(expected))
        else:
            print('Fidelity: no expected file (local/samples/expected/fidelity.csv); rows not compared')
