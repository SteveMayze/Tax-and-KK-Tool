"""Tax information and the verified checks (section 20(9) and 23(3) EStG). Synthetic data."""
import datetime
from decimal import Decimal as D

from django.test import TestCase

from core.models import AssessmentSettings, IncomeCategory, Organisation, Payment
from core.services import report_csv, reports
from core.services.conversion import convert_payment
from core.services.policies import tax

from .test_helpers import make_payment

Y = datetime.date(2026, 6, 15)


def map_tax(**mapping):
    for name, t in mapping.items():
        IncomeCategory.objects.filter(name=name.replace('_', ' ')).update(tax_income_type=t)


def add(gross, category, org='Org', country='', currency='EUR', rate=None, convert=True, date=Y, **kw):
    o, _ = Organisation.objects.get_or_create(name=org)
    if country != o.country:
        o.country = country
        o.save()
    p = make_payment(gross=str(gross), category=category, org=org, currency=currency, date=date, **kw)
    p.save()
    if convert:
        convert_payment(p, manual_rate=rate) if rate else convert_payment(p)
    return p


def check(year=2026):
    return {r.check.split(' (')[0]: r for r in tax.tax_checks(year)}


class SparerPauschbetragTests(TestCase):
    def setUp(self):
        map_tax(Interest='capital', Dividends='capital')

    def test_income_above_allowance(self):
        add(700, 'Interest', 'German Bank', 'DE')
        add(300, 'Dividends', 'Broker', 'DE')
        add(600, 'Interest', 'Aussie Bank', 'AU', currency='AUD', rate='1')        # 600 EUR, foreign
        r = check()['Sparer-Pauschbetrag']
        self.assertEqual(r.amount, D('1600'))
        self.assertIn('Allowance used 1,000.00 EUR, remaining 0.00 EUR', r.result)
        self.assertIn('above the allowance 600.00 EUR', r.result)
        self.assertIn('1,000 EUR (single assessment)', r.limit)

    def test_income_below_allowance(self):
        add(250, 'Interest')
        r = check()['Sparer-Pauschbetrag']
        self.assertIn('Allowance used 250.00 EUR, remaining 750.00 EUR', r.result)
        self.assertIn('above the allowance 0.00 EUR', r.result)

    def test_joint_assessment_doubles_it(self):
        add(1600, 'Interest')
        s = AssessmentSettings.load()
        s.joint_assessment = True
        s.save()
        r = check()['Sparer-Pauschbetrag']
        self.assertIn('2,000 EUR (joint assessment)', r.limit)
        self.assertIn('Allowance used 1,600.00 EUR, remaining 400.00 EUR', r.result)

    def test_no_capital_income(self):
        r = check()['Sparer-Pauschbetrag']
        self.assertEqual(r.amount, D('0'))
        self.assertIn('Allowance used 0.00 EUR, remaining 1,000.00 EUR', r.result)

    def test_exactly_at_allowance(self):
        add(1000, 'Interest')
        r = check()['Sparer-Pauschbetrag']
        self.assertIn('remaining 0.00 EUR', r.result)
        self.assertIn('above the allowance 0.00 EUR', r.result)

    def test_unmapped_unconverted_and_other_year_are_ignored(self):
        add(500, 'Interest', convert=False)                       # unconverted
        add(500, 'Rental')                                        # category not mapped
        add(500, 'Interest', date=datetime.date(2025, 6, 1))      # other year
        self.assertEqual(check()['Sparer-Pauschbetrag'].amount, D('0'))

    def test_costs_are_not_deductible_by_design(self):
        self.assertIn('Actual costs cannot be deducted', check()['Sparer-Pauschbetrag'].note)


class PrivateSaleFreigrenzeTests(TestCase):
    def setUp(self):
        map_tax(Capital_gains='private_sale')

    def result(self):
        return check()['Private sale gains Freigrenze']

    def test_below_limit_is_not_taxed(self):
        add('999.99', 'Capital gains')
        r = self.result()
        self.assertEqual(r.amount, D('999.99'))
        self.assertIn('Below the Freigrenze: no tax', r.result)

    def test_at_limit_whole_gain_is_taxable(self):
        add('1000.00', 'Capital gains')
        self.assertIn('WHOLE gain is taxable', self.result().result)

    def test_above_limit_whole_gain_is_taxable(self):
        add('5000', 'Capital gains')
        r = self.result()
        self.assertEqual(r.amount, D('5000'))
        self.assertIn('WHOLE gain is taxable', r.result)

    def test_losses_offset_gains_of_the_same_year(self):
        a = add(1500, 'Capital gains')
        loss = make_payment(gross='-600', kind='correction', corrects=a, date=Y, category='Capital gains')
        loss.save()
        convert_payment(loss)
        r = self.result()
        self.assertEqual(r.amount, D('900'))
        self.assertIn('Below the Freigrenze', r.result)

    def test_net_loss_is_described(self):
        a = add(100, 'Capital gains')
        loss = make_payment(gross='-300', kind='correction', corrects=a, date=Y, category='Capital gains')
        loss.save()
        convert_payment(loss)
        r = self.result()
        self.assertEqual(r.amount, D('-200'))
        self.assertIn('Net loss', r.result)

    def test_no_sales(self):
        r = self.result()
        self.assertEqual(r.amount, D('0'))
        self.assertIn('Below the Freigrenze', r.result)

    def test_limit_text_states_per_person_and_all_or_nothing(self):
        self.assertIn('per person (all-or-nothing)', self.result().limit)


class FlatTaxReferenceTests(TestCase):
    def test_rate_is_reference_only_no_amount(self):
        r = check()['Flat tax on capital income']
        self.assertIsNone(r.amount)
        self.assertIn('25', r.limit)
        self.assertEqual(r.result, 'No amount calculated')


class TaxSummaryTests(TestCase):
    def setUp(self):
        map_tax(Interest='capital', Rental='rental')
        add(700, 'Interest', 'German Bank', 'DE')
        add(100, 'Interest', 'German Bank', 'DE', date=datetime.date(2026, 7, 1))
        add(400, 'Interest', 'UK Bank', 'GB', currency='GBP', rate='1.2')           # 480 EUR, manual rate
        add(200, 'Interest', 'UK Bank', 'GB', currency='GBP', convert=False)       # unconverted
        add(900, 'Rental', 'Landlord Co', '')                                      # country not set
        add(50, 'Other', 'Misc', 'DE')                                            # category not mapped

    def rows(self):
        rows, _ = tax.tax_summary_rows(2026)
        return {(r['income_type'], r['country']): r for r in rows}

    def test_grouping_totals_and_flags(self):
        r = self.rows()
        de = r[('Capital assets (section 20)', 'DE')]
        self.assertEqual((de['payments'], de['gross_eur'], de['original'], de['unconverted'], de['flags']), (2, D('800'), 'EUR 800.00', 0, ''))
        gb = r[('Capital assets (section 20)', 'GB')]
        self.assertEqual((gb['payments'], gb['gross_eur'], gb['unconverted'], gb['manual_rates']), (2, D('480'), 1, 1))
        self.assertEqual(gb['original'], 'GBP 600.00')
        self.assertIn('Foreign source: treaty treatment and foreign-tax credit not applied', gb['flags'])
        unset = r[('Rental and leasing (section 21)', '(not set)')]
        self.assertIn('Organisation country not set', unset['flags'])
        unmapped = r[('Not mapped', 'DE')]
        self.assertIn('Category not mapped to an income type', unmapped['flags'])

    def test_unmapped_rows_sort_last(self):
        rows, _ = tax.tax_summary_rows(2026)
        self.assertEqual(rows[-1]['income_type'], 'Not mapped')

    def test_year_filter(self):
        add(10, 'Interest', 'German Bank', 'DE', date=datetime.date(2025, 1, 1))
        self.assertEqual(sum(r['payments'] for r in tax.tax_summary_rows(2026)[0]), 6)
        self.assertEqual(sum(r['payments'] for r in tax.tax_summary_rows(None)[0]), 7)


class TaxReportTests(TestCase):
    def setUp(self):
        map_tax(Interest='capital', Capital_gains='private_sale')
        add(1500, 'Interest', 'German Bank', 'DE')
        add(1200, 'Capital gains', 'Broker', 'DE')

    def test_checks_report_contents(self):
        rep = reports.REPORTS['tax_checks'].build(2026)
        self.assertEqual([r['check'].split(' (')[0] for r in rep.rows],
                         ['Sparer-Pauschbetrag', 'Private sale gains Freigrenze', 'Flat tax on capital income'])
        b = [t for k, t in rep.basis if k == 'Not applied']
        self.assertEqual(len(b), len(tax.NOT_APPLIED))
        self.assertTrue(any('Double-taxation treaties' in t for t in b))
        self.assertTrue(any('No tax amount is calculated' in t for t in b))
        self.assertIn('tax-information 1.0', dict(rep.basis)['Policy'])

    def test_checks_and_summary_csv(self):
        text = report_csv.render(reports.REPORTS['tax_checks'].build(2026))
        for needle in ('Not applied', 'Double-taxation treaties', 'WHOLE gain is taxable', 'Allowance used 1,000.00 EUR'):
            self.assertIn(needle, text)
        text = report_csv.render(reports.REPORTS['tax_summary'].build(None))
        for needle in ('grouped by tax income type and country', 'Capital assets (section 20)', 'Not applied'):
            self.assertIn(needle, text)

    def test_no_tax_amount_anywhere(self):
        text = report_csv.render(reports.REPORTS['tax_checks'].build(2026)).lower()
        self.assertNotIn('tax due', text)
        self.assertNotIn('tax payable', text)
