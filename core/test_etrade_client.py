"""Phase 18: E*TRADE client statements (USD). Synthetic PDFs only: invented company ("EXAMPLE CORP"), fund
("EXAMPLE LIQUIDITY FUND") and figures, worked out by hand next to each fixture."""
import datetime
import logging
from decimal import Decimal as D
from pathlib import Path
from unittest import skipUnless

from django.test import SimpleTestCase, TestCase

from core.services import etrade_client, organisations, pdf_imports, pdf_text
from core.services import imports as svc
from core.services import statement_readers as sr
from core.services.rates import FakeRateProvider

from .test_pdf_imports import UploadDirMixin
from .test_pdf_support import make_pdf

FUND = 'EXAMPLE LIQUIDITY FUND'
STOCK = 'EXAMPLE CORP'
SECRET = 'hunter2-secret-password'


def statement(period='February 1- March 31, 2025', rows=(), net='87.50', sweep=('85.00', '2.50'), qualified='100.00', other='2.50',
              total='102.50', tax='(15.00)', closing='1,500.00', messages=(f'Fund documents password: {SECRET}',), summary_other=True):
    """Default: fund dividend 2.50 + company dividend 100.00 with 15.00 withheld = 87.50 net; the sweep invests 85.00 + 2.50."""
    lines = [f'CLIENT STATEMENT For the Period {period}', 'Beginning Total Value (as of 2/1/25) $1,000.00',
             f'Ending Total Value (as of 3/31/25) ${closing}', 'Account Summary', f'Total Assets $1,500.00 Tax Withholdings {tax} {tax}',
             'INCOME AND DISTRIBUTION SUMMARY', f'Qualified Dividends ${qualified} ${qualified}']
    if summary_other and D(other):
        lines.append(f'Other Dividends ${other} ${other}')
    lines += [f'Income And Distributions ${total} ${total}', 'Tax-Exempt Income — —', f'TOTAL INCOME AND DISTRIBUTIONS ${total} ${total}',
              'ACTIVITY', 'CASH FLOW ACTIVITY BY DATE', 'Activity Settlement', 'Date Date Activity Type Description Quantity Price Credits/(Debits)', *rows,
              f'NET CREDITS/(DEBITS) ${net}', 'MONEY MARKET FUND (MMF) AND BANK DEPOSIT PROGRAM ACTIVITY', 'Activity',
              'Date Activity Type Description Credits/(Debits)']
    lines += [f'2/{3 + i} Automatic Investment {FUND} ${amount}' for i, amount in enumerate(sweep)]
    lines += ['NET ACTIVITY FOR PERIOD $' + net, 'MESSAGES', *messages, 'Standard disclosures follow.']
    return [lines]


DEFAULT_ROWS = (f'2/3 Dividend {FUND} $2.50', 'DIV PAYMENT', f'2/14 Qualified Dividend {STOCK} 100.00', f'2/14 Tax Withholding {STOCK} (15.00)')


def read(pages):
    return sr.read_statement(make_pdf(pages))


class EtradeReaderTests(SimpleTestCase):
    def test_a_stock_dividend_with_withholding_and_a_fund_dividend_give_two_rows(self):
        outcome = read(statement(rows=DEFAULT_ROWS))
        self.assertEqual(outcome.reader_id, 'etrade_client', outcome.error)
        fund, stock = outcome.result.rows
        self.assertEqual((fund.data['payment_date'], fund.data['gross_amount'], fund.data['withholding_tax'], fund.data['net_amount'],
                          fund.data['frequency'], fund.data['organisation']),
                         ('2025-02-03', '2.50', '0', '2.50', 'monthly', 'E*Trade Example Liquidity Fund'))
        self.assertEqual((stock.data['payment_date'], stock.data['gross_amount'], stock.data['withholding_tax'], stock.data['net_amount'],
                          stock.data['frequency'], stock.data['organisation']),
                         ('2025-02-14', '100.00', '15.00', '85.00', 'quarterly', 'E*Trade Example Corp'))      # 100.00 - 15.00
        for r, category in ((fund, 'Interest'), (stock, 'Dividends')):      # Phase 32: fund income is Interest
            d = r.data
            self.assertEqual((d['currency'], d['category'], d['expenses']), ('USD', category, '0'))
        self.assertEqual(fund.data['comment'], 'Fund dividend via E*TRADE.')
        self.assertEqual(stock.data['comment'], 'Qualified dividend via E*TRADE.')
        self.assertEqual(outcome.result.notices, [])                       # sweep and tax checks both ran and closed
        self.assertEqual(outcome.result.period, (datetime.date(2025, 2, 1), datetime.date(2025, 3, 31)))

    def test_provenance_cites_the_dividend_line_and_the_withholding_line(self):
        fund, stock = read(statement(rows=DEFAULT_ROWS)).result.rows
        self.assertEqual(stock.provenance['gross_amount'], (1, f'2/14 Qualified Dividend {STOCK} 100.00'))
        self.assertEqual(stock.provenance['withholding_tax'], (1, f'2/14 Tax Withholding {STOCK} (15.00)'))
        self.assertNotIn('withholding_tax', fund.provenance)

    def test_year_end_period_gives_each_date_its_year(self):                # G5
        rows = (f'12/31 Dividend {FUND} $3.00', f'1/2 Dividend {FUND} $4.00')
        outcome = read(statement(period='December 1- January 31, 2026', rows=rows, net='7.00', sweep=('3.00', '4.00'), qualified='0.00',
                                 other='7.00', total='7.00', tax='—'))
        self.assertEqual([r.data['payment_date'] for r in outcome.result.rows], ['2025-12-31', '2026-01-02'], outcome.error)
        self.assertEqual(outcome.result.period, (datetime.date(2025, 12, 1), datetime.date(2026, 1, 31)))

    def test_a_january_fund_dividend_reportable_for_the_prior_year_keeps_its_date_and_the_remark(self):       # E1
        rows = (f'1/2 Dividend {FUND} Transaction Reportable for the Prior Year. $5.00', f'1/15 Qualified Dividend {STOCK} 50.00',
                f'1/15 Tax Withholding {STOCK} (7.50)')
        # the statement's own totals leave the prior-year item out: no "Other Dividends" row, total = 50.00
        outcome = read(statement(period='January 1-31, 2025', rows=rows, net='47.50', sweep=('5.00', '42.50'), qualified='50.00',
                                 total='50.00', tax='(7.50)', summary_other=False))
        self.assertEqual(outcome.error, '')
        fund, stock = outcome.result.rows
        self.assertEqual((fund.data['payment_date'], fund.data['gross_amount'], fund.data['organisation']), ('2025-01-02', '5.00', 'E*Trade Example Liquidity Fund'))
        self.assertEqual(fund.data['comment'], 'Fund dividend via E*TRADE. The statement marks this transaction as reportable for the prior year.')
        self.assertEqual(stock.data['withholding_tax'], '7.50')

    def test_dividend_amounts_are_read_as_printed_when_they_change_between_statements(self):      # E6
        a = read(statement(rows=DEFAULT_ROWS)).result.rows[1].data
        rows = (f'2/3 Dividend {FUND} $2.50', f'2/14 Qualified Dividend {STOCK} 120.00', f'2/14 Tax Withholding {STOCK} (18.00)')
        b = read(statement(rows=rows, net='104.50', sweep=('102.00', '2.50'), qualified='120.00', total='122.50', tax='(18.00)')).result.rows[1].data
        self.assertEqual((a['gross_amount'], a['withholding_tax']), ('100.00', '15.00'))
        self.assertEqual((b['gross_amount'], b['withholding_tax'], b['net_amount']), ('120.00', '18.00', '102.00'))

    def test_a_cash_flow_total_one_cent_off_is_refused(self):               # E7
        outcome = read(statement(rows=DEFAULT_ROWS, net='87.51', sweep=('85.01', '2.50')))
        self.assertIsNone(outcome.result)
        self.assertIn('do not add up to the net', outcome.error)

    def test_a_sweep_that_does_not_match_the_net_is_refused(self):
        self.assertIn('sweep table', read(statement(rows=DEFAULT_ROWS, sweep=('85.00', '2.51'))).error)

    def test_income_summary_that_disagrees_with_the_lines_is_refused(self):
        self.assertIn('income and distribution summary', read(statement(rows=DEFAULT_ROWS, qualified='100.01', total='102.51')).error)

    def test_tax_total_that_disagrees_with_the_withholding_lines_is_refused(self):
        self.assertIn('tax withholdings of the account summary', read(statement(rows=DEFAULT_ROWS, tax='(14.00)')).error)

    def test_a_withholding_line_with_no_dividend_is_refused(self):          # E2
        rows = (*DEFAULT_ROWS, f'2/20 Tax Withholding OTHER CORP (1.00)')
        outcome = read(statement(rows=rows, net='86.50', sweep=('84.00', '2.50'), tax='(16.00)'))
        self.assertIn('no matching dividend', outcome.error)

    def test_two_withholding_lines_for_one_dividend_are_refused(self):
        rows = (*DEFAULT_ROWS, f'2/14 Tax Withholding {STOCK} (1.00)')
        self.assertIn('Two withholding lines', read(statement(rows=rows, net='86.50', sweep=('84.00', '2.50'), tax='(16.00)')).error)

    def test_a_company_dividend_without_a_withholding_line_is_refused(self):
        rows = (f'2/3 Dividend {FUND} $2.50', f'2/14 Qualified Dividend {STOCK} 100.00')
        outcome = read(statement(rows=rows, net='102.50', sweep=('100.00', '2.50'), tax='—'))
        self.assertIn('no withholding line', outcome.error)

    def test_an_activity_type_that_is_not_listed_is_refused_naming_it(self):          # G12
        rows = (*DEFAULT_ROWS, '2/20 Interest Income FUND 0.50')
        outcome = read(statement(rows=rows, net='88.00', sweep=('85.50', '2.50')))
        self.assertIn('Interest Income', outcome.error)

    def test_purchases_and_sales_are_a_notice_with_type_and_date_only(self):
        rows = (*DEFAULT_ROWS, '2/20 Sold EXAMPLE CORP 1.00')
        outcome = read(statement(rows=rows, net='88.50', sweep=('86.00', '2.50')))
        self.assertEqual(outcome.error, '')
        self.assertEqual(len(outcome.result.rows), 2)
        self.assertIn('Sold on 2025-02-20 is not imported.', outcome.result.notices)

    def test_dash_means_zero_and_parentheses_mean_negative(self):                    # E4
        rows = (f'2/3 Dividend {FUND} $2.50', f'2/3 Tax Withholding {FUND} —')
        outcome = read(statement(rows=rows, net='2.50', sweep=('2.50',), qualified='0.00', total='2.50', tax='—'))
        self.assertEqual(outcome.error, '')
        self.assertEqual(outcome.result.rows[0].data['withholding_tax'], '0')

    def test_a_statement_with_no_activity_has_nothing_to_import(self):               # E5
        pages = statement(period='April 1-30, 2025', rows=(), net='0.00', sweep=(), qualified='0.00', other='0.00', total='0.00', tax='—')
        outcome = read(pages)
        self.assertEqual((outcome.error, outcome.result.rows), ('', []))

    def test_other_documents_are_not_claimed(self):
        self.assertIsNone(read([['A letter about nothing']]).reader_id)

    def test_the_messages_section_is_never_read_stored_or_logged(self):            # E8
        pages = statement(rows=DEFAULT_ROWS)
        with self.assertNoLogs(level=logging.DEBUG):
            outcome = read(pages)
        blob = repr([(r.data, r.provenance) for r in outcome.result.rows]) + repr(outcome.result.notices) + outcome.error + repr(outcome.result.fingerprint)
        self.assertNotIn(SECRET, blob)
        self.assertNotIn('password', blob.lower())
        # even a malformed message text cannot break or leak: the reader stops at the MESSAGES heading
        weird = statement(rows=DEFAULT_ROWS, messages=('2/3 Dividend 9,999.99', SECRET))
        self.assertEqual(len(read(weird).result.rows), 2)


class EtradeStagingTests(UploadDirMixin, TestCase):
    PROVIDER = FakeRateProvider({('USD', datetime.date(2025, 2, 3)): D('0.9'), ('USD', datetime.date(2025, 2, 14)): D('0.9')})

    def test_identical_text_with_different_bytes_stages_once(self):         # G7
        a, b = statement(rows=DEFAULT_ROWS), statement(rows=DEFAULT_ROWS)
        b[0].append('Page 2 of 8')
        self.assertNotEqual(make_pdf(a), make_pdf(b))
        batch = pdf_imports.stage_pdf_batch([('one.pdf', make_pdf(a)), ('two.pdf', make_pdf(b))], self.PROVIDER)
        self.assertEqual(batch.rows.count(), 2)
        self.assertTrue(any('same statement as one.pdf' in w for w in batch.warnings), batch.warnings)

    def test_real_chain_to_staged_rows_with_the_proposed_rate(self):
        batch = pdf_imports.stage_pdf_batch([('stmt.pdf', make_pdf(statement(rows=DEFAULT_ROWS)))], self.PROVIDER)
        self.assertEqual(set(batch.rows.values_list('status', flat=True)), {'valid'})
        self.assertEqual(batch.rows.first().rate, D('0.9'))

    def test_messages_text_never_reaches_the_staged_data(self):
        batch = pdf_imports.stage_pdf_batch([('stmt.pdf', make_pdf(statement(rows=DEFAULT_ROWS)))], self.PROVIDER)
        blob = repr(list(batch.rows.values('data', 'provenance', 'source_name'))) + repr(batch.warnings) + batch.file_name
        self.assertNotIn(SECRET, blob)

    def test_the_same_company_gets_the_identical_organisation_string_from_any_broker_spelling(self):
        # Phase 19 will add the Fidelity reader; both use the one shared function, whatever capitalisation the broker prints.
        for printed in ('EXAMPLE CORP', 'Example Corp'):
            self.assertEqual(organisations.tidy_security_name(printed), 'Example Corp')
        row = read(statement(rows=DEFAULT_ROWS)).result.rows[1].data
        self.assertEqual(row['organisation'], 'E*Trade ' + organisations.tidy_security_name('EXAMPLE CORP'))


SAMPLES = Path(__file__).resolve().parent.parent / 'local' / 'samples'


@skipUnless((SAMPLES / 'ETrade').is_dir(), 'owner-supplied E*TRADE statements are not present (they are never committed)')
class LocalEtradeTests(SimpleTestCase):
    """Reads the owner's real statements; prints counts only. If local/samples/expected/etrade.csv exists
    (payment_date,gross_amount,withholding_tax,net_amount,frequency) the rows must equal it."""

    def test_all_files_are_staged_without_gaps_or_name_mismatches(self):
        from core.services import pdf_inventory
        entries = pdf_inventory.inventory(SAMPLES / 'ETrade')
        self.assertTrue(entries)
        self.assertEqual([e.name for e in entries if not e.outcome == 'staged'], [])
        self.assertEqual([e.flags for e in entries if e.flags], [])
        rows = []
        for path in sorted((SAMPLES / 'ETrade').glob('*.pdf')):
            rows += [(r.data['payment_date'], r.data['gross_amount'], r.data['withholding_tax'], r.data['net_amount'], r.data['frequency'])
                     for r in sr.read_statement(path.read_bytes()).result.rows]
        print(f'\nE*TRADE: {len(entries)} files staged, {len(rows)} rows, no period gaps, no name/period mismatches')
        expected_file = SAMPLES / 'expected' / 'etrade.csv'
        if expected_file.is_file():
            expected = [tuple(l.split(',')) for l in expected_file.read_text().splitlines()[1:] if l.strip()]
            self.assertEqual(sorted(rows), sorted(expected))
        else:
            print('E*TRADE: no expected file (local/samples/expected/etrade.csv); rows not compared')
