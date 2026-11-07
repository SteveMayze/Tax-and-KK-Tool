"""SBK contribution estimate, checked against figures worked out by hand (synthetic data).

2026 dataset (all EUR). Category mapping: Pension -> pension, Rental -> rental, Interest -> capital,
Capital gains -> one_off, Other -> not mapped.
  Pension          1,000.00 every month Jan-Dec                         -> 1,000 per month
  Rental             500.00 each month Jul-Dec (3,000); inputs: costs 600, months 7-12
                                                                        -> (3,000-600)/6 = 400 per month Jul-Dec
  Interest           100.00 (2026-03-31) + 150.00 (2026-09-30) = 250; no inputs
                                                                        -> (250-51 flat)/12 = 199/12 = 16.5833.. per month
  Capital gains    6,000.00 on 2026-05-10 -> 500 per month May 2026-Apr 2027;
                   2,400.00 on 2025-11-20 -> 200 per month Nov 2025-Oct 2026
  Other              777.00 (unmapped, excluded);  one unconverted GBP 50 Pension payment (excluded)

Monthly base: Jan-Apr 1,216.58 (below minimum 1,318.33 -> minimum), May-Jun 1,716.58,
Jul-Oct 2,116.58, Nov-Dec 1,916.58. Rates: health 14.6 + 3.8, care 4.2.
Hand-rounded (half-up) contributions per month, health / care:
  minimum 1,318.33...: 192.48 + 50.10 = 242.58 / 55.37        (x4)
  1,716.583 (= 20599/12): 250.62 + 65.23 = 315.85 / 72.0965 -> 72.10   (x2)
  2,116.583 (= 25399/12): 309.02 + 80.43 = 389.45 / 88.8965 -> 88.90   (x4)
  1,916.583 (= 22999/12): 279.82 + 72.83 = 352.65 / 80.4965 -> 80.50   (x2)
Year: health 970.32 + 631.70 + 1,557.80 + 705.30 = 3,865.12; care 221.48 + 144.20 + 355.60 + 161.00 = 882.28; total 4,747.40
"""
import datetime
from decimal import Decimal as D

from django.core.exceptions import ValidationError
from django.test import TestCase

from core.models import AnnualInput, AssessmentSettings, IncomeCategory, Payment, ReportingYear
from core.services import report_csv, reports
from core.services.conversion import convert_payment
from core.services.policies import sbk

from .test_helpers import make_payment


def map_categories(**mapping):
    for name, treatment in mapping.items():
        IncomeCategory.objects.filter(name=name.replace('_', ' ')).update(sbk_treatment=treatment)


def add(gross, date, category, org='Org', convert=True, **kw):
    p = make_payment(gross=str(gross), date=date, category=category, org=org, **kw)
    p.save()
    if convert:
        convert_payment(p, manual_rate='0.5') if kw.get('currency', 'EUR') != 'EUR' else convert_payment(p)
    return p


def use_general_rate():
    """The hand calculations in these tests are at the general rate (14.6 %); the default setting is the reduced rate
    since SBK's letter of 2026-11-06, so the tests select the general rate explicitly."""
    AssessmentSettings.objects.update_or_create(pk=1, defaults={'kv_rate': 'general'})


def build_2026():
    use_general_rate()
    map_categories(Pension='pension', Rental='rental', Interest='capital', Capital_gains='one_off')
    for m in range(1, 13):
        add(1000, datetime.date(2026, m, 15), 'Pension', 'Pension Fund')
    for m in range(7, 13):
        add(500, datetime.date(2026, m, 3), 'Rental', 'Tenant')
    y = ReportingYear.objects.get(year=2026)
    AnnualInput.objects.create(year=y, treatment='rental', costs_eur=D('600'), first_month=7, last_month=12)
    add(100, datetime.date(2026, 3, 31), 'Interest', 'Bank')
    add(150, datetime.date(2026, 9, 30), 'Interest', 'Bank')
    add(6000, datetime.date(2026, 5, 10), 'Capital gains', 'Broker', frequency='one_off')
    add(2400, datetime.date(2025, 11, 20), 'Capital gains', 'Broker', frequency='one_off')
    add(777, datetime.date(2026, 2, 2), 'Other', 'Misc')
    add(50, datetime.date(2026, 8, 5), 'Pension', 'Pension Fund', currency='GBP', convert=False)


class SbkParametersTests(TestCase):
    def test_2026_parameters_and_minimum(self):
        p = sbk.parameters_for(2026)
        self.assertEqual((p.bbg_monthly, p.bezugsgroesse_monthly), (D('5812.50'), D('3955')))
        self.assertEqual(round(p.min_monthly, 2), D('1318.33'))
        self.assertEqual((p.kv_general_pct, p.zusatz_pct, p.pflege_base_pct), (D('14.6'), D('3.8'), D('3.6')))

    def test_unverified_years_are_refused(self):
        for year in (2024, 2027):
            with self.assertRaises(sbk.PolicyUnavailable) as cm:
                sbk.parameters_for(year)
            self.assertIn('2025, 2026', str(cm.exception))

    def test_2025_parameters_are_the_2025_figures_not_a_copy_of_2026(self):
        p = sbk.parameters_for(2025)
        self.assertEqual((p.bbg_monthly, p.bezugsgroesse_monthly), (D('5512.50'), D('3745')))
        self.assertEqual(round(p.min_monthly, 2), D('1248.33'))
        self.assertEqual((p.kv_reduced_pct, p.zusatz_pct, p.pflege_base_pct, p.pflege_childless_surcharge_pct),
                         (D('14.0'), D('3.8'), D('3.6'), D('0.6')))
        self.assertTrue(any('2026-11-06' in src for src in p.sources))

    def test_letter_of_2026_11_06_is_reproduced(self):
        # Hand calculation, reduced rate 14.0 / additional 3.8 / care 4.2 (3.6 + 0.6):
        #   3,971.82: 556.0548 -> 556.05 ; 150.9292 -> 150.93 ; 166.8164 -> 166.82 ; sum 873.80
        #   2,296.98: 321.5772 -> 321.58 ;  87.2852 ->  87.29 ;  96.4732 ->  96.47 ; sum 505.34
        # SBK's per-type figures sum to the same base, so rounding the total once gives the letter's cents.
        for base, kv_g, zusatz, pv, total in ((D('3971.82'), '556.05', '150.93', '166.82', '873.80'),
                                              (D('2296.98'), '321.58', '87.29', '96.47', '505.34')):
            got = sbk.contributions(base, D('14.0'), D('3.8'), D('4.2'))
            self.assertEqual(got[0], D(kv_g))
            self.assertEqual(got[1], D(zusatz))
            self.assertEqual(got[3], D(pv))
            self.assertEqual(got[2] + got[3], D(total))

    def test_rates_follow_settings(self):
        p = sbk.parameters_for(2026)
        s = AssessmentSettings(kv_rate='general', pflege='childless')
        self.assertEqual(sbk.rates_for(p, s)[:3], (D('14.6'), D('3.8'), D('4.2')))
        s = AssessmentSettings(kv_rate='reduced', pflege='base', kv_rate_confirmed=True)
        kv, z, pf, label = sbk.rates_for(p, s)
        self.assertEqual((kv, z, pf), (D('14.0'), D('3.8'), D('3.6')))
        self.assertIn('confirmed with SBK', label)
        self.assertNotIn('NOT confirmed', label)

    def test_unconfirmed_general_rate_is_labelled_upper_bound(self):
        label = sbk.rates_for(sbk.parameters_for(2026), AssessmentSettings(kv_rate='general'))[3]
        self.assertIn('NOT confirmed with SBK', label)
        self.assertIn('upper-bound', label)
        self.assertIn('affordability', label)

    def test_defaults_record_the_owners_decisions(self):
        s = AssessmentSettings.load()
        self.assertEqual((s.kv_rate, s.kv_rate_confirmed, s.pflege, s.joint_assessment), ('reduced', False, 'childless', False))

    def test_unconfirmed_default_reduced_rate_is_not_an_upper_bound(self):
        kv, _z, _pf, label = sbk.rates_for(sbk.parameters_for(2026), AssessmentSettings())
        self.assertEqual(kv, D('14.0'))
        self.assertIn('NOT confirmed with SBK', label)
        self.assertNotIn('upper-bound', label)

    def test_general_rate_is_the_statutory_14_6_in_both_years(self):
        for year in (2025, 2026):
            self.assertEqual(sbk.parameters_for(year).kv_general_pct, D('14.6'))
            self.assertEqual(sbk.parameters_for(year).kv_reduced_pct, D('14.0'))


class ContributionRoundingTests(TestCase):
    """Anchors from SBK's own 2026 page plus exact half-cent cases (BVSz section 9: half-up per component)."""

    def test_sbk_page_maximum_at_reduced_rate(self):
        # SBK page: base 5,812.50 -> health 1,034.63 (17.8%), care 209.25 (3.6%)
        kv_g, z, kv, pf = sbk.contributions(D('5812.50'), D('14.0'), D('3.8'), D('3.6'))
        self.assertEqual((kv_g, z, kv, pf), (D('813.75'), D('220.88'), D('1034.63'), D('209.25')))   # 220.875 rounds up

    def test_sbk_page_minimum_care_and_known_one_cent_difference(self):
        kv_g, z, kv, pf = sbk.contributions(D(3955) / 3, D('14.0'), D('3.8'), D('3.6'))
        self.assertEqual(pf, D('47.46'))                     # matches SBK page
        self.assertEqual((kv_g, z, kv), (D('184.57'), D('50.10'), D('234.67')))
        # SBK's page shows 234.66 because it applies 17.8% in one step; BVSz section 9(1a) rounds the
        # additional contribution separately, which this policy follows. The difference is one cent.

    def test_exact_half_cents_round_up(self):
        kv_g, z, kv, pf = sbk.contributions(D('5812.50'), D('14.6'), D('3.8'), D('4.2'))
        self.assertEqual((kv_g, z, kv, pf), (D('848.63'), D('220.88'), D('1069.51'), D('244.13')))   # 848.625, 220.875, 244.125
        self.assertEqual(sbk.round_cents(D('0.005')), D('0.01'))
        self.assertEqual(sbk.round_cents(D('0.004999')), D('0.00'))


class SbkEstimateTests(TestCase):
    def setUp(self):
        build_2026()
        self.a = sbk.assess_year(2026)
        self.m = {r.month: r for r in self.a.months}

    def test_components_by_month(self):
        capital = D('199') / 12
        for month in range(1, 13):
            c = self.m[month].components
            self.assertEqual(c['pension'], D('1000'))
            self.assertEqual(c['capital'], capital)
            self.assertEqual(c['rental'], D('400') if month >= 7 else D('0'))
            expected_one_off = (D('200') if month <= 10 else D('0')) + (D('500') if month >= 5 else D('0'))
            self.assertEqual(c['one_off'], expected_one_off, month)
            self.assertEqual(c['employment'] + c['self_employed'], D('0'))

    def test_base_and_limits(self):
        # base = 1000 pension + 199/12 capital + one-offs (+ rental from July)
        self.assertEqual(self.m[1].base, D('1200') + D(199) / 12)                  # 1,216.58: below the minimum
        for month in (1, 2, 3, 4):
            self.assertEqual((self.m[month].limit, self.m[month].assessed), ('minimum', D(3955) / 3))
        for month, (low, high) in {5: ('1716.58', None), 6: ('1716.58', None), 7: ('2116.58', None),
                                   10: ('2116.58', None), 11: ('1916.58', None), 12: ('1916.58', None)}.items():
            r = self.m[month]
            self.assertEqual((r.limit, r.assessed), ('', r.base), month)           # inside the limits: used as is
            self.assertEqual(round(r.base, 2), D(low), month)

    def test_contributions_match_hand_calculation(self):
        expected = {  # month: (health general, additional, health total, care, total)
            1: ('192.48', '50.10', '242.58', '55.37', '297.95'), 4: ('192.48', '50.10', '242.58', '55.37', '297.95'),
            5: ('250.62', '65.23', '315.85', '72.10', '387.95'), 6: ('250.62', '65.23', '315.85', '72.10', '387.95'),
            7: ('309.02', '80.43', '389.45', '88.90', '478.35'), 10: ('309.02', '80.43', '389.45', '88.90', '478.35'),
            11: ('279.82', '72.83', '352.65', '80.50', '433.15'), 12: ('279.82', '72.83', '352.65', '80.50', '433.15'),
        }
        for month, vals in expected.items():
            r = self.m[month]
            self.assertEqual(tuple(str(x) for x in (r.kv_general, r.kv_zusatz, r.kv, r.pflege, r.total)), vals, month)

    def test_year_totals(self):
        self.assertEqual(self.a.total_kv, D('3865.12'))
        self.assertEqual(self.a.total_pflege, D('882.28'))
        self.assertEqual(self.a.total, D('4747.40'))

    def test_exclusions_are_reported(self):
        self.assertEqual(self.a.unmapped, [('Other', 1, D('777'))])
        self.assertEqual(self.a.unconverted_mapped, 1)
        self.assertEqual((self.a.kv_pct, self.a.zusatz_pct, self.a.pflege_pct), (D('14.6'), D('3.8'), D('4.2')))

    def test_notes_say_capital_defaults(self):
        self.assertTrue(any('Capital income' in n and 'assumed January to December' in n and '51' in n for n in self.a.notes))
        self.assertFalse(any('Rental' in n for n in self.a.notes))       # rental inputs were entered


class SbkEdgeCaseTests(TestCase):
    def setUp(self):
        use_general_rate()

    def assess(self, **kw):
        return sbk.assess_year(2026, **kw)

    def test_no_income_pays_the_minimum_every_month(self):
        a = self.assess()
        self.assertTrue(all(m.limit == 'minimum' for m in a.months))
        self.assertEqual(a.total, D('297.95') * 12)
        self.assertEqual(a.unmapped, [])

    def test_maximum_applies_above_the_ceiling(self):
        map_categories(Salary='employment')
        add(10000, datetime.date(2026, 1, 25), 'Salary', 'Employer')
        jan = self.assess().months[0]
        self.assertEqual((jan.base, jan.assessed, jan.limit), (D('10000'), D('5812.50'), 'maximum'))
        self.assertEqual((jan.kv, jan.pflege, jan.total), (D('1069.51'), D('244.13'), D('1313.64')))

    def test_exactly_at_the_ceiling_is_not_flagged(self):
        map_categories(Salary='employment')
        add(5812.50, datetime.date(2026, 1, 25), 'Salary')
        self.assertEqual(self.assess().months[0].limit, '')

    def test_reduced_rate_and_base_care_setting(self):
        map_categories(Salary='employment')
        add(5812.50, datetime.date(2026, 1, 25), 'Salary')
        s = AssessmentSettings.load()
        s.kv_rate, s.pflege = 'reduced', 'base'
        s.save()
        jan = self.assess().months[0]
        self.assertEqual((jan.kv, jan.pflege), (D('1034.63'), D('209.25')))

    def test_corrections_reduce_the_base(self):
        map_categories(Salary='employment')
        a = add(3000, datetime.date(2026, 2, 10), 'Salary')
        r = make_payment(gross='-500', kind='reversal', corrects=a, date=datetime.date(2026, 2, 12), category='Salary')
        r.save()
        convert_payment(r)
        self.assertEqual(self.assess().months[1].components['employment'], D('2500'))

    def test_capital_costs_above_flat_amount_are_used(self):
        map_categories(Interest='capital')
        add(1200, datetime.date(2026, 6, 1), 'Interest')
        AnnualInput.objects.create(year=ReportingYear.objects.get(year=2026), treatment='capital', costs_eur=D('300'))
        self.assertEqual(self.assess().months[0].components['capital'], D('900') / 12)        # (1200-300)/12, not 51

    def test_capital_flat_amount_applies_without_inputs(self):
        map_categories(Interest='capital')
        add(1200, datetime.date(2026, 6, 1), 'Interest')
        self.assertEqual(self.assess().months[0].components['capital'], D('1149') / 12)      # (1200-51)/12

    def test_capital_below_flat_amount_floors_at_zero_with_note(self):
        map_categories(Interest='capital')
        add(40, datetime.date(2026, 6, 1), 'Interest')
        a = self.assess()
        self.assertEqual(a.months[0].components['capital'], D('0'))
        self.assertTrue(any('costs exceed income' in n for n in a.notes))

    def test_rental_loss_floors_at_zero(self):
        map_categories(Rental='rental')
        add(1000, datetime.date(2026, 6, 1), 'Rental')
        AnnualInput.objects.create(year=ReportingYear.objects.get(year=2026), treatment='rental', costs_eur=D('5000'))
        a = self.assess()
        self.assertEqual(sum(m.components['rental'] for m in a.months), D('0'))
        self.assertTrue(any('costs exceed income' in n for n in a.notes))

    def test_self_employed_partial_year(self):
        map_categories(Other='self_employed')
        add(12000, datetime.date(2026, 11, 30), 'Other')
        AnnualInput.objects.create(year=ReportingYear.objects.get(year=2026), treatment='self_employed',
                                   costs_eur=D('2000'), first_month=4, last_month=9)
        a = self.assess()
        for m in a.months:
            self.assertEqual(m.components['self_employed'], D('10000') / 6 if 4 <= m.month <= 9 else D('0'))

    def test_one_off_spills_into_next_year_but_not_into_this_one(self):
        map_categories(Capital_gains='one_off')
        add(1200, datetime.date(2026, 12, 20), 'Capital gains')
        a = self.assess()
        self.assertEqual([m.components['one_off'] for m in a.months], [D('0')] * 11 + [D('100')])
        add(2400, datetime.date(2027, 1, 5), 'Capital gains')                               # next year: ignored for 2026
        self.assertEqual(self.assess().months[11].components['one_off'], D('100'))

    def test_one_off_from_two_years_ago_has_expired(self):
        map_categories(Capital_gains='one_off')
        add(1200, datetime.date(2024, 12, 1), 'Capital gains')
        self.assertEqual(sum(m.components['one_off'] for m in self.assess().months), D('0'))

    def test_excluded_mapping_is_counted_not_summed(self):
        map_categories(Other='excluded')
        add(500, datetime.date(2026, 3, 1), 'Other')
        a = self.assess()
        self.assertEqual((a.excluded_by_mapping, a.unmapped), (1, []))
        self.assertTrue(all(sum(m.components.values()) == 0 for m in a.months))

    def test_unmapped_category_is_listed_and_not_counted(self):
        add(500, datetime.date(2026, 3, 1), 'Other')
        a = self.assess()
        self.assertEqual(a.unmapped, [('Other', 1, D('500'))])
        self.assertTrue(all(sum(m.components.values()) == 0 for m in a.months))

    def test_other_years_data_does_not_leak_in(self):
        map_categories(Pension='pension')
        add(1000, datetime.date(2025, 6, 1), 'Pension')
        add(1000, datetime.date(2027, 6, 1), 'Pension')
        self.assertEqual(sum(m.components['pension'] for m in self.assess().months), D('0'))

    def test_settings_row_is_a_singleton(self):
        a, b = AssessmentSettings.load(), AssessmentSettings.load()
        self.assertEqual((a.pk, b.pk, AssessmentSettings.objects.count()), (1, 1, 1))


class AnnualInputValidationTests(TestCase):
    def setUp(self):
        self.year = ReportingYear.objects.create(year=2026)

    def test_month_order_and_treatment_rules(self):
        with self.assertRaises(ValidationError):
            AnnualInput(year=self.year, treatment='rental', first_month=8, last_month=3).full_clean()
        for t in ('employment', 'pension', 'one_off', 'excluded'):
            with self.assertRaises(ValidationError, msg=t):
                AnnualInput(year=self.year, treatment=t).full_clean()
        with self.assertRaises(ValidationError):
            AnnualInput(year=self.year, treatment='rental', first_month=0).full_clean()
        with self.assertRaises(ValidationError):
            AnnualInput(year=self.year, treatment='rental', costs_eur=D('-1')).full_clean()
        i = AnnualInput(year=self.year, treatment='rental', first_month=7, last_month=12)
        i.full_clean()
        self.assertEqual(i.months_earned, 6)


class SbkReportTests(TestCase):
    def setUp(self):
        build_2026()

    def test_report_rows_totals_and_basis(self):
        rep = reports.REPORTS['sbk'].build(2026)
        self.assertEqual(len(rep.rows), 12)
        self.assertEqual((rep.totals['kv'], rep.totals['pflege'], rep.totals['total']), (D('3865.12'), D('882.28'), D('4747.40')))
        self.assertEqual(rep.rows[0]['limit'], 'minimum')
        self.assertEqual(rep.rows[0]['month'], '2026-01 January')
        b = dict(rep.basis)
        self.assertIn('NOT an SBK assessment', b['Status'])
        self.assertIn('sbk-contribution-estimate 1.1', b['Policy'])
        self.assertIn('5,812.50', b['Parameters'])
        self.assertIn('1,318.33', b['Parameters'])
        self.assertIn('18.4%', b['Parameters'])
        self.assertIn('NOT confirmed with SBK', b['Rate basis'])
        self.assertIn('Other (1 payment(s), 777.00 EUR converted)', b['Excluded / missing'])
        self.assertIn('1 unconverted payment(s) in mapped categories', b['Excluded / missing'])
        self.assertEqual(sum(1 for k, _ in rep.basis if k == 'Assumption'), len(sbk.ASSUMPTIONS))
        self.assertTrue(any('Average total contribution per month (12 months): 395.62' in n for n in rep.notes))   # 4747.40 / 12

    def test_csv_carries_policy_version_assumptions_and_exclusions(self):
        text = report_csv.render(reports.REPORTS['sbk'].build(2026))
        for needle in ('sbk-contribution-estimate 1.1', 'NOT an SBK assessment', 'Assumption,', 'BVSz section 5(3)',
                       'EXCLUDED', '4747.40', 'Year total'):
            self.assertIn(needle, text)

    def test_report_for_unverified_year_is_unavailable(self):
        with self.assertRaises(sbk.PolicyUnavailable):
            reports.REPORTS['sbk'].build(2024)


class MembershipMonthsTests(TestCase):
    """SBK letter 2026-11-06: self-pay from November 2025. Pension 3,971.82 in every month of 2025 (base per month),
    reduced rate 14.0 / 3.8, care 4.2 -> 873.80 for each of Nov and Dec = 1,747.60; January to October carry nothing."""

    def setUp(self):
        map_categories(Pension='pension')
        for month in range(1, 13):
            add('3971.82', datetime.date(2025, month, 15), 'Pension')
        self.settings = AssessmentSettings(kv_rate='reduced', kv_rate_confirmed=True, pflege='childless')

    def test_default_is_all_twelve_months(self):
        a = sbk.assess_year(2025, self.settings)
        self.assertEqual((a.first_month, a.member_months), (1, 12))
        self.assertEqual(a.total, D('873.80') * 12)

    def test_first_self_pay_month_limits_the_estimate(self):
        ReportingYear.objects.filter(year=2025).update(self_pay_first_month=11)
        a = sbk.assess_year(2025, self.settings)
        self.assertEqual(a.member_months, 2)
        self.assertEqual([m.member for m in a.months], [False] * 10 + [True] * 2)
        self.assertEqual(a.months[0].total, D(0))
        self.assertEqual((a.months[10].total, a.months[11].total), (D('873.80'), D('873.80')))
        self.assertEqual(a.total, D('1747.60'))
        self.assertTrue(any('from month 11' in n for n in a.notes))

    def test_report_states_the_months_and_average(self):
        ReportingYear.objects.filter(year=2025).update(self_pay_first_month=11)
        sbk.assess_year(2025, self.settings)
        AssessmentSettings.objects.create(pk=1, kv_rate='reduced', kv_rate_confirmed=True, pflege='childless')
        rep = reports.REPORTS['sbk'].build(2025)
        self.assertEqual(rep.rows[0]['limit'], 'not self-paid')
        self.assertEqual(rep.totals['total'], D('1747.60'))
        self.assertIn('2 months', dict(rep.basis)['Period'])
        self.assertTrue(any('873.80' in n for n in rep.notes))

    def test_form_rejects_month_outside_1_to_12(self):
        from core.forms import SelfPayFirstMonthForm
        y = ReportingYear.objects.get(year=2025)
        self.assertFalse(SelfPayFirstMonthForm({'self_pay_first_month': '13'}, instance=y).is_valid())
        self.assertTrue(SelfPayFirstMonthForm({'self_pay_first_month': ''}, instance=y).is_valid())


class RentalCostsVisibilityTests(TestCase):
    def setUp(self):
        map_categories(Rental='rental')
        p = add(1200, datetime.date(2025, 3, 1), 'Rental', expenses='300', net='900')
        p.refresh_from_db()

    def test_recorded_expenses_without_annual_costs_warn_loudly_and_are_not_deducted(self):
        a = sbk.assess_year(2025, AssessmentSettings(kv_rate='reduced', kv_rate_confirmed=True))
        self.assertEqual(a.cost_lines, [('rental', D('1200'), D('300'), D(0))])
        self.assertEqual(a.months[0].components['rental'], D(100))          # 1,200 / 12, no deduction
        warn = [n for n in a.notes if n.startswith('WARNING')]
        self.assertEqual(len(warn), 1)
        self.assertIn('300', warn[0])

    def test_entered_costs_are_used_and_no_warning(self):
        AnnualInput.objects.create(year=ReportingYear.objects.get(year=2025), treatment='rental', costs_eur=300)
        a = sbk.assess_year(2025, AssessmentSettings(kv_rate='reduced', kv_rate_confirmed=True))
        self.assertEqual(a.months[0].components['rental'], D(75))           # (1,200 - 300) / 12
        self.assertFalse([n for n in a.notes if n.startswith('WARNING')])
        self.assertEqual(a.cost_lines, [('rental', D('1200'), D('300'), D(300))])


class TaxAssessmentFiguresTests(TestCase):
    def test_figures_are_stored_per_year_and_shown_by_the_comparison_command(self):
        from io import StringIO
        from django.core.management import call_command
        from core.models import TaxAssessmentFigures
        y = ReportingYear.objects.create(year=2025)
        TaxAssessmentFigures.objects.create(year=y, capital_income=D('11000.00'), rental_income_after_costs=D('19000.00'))
        out = StringIO()
        call_command('sbk_letter_reconciliation', year=2025, stdout=out)
        self.assertIn('rental after costs 19000.00', out.getvalue())
        self.assertIn('other None', out.getvalue())

    def test_page_saves_figures(self):
        from django.contrib.auth import get_user_model
        from django.urls import reverse
        ReportingYear.objects.create(year=2025)
        get_user_model().objects.create_user('t', password='x')
        self.client.login(username='t', password='x')
        r = self.client.post(reverse('annual_inputs', args=[2025]), {'capital_income': '11000.50', 'rental_income_after_costs': '', 'other_income': '', 'note': ''})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(ReportingYear.objects.get(year=2025).tax_assessment_figures.capital_income, D('11000.50'))
