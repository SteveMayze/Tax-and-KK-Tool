"""Phase 31 (ADR 0032, spike): the payments page. Synthetic data only ("EXAMPLE ..." names). Figures are worked out
from this table (EUR rows have rate 1; USD rows use the manual rate 0.90; p4 is not converted):

    id  date        org  category  ccy  gross   net    withholding  gross EUR  net EUR
    p1  2026-01-10  A    X         EUR   100     90      10          100         90
    p2  2026-01-20  A    Y         EUR   200    200       0          200        200
    p3  2026-02-10  B    X         USD   400    340      60          360        306
    p4  2026-02-15  B    Z         USD   100    100       0          (not converted)
    p5  2026-03-10  C    W         EUR   -50    -50       0          -50        -50     (W may be negative)
    p6  2025-06-10  A    X         EUR    40     40       0           40         40

2026 (p1 to p5, 5 rows): EUR gross 100+200+360-50 = 610, net 90+200+306-50 = 546, 1 unconverted.
Original currencies 2026: EUR 3 payments gross 250, net 240, withholding 10; USD 2 payments gross 500, net 440,
withholding 60. All years add p6: EUR gross 290, net 280; EUR totals gross 650, net 586.
"""
import datetime
from decimal import Decimal as D
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import translation

from core.models import IncomeCategory, Organisation, Payment
from core.services import payment_list, report_filter
from core.services.conversion import convert_payment

from .test_helpers import make_payment
from .test_views import payment_post

NOW = 'core.services.payment_list.current_year'


def add(gross, net, date, org, cat, currency='EUR', withholding='0', convert=True, **kw):
    p = make_payment(gross=gross, net=net, date=date, currency=currency, org=f'EXAMPLE ORG {org}',
                     category=f'EXAMPLE CATEGORY {cat}', **kw)
    p.withholding_tax = D(withholding)
    p.save()
    if convert:
        convert_payment(p, manual_rate='0.90') if currency == 'USD' else convert_payment(p)
    return p


class Base(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user('pl', password='pw-for-tests-123'))
        d = datetime.date
        IncomeCategory.objects.create(name='EXAMPLE CATEGORY W', may_be_negative=True)
        self.p1 = add('100', '90', d(2026, 1, 10), 'A', 'X', withholding='10')
        self.p2 = add('200', '200', d(2026, 1, 20), 'A', 'Y')
        self.p3 = add('400', '340', d(2026, 2, 10), 'B', 'X', 'USD', '60')
        self.p4 = add('100', '100', d(2026, 2, 15), 'B', 'Z', 'USD', convert=False)
        self.p5 = add('-50', '-50', d(2026, 3, 10), 'C', 'W')
        self.p6 = add('40', '40', d(2025, 6, 10), 'A', 'X')
        self.org = {n: Organisation.objects.get(name=f'EXAMPLE ORG {n}').pk for n in 'ABC'}
        self.cat = {n: IncomeCategory.objects.get(name=f'EXAMPLE CATEGORY {n}').pk for n in 'XYZW'}
        patcher = mock.patch(NOW, return_value=2026)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.url = reverse('payment_list')

    def ids(self, response):
        return [p.pk for p in response.context['payments']]


class PageTests(Base):
    def test_P1_default_is_current_year_all_months_no_filter(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.context['year'], r.context['month'], r.context['filter'].is_active), (2026, None, False))
        self.assertEqual(self.ids(r), [self.p1.pk, self.p2.pk, self.p3.pk, self.p4.pk, self.p5.pk])
        self.assertNotContains(r, '<em>no filter</em>')
        self.assertNotIn('Filter', [label for label, _ in r.context['basis']])

    def test_P1_current_year_without_a_reporting_year_is_an_empty_list_not_an_error(self):
        with mock.patch(NOW, return_value=2031):
            r = self.client.get(self.url)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(self.ids(r), [])
            self.assertContains(r, 'There is no reporting year 2031')
            self.assertContains(r, 'No payments in this period.')
            self.assertContains(r, '<option value="2031" selected>')
            self.assertEqual(self.client.get(self.url, {'year': '2031'}).status_code, 200)

    def test_P2_month_lists_exactly_that_reporting_month(self):
        self.assertEqual(self.ids(self.client.get(self.url, {'year': '2026', 'month': '2'})), [self.p3.pk, self.p4.pk])
        self.assertEqual(self.ids(self.client.get(self.url, {'year': '2026', 'month': '1'})), [self.p1.pk, self.p2.pk])
        self.assertEqual(self.ids(self.client.get(self.url, {'year': '2026', 'month': '12'})), [])
        self.assertEqual(len(self.ids(self.client.get(self.url, {'year': '2026', 'month': 'all'}))), 5)

    def test_P2_all_years_ignores_the_month_and_says_so(self):
        r = self.client.get(self.url, {'year': 'all', 'month': '2'})
        self.assertEqual(len(self.ids(r)), 6)
        self.assertContains(r, 'a month without a year is meaningless')
        r = self.client.get(self.url, {'year': 'all'})
        self.assertNotContains(r, 'a month without a year is meaningless')
        self.assertEqual(r.context['eur'].gross_eur, D('650'))      # 610 + 40

    def test_P3_bad_parameters_are_messages_never_500(self):
        bad = [{'year': 'abc'}, {'year': '-1'}, {'year': '1999'}, {'year': '9' * 5000}, {'year': '²'}, {'year': '2026.5'},
               {'month': '0'}, {'month': '13'}, {'month': 'x' * 300}, {'month': '-3'}, {'month': '²'},
               {'organisation': 'abc'}, {'organisation': '99999'}, {'category': '-1'}, {'category': '7' * 400},
               {'ORGANISATION': '1'}, {'year': ['2026', '2025']}, {'month': ['1', '2']}]
        for params in bad:
            r = self.client.get(self.url, params, follow=True)
            self.assertEqual(r.status_code, 200, params)
            texts = [str(m) for m in r.context['messages']]
            self.assertEqual(len(texts), 1, params)
            self.assertTrue(texts[0].startswith('Unknown '), (params, texts))
            self.assertLessEqual(len(texts[0]), 80)
            self.assertEqual(r.redirect_chain[-1][0], self.url)
        r = self.client.get(self.url, {'year': 'abcdefghijklmnop'}, follow=True)
        self.assertEqual([str(m) for m in r.context['messages']], ['Unknown year "abcdefghij".'])

    def test_P4_filter_semantics_are_phase_30s(self):
        a, x = self.org['A'], self.cat['X']
        self.assertEqual(self.ids(self.client.get(self.url, {'organisation': a})), [self.p1.pk, self.p2.pk])
        self.assertEqual(self.ids(self.client.get(self.url, {'category': x})), [self.p1.pk, self.p3.pk])
        self.assertEqual(self.ids(self.client.get(self.url, {'organisation': a, 'category': x})), [self.p1.pk])
        self.assertEqual(self.ids(self.client.get(self.url, {'organisation': [a, self.org['B']], 'category': x})),
                         [self.p1.pk, self.p3.pk])
        self.assertEqual(self.ids(self.client.get(self.url, {'organisation': [a, a]})), [self.p1.pk, self.p2.pk])
        r = self.client.get(self.url, {'organisation': a})
        self.assertIn('Filter', [label for label, _ in r.context['basis']])
        self.assertContains(r, 'EXAMPLE ORG A.')

    def test_P4_the_page_uses_the_reports_partials(self):
        r = self.client.get(self.url)
        self.assertTemplateUsed(r, 'core/_report_filter.html')
        self.assertTemplateUsed(r, 'core/_filter_group.html')

    def test_P5_query_string_survives(self):
        params = {'year': '2026', 'month': '1', 'organisation': self.org['A'], 'category': [self.cat['X'], self.cat['Y']]}
        r = self.client.get(self.url, params)
        html = r.content.decode()
        self.assertIn('<option value="2026" selected>', html)
        self.assertIn('<option value="1" selected>', html)
        self.assertEqual(html.count(' checked>'), 3)
        # the edit and delete links carry this page's own address, with year, month and ticked boxes
        nxt = r.context['next_query']
        self.assertIn('year%3D2026', nxt)
        self.assertIn('month%3D1', nxt)
        self.assertIn(f'organisation%3D{self.org["A"]}', nxt)
        self.assertIn(f'href="{reverse("payment_edit", args=[self.p1.pk])}?{nxt}"', html.replace('&amp;', '&'))
        # Clear filters keeps year and month and drops the boxes
        self.assertIn(f'href="{self.url}?year=2026&amp;month=1"', html)
        # the language switch posts the full path back
        self.assertIn(f'name="next" value="{r.request["PATH_INFO"]}?', html)
        self.assertIn('organisation=', html.split('name="next" value="')[1].split('"')[0])

    def test_P5_language_switch_returns_to_the_same_query(self):
        target = f'{self.url}?year=2026&month=2&organisation={self.org["B"]}'
        r = self.client.post(reverse('set_language'), {'language': 'de', 'next': target})
        self.assertEqual(r.url, target)

    def test_P6_counts_for_the_selected_year_and_month_one_query_per_list(self):
        year = report_filter.options(2026, report_filter.NO_FILTER, 1)
        self.assertEqual({o['name']: o['count'] for o in year['organisation']},
                         {'EXAMPLE ORG A': 2, 'EXAMPLE ORG B': 0, 'EXAMPLE ORG C': 0})
        self.assertEqual({o['name']: o['count'] for o in year['category']}['EXAMPLE CATEGORY X'], 1)
        whole = report_filter.options(2026)
        self.assertEqual({o['name']: o['count'] for o in whole['organisation']}['EXAMPLE ORG A'], 2)
        allyears = report_filter.options(None, report_filter.NO_FILTER, 1)     # a month without a year is ignored
        self.assertEqual({o['name']: o['count'] for o in allyears['organisation']}['EXAMPLE ORG A'], 3)
        with self.assertNumQueries(2):
            report_filter.options(2026, report_filter.NO_FILTER, 2)
        r = self.client.get(self.url, {'year': '2026', 'month': '2'})
        self.assertContains(r, '<span class="note">(2)</span>')           # B has two payments in February 2026

    def test_P7_no_match(self):
        r = self.client.get(self.url, {'organisation': self.org['C'], 'category': self.cat['X']})
        self.assertEqual(self.ids(r), [])
        self.assertContains(r, 'No payments match this filter')
        self.assertIn('Filter', [label for label, _ in r.context['basis']])
        eur = r.context['eur']
        self.assertEqual((eur.payment_count, eur.gross_eur, eur.net_eur, eur.unconverted_count), (0, D(0), D(0), 0))
        self.assertEqual(r.context['by_currency'], [])

    def test_P8_totals_equal_the_rows_and_the_month_pages(self):
        for month in (1, 2, 3):
            page = self.client.get(self.url, {'year': '2026', 'month': str(month)})
            oracle = self.client.get(reverse('month_detail', args=[2026, month]))
            for field in ('payment_count', 'gross_eur', 'net_eur', 'unconverted_count', 'net_missing_count', 'withholding_eur'):
                self.assertEqual(getattr(page.context['eur'], field), getattr(oracle.context['actual'], field), (month, field))
        r = self.client.get(self.url)
        self.assertEqual(r.context['eur'].gross_eur, sum((p.gross_eur for p in r.context['payments'] if p.gross_eur is not None), D(0)))
        self.assertEqual(r.context['eur'].gross_eur, D('610'))
        self.assertEqual(r.context['eur'].net_eur, D('546'))

    def test_P8_filter_plus_complement_equals_unfiltered(self):
        whole = self.client.get(self.url).context
        a = self.client.get(self.url, {'organisation': self.org['A']}).context
        rest = self.client.get(self.url, {'organisation': [self.org['B'], self.org['C']]}).context
        self.assertEqual(len(a['payments']) + len(rest['payments']), len(whole['payments']))
        for field in ('gross_eur', 'net_eur', 'withholding_eur', 'unconverted_count'):
            self.assertEqual(getattr(a['eur'], field) + getattr(rest['eur'], field), getattr(whole['eur'], field), field)

    def test_P9_unconverted_and_negative_payments(self):
        r = self.client.get(self.url, {'month': '2'})
        self.assertIn(self.p4.pk, self.ids(r))
        self.assertContains(r, 'not converted')
        self.assertEqual(r.context['eur'].gross_eur, D('360'))              # p4 is left out
        self.assertEqual(r.context['eur'].unconverted_count, 1)
        self.assertContains(r, '1 payment(s) not converted are excluded from the EUR totals.')
        r = self.client.get(self.url, {'month': '3'})
        self.assertEqual(self.ids(r), [self.p5.pk])
        self.assertEqual(r.context['eur'].gross_eur, D('-50'))
        # a reversal is listed and totalled with its sign, as on the month page
        rev = add('-100', '-90', datetime.date(2026, 1, 25), 'A', 'X', kind='reversal', corrects=self.p1)
        r = self.client.get(self.url, {'month': '1'})
        self.assertIn(rev.pk, self.ids(r))
        self.assertEqual(r.context['eur'].gross_eur, D('200'))              # 100 + 200 - 100
        self.assertContains(r, '(Reversal)')

    def test_P10_original_currencies_are_never_added(self):
        by = {c.currency: c for c in self.client.get(self.url).context['by_currency']}
        self.assertEqual(set(by), {'EUR', 'USD'})
        self.assertEqual((by['EUR'].count, by['EUR'].gross, by['EUR'].net, by['EUR'].withholding), (3, D('250'), D('240'), D('10')))
        self.assertEqual((by['USD'].count, by['USD'].gross, by['USD'].net, by['USD'].withholding), (2, D('500'), D('440'), D('60')))

    def test_P11_login_and_get_only(self):
        self.client.logout()
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.url.startswith(reverse('login')))
        self.client.force_login(get_user_model().objects.get(username='pl'))
        before = list(Payment.objects.order_by('pk').values_list('pk', 'gross_amount', 'rate'))
        for method in (self.client.post, self.client.put, self.client.delete, self.client.patch):
            self.assertEqual(method(self.url).status_code, 405)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(list(Payment.objects.order_by('pk').values_list('pk', 'gross_amount', 'rate')), before)

    def test_P11_row_controls_keep_their_own_methods_and_accessible_names(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn(f'href="{reverse("payment_delete", args=[self.p1.pk])}?', html)    # a link only opens the confirmation page
        for label in ('View', 'Edit', 'Delete'):
            self.assertEqual(html.count(f'aria-label="{label}" title="{label}"'), 5)

    def test_P12_form_is_hidden_in_print_basis_and_totals_are_not(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('<form method="get" id="period" class="no-print">', html)
        self.assertIn('<section class="report-basis"', html)
        self.assertNotIn('no-print"><section', html)
        self.assertNotIn('class="no-print"><h2', html)
        self.assertIn('@media print', open('core/static/core/base.css').read())

    def test_P13_existing_pages_render_and_only_the_header_link_differs(self):
        for url in (reverse('home'), reverse('year_detail', args=[2026]), reverse('month_detail', args=[2026, 1]),
                    reverse('report_index'), reverse('report_view', args=['annual']), reverse('reconciliation')):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200, url)
            self.assertContains(r, f'href="{self.url}"')
        r = self.client.get(reverse('month_detail', args=[2026, 1]))
        self.assertNotContains(r, '?next=')

    def test_url_does_not_clash_with_the_payment_pages(self):
        self.assertEqual(reverse('payment_list'), '/payments/')
        self.assertEqual(self.client.get(reverse('payment_detail', args=[self.p1.pk])).status_code, 200)

    def test_sort_order_is_date_then_organisation_then_id(self):
        same = add('1', '1', datetime.date(2026, 1, 10), 'B', 'X')
        same2 = add('1', '1', datetime.date(2026, 1, 10), 'A', 'X')
        ids = self.ids(self.client.get(self.url, {'month': '1'}))
        self.assertEqual(ids, [self.p1.pk, same2.pk, same.pk, self.p2.pk])      # 10 Jan: A (p1, id order), A, B; then 20 Jan

    def test_template_has_fieldsets_labels_and_no_inline_style(self):
        html = self.client.get(self.url).content.decode()
        self.assertEqual(html.count('<fieldset'), 2)
        self.assertEqual(html.count('<legend>'), 2)
        for kind, ids in (('organisation', self.org), ('category', self.cat)):
            for pk in ids.values():
                self.assertIn(f'<label for="f-{kind}-{pk}">', html)
        self.assertNotIn('style=', html)
        self.assertIn('<label for="year"', html)
        self.assertIn('<label for="month"', html)
        self.assertIn('>Show</button>', html)
        self.assertIn('>Clear filters</a>', html)

    def test_the_form_is_plain_html_get(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('method="get"', html)
        self.assertNotIn('onchange=', html)

    def test_german_page(self):
        self.client.post(reverse('set_language'), {'language': 'de', 'next': '/'})
        html = self.client.get(self.url, {'month': '2'}).content.decode()
        self.assertIn('<h1>Zahlungen</h1>', html)
        self.assertIn('Februar', html)
        self.assertIn('Nicht umgerechnet', html.replace('nicht umgerechnet', 'Nicht umgerechnet'))
        self.assertIn('360,00', html)
        self.assertIn('Zeitraum', html)
        self.assertNotIn('Clear filters', html)
        self.assertNotIn('>Show<', html)

    def test_scale_with_many_rows(self):
        month_rows = [make_payment(gross='1', net='1', date=datetime.date(2026, 4, 1 + i % 28), org='EXAMPLE ORG A',
                                   category='EXAMPLE CATEGORY X') for i in range(400)]
        for p in month_rows:
            p.save()
        with self.assertNumQueries(7):
            r = self.client.get(self.url, {'year': '2026', 'month': '4'})
        self.assertEqual(len(r.context['payments']), 400)


class ParsePeriodTests(Base):
    def test_parse_defaults_and_values(self):
        from django.http import QueryDict
        parse = lambda q: payment_list.parse_period(QueryDict(q))
        self.assertEqual(parse(''), (2026, None, None))
        self.assertEqual(parse('year=all&month=3'), (None, 3, None))
        self.assertEqual(parse('year=2025&month=12'), (2025, 12, None))
        self.assertEqual(parse('year=&month='), (None, None, None))


class ReturnTests(Base):
    """Q31.7: edit and delete started from the payments page return to it; nothing else does."""

    def page(self):
        return f'{self.url}?year=2026&month=1&organisation={self.org["A"]}'

    def edit_url(self, nxt=None):
        url = reverse('payment_edit', args=[self.p1.pk])
        return url if nxt is None else f'{url}?next={nxt}'

    def post_edit(self, nxt=None, **over):
        data = payment_post(payment_date='2026-01-10', organisation_name='EXAMPLE ORG A', category_name='EXAMPLE CATEGORY X',
                            gross_amount='100', net_amount='90', withholding_tax='10', **over)
        return self.client.post(self.edit_url(nxt), data)

    def test_edit_without_next_is_unchanged(self):
        r = self.post_edit()
        self.assertRedirects(r, reverse('payment_detail', args=[self.p1.pk]))

    def test_edit_returns_to_the_page_with_its_query_string(self):
        from urllib.parse import quote
        r = self.post_edit(quote(self.page(), safe=''), comment='changed')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, self.page())
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.comment, 'changed')
        self.assertEqual(self.p1.gross_eur, D('100'))               # the stored rate is untouched

    def test_edit_form_offers_the_page_as_cancel_and_back(self):
        from urllib.parse import quote
        r = self.client.get(self.edit_url(quote(self.page(), safe='')))
        self.assertContains(r, f'href="{self.page().replace("&", "&amp;")}"', count=2)

    def test_unsafe_next_values_are_ignored(self):
        from urllib.parse import quote
        for bad in ('https://evil.example/payments/', '//evil.example/payments/', 'javascript:alert(1)',
                    '/payments/../years/', '/years/2026/', '/payments/1/', 'payments/', '/payments/%0d%0a',
                    '/payments/\\evil', 'x' * 500):
            r = self.post_edit(quote(bad, safe=''))
            self.assertEqual(r.url, reverse('payment_detail', args=[self.p1.pk]), bad)
            r = self.client.post(reverse('payment_delete', args=[self.p6.pk]) + '?next=' + quote(bad, safe=''), follow=False)
            self.assertEqual(r.status_code, 302)
            self.assertTrue(r.url.startswith('/years/'), (bad, r.url))
            self.p6 = add('40', '40', datetime.date(2025, 6, 10), 'A', 'X')

    def test_delete_confirmation_and_return(self):
        from urllib.parse import quote
        url = reverse('payment_delete', args=[self.p2.pk]) + '?next=' + quote(self.page(), safe='')
        r = self.client.get(url)
        self.assertContains(r, f'href="{self.page().replace("&", "&amp;")}"')
        self.assertContains(r, 'Yes, delete')
        r = self.client.post(url)
        self.assertEqual(r.url, self.page())
        self.assertFalse(Payment.objects.filter(pk=self.p2.pk).exists())

    def test_delete_without_next_still_returns_to_the_month_page(self):
        r = self.client.post(reverse('payment_delete', args=[self.p2.pk]))
        self.assertRedirects(r, reverse('month_detail', args=[2026, 1]))
        r = self.client.get(reverse('payment_delete', args=[self.p5.pk]))
        self.assertContains(r, f'href="{reverse("payment_detail", args=[self.p5.pk])}"')
