"""Phase 32 (ADR 0033): broker prefix on the organisation, fund income as Interest, and the interleaved income summary.
Synthetic text PDFs only; invented names ("EXAMPLE MONEY MARKET FUND", "EXAMPLE STOCK CO"). Each B-case is a test name."""
import datetime
from decimal import Decimal as D

from django.test import SimpleTestCase, TestCase

from core.models import IncomeCategory, Organisation, Payment, ReportingMonth
from core.services import etrade_client, fidelity_stock_plan, organisations, pdf_imports
from core.services.organisations import ETRADE, FIDELITY, broker_category, broker_organisation, tidy_security_name
from core.services.rates import FakeRateProvider

from . import test_etrade_client as et
from . import test_fidelity_stock_plan as fi
from .test_pdf_imports import UploadDirMixin
from .test_pdf_support import make_pdf

RATES = FakeRateProvider({('USD', datetime.date(2025, d[0], d[1])): D('0.9') for d in ((1, 23), (1, 31), (2, 3), (2, 14), (2, 28))})


class HelperTests(SimpleTestCase):
    def test_B3_fid_abbreviation_is_replaced_not_kept(self):
        self.assertEqual(broker_organisation(FIDELITY, 'FID Example Money Market Fund'), 'Fidelity Example Money Market Fund')

    def test_B4_no_abbreviation_means_prefix_only_and_fid_inside_a_word_is_not_replaced(self):
        self.assertEqual(broker_organisation(FIDELITY, 'Example Money Market Fund'), 'Fidelity Example Money Market Fund')
        self.assertEqual(broker_organisation(FIDELITY, 'Fido Example Fund'), 'Fidelity Fido Example Fund')
        self.assertEqual(broker_organisation(FIDELITY, 'Example FID Fund'), 'Fidelity Example FID Fund')
        self.assertEqual(broker_organisation(FIDELITY, 'Fiduciary Example'), 'Fidelity Fiduciary Example')

    def test_B4a_a_name_that_already_starts_with_the_broker_is_not_doubled(self):
        self.assertEqual(broker_organisation(FIDELITY, 'Fidelity Example Cash Reserves'), 'Fidelity Example Cash Reserves')
        self.assertEqual(broker_organisation(FIDELITY, 'FIDELITY Example Cash Reserves'), 'Fidelity Example Cash Reserves')
        for printed in ('E*Trade Example Fund', 'E*TRADE Example Fund', 'e*trade Example Fund'):
            self.assertEqual(broker_organisation(ETRADE, printed), 'E*Trade Example Fund')

    def test_single_spaces_only(self):
        self.assertEqual(broker_organisation(FIDELITY, 'FID  Example   Fund'), 'Fidelity Example Fund')
        self.assertEqual(broker_organisation(ETRADE, ' Example  Corp '), 'E*Trade Example Corp')

    def test_B6_the_same_security_at_both_brokers_is_two_organisations(self):
        self.assertNotEqual(broker_organisation(ETRADE, 'Example Stock Co'), broker_organisation(FIDELITY, 'Example Stock Co'))

    def test_B10_tidy_security_name_is_unchanged_for_other_readers(self):
        self.assertEqual(tidy_security_name('EXAMPLE STOCK CO'), 'Example Stock Co')
        self.assertEqual(tidy_security_name('FID EXAMPLE FUND'), 'FID Example Fund')           # no prefix logic inside it
        self.assertEqual(tidy_security_name('ENDEAVOUR GROUP LIMITED'), 'Endeavour Group Limited')
        self.assertEqual(organisations.BANK_ORGANISATIONS['hsbc_savings'], 'HSBC UK (Flexible Saver)')

    def test_categories(self):
        self.assertEqual((broker_category(True), broker_category(False)), ('Interest', 'Dividends'))


class EtradeRowTests(SimpleTestCase):
    def test_B1_B2_fund_is_interest_stock_is_dividends_with_the_broker_prefix(self):
        fund, stock = et.read(et.statement(rows=et.DEFAULT_ROWS)).result.rows
        self.assertEqual((fund.data['organisation'], fund.data['category']), ('E*Trade Example Liquidity Fund', 'Interest'))
        self.assertEqual((stock.data['organisation'], stock.data['category']), ('E*Trade Example Corp', 'Dividends'))
        # everything else as before
        self.assertEqual((fund.data['gross_amount'], fund.data['withholding_tax'], fund.data['net_amount'], fund.data['frequency'], fund.data['comment']),
                         ('2.50', '0', '2.50', 'monthly', 'Fund dividend via E*TRADE.'))
        self.assertEqual((stock.data['gross_amount'], stock.data['withholding_tax'], stock.data['net_amount'], stock.data['frequency'], stock.data['comment']),
                         ('100.00', '15.00', '85.00', 'quarterly', 'Qualified dividend via E*TRADE.'))

    def test_B4a_an_etrade_name_that_already_begins_with_the_broker(self):
        rows = ('2/3 Dividend E*TRADE EXAMPLE LIQUIDITY FUND $2.50', 'DIV PAYMENT')
        pages = et.statement(rows=rows, net='2.50', sweep=('2.50',), qualified='0.00', other='2.50', total='2.50', tax='—')
        fund = et.read(pages).result.rows[0]
        self.assertEqual(fund.data['organisation'], 'E*Trade Example Liquidity Fund')


def fidelity_funds(first_withholding='3.00'):
    """Two core funds with a row on the same date, 01/31: the first (name already begins with Fidelity) 20.00 with 3.00 withheld,
    the second (printed FID ...) 10.00 with nothing withheld. Income 30.00; tax lines sum -3.00."""
    first, second = 'FIDELITY EXAMPLE CASH 888888888', 'FID EXAMPLE MONEY MARKET 999999999'
    return fi.statement(
        income_rows=[*fi.income('01/31', first, '$20.00', 'RESERVES'), *fi.income('01/31', second, '$10.00', 'FUND')],
        income_total='30.00', tax_total=first_withholding,
        tax_rows=fi.tax('01/31', 'FIDELITY EXAMPLE CASH RESERVES', 'Non-Resident Tax', f'-{first_withholding}'),
        core_rows=('01/31 CASH Reinvestment FIDELITY EXAMPLE CASH RESERVES 1.000 1.0000 1.00 100.00',
                   '01/31 CASH Reinvestment FID EXAMPLE MONEY MARKET FUND 1.000 1.0000 1.00 100.00'))


class FidelityRowTests(SimpleTestCase):
    def test_B3_B5_fid_fund_and_stock_rows(self):
        stock, fund = fi.read(fi.basic()).result.rows
        self.assertEqual((stock.data['organisation'], stock.data['category']), ('Fidelity Example Corp', 'Dividends'))
        self.assertEqual((fund.data['organisation'], fund.data['category']), ('Fidelity Example Cash Reserves Portfolio', 'Interest'))

    def test_B3_the_fid_abbreviation_of_a_printed_fund_is_replaced(self):
        pages = fi.statement(income_rows=fi.income('01/31', 'FID EXAMPLE MONEY MARKET 999999999', '$10.00', 'FUND'), income_total='10.00',
                             core_rows=('01/31 CASH Reinvestment FID EXAMPLE MONEY MARKET FUND 1.000 1.0000 1.00 100.00',))
        row = fi.read(pages).result.rows[0]
        self.assertEqual((row.data['organisation'], row.data['category']), ('Fidelity Example Money Market Fund', 'Interest'))

    def test_B4_a_fund_without_the_abbreviation_gets_the_prefix_only(self):
        pages = fi.statement(income_rows=fi.income('01/31', 'EXAMPLE MONEY MARKET 999999999', '$10.00', 'FUND'), income_total='10.00',
                             core_rows=('01/31 CASH Reinvestment EXAMPLE MONEY MARKET FUND 1.000 1.0000 1.00 100.00',))
        self.assertEqual(fi.read(pages).result.rows[0].data['organisation'], 'Fidelity Example Money Market Fund')

    def test_B4a_a_fund_that_already_begins_with_fidelity_keeps_its_withholding_and_is_not_doubled(self):
        first, second = fi.read(fidelity_funds()).result.rows
        self.assertEqual((first.data['organisation'], first.data['category'], first.data['withholding_tax']),
                         ('Fidelity Example Cash Reserves', 'Interest', '3.00'))

    def test_B8_two_funds_on_one_date_stay_two_rows_each_with_its_own_name(self):
        result = fi.read(fidelity_funds()).result
        self.assertEqual(len(result.rows), 2)
        first, second = result.rows
        self.assertEqual({r.data['payment_date'] for r in result.rows}, {'2025-01-31'})
        self.assertEqual([(r.data['organisation'], r.data['category'], r.data['gross_amount'], r.data['withholding_tax']) for r in (first, second)],
                         [('Fidelity Example Cash Reserves', 'Interest', '20.00', '3.00'),
                          ('Fidelity Example Money Market Fund', 'Interest', '10.00', '0')])

    def test_B12_notices_are_unchanged(self):
        pages = fi.statement(income_rows=fi.fund_income('01/31', '3.00'), income_total='3.00',
                             sections=('Securities Bought & Sold', '09/24 EXAMPLE STOCK CO RSU 000000000 You Bought 1.000 $1.00 - -', 'Total Securities Bought - -'))
        notices = fi.read(pages).result.notices
        self.assertEqual(notices, ['Not imported: shares bought (a delivery or purchase) on 09/24.'])
        self.assertEqual(et.read(et.statement(rows=(*et.DEFAULT_ROWS, '2/20 Journal Cash $0.00'), net='87.50')).result.notices[:1],
                         ['Journal on 2025-02-20 is not imported.'])


class InterleavedSummaryTests(SimpleTestCase):
    """B14: the heading shares a printed line with 'Credit Balance' and the 'Total' line is interleaved with other text."""

    def interleaved(self, total='43.00'):
        pages = fi.basic()
        lines = [l.replace('Income Summary', 'Credit Balance 109.07 Income Summary') if l == 'Income Summary' else l for l in pages[0]]
        lines = [f'cash dividends, and interest payments which have not been transferred, Total ${total} ${total}' if l.startswith('Total $') else l
                 for l in lines]
        return [lines]

    def test_B14_the_total_is_found_and_the_check_runs(self):
        outcome = fi.read(self.interleaved())
        self.assertEqual(outcome.reader_id, 'fidelity_stock_plan', outcome.error)
        self.assertNotIn('The income summary was not found; that check was skipped.', outcome.result.notices)

    def test_B14_a_disagreeing_interleaved_total_is_refused(self):
        outcome = fi.read(self.interleaved(total='99.00'))
        self.assertIsNone(outcome.result)
        self.assertIn('income summary does not agree', outcome.error)

    def test_B14_a_statement_without_any_summary_still_gives_the_notice(self):
        pages = [[l for l in fi.basic()[0] if not l.startswith(('Income Summary', 'This Period', 'Taxable', 'Total $'))]]
        self.assertIn('The income summary was not found; that check was skipped.', fi.read(pages).result.notices)


class StagingTests(UploadDirMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.cat = IncomeCategory.objects.get_or_create(name='Dividends')[0]

    def stored(self, org, date, gross):
        return Payment.objects.create(month=ReportingMonth.for_date(date), organisation=Organisation.objects.get_or_create(name=org)[0],
                                      category=self.cat, payment_date=date, currency='USD', gross_amount=D(gross), frequency='quarterly')

    def stage(self, *named):
        return pdf_imports.stage_pdf_batch([(n, make_pdf(p)) for n, p in named], RATES)

    def feb14_fidelity(self):
        return fi.statement(period='February 1, 2025 - February 28, 2025', income_rows=fi.income('02/14', fi.STOCK_INCOME, '$100.00'),
                            income_total='100.00', tax_total='15.00', tax_rows=fi.tax('02/14', fi.STOCK_TAX, 'Non-Resident Tax', '-15.00'), core_rows=())

    def test_B7_a_payment_stored_under_the_new_name_makes_the_reupload_a_duplicate_and_the_other_broker_is_not(self):
        self.stored('E*Trade Example Corp', datetime.date(2025, 2, 14), '100.00')
        etrade = self.stage(('e.pdf', et.statement(rows=et.DEFAULT_ROWS)))
        by_org = {r.data['organisation']: r.status for r in etrade.rows.all()}
        self.assertEqual(by_org['E*Trade Example Corp'], 'duplicate')
        self.assertEqual(by_org['E*Trade Example Liquidity Fund'], 'valid')
        fidelity = self.stage(('f.pdf', self.feb14_fidelity()))                # same date and amount, other broker
        self.assertEqual([r.status for r in fidelity.rows.all()], ['valid'])

    def test_B7_the_old_name_is_no_longer_recognised_so_the_owner_must_keep_the_new_names(self):
        self.stored('Example Corp', datetime.date(2025, 2, 14), '100.00')
        etrade = self.stage(('e.pdf', et.statement(rows=et.DEFAULT_ROWS)))
        self.assertEqual({r.data['organisation']: r.status for r in etrade.rows.all()}['E*Trade Example Corp'], 'valid')

    def test_B9_settlement_matches_by_normalised_security_name_not_by_the_organisation_string(self):
        batch = self.stage(('a-jan.pdf', fi.jan_with_original_withholding()), ('b-feb.pdf', fi.feb_with_reversal_and_rebooking()))
        january = batch.rows.get(data__payment_date='2025-01-31').data
        self.assertEqual((january['organisation'], january['category'], january['withholding_tax']),
                         ('Fidelity Example Cash Reserves Portfolio', 'Interest', '0.75'))
        self.assertFalse(any('not in this upload' in w for w in batch.warnings), batch.warnings)
        alone = self.stage(('x.pdf', fi.statement(period='January 1, 2026 - January 31, 2026', income_total='0.00', tax_total='0.75', core_rows=(),
                            tax_rows=[*fi.tax('12/15', fi.FUND_TAX, 'Adj Non-Resident Tax', '1.50', flag='A'),
                                      *fi.tax('12/15', fi.FUND_TAX, 'Non-Resident Tax', '-0.75', flag='A')])), ('y.pdf', fi.basic()))
        self.assertIn('Tax postings for events not in this upload: 2 (not staged).', alone.warnings)

    def test_B8_two_funds_on_one_date_are_not_duplicates_of_each_other(self):
        batch = self.stage(('f.pdf', fidelity_funds()))
        self.assertEqual([r.status for r in batch.rows.all()], ['valid', 'valid'])


class ReportAndToolTests(UploadDirMixin, TestCase):
    """B11: committed broker rows show up under Interest and Dividends in the existing reports, with no report code changed."""

    def commit(self):
        files = [('e.pdf', make_pdf(et.statement(rows=et.DEFAULT_ROWS))), ('f.pdf', make_pdf(fi.basic()))]
        provider = FakeRateProvider({('USD', datetime.date(2025, *d)): D('0.9') for d in ((2, 3), (2, 14), (1, 23), (1, 31))})
        from core.services import imports as svc
        batch = pdf_imports.stage_pdf_batch(files, provider)
        svc.commit_batch(batch)
        return batch

    def test_B11_by_category_and_payment_reports(self):
        from core.services import reports
        self.commit()
        rows = {r['name']: r for r in reports.by_category(None).rows}
        self.assertEqual(set(rows), {'Interest', 'Dividends'})
        self.assertEqual(rows['Interest']['payments'], 2)           # one fund per broker
        self.assertEqual(rows['Dividends']['payments'], 2)          # one stock dividend per broker
        orgs = {r['name'] for r in reports.by_organisation(None).rows}
        self.assertEqual(orgs, {'E*Trade Example Liquidity Fund', 'E*Trade Example Corp', 'Fidelity Example Corp',
                                'Fidelity Example Cash Reserves Portfolio'})

    def test_summary_tool_is_read_only_and_groups_by_organisation_and_category(self):
        import importlib.util, io
        from pathlib import Path
        self.commit()
        spec = importlib.util.spec_from_file_location('broker_summary_tool', Path(__file__).resolve().parent.parent / 'tools' / 'broker_summary.py')
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        before = list(Payment.objects.order_by('pk').values_list('pk', 'gross_amount', 'organisation_id'))
        rows = tool.summary(2025, 'fidelity')
        self.assertEqual(sorted((o, c, ccy, n, g, w, net) for o, c, ccy, n, g, w, net in rows),
                         [('Fidelity Example Cash Reserves Portfolio', 'Interest', 'USD', 1, D('3.00'), D('0.00'), D('3.00')),
                          ('Fidelity Example Corp', 'Dividends', 'USD', 1, D('40.00'), D('6.00'), D('34.00'))])
        self.assertEqual(list(Payment.objects.order_by('pk').values_list('pk', 'gross_amount', 'organisation_id')), before)
