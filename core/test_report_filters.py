"""Phase 30 (ADR 0031): organisation and category filters on reports. Synthetic data only ("EXAMPLE ..." names).

Dataset (EUR, so gross EUR = gross; every figure below is worked out from this table):
    id  date        organisation  category  gross
    p1  2026-01-10  A             X         100
    p2  2026-02-10  A             Y         200
    p3  2026-03-10  B             X         400
    p4  2026-04-10  B             Z         800
    p5  2026-05-10  C             Y        1600
    p6  2025-06-10  A             X          50
2026 totals: A 300, B 1200, C 1600; X 500, Y 1800, Z 800; all 3100. All years: A 350, X 550, all 3150.
"""
import csv
import datetime
import io
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import IncomeCategory, Organisation, Payment
from core.services import report_csv, report_filter, reports
from core.services.conversion import convert_payment
from core.services.report_filter import NO_FILTER, ReportFilter

from .test_helpers import make_payment


def add(gross, date, org, cat, **kw):
    p = make_payment(gross=gross, net=gross, date=date, org=f'EXAMPLE ORG {org}', category=f'EXAMPLE CATEGORY {cat}', **kw)
    p.save()
    if p.currency == 'EUR':
        convert_payment(p)
    return p


class FilterBase(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user('flt', password='pw-for-tests-123'))
        d = datetime.date
        add('100', d(2026, 1, 10), 'A', 'X')
        add('200', d(2026, 2, 10), 'A', 'Y')
        add('400', d(2026, 3, 10), 'B', 'X')
        add('800', d(2026, 4, 10), 'B', 'Z')
        add('1600', d(2026, 5, 10), 'C', 'Y')
        add('50', d(2025, 6, 10), 'A', 'X')
        self.org = {n: Organisation.objects.get(name=f'EXAMPLE ORG {n}').pk for n in 'ABC'}
        self.cat = {n: IncomeCategory.objects.get(name=f'EXAMPLE CATEGORY {n}').pk for n in 'XYZ'}

    def flt(self, orgs='', cats=''):
        return ReportFilter(tuple(sorted(self.org[o] for o in orgs)), tuple(sorted(self.cat[c] for c in cats)))

    def rows(self, report, key='name', value='gross_eur'):
        return {r[key]: r[value] for r in report.rows}

    def get(self, name, key=None, **params):
        args = [key] if key else []
        return self.client.get(reverse(name, args=args), params)

    def csv_rows(self, key, query=''):
        text = self.client.get(reverse('report_csv', args=[key]) + query).content.decode()
        return list(csv.reader(io.StringIO(text)))


class SemanticsTests(FilterBase):
    def test_F0_unfiltered_equals_no_filter_and_has_no_filter_row(self):
        for key, spec in reports.REPORTS.items():
            if not spec.supports_filter:
                continue
            year = 2026
            a, b = spec.build(year), spec.build(year, flt=NO_FILTER)
            self.assertEqual((a.rows, a.totals, [x for x in a.basis]), (b.rows, b.totals, [x for x in b.basis]), key)
            self.assertNotIn('Filter', [str(l) for l, _t in a.basis], key)

    def test_F1_organisation_across_categories(self):
        # A in 2026: X 100 + Y 200.
        self.assertEqual(self.rows(reports.by_category(2026, self.flt('A'))), {'EXAMPLE CATEGORY X': D(100), 'EXAMPLE CATEGORY Y': D(200)})
        self.assertEqual(self.rows(reports.by_organisation(2026, self.flt('A'))), {'EXAMPLE ORG A': D(300)})
        # A and X only: 100.
        self.assertEqual(self.rows(reports.by_category(2026, self.flt('A', 'X'))), {'EXAMPLE CATEGORY X': D(100)})

    def test_F2_category_across_organisations(self):
        # Y in 2026: A 200 + C 1600.
        self.assertEqual(self.rows(reports.by_organisation(2026, self.flt(cats='Y'))), {'EXAMPLE ORG C': D(1600), 'EXAMPLE ORG A': D(200)})

    def test_F3_and_between_groups_or_within(self):
        # orgs A,B and cats X,Y: A/X 100 + A/Y 200 + B/X 400 = 700 (B/Z and C/Y excluded).
        report = reports.payment_level(2026, self.flt('AB', 'XY'))
        self.assertEqual(sorted(r['gross_eur'] for r in report.rows), [D(100), D(200), D(400)])
        self.assertEqual(report.totals['gross_eur'], D(700))

    def test_F4_empty_group_is_no_restriction(self):
        self.assertEqual(reports.payment_level(2026, self.flt(cats='X')).totals['gross_eur'], D(500))
        self.assertEqual(reports.payment_level(2026, self.flt(orgs='B')).totals['gross_eur'], D(1200))
        self.assertEqual(reports.payment_level(2026, ReportFilter()).totals['gross_eur'], D(3100))
        self.assertFalse(ReportFilter().is_active)

    def test_F5_ticking_everything_equals_ticking_nothing(self):
        everything = self.flt('ABC', 'XYZ')
        for key in ('annual', 'organisation', 'category', 'payments', 'currency', 'cross'):
            a, b = reports.REPORTS[key].build(None), reports.REPORTS[key].build(None, flt=everything)
            self.assertEqual((a.rows, a.totals), (b.rows, b.totals), key)
        self.assertIn('Filter', [str(l) for l, _t in reports.annual_summary(None, everything).basis])

    def test_F14_year_and_filter_together(self):
        self.assertEqual(reports.payment_level(2025, self.flt('A')).totals['gross_eur'], D(50))
        annual = reports.annual_summary(None, self.flt('A'))
        self.assertEqual(self.rows(annual, 'year'), {'2025': D(50), '2026': D(300)})
        only_b = reports.annual_summary(None, self.flt('B'))
        self.assertEqual(self.rows(only_b, 'year'), {'2026': D(1200)})              # 2025 has no B payment: not listed

    def test_partition_filtered_plus_complement_equals_unfiltered(self):
        def gross(report):
            if report.totals and 'gross_eur' in report.totals:
                return report.totals['gross_eur']
            if report.key == 'normalised':
                return sum((r['gross_monthly'] for r in report.rows), D(0))
            return sum((r['gross_eur'] for r in report.rows), D(0))
        for key, spec in reports.REPORTS.items():
            if not spec.supports_filter or key == 'reconciliation':
                continue
            year = 2026 if spec.needs_year else None
            whole = gross(spec.build(year))
            by_org = gross(spec.build(year, flt=self.flt('A'))) + gross(spec.build(year, flt=self.flt('BC')))
            by_cat = gross(spec.build(year, flt=self.flt(cats='X'))) + gross(spec.build(year, flt=self.flt(cats='YZ')))
            self.assertEqual(by_org, whole, key)
            self.assertEqual(by_cat, whole, key)

    def test_F8_look_alike_names_are_never_mixed(self):
        make_payment(gross='7', net='7', org='EXAMPLE ORG Ä', category='EXAMPLE CATEGORY X', date=datetime.date(2026, 6, 1)).save()
        make_payment(gross='9', net='9', org='EXAMPLE ORG AE', category='EXAMPLE CATEGORY X', date=datetime.date(2026, 6, 2)).save()
        umlaut, ae = (Organisation.objects.get(name=n).pk for n in ('EXAMPLE ORG Ä', 'EXAMPLE ORG AE'))
        only = reports.by_organisation(2026, ReportFilter((umlaut,)))
        self.assertEqual([r['name'] for r in only.rows], ['EXAMPLE ORG Ä'])
        self.assertEqual([r['name'] for r in reports.by_organisation(2026, ReportFilter((ae,))).rows], ['EXAMPLE ORG AE'])
        self.assertNotIn('EXAMPLE ORG A,', ReportFilter((umlaut,)).describe() + ',')

    def test_F9_corrections_and_reversals_follow_the_filter(self):
        orig = Payment.objects.get(gross_amount=D(400))
        rev = make_payment(gross='-400', net='-400', date=datetime.date(2026, 3, 20), org='EXAMPLE ORG B',
                           category='EXAMPLE CATEGORY X', kind='reversal', corrects=orig)
        rev.save()
        convert_payment(rev)
        b = reports.by_organisation(2026, self.flt('B'))
        row = b.rows[0]
        # B: X 400 - 400 reversal, Z 800 -> gross 800; gains 1200 (normal), reversal -400 in the corrections column.
        self.assertEqual((row['gross_eur'], row['gains_eur'], row['adjustments_eur']), (D(800), D(1200), D(-400)))
        a = reports.by_organisation(2026, self.flt('A'))
        self.assertEqual(a.rows[0]['adjustments_eur'], D(0))
        self.assertIn('1 correction/reversal entry included', reports._exclusions(list(reports._payments(2026, self.flt('B')))))
        self.assertEqual(reports._exclusions(list(reports._payments(2026, self.flt('A')))), 'None.')

    def test_F10_exclusions_and_rate_basis_count_only_the_filtered_payments(self):
        make_payment(gross='30', currency='GBP', org='EXAMPLE ORG C', category='EXAMPLE CATEGORY Y',
                     date=datetime.date(2026, 7, 1)).save()           # not converted
        c = reports.by_organisation(2026, self.flt('C'))
        self.assertEqual(c.rows[0]['unconverted'], 1)
        self.assertIn('1 unconverted payment(s)', dict((str(l), t) for l, t in c.basis)['Excluded / missing'])
        a = reports.by_organisation(2026, self.flt('A'))
        self.assertEqual(a.rows[0]['unconverted'], 0)
        basis = dict((str(l), t) for l, t in a.basis)
        self.assertEqual(basis['Excluded / missing'], 'None.')
        self.assertIn('2 x EUR (rate 1)', basis['Exchange-rate basis'])      # A's two 2026 payments only

    def test_F11_empty_months_stay(self):
        monthly = reports.monthly_breakdown(2026, self.flt('A'))
        self.assertEqual(len(monthly.rows), 12)
        self.assertEqual([r['gross_eur'] for r in monthly.rows][:3], [D(100), D(200), D(0)])
        self.assertEqual(monthly.totals['gross_eur'], D(300))
        self.assertEqual(len(reports.normalised_monthly(2026, self.flt('A')).rows), 12)

    def test_F12_shares_add_up_within_the_filter(self):
        report = reports.by_organisation(2026, self.flt('AB'))
        # A 300 and B 1200 of 1500: 20 % and 80 %.
        self.assertEqual(self.rows(report, 'name', 'share'), {'EXAMPLE ORG A': D('0.2'), 'EXAMPLE ORG B': D('0.8')})
        self.assertTrue(any('relative to the filtered total' in n for n in report.notes))
        self.assertFalse(any('relative to the filtered total' in n for n in reports.by_organisation(2026).notes))

    def test_F13_no_match(self):
        report = reports.by_organisation(2026, self.flt('A', 'Z'))     # A has no payment in Z
        self.assertTrue(report.no_match)
        self.assertEqual((report.rows, report.totals['payments']), ([], 0))
        self.assertIn('No payments match this filter', report.notes)
        self.assertIn('Filter', [str(l) for l, _t in report.basis])
        page = self.get('report_view', 'organisation', year='2026', organisation=self.org['A'], category=self.cat['Z']).content.decode()
        self.assertIn('No payments match this filter', page)
        self.assertNotIn('No data for this period', page)
        rows = self.csv_rows('organisation', f"?year=2026&organisation={self.org['A']}&category={self.cat['Z']}")
        header_at = [i for i, r in enumerate(rows) if r[:1] == ['Organisation']][0]
        self.assertEqual([r for r in rows[header_at + 1:] if r], [r for r in rows[header_at + 1:] if r and r[0] == 'Total'])

    def test_reconciliation_and_tax_summary_honour_the_filter(self):
        make_payment(gross='30', currency='GBP', org='EXAMPLE ORG C', category='EXAMPLE CATEGORY Y', date=datetime.date(2026, 7, 1)).save()
        # the one GBP payment has no rate yet and no net amount: two issues, both organisation C
        self.assertEqual([r['organisation'] for r in reports.reconciliation(2026, self.flt('C')).rows], ['EXAMPLE ORG C'] * 2)
        self.assertEqual(len(reports.reconciliation(2026, self.flt('A')).rows), 0)
        rows = reports.REPORTS['tax_summary'].build(2026, flt=self.flt('B')).rows
        self.assertEqual(sum(r['payments'] for r in rows), 2)
        self.assertEqual(sum(r['gross_eur'] for r in rows), D(1200))

    def test_cross_table_shows_every_pairing(self):
        report = reports.cross_table(2026)
        cols = {str(c.label): c.key for c in report.columns}
        a = {r['organisation']: r for r in report.rows}
        self.assertEqual(a['EXAMPLE ORG A'][cols['EXAMPLE CATEGORY X']], D(100))
        self.assertEqual(a['EXAMPLE ORG A'][cols['EXAMPLE CATEGORY Y']], D(200))
        self.assertIsNone(a['EXAMPLE ORG A'][cols['EXAMPLE CATEGORY Z']])           # no pairing: blank
        self.assertEqual(a['EXAMPLE ORG B'][cols['EXAMPLE CATEGORY Z']], D(800))
        self.assertEqual(report.totals[cols['EXAMPLE CATEGORY Y']], D(1800))
        self.assertEqual(report.totals['gross_eur'], D(3100))
        self.assertEqual(sum(r['gross_eur'] for r in report.rows), D(3100))
        filtered = reports.cross_table(2026, self.flt('A', 'XY'))
        self.assertEqual([str(c.label) for c in filtered.columns][:3], ['Organisation', 'EXAMPLE CATEGORY X', 'EXAMPLE CATEGORY Y'])
        self.assertEqual(filtered.totals['gross_eur'], D(300))


class ParseTests(FilterBase):
    def parse(self, query):
        from django.http import QueryDict
        return report_filter.parse(QueryDict(query))

    def test_ids_are_sorted_and_duplicates_collapse(self):
        a, b = self.org['A'], self.org['B']
        flt, error = self.parse(f'organisation={b}&organisation={a}&organisation={b}')
        self.assertIsNone(error)
        self.assertEqual(flt.organisation_ids, (a, b))
        self.assertEqual(flt.querystring(2026), f'year=2026&organisation={a}&organisation={b}')

    def test_F7_bad_ids_are_errors_that_echo_at_most_ten_characters(self):
        for query in ('organisation=abc', 'organisation=-1', 'organisation=99999', 'category=' + '9' * 40, 'category=1.5',
                      'organisation=%E2%82%AC', 'Organisation=1', 'CATEGORY=1', 'organisation=1+OR+1%3D1'):
            flt, error = self.parse(query)
            self.assertIsNotNone(error, query)
            self.assertFalse(flt.is_active, query)
            self.assertLessEqual(len(error), 80, query)
            self.assertNotIn('9' * 11, error)

    def test_F7_views_never_500_and_redirect_with_the_message(self):
        for query in ('organisation=abc', 'category=-1', 'organisation=999999', 'ORGANISATION=1', 'organisation=' + 'x' * 5000):
            for name, args in (('report_view', ['annual']), ('report_csv', ['annual']), ('report_view', ['sbk'])):
                r = self.client.get(reverse(name, args=args) + '?year=2026&' + query, follow=True)
                self.assertEqual(r.status_code, 200, (name, query))
                self.assertRedirects(r, reverse('report_index'))
                self.assertContains(r, 'role="status"')
                self.assertNotContains(r, 'x' * 11)

    def test_blank_values_mean_nothing_ticked(self):
        flt, error = self.parse('organisation=&category=')
        self.assertEqual((error, flt.is_active), (None, False))


class OptionsTests(FilterBase):
    def test_options_list_every_party_with_payments_and_counts_for_the_period(self):
        Organisation.objects.create(name='EXAMPLE ORG NO PAYMENTS')
        opts = report_filter.options(2026)
        self.assertEqual([o['name'] for o in opts['organisation']], ['EXAMPLE ORG A', 'EXAMPLE ORG B', 'EXAMPLE ORG C'])
        self.assertEqual({o['name']: o['count'] for o in opts['organisation']},
                         {'EXAMPLE ORG A': 2, 'EXAMPLE ORG B': 2, 'EXAMPLE ORG C': 1})
        self.assertEqual({o['name']: o['count'] for o in report_filter.options(None)['organisation']}['EXAMPLE ORG A'], 3)
        self.assertEqual({o['name']: o['count'] for o in report_filter.options(2025)['organisation']}['EXAMPLE ORG B'], 0)   # zero is visible

    def test_options_use_one_query_per_list(self):
        with self.assertNumQueries(2):
            report_filter.options(2026, self.flt('A'))

    def test_F6_inactive_is_listed_marked_and_filterable(self):
        Organisation.objects.filter(pk=self.org['C']).update(active=False)
        IncomeCategory.objects.filter(pk=self.cat['Z']).update(active=False)
        page = self.get('report_view', 'organisation', year='2026').content.decode()
        self.assertIn('EXAMPLE ORG C <span class="note">(inactive)</span>', page)
        self.assertIn('EXAMPLE CATEGORY Z <span class="note">(inactive)</span>', page)
        self.assertEqual(reports.payment_level(2026, self.flt('C')).totals['gross_eur'], D(1600))

    def test_F18_long_lists_scroll_inside_a_details_block(self):
        for i in range(30):
            make_payment(gross='1', org=f'EXAMPLE ORG LONG {i:02d}', category=f'EXAMPLE CATEGORY LONG {i % 12:02d}',
                         date=datetime.date(2026, 8, 1)).save()
        page = self.get('report_view', 'annual').content.decode()
        self.assertEqual(page.count('type="checkbox" id="f-organisation-'), 33)
        self.assertEqual(page.count('type="checkbox" id="f-category-'), 15)
        self.assertIn('<details class="filter">', page)
        self.assertNotIn('<details class="filter" open', page)
        css = (reports.__file__.rsplit('/services/', 1)[0] + '/static/core/base.css')
        self.assertRegex(open(css).read(), r'\.filter-options \{[^}]*max-height[^}]*overflow-y: auto')


class ViewTests(FilterBase):
    def test_F19_login_get_only_and_no_store(self):
        self.client.logout()
        for name in ('report_view', 'report_csv'):
            r = self.client.get(reverse(name, args=['annual']) + '?organisation=1')
            self.assertEqual(r.status_code, 302)
            self.assertIn('/accounts/login/', r['Location'])
        self.client.force_login(get_user_model().objects.get(username='flt'))
        for name in ('report_view', 'report_csv', 'report_index'):
            args = [] if name == 'report_index' else ['annual']
            self.assertEqual(self.client.post(reverse(name, args=args), {'organisation': self.org['A']}).status_code, 405)
        n = Payment.objects.count()
        r = self.get('report_csv', 'annual', organisation=self.org['A'])
        self.assertEqual(r['Cache-Control'], 'no-store')
        self.assertEqual(Payment.objects.count(), n)

    def test_filter_row_on_page_and_csv_and_not_when_unfiltered(self):
        q = {'year': '2026', 'organisation': [self.org['A'], self.org['B']], 'category': self.cat['X']}
        page = self.client.get(reverse('report_view', args=['category']), q).content.decode()
        self.assertIn('<dt><strong>Filter</strong></dt>', page)
        self.assertIn('Organisations: EXAMPLE ORG A, EXAMPLE ORG B. Categories: EXAMPLE CATEGORY X. Combined as: any of the ticked '
                      'organisations AND any of the ticked categories', page)
        rows = self.csv_rows('category', f"?year=2026&organisation={self.org['A']}&organisation={self.org['B']}&category={self.cat['X']}")
        self.assertEqual(rows[1], ['Report format version', '2'])
        flt = [r for r in rows[:14] if r and r[0] == 'Filter']
        self.assertEqual(len(flt), 1)
        self.assertIn('EXAMPLE ORG A, EXAMPLE ORG B', flt[0][1])
        firsts = [r[:1] for r in rows]
        self.assertLess(firsts.index(['Period']), firsts.index(['Filter']))
        unfiltered = self.get('report_view', 'category', year='2026').content.decode()
        self.assertNotIn('<dt><strong>Filter</strong></dt>', unfiltered)
        self.assertNotIn('Filter', [r[0] for r in self.csv_rows('category', '?year=2026') if r])

    def test_csv_file_name(self):
        plain = self.get('report_csv', 'annual', year='2026')
        self.assertEqual(plain['Content-Disposition'], 'attachment; filename="report-annual-2026.csv"')
        filtered = self.get('report_csv', 'annual', year='2026', organisation=self.org['A'])
        self.assertEqual(filtered['Content-Disposition'], 'attachment; filename="report-annual-2026-filtered.csv"')
        self.assertEqual(self.get('report_csv', 'annual', organisation=self.org['A'])['Content-Disposition'],
                         'attachment; filename="report-annual-all-filtered.csv"')

    def test_csv_filter_names_are_protected_against_formulas(self):
        make_payment(gross='5', org='=EXAMPLE ORG F', category='EXAMPLE CATEGORY X', date=datetime.date(2026, 9, 1)).save()
        oid = Organisation.objects.get(name='=EXAMPLE ORG F').pk
        rows = self.csv_rows('organisation', f'?year=2026&organisation={oid}')
        flt = [r for r in rows if r[:1] == ['Filter']][0]
        self.assertTrue(flt[1].startswith("'") or "'=EXAMPLE ORG F" in flt[1] or flt[1].startswith('Organisations'))
        self.assertTrue(any(r and r[0] == "'=EXAMPLE ORG F" for r in rows))

    def test_F15_reports_that_cannot_honour_the_filter(self):
        for key in ('sbk', 'tax_checks'):
            plain = self.get('report_view', key, year='2026')
            filtered = self.client.get(reverse('report_view', args=[key]), {'year': '2026', 'organisation': self.org['A'], 'category': self.cat['X']})
            self.assertEqual(plain.status_code, 200)
            body = lambda r: r.content.decode().split('id="basis-heading"', 1)[1].split('Generated', 1)[0]
            # the figures (table) are identical; only the explicit Filter row differs
            self.assertEqual(body(plain).split('<table', 1)[1], body(filtered).split('<table', 1)[1], key)
            self.assertIn('Not applied to this report', filtered.content.decode())
            self.assertIn('does not apply to this report', filtered.content.decode())
            self.assertNotIn('f-organisation-', filtered.content.decode())          # no filter form on these pages
            csv_plain = self.csv_rows(key, '?year=2026')
            csv_filtered = self.csv_rows(key, f"?year=2026&organisation={self.org['A']}")
            self.assertEqual([r for r in csv_filtered if r[:1] != ['Filter'] and r[:1] != ['Generated (UTC)']],
                             [r for r in csv_plain if r[:1] != ['Generated (UTC)']])
            self.assertTrue(any(r[0] == 'Filter' and r[1].startswith('Not applied to this report') for r in csv_filtered))
            self.assertEqual(self.get('report_csv', key, year='2026', organisation=self.org['A'])['Content-Disposition'],
                             f'attachment; filename="report-{key}-2026.csv"')

    def test_F16_query_string_survives(self):
        a = self.org['A']
        page = self.client.get(reverse('report_view', args=['annual']), {'year': '2026', 'organisation': a}).content.decode()
        self.assertIn(f'id="f-organisation-{a}" name="organisation" value="{a}" checked', page)
        self.assertIn(f'href="{reverse("report_csv", args=["annual"])}?year=2026&amp;organisation={a}"', page)
        self.assertIn(f'href="{reverse("report_index")}?year=2026&amp;organisation={a}"', page)
        self.assertIn('name="year"', page)                                           # year selector is in the same GET form as the boxes
        form = page.split('<form method="get"', 1)[1].split('</form>', 1)[0]
        self.assertIn('id="year"', form)
        self.assertIn('Clear filters', form)
        index = self.client.get(reverse('report_index'), {'year': '2026', 'organisation': a}).content.decode()
        self.assertIn(f'id="f-organisation-{a}" name="organisation" value="{a}" checked', index)
        self.assertIn('<details class="filter" open>', index)
        # the header language switch posts the full path including the query string
        self.assertIn(f'name="next" value="{reverse("report_view", args=["annual"])}?year=2026&amp;organisation={a}"', page)

    def test_F16_language_switch_keeps_the_query_string(self):
        a = self.org['A']
        target = f"{reverse('report_view', args=['annual'])}?year=2026&organisation={a}"
        r = self.client.post(reverse('set_language'), {'language': 'de', 'next': target})
        self.assertRedirects(r, target, fetch_redirect_response=False)

    def test_F17_print_hides_the_form_but_not_the_filter_row(self):
        page = self.get('report_view', 'annual', organisation=self.org['A']).content.decode()
        form = page.split('<form method="get"', 1)[1].split('>', 1)[0]
        self.assertIn('no-print', form)
        self.assertIn('Filter</strong></dt>', page.split('report-basis', 1)[1])
        css = open(reports.__file__.rsplit('/services/', 1)[0] + '/static/core/base.css').read()
        self.assertIn('.no-print', css.split('@media print', 1)[1])

    def test_index_page_has_the_filter_and_links_open_unfiltered_without_javascript(self):
        page = self.get('report_index').content.decode()
        self.assertIn('f-organisation-', page)
        self.assertIn(f'href="{reverse("report_view", args=["annual"])}"', page)
        self.assertIn('every report except the SBK contribution estimate', page)

    def test_cross_report_is_listed_and_downloadable(self):
        self.assertContains(self.get('report_index'), reverse('report_view', args=['cross']))
        rows = self.csv_rows('cross', '?year=2026')
        header = [r for r in rows if r[:1] == ['Organisation']][0]
        self.assertEqual(header, ['Organisation', 'EXAMPLE CATEGORY X', 'EXAMPLE CATEGORY Y', 'EXAMPLE CATEGORY Z', 'Payments', 'Gross EUR (signed sum)'])


class TemplateAndLanguageTests(FilterBase):
    def test_fieldsets_legends_and_labels(self):
        import re
        page = self.get('report_view', 'annual').content.decode()
        self.assertEqual(page.count('<fieldset class="filter-group"'), 2)
        self.assertEqual(page.count('<legend>'), 2)
        ids = re.findall(r'<input type="checkbox" id="([^"]+)"', page)
        self.assertEqual(len(ids), 6)
        for i in ids:
            self.assertIn(f'<label for="{i}">', page)
        self.assertNotRegex(page, r'\sstyle\s*=')

    def test_the_form_is_plain_html_get_that_works_without_javascript(self):
        page = self.get('report_view', 'annual').content.decode()
        form = page.split('<form method="get"', 1)[1].split('</form>', 1)[0]
        self.assertIn('type="submit"', form)
        self.assertIn('<details class="filter">', form)
        self.assertIn('report_filter.js', form)                                     # enhancement only (All / None buttons)

    def test_german_page_and_english_csv(self):
        self.client.post(reverse('set_language'), {'language': 'de', 'next': '/'})
        page = self.client.get(reverse('report_view', args=['annual']), {'year': '2026', 'organisation': self.org['A']}).content.decode()
        for text in ('Nach Organisation und Kategorie filtern', 'Filter zurücksetzen', 'Organisationen', 'Kategorien', 'aktiv',
                     'Verknüpfung: eine der angekreuzten Organisationen UND eine der angekreuzten Kategorien'):
            self.assertIn(text, page)
        self.assertNotIn('Clear filters', page)
        sbk = self.client.get(reverse('report_view', args=['sbk']), {'year': '2026', 'organisation': self.org['A']}).content.decode()
        self.assertIn('nicht angewendet', sbk.lower())
        rows = self.csv_rows('annual', f"?year=2026&organisation={self.org['A']}")
        flt = [r for r in rows if r[:1] == ['Filter']][0]
        self.assertIn('Combined as: any of the ticked organisations AND', flt[1])
        self.assertEqual(self.get('report_view', 'cross').status_code, 200)
        self.assertContains(self.get('report_view', 'cross', year='2026'), 'Organisation nach Kategorie')
