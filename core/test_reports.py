"""Reports are checked against figures worked out by hand from a fixed synthetic dataset.

2024 dataset (P = payment; EUR amounts = original x manual rate):
  P1 2024-01-15 Alpha Corp   Salary   EUR 3000.00 net 2100.00 monthly
  P2 2024-02-15 Alpha Corp   Salary   EUR 3000.00 net 2100.00 monthly
  P3 2024-03-10 Beta Pension Pension  GBP  400.00 net  360.00 monthly     rate 1.20 -> 480.00 / 432.00
  P4 2024-03-20 Gamma Bank   Interest AUD  100.00 no net       one_off     rate 0.60 ->  60.00 / -
  P5 2024-06-30 Alpha Corp   Salary   EUR 1200.00 net  800.00 quarterly
  P6 2024-07-01 Delta Rental Rental   USD  500.00 net  450.00 half_yearly  rate 0.90 -> 450.00 / 405.00
  P7 2024-08-05 Beta Pension Pension  GBP  250.00 no net       monthly     NOT converted
  P8 2024-02-20 Alpha Corp   Salary   EUR -3000.00 net -2100.00 reversal of P2
2023: P9 2023-12-01 Alpha Corp Salary EUR 1000.00 net 700.00 monthly
"""
import csv
import datetime
import io
from decimal import Decimal as D
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from core.models import Payment
from core.services import report_csv, reports
from core.services.conversion import convert_payment
from core.services.rates import FakeRateProvider

from .test_helpers import make_payment


def d(y, m, day):
    return datetime.date(y, m, day)


def build_dataset():
    def add(rate=None, convert=True, **kw):
        p = make_payment(**kw)
        p.save()
        if convert:
            convert_payment(p, manual_rate=rate) if rate else convert_payment(p)
        return p
    p = {}
    p[1] = add(gross='3000', net='2100', date=d(2024, 1, 15), org='Alpha Corp')
    p[2] = add(gross='3000', net='2100', date=d(2024, 2, 15), org='Alpha Corp')
    p[3] = add(rate='1.20', gross='400', net='360', currency='GBP', date=d(2024, 3, 10), org='Beta Pension', category='Pension')
    p[4] = add(rate='0.60', gross='100', currency='AUD', date=d(2024, 3, 20), org='Gamma Bank', category='Interest', frequency='one_off')
    p[5] = add(gross='1200', net='800', date=d(2024, 6, 30), org='Alpha Corp', frequency='quarterly')
    p[6] = add(rate='0.90', gross='500', net='450', currency='USD', date=d(2024, 7, 1), org='Delta Rental', category='Rental', frequency='half_yearly')
    p[7] = add(convert=False, gross='250', currency='GBP', date=d(2024, 8, 5), org='Beta Pension', category='Pension')
    p[8] = add(gross='-3000', net='-2100', date=d(2024, 2, 20), org='Alpha Corp', kind='reversal', corrects=p[2])
    p[9] = add(gross='1000', net='700', date=d(2023, 12, 1), org='Alpha Corp')
    return p


# The Phase 6 reports. Policy-based reports (SBK, tax) are tested in test_policies_*.py: the SBK
# estimate exists only for years with verified parameters (2026).
BASE_KEYS = ['annual', 'monthly', 'payments', 'organisation', 'category', 'currency', 'normalised', 'reconciliation']


def base_specs():
    return [reports.REPORTS[k] for k in BASE_KEYS]


def wipe(keep=()):
    """Delete payments except `keep`, corrections first (corrected payments are protected)."""
    Payment.objects.exclude(pk__in=keep).exclude(kind='normal').delete()
    Payment.objects.exclude(pk__in=keep).delete()


def rows_by(report, key):
    return {r[key]: r for r in report.rows}


class ReportNumbersTests(TestCase):
    def setUp(self):
        self.p = build_dataset()

    def test_annual_summary(self):
        rep = reports.annual_summary()
        r = rows_by(rep, 'year')
        self.assertEqual(list(r), ['2023', '2024'])
        y = r['2024']
        self.assertEqual((y['payments'], y['months']), (8, 6))
        self.assertEqual((y['gross_eur'], y['net_eur']), (D('5190'), D('3737')))   # 3000+3000+480+60+1200+450-3000 ; 2100+2100+432+800+405-2100
        self.assertEqual((y['gross_12'], y['net_12']), (D('5190') / 12, D('3737') / 12))
        self.assertEqual(y['gross_12'], D('432.5'))
        self.assertEqual((y['net_missing'], y['unconverted']), (1, 1))
        self.assertEqual((r['2023']['gross_eur'], r['2023']['net_eur'], r['2023']['payments']), (D('1000'), D('700'), 1))
        self.assertEqual(r['2023']['gross_12'], D('1000') / 12)

    def test_annual_summary_single_year_filter(self):
        rep = reports.annual_summary(2023)
        self.assertEqual([r['year'] for r in rep.rows], ['2023'])
        self.assertEqual(rep.period, 'Calendar year 2023')

    def test_monthly_breakdown(self):
        rep = reports.monthly_breakdown(2024)
        self.assertEqual(len(rep.rows), 12)
        m = {i + 1: r for i, r in enumerate(rep.rows)}
        self.assertEqual((m[1]['payments'], m[1]['gross_eur'], m[1]['net_eur']), (1, D('3000'), D('2100')))
        self.assertEqual((m[2]['payments'], m[2]['gross_eur'], m[2]['net_eur']), (2, D('0'), D('0')))   # reversal nets out
        self.assertEqual((m[3]['payments'], m[3]['gross_eur'], m[3]['net_eur'], m[3]['net_missing']), (2, D('540'), D('432'), 1))
        self.assertEqual((m[4]['payments'], m[4]['gross_eur']), (0, D('0')))                            # empty months present
        self.assertEqual((m[6]['gross_eur'], m[6]['net_eur']), (D('1200'), D('800')))
        self.assertEqual((m[7]['gross_eur'], m[7]['net_eur']), (D('450'), D('405')))
        self.assertEqual((m[8]['payments'], m[8]['gross_eur'], m[8]['unconverted']), (1, D('0'), 1))   # pending excluded
        self.assertEqual(rep.totals['gross_eur'], D('5190'))
        self.assertEqual(rep.totals['net_eur'], D('3737'))
        self.assertEqual(sum(r['gross_eur'] for r in rep.rows), rep.totals['gross_eur'])
        self.assertEqual(rep.rows[0]['month'], '2024-01 January')

    def test_by_organisation(self):
        rep = reports.by_organisation(2024)
        self.assertEqual([r['name'] for r in rep.rows], ['Alpha Corp', 'Beta Pension', 'Delta Rental', 'Gamma Bank'])
        r = rows_by(rep, 'name')
        self.assertEqual((r['Alpha Corp']['payments'], r['Alpha Corp']['gross_eur'], r['Alpha Corp']['net_eur']), (4, D('4200'), D('2900')))
        self.assertEqual((r['Beta Pension']['payments'], r['Beta Pension']['gross_eur'], r['Beta Pension']['net_eur'], r['Beta Pension']['unconverted']),
                         (2, D('480'), D('432'), 1))
        self.assertEqual((r['Delta Rental']['gross_eur'], r['Delta Rental']['net_eur']), (D('450'), D('405')))
        self.assertEqual((r['Gamma Bank']['gross_eur'], r['Gamma Bank']['net_eur'], r['Gamma Bank']['net_missing']), (D('60'), D('0'), 1))
        self.assertEqual(r['Alpha Corp']['share'], D('4200') / D('5190'))
        self.assertEqual(rep.totals['gross_eur'], D('5190'))
        self.assertEqual(sum(x['gross_eur'] for x in rep.rows), D('5190'))

    def test_by_organisation_all_years_includes_2023(self):
        r = rows_by(reports.by_organisation(), 'name')
        self.assertEqual((r['Alpha Corp']['payments'], r['Alpha Corp']['gross_eur']), (5, D('5200')))

    def test_by_category(self):
        r = rows_by(reports.by_category(2024), 'name')
        self.assertEqual({k: (v['payments'], v['gross_eur'], v['net_eur']) for k, v in r.items()}, {
            'Salary': (4, D('4200'), D('2900')), 'Pension': (2, D('480'), D('432')),
            'Rental': (1, D('450'), D('405')), 'Interest': (1, D('60'), D('0'))})

    def test_original_currency_summary(self):
        rep = reports.original_currency_summary(2024)
        self.assertEqual([r['currency'] for r in rep.rows], ['AUD', 'EUR', 'GBP', 'USD'])
        r = rows_by(rep, 'currency')
        self.assertEqual((r['AUD']['gross_original'], r['AUD']['net_original'], r['AUD']['net_original_missing'], r['AUD']['gross_eur']),
                         (D('100'), D('0'), 1, D('60')))
        self.assertEqual((r['EUR']['payments'], r['EUR']['gross_original'], r['EUR']['net_original'], r['EUR']['gross_eur']),
                         (4, D('4200'), D('2900'), D('4200')))
        # GBP: original totals include the unconverted P7; EUR figures do not
        self.assertEqual((r['GBP']['payments'], r['GBP']['gross_original'], r['GBP']['net_original'], r['GBP']['net_original_missing']),
                         (2, D('650'), D('360'), 1))
        self.assertEqual((r['GBP']['converted'], r['GBP']['gross_eur'], r['GBP']['net_eur'], r['GBP']['unconverted']),
                         (1, D('480'), D('432'), 1))
        self.assertEqual((r['USD']['gross_original'], r['USD']['gross_eur']), (D('500'), D('450')))

    def test_normalised_monthly(self):
        rep = reports.normalised_monthly(2024)
        m = {i + 1: r for i, r in enumerate(rep.rows)}
        self.assertEqual((m[1]['gross_monthly'], m[1]['net_monthly'], m[1]['recurring']), (D('3000'), D('2100'), 1))
        self.assertEqual((m[2]['gross_monthly'], m[2]['net_monthly'], m[2]['recurring']), (D('0'), D('0'), 2))
        self.assertEqual((m[3]['gross_monthly'], m[3]['net_monthly'], m[3]['recurring'], m[3]['one_off']), (D('480'), D('432'), 1, 1))
        self.assertEqual((m[6]['gross_monthly'], m[6]['net_monthly']), (D('1200') / 3, D('800') / 3))      # quarterly: /3
        self.assertEqual(m[6]['gross_monthly'], D('400'))
        self.assertEqual((m[7]['gross_monthly'], m[7]['net_monthly']), (D('75'), D('67.5')))               # half-yearly: /6
        self.assertEqual((m[8]['gross_monthly'], m[8]['recurring'], m[8]['unconverted']), (D('0'), 0, 1))
        self.assertEqual(m[4]['gross_monthly'], D('0'))
        self.assertIsNone(rep.totals)
        self.assertTrue(any('No year total' in n for n in rep.notes))

    def test_payment_level(self):
        rep = reports.payment_level(2024)
        self.assertEqual(len(rep.rows), 8)
        self.assertEqual([r['id'] for r in rep.rows], [self.p[i].pk for i in (1, 2, 8, 3, 4, 5, 6, 7)])  # by date
        r = rows_by(rep, 'id')
        p3 = r[self.p[3].pk]
        self.assertEqual((p3['currency'], p3['gross_original'], p3['rate'], p3['rate_source'], p3['gross_eur'], p3['net_eur']),
                         ('GBP', D('400'), D('1.2'), 'manual', D('480'), D('432')))
        p7 = r[self.p[7].pk]
        self.assertEqual((p7['status'], p7['gross_eur'], p7['rate'], p7['gross_original']), ('NOT CONVERTED', None, None, D('250')))
        self.assertEqual(r[self.p[5].pk]['monthly_equiv'], D('400'))
        self.assertIsNone(r[self.p[4].pk]['monthly_equiv'])          # one-off
        self.assertEqual(r[self.p[8].pk]['type' if False else 'kind'], 'Reversal')
        self.assertEqual((rep.totals['gross_eur'], rep.totals['net_eur']), (D('5190'), D('3737')))

    def test_reconciliation(self):
        rep = reports.reconciliation(2024)
        found = [(r['issue'], r['id']) for r in rep.rows]
        expected = [('Not converted', self.p[7].pk)] + [('Manually entered rate', self.p[i].pk) for i in (3, 4, 6)] + \
                   [('No net amount', self.p[i].pk) for i in (4, 7)] + \
                   [('Gross differs from net + withholding tax + expenses (unallocated)', self.p[i].pk) for i in (1, 2, 3, 5, 6, 8)]
        self.assertCountEqual(found, expected)

    def test_basis_block_states_everything(self):
        rep = reports.annual_summary(2024)
        b = dict(rep.basis)
        self.assertEqual(b['Period'], 'Calendar year 2024')
        self.assertIn('EUR', b['Currency'])
        self.assertIn('stored on it', b['Currency'])
        self.assertEqual(b['Basis'], 'Actual payments received (not normalised)')
        self.assertIn('never mixed', b['Gross/net'])
        self.assertEqual(b['Exchange-rate basis'],
                         'Stored rate per payment (EUR per 1 unit of original currency): 4 x EUR (rate 1); 3 x manually entered rate.')
        self.assertEqual(b['Excluded / missing'],
                         '1 unconverted payment(s) excluded from every EUR figure (original gross: GBP 250.00). '
                         '1 converted payment(s) have no net amount and are excluded from net figures only. '
                         '1 correction/reversal entry included as signed amounts.')
        self.assertIn('rounded', b['Rounding'])
        self.assertEqual(dict(reports.normalised_monthly(2024).basis)['Basis'][:10], 'Normalised')

    def test_clean_data_says_none_excluded(self):
        wipe([self.p[1].pk, self.p[3].pk])
        self.assertEqual(dict(reports.annual_summary(2024).basis)['Excluded / missing'], 'None.')

    def test_weekend_rate_is_called_out_in_rate_basis(self):
        sat = d(2024, 3, 16)
        prov = FakeRateProvider({('GBP', sat): D('1.2')}, date_overrides={('GBP', sat): d(2024, 3, 15)})
        p = make_payment(currency='GBP', date=sat, gross='10'); p.save()
        convert_payment(p, prov)
        text = dict(reports.annual_summary(2024).basis)['Exchange-rate basis']
        self.assertIn('1 x fake', text)
        self.assertIn('1 used the nearest earlier ECB rate', text)

    def test_reports_are_reproducible_and_read_only(self):
        before = (Payment.objects.count(), list(Payment.objects.values_list('gross_eur', 'rate')))
        for spec in base_specs():
            year = 2024 if spec.needs_year else None
            a, b = spec.build(year), spec.build(year)
            self.assertEqual((a.rows, a.totals, a.basis), (b.rows, b.totals, b.basis), spec.key)
        self.assertEqual(before, (Payment.objects.count(), list(Payment.objects.values_list('gross_eur', 'rate'))))

    def test_empty_database_reports(self):
        wipe()
        for spec in base_specs():
            rep = spec.build(2024 if spec.needs_year else None)
            self.assertIsNotNone(rep.basis, spec.key)
        self.assertEqual(reports.annual_summary().rows, [])
        self.assertEqual(len(reports.monthly_breakdown(2024).rows), 12)
        self.assertEqual(reports.monthly_breakdown(2024).totals['gross_eur'], D('0'))
        self.assertEqual(dict(reports.annual_summary().basis)['Exchange-rate basis'], 'No converted payments.')

    def test_share_is_none_when_total_is_zero(self):
        a = make_payment(gross='5', org='Zero A'); a.save(); convert_payment(a)
        b = make_payment(gross='-5', org='Zero A', kind='reversal', corrects=a); b.save(); convert_payment(b)
        wipe([a.pk, b.pk])
        rep = reports.by_organisation(2024)
        self.assertIsNone(rep.rows[0]['share'])
        self.assertIsNone(rep.totals['share'])


class RoundingTests(TestCase):
    def test_totals_rounded_once_from_unrounded_sums(self):
        for name in ('A', 'B', 'C'):
            p = make_payment(gross='0.005', org=f'Org {name}'); p.save(); convert_payment(p)
        rep = reports.by_organisation(2024)
        text = report_csv.render(rep).splitlines()
        rows = [r for r in csv.reader(text) if r and r[0].startswith('Org ')]
        self.assertEqual([r[2] for r in rows], ['0.01', '0.01', '0.01'])      # each 0.005 rounds half-up to 0.01
        total = [r for r in csv.reader(text) if r and r[0] == 'Total'][0]
        self.assertEqual(total[2], '0.02')                                     # 0.015 rounded once, not 0.03
        self.assertEqual(rep.totals['gross_eur'], D('0.015'))                  # unrounded value untouched


def parse_csv_report(text):
    rows = list(csv.reader(io.StringIO(text)))
    split = rows.index([])
    return rows[:split], rows[split + 1:]


class CsvRenderTests(TestCase):
    def setUp(self):
        self.p = build_dataset()

    def test_structure_and_formatting(self):
        meta, table = parse_csv_report(report_csv.render(reports.by_organisation(2024)))
        m = {r[0]: r[1] for r in meta if r[0] != 'Note'}
        self.assertEqual(m['Report'], 'By organisation')
        self.assertTrue(m['Generated (UTC)'].startswith('20'))
        for key in ('Period', 'Currency', 'Basis', 'Gross/net', 'Exchange-rate basis', 'Excluded / missing', 'Rounding'):
            self.assertIn(key, m)
        self.assertEqual(m['Report format version'], '2')
        self.assertEqual(table[0], ['Organisation', 'Payments', 'Gains EUR', 'Losses EUR (signed)', 'Corrections / reversals EUR (signed)',
                                    'Gross EUR (signed sum)', 'Net EUR', 'Withholding tax EUR', 'Expenses EUR',
                                    'Unallocated EUR', 'Share of gross', 'Payments without net', 'Unconverted payments'])
        pick = lambda row: [row[i] for i in (0, 1, 5, 6, 10, 11, 12)]
        self.assertEqual(pick(table[1]), ['Alpha Corp', '4', '4200.00', '2900.00', '80.9%', '0', '0'])    # 4200/5190 = 80.92%
        self.assertEqual(pick(table[-1]), ['Total', '8', '5190.00', '3737.00', '100.0%', '1', '1'])

    def test_money_has_two_decimals_no_thousands_and_negatives_intact(self):
        _, table = parse_csv_report(report_csv.render(reports.payment_level(2024)))
        hdr = table[0]
        reversal = [r for r in table[1:] if r[hdr.index('Type')] == 'Reversal'][0]
        self.assertEqual((reversal[hdr.index('Gross EUR')], reversal[hdr.index('Net EUR')]), ('-3000.00', '-2100.00'))
        p3 = [r for r in table[1:] if r[hdr.index('Organisation')] == 'Beta Pension' and r[hdr.index('Currency')] == 'GBP' and r[hdr.index('Conversion')] == 'converted'][0]
        self.assertEqual((p3[hdr.index('Rate (EUR per 1 unit)')], p3[hdr.index('Gross (original)')], p3[hdr.index('Gross EUR')]), ('1.2', '400.00', '480.00'))
        unconverted = [r for r in table[1:] if r[hdr.index('Conversion')] == 'NOT CONVERTED'][0]
        self.assertEqual((unconverted[hdr.index('Gross EUR')], unconverted[hdr.index('Rate (EUR per 1 unit)')]), ('', ''))

    def test_normalised_csv_values(self):
        _, table = parse_csv_report(report_csv.render(reports.normalised_monthly(2024)))
        jun = [r for r in table if r[0].startswith('2024-06')][0]
        self.assertEqual(jun[1:3], ['400.00', '266.67'])                # 800/3 = 266.666... rounded for export only
        self.assertEqual(len(table), 13)                                # header + 12 months, no total row

    def test_formula_injection_neutralised_for_text_only(self):
        self.p[1].comment = '=HYPERLINK("http://x.example","click")'
        self.p[1].save()
        org = make_payment(org='+SUM(A1)', gross='1'); org.save()
        _, table = parse_csv_report(report_csv.render(reports.payment_level(2024)))
        hdr = table[0]
        comments = {r[hdr.index('Comment')] for r in table[1:]}
        self.assertIn("'=HYPERLINK(\"http://x.example\",\"click\")", comments)
        orgs = {r[hdr.index('Organisation')] for r in table[1:]}
        self.assertIn("'+SUM(A1)", orgs)
        self.assertTrue(all(not c.startswith('=') for c in comments))
        negatives = [r[hdr.index('Gross (original)')] for r in table[1:] if r[hdr.index('Type')] == 'Reversal']
        self.assertEqual(negatives, ['-3000.00'])                       # numbers are not apostrophe-prefixed

    def test_safe_text_helper(self):
        for bad in ('=1+1', '+1', '-1', '@x', '\tx', '\rx'):
            self.assertEqual(report_csv.safe_text(bad), "'" + bad)
        self.assertEqual(report_csv.safe_text('Plain'), 'Plain')
        self.assertEqual(report_csv.safe_text(None), '')

    def test_commas_quotes_and_newlines_round_trip(self):
        self.p[1].comment = 'a, "b"\nc'
        self.p[1].save()
        _, table = parse_csv_report(report_csv.render(reports.payment_level(2024)))
        self.assertIn('a, "b"\nc', {r[table[0].index('Comment')] for r in table[1:]})


@override_settings(RATE_PROVIDER='core.services.rates.ManualOnlyProvider')
class ReportViewTests(TestCase):
    def setUp(self):
        self.p = build_dataset()
        self.client.force_login(get_user_model().objects.create_user('t', password='pw-for-tests-123'))

    def test_login_required_everywhere(self):
        self.client.logout()
        urls = [reverse('report_index')] + [reverse(n, args=[k]) for k in reports.REPORTS for n in ('report_view', 'report_csv')]  # all, incl. policy reports
        for url in urls:
            r = self.client.get(url)
            self.assertEqual(r.status_code, 302, url)
            self.assertTrue(r.url.startswith(reverse('login')), url)

    def test_index_lists_all_reports(self):
        r = self.client.get(reverse('report_index'))
        for spec in reports.REPORTS.values():
            self.assertContains(r, spec.title)
        self.assertContains(r, '<option value="2024">')
        self.assertContains(r, 'not stored on the server')

    def test_every_report_renders_and_downloads(self):
        for key, spec in [(k, reports.REPORTS[k]) for k in BASE_KEYS]:
            q = '?year=2024'
            r = self.client.get(reverse('report_view', args=[key]) + q)
            self.assertEqual(r.status_code, 200, key)
            self.assertContains(r, 'Basis')
            self.assertContains(r, 'Exchange-rate basis')
            self.assertContains(r, 'Excluded / missing')
            c = self.client.get(reverse('report_csv', args=[key]) + q)
            self.assertEqual(c.status_code, 200, key)
            self.assertEqual(c['Content-Type'], 'text/csv; charset=utf-8')
            self.assertEqual(c['Content-Disposition'], f'attachment; filename="report-{key}-2024.csv"')
            self.assertEqual(c['Cache-Control'], 'no-store')
            self.assertEqual(c['X-Content-Type-Options'], 'nosniff')
            meta, table = parse_csv_report(c.content.decode())
            self.assertEqual(meta[0], ['Report', spec.title])

    def test_html_shows_figures(self):
        r = self.client.get(reverse('report_view', args=['annual']) + '?year=2024')
        self.assertContains(r, '5,190.00')
        self.assertContains(r, '3,737.00')
        self.assertContains(r, '432.50')
        self.assertContains(r, '311.42')       # 3737/12 = 311.4166...
        r = self.client.get(reverse('report_view', args=['payments']))
        self.assertContains(r, 'NOT CONVERTED')
        self.assertContains(r, '-3,000.00')

    def test_all_years_default_and_filename(self):
        c = self.client.get(reverse('report_csv', args=['annual']))
        self.assertEqual(c['Content-Disposition'], 'attachment; filename="report-annual-all.csv"')
        _, table = parse_csv_report(c.content.decode())
        self.assertEqual([r[0] for r in table[1:]], ['2023', '2024'])

    def test_year_validation(self):
        for url in (reverse('report_view', args=['annual']) + '?year=1999', reverse('report_csv', args=['annual']) + '?year=abc',
                    reverse('report_view', args=['annual']) + '?year=2024;DROP'):
            r = self.client.get(url, follow=True)
            self.assertRedirects(r, reverse('report_index'))
            self.assertContains(r, 'Unknown year')

    def test_year_required_for_monthly_and_normalised(self):
        for key in ('monthly', 'normalised'):
            for name in ('report_view', 'report_csv'):
                r = self.client.get(reverse(name, args=[key]), follow=True)
                self.assertContains(r, 'needs a specific year')
            self.assertEqual(self.client.get(reverse('report_view', args=[key]) + '?year=2024').status_code, 200)

    def test_unknown_report_404_and_post_rejected(self):
        self.assertEqual(self.client.get(reverse('report_view', args=['nope'])).status_code, 404)
        self.assertEqual(self.client.get(reverse('report_csv', args=['nope'])).status_code, 404)
        self.assertEqual(self.client.post(reverse('report_view', args=['annual'])).status_code, 405)
        self.assertEqual(self.client.post(reverse('report_csv', args=['annual'])).status_code, 405)

    def test_html_escapes_text(self):
        make_payment(org='<b>Bold</b> Co', gross='1').save()
        r = self.client.get(reverse('report_view', args=['organisation']))
        self.assertNotContains(r, '<b>Bold</b>')
        self.assertContains(r, '&lt;b&gt;Bold&lt;/b&gt; Co')

    def test_viewing_reports_changes_nothing_and_writes_no_files(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp, override_settings(UPLOAD_DIR=tmp):
            counts = Payment.objects.count()
            for key in BASE_KEYS:
                self.client.get(reverse('report_csv', args=[key]) + '?year=2024')
            self.assertEqual(Payment.objects.count(), counts)
            self.assertEqual(list(Path(tmp).rglob('*')), [])
