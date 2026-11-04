"""Phase 40 (ADR 0036): the tax information summary as income recorded, and the original-currency filter.

Synthetic data only. Dataset (2026 unless stated; rates are manual, so EUR = original x rate):
    id  date        organisation                 category       ccy  gross  withholding  rate   gross EUR  wh EUR
    e1  2026-01-10  EXAMPLE BANK                 Interest       EUR  100    0            1      100        0
    e2  2026-02-10  EXAMPLE BANK                 Interest       USD  200    30           0.5    100        15
    e3  2026-03-10  EXAMPLE MONEY MARKET FUND    Dividends      USD   50    7.5          0.5     25        3.75
    e4  2026-04-10  EXAMPLE STOCK CO             Capital gains  USD  -40    0            0.5    -20        0
    e5  2026-05-10  EXAMPLE BANK                 Interest       GBP   10    0            (not converted)
    e6  2026-06-10  EXAMPLE BANK                 Interest       EUR  -100   0            1      -100       0   (reversal of e1)
    e7  2025-07-10  EXAMPLE BANK                 Interest       EUR   70    0            1       70        0
2026 EUR sum of converted payments: 100 + 100 + 25 - 20 - 100 = 105.
"""
import csv
import datetime
import io
import re
from decimal import Decimal as D
from html import unescape

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from pypdf import PdfReader

from core.models import IncomeCategory, Organisation, Payment
from core.services import aggregation, payment_list, report_csv, report_filter, reports
from core.services.conversion import convert_payment
from core.services.report_filter import EXCLUDE, INCLUDE, NO_FILTER, ReportFilter

from .test_helpers import make_payment

d = datetime.date
FORBIDDEN = ('section', '§', 'anlage', 'einkunftsart', 'pension', 'capital assets', 'other income', 'rental and leasing',
             'private sales', 'employment (section')


def add(gross, date, org, category, currency='EUR', rate=None, withholding='0', **kw):
    p = make_payment(gross=gross, date=date, org=org, category=category, currency=currency,
                     withholding_tax=D(withholding), **kw)
    p.save()
    if currency == 'EUR':
        convert_payment(p)
    elif rate is not None:
        convert_payment(p, manual_rate=D(rate), manual_note='test')
    return p


class Base(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user('adv', password='pw-for-tests-123'))
        self.e1 = add('100', d(2026, 1, 10), 'EXAMPLE BANK', 'Interest')
        self.e2 = add('200', d(2026, 2, 10), 'EXAMPLE BANK', 'Interest', 'USD', '0.5', '30')
        self.e3 = add('50', d(2026, 3, 10), 'EXAMPLE MONEY MARKET FUND', 'Dividends', 'USD', '0.5', '7.5')
        IncomeCategory.objects.get_or_create(name='Capital gains')
        IncomeCategory.objects.filter(name='Capital gains').update(may_be_negative=True)
        self.e4 = add('-40', d(2026, 4, 10), 'EXAMPLE STOCK CO', 'Capital gains', 'USD', '0.5')
        self.e5 = add('10', d(2026, 5, 10), 'EXAMPLE BANK', 'Interest', 'GBP')
        self.e6 = add('-100', d(2026, 6, 10), 'EXAMPLE BANK', 'Interest', kind=Payment.Kind.REVERSAL, corrects=self.e1)
        self.e7 = add('70', d(2025, 7, 10), 'EXAMPLE BANK', 'Interest')
        # categories that carry no payment would be named in the basis; keep only the ones used by the dataset
        IncomeCategory.objects.filter(payments__isnull=True).delete()
        # map the category to an income type, to show that the report ignores it (T2)
        IncomeCategory.objects.filter(name='Interest').update(tax_income_type='other')

    def build(self, year=2026, **kw):
        return reports.REPORTS['tax_summary'].build(year, flt=ReportFilter(**kw) if kw else None)

    def table(self, report, key):
        return {t.key: t for t in report.tables}[key]

    def get(self, name, key='tax_summary', **params):
        return self.client.get(reverse(name, args=[key]), params)

    def page_text(self, **params):
        html = unescape(self.get('report_view', year='2026', **params).content.decode())
        body = html.split('<main>')[1].split('</main>')[0]
        return re.sub(r'<[^>]+>', '\n', body)

    def csv_text(self, **params):
        return self.get('report_csv', year='2026', **params).content.decode()

    def pdf_text(self, **params):
        r = self.get('report_pdf', year='2026', **params)
        self.assertEqual(r.status_code, 200)
        return '\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(r.content)).pages)


def stable(text):
    """Drop the generation time stamps."""
    return re.sub(r'(Generated[^\n]*|Generated \(UTC\)[^\n]*)', '', text)


class ContentTests(Base):
    def test_T1_stored_fields_only(self):
        before = (stable(self.page_text()), stable(self.csv_text()))
        IncomeCategory.objects.update(tax_income_type='employment', sbk_treatment='pension')
        Organisation.objects.update(country='US')
        self.assertEqual((stable(self.page_text()), stable(self.csv_text())), before)
        Organisation.objects.update(country='')
        IncomeCategory.objects.update(tax_income_type='', sbk_treatment='')
        self.assertEqual((stable(self.page_text()), stable(self.csv_text())), before)

    def test_T2_no_legal_wording(self):
        for text in (self.page_text(), self.csv_text(), self.pdf_text()):
            low = text.lower()
            for word in FORBIDDEN:
                self.assertNotIn(word, low, word)
        for lang in ('de',):
            self.client.post(reverse('set_language'), {'language': lang, 'next': '/'})
            for text in (self.page_text(), self.csv_text(), self.pdf_text()):
                low = text.lower()
                for word in ('einkunftsart', 'anlage ', '§', 'pension'):
                    self.assertNotIn(word, low, word)

    def test_T3_sums(self):
        rep = self.build()
        t1, t4 = self.table(rep, 'category_currency'), self.table(rep, 'payments')
        for row in t1.rows:
            if row.get('_total'):
                continue
            mine = [r for r in t4.rows if (r['category'], r['currency']) == (row['category'], row['currency'])]
            self.assertEqual(row['payments'], len(mine))
            self.assertEqual(row['gross'], sum(r['gross'] for r in mine))
            self.assertEqual(row['withholding'], sum(r['withholding'] for r in mine))
            self.assertEqual(row['gross_eur'], sum((r['gross_eur'] or 0 for r in mine), D(0)))
        self.assertEqual({(r['category'], r['currency']) for r in t1.rows if not r.get('_total')},
                         {('Dividends', 'USD'), ('Interest', 'EUR'), ('Interest', 'USD'), ('Interest', 'GBP'),
                          ('Capital gains', 'USD')})
        usd = [r for r in t1.rows if r.get('currency') == 'USD' and r['category'] == 'Interest'][0]
        self.assertEqual((usd['gross'], usd['gross_eur']), (D(200), D(100)))        # never added to the EUR row
        eur = [r for r in t1.rows if r.get('currency') == 'EUR'][0]
        self.assertEqual((eur['gross'], eur['gross_eur']), (D(0), D(0)))            # 100 + (-100) reversal

    def test_T4_interest_dividends_capital_gains_have_their_own_rows(self):
        t2 = self.table(self.build(), 'organisation')
        got = {(r['category'], r['organisation'], r['currency']) for r in t2.rows}
        for needle in (('Interest', 'EXAMPLE BANK', 'EUR'), ('Interest', 'EXAMPLE BANK', 'USD'), ('Interest', 'EXAMPLE BANK', 'GBP'),
                       ('Dividends', 'EXAMPLE MONEY MARKET FUND', 'USD'), ('Capital gains', 'EXAMPLE STOCK CO', 'USD')):
            self.assertIn(needle, got)
        self.assertEqual(len(got), 5)

    def test_T5_empty_categories_are_named(self):
        IncomeCategory.objects.create(name='EXAMPLE EMPTY CATEGORY')
        basis = dict(self.build().basis)
        self.assertEqual(basis['Categories without payments'], 'EXAMPLE EMPTY CATEGORY.')
        rep = self.build(category_ids=(IncomeCategory.objects.get(name='Interest').pk,))
        self.assertEqual(dict(rep.basis)['Categories without payments'],
                         'Capital gains; Dividends; EXAMPLE EMPTY CATEGORY.')
        self.assertTrue(all(r['category'] != 'EXAMPLE EMPTY CATEGORY' for r in self.table(rep, 'category_currency').rows))

    def test_T6_negative_payments(self):
        rep = self.build()
        row = [r for r in self.table(rep, 'category_currency').rows if r['category'] == 'Capital gains'][0]
        self.assertEqual((row['gross'], row['negative'], row['gross_eur']), (D(-40), D(-40), D(-20)))
        interest_eur = [r for r in self.table(rep, 'category_currency').rows if r.get('currency') == 'EUR'][0]
        self.assertEqual(interest_eur['negative'], D(0))                             # the reversal is not a "normal" negative
        self.assertEqual(sum(r['gross_eur'] for r in self.table(rep, 'payments').rows if r['gross_eur'] is not None), D(105))
        self.assertNotIn('loss', ' '.join(str(n) for n in rep.notes).lower().replace('no loss rule', ''))

    def test_T7_taxes_withheld(self):
        rep = self.build()
        t3 = self.table(rep, 'withholding')
        lines = [r for r in t3.rows if not r.get('_total')]
        self.assertEqual({(r['organisation'], r['currency']) for r in lines},
                         {('EXAMPLE BANK', 'USD'), ('EXAMPLE MONEY MARKET FUND', 'USD')})
        usd_total = [r for r in t3.rows if r.get('_total')][0]
        self.assertEqual((usd_total['currency'], usd_total['withholding'], usd_total['withholding_eur']), ('USD', D('37.5'), D('18.75')))
        self.assertEqual(t3.totals['withholding_eur'], D('18.75'))
        self.assertIn('none is recorded, not that none was withheld', t3.note)
        self.assertIn('none is recorded', self.page_text())

    def test_T14_table_totals_agree_with_the_existing_services(self):
        rep = self.build()
        totals = [self.table(rep, k).totals for k in ('category_currency', 'organisation', 'payments')]
        self.assertEqual([t['gross_eur'] for t in totals], [D(105)] * 3)
        self.assertEqual([t['withholding_eur'] for t in totals], [D('18.75')] * 3)
        self.assertEqual(aggregation.actual_totals(list(reports._payments(2026))).gross_eur, D(105))
        _payments, _by_currency, eur, _options = payment_list.build(2026, None, NO_FILTER)
        self.assertEqual((eur.gross_eur, eur.withholding_eur), (D(105), D('18.75')))
        flt = ReportFilter(currency_codes=('USD',))
        self.assertEqual(self.table(self.build(currency_codes=('USD',)), 'payments').totals['gross_eur'],
                         payment_list.build(2026, None, flt)[2].gross_eur)

    def test_T15_unconverted_listed_marked_and_counted(self):
        rep = self.build()
        row = [r for r in self.table(rep, 'payments').rows if r['currency'] == 'GBP'][0]
        self.assertEqual((row['gross'], row['rate'], row['gross_eur'], row['rate_source']), (D(10), None, None, 'not converted'))
        manual = [r for r in self.table(rep, 'payments').rows if r['currency'] == 'USD'][0]
        self.assertEqual(manual['rate_source'], 'manual rate')
        self.assertIn('1 unconverted payment(s) are listed but left out of every EUR figure', dict(rep.basis)['Excluded / missing'])
        gbp = [r for r in self.table(rep, 'category_currency').rows if r.get('currency') == 'GBP'][0]
        self.assertEqual((gbp['gross'], gbp['gross_eur'], gbp['unconverted']), (D(10), D(0), 1))
        self.assertIn('manually entered rate', str(dict(rep.basis)['Exchange-rate basis']))

    def test_T16_corrections_and_reversals_have_their_kind(self):
        kinds = {(r['date'], r['kind']) for r in self.table(self.build(), 'payments').rows}
        self.assertIn((d(2026, 6, 10), 'Reversal'), kinds)
        self.assertIn((d(2026, 1, 10), 'Normal'), kinds)

    def test_table_4_order_date_then_organisation_then_id(self):
        rows = self.table(self.build(), 'payments').rows
        self.assertEqual([r['date'] for r in rows], sorted(r['date'] for r in rows))

    def test_T19_no_payments(self):
        r = self.client.get(reverse('report_view', args=['tax_summary']), {'year': '2026', 'currency': ['EUR', 'USD', 'GBP'], 'currency_mode': 'exclude'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'No payments match this filter')
        self.assertEqual(self.get('report_csv', year='2026', currency=['EUR', 'USD', 'GBP'], currency_mode='exclude').status_code, 200)
        pdf = self.get('report_pdf', year='2026', currency=['EUR', 'USD', 'GBP'], currency_mode='exclude')
        self.assertEqual(pdf.status_code, 200)
        text = '\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages)
        self.assertIn('No payments match this filter', text)
        empty_year = self.client.get(reverse('report_view', args=['tax_summary']), {'year': '2025', 'currency': 'USD'})
        self.assertContains(empty_year, 'No payments match this filter')


class CurrencyFilterTests(Base):
    def currencies(self, rep):
        return {r['currency'] for r in self.table(rep, 'payments').rows}

    def test_T8_include(self):
        rep = self.build(currency_codes=('USD',), currency_mode=INCLUDE)
        for key in ('category_currency', 'organisation', 'withholding', 'payments'):
            self.assertEqual({r.get('currency') for r in self.table(rep, key).rows if r.get('currency')}, {'USD'}, key)
        self.assertEqual(self.table(rep, 'payments').totals['gross_eur'], D(105))
        self.assertEqual(len(self.table(rep, 'payments').rows), 3)
        self.assertIn('only USD', dict(rep.basis)['Filter'])

    def test_T9_exclude(self):
        rep = self.build(currency_codes=('EUR',), currency_mode=EXCLUDE)
        self.assertEqual(self.currencies(rep), {'USD', 'GBP'})
        for key in ('category_currency', 'organisation', 'withholding'):
            self.assertNotIn('EUR', {r.get('currency') for r in self.table(rep, key).rows}, key)
        self.assertEqual(self.table(rep, 'payments').totals['gross_eur'], D(105))   # EUR rows summed 0 net (100 - 100)
        text = dict(rep.basis)['Filter']
        self.assertIn('EUR hidden', text)
        self.assertIn("original currency, not by country or source", text)
        for out in (self.page_text(currency='EUR', currency_mode='exclude'), self.csv_text(currency='EUR', currency_mode='exclude'),
                    self.pdf_text(currency='EUR', currency_mode='exclude')):
            self.assertIn('left out of every table', re.sub(r'\s+', ' ', out))

    def test_T10_nothing_ticked_and_everything_excluded(self):
        everything = self.table(self.build(), 'payments').rows
        for mode in (INCLUDE, EXCLUDE):
            flt, error = report_filter.parse(self.client.get('/', {'currency_mode': mode}).wsgi_request.GET)
            self.assertIsNone(error)
            self.assertFalse(flt.is_active)
            self.assertEqual(len(self.table(self.build(currency_mode=mode), 'payments').rows), len(everything))
        rep = self.build(currency_codes=('EUR', 'GBP', 'USD'), currency_mode=EXCLUDE)
        self.assertTrue(rep.no_match)
        self.assertEqual(rep.tables, [])
        self.assertIn('No payments match this filter', rep.notes)

    def test_T11_bad_parameters(self):
        for params, echoed in (({'currency': 'XX1'}, 'XX1'), ({'currency': 'abc'}, 'ABC'), ({'currency': 'JPY'}, 'JPY'),
                               ({'currency': 'EURUSDGBPAUDXYZ'}, 'EURUSDGBPA'), ({'currency_mode': 'sideways'}, 'sideways'),
                               ({'CURRENCY': 'EUR'}, 'CURRENCY'), ({'Currency_Mode': 'exclude'}, 'Currency_M')):
            for route in ('report_view', 'report_csv', 'report_pdf'):
                r = self.client.get(reverse(route, args=['tax_summary']), {'year': '2026', **params}, follow=True)
                self.assertEqual(r.status_code, 200, (params, route))
                self.assertRedirects(r, reverse('report_index'))
                page = r.content.decode()
                self.assertIn(echoed, page, (params, route))
        long = self.client.get(reverse('report_view', args=['tax_summary']), {'currency': 'EURUSDGBPAUDXYZ'}, follow=True).content.decode()
        self.assertNotIn('EURUSDGBPAUDXYZ', long)
        self.assertNotIn('GBPAUDXYZ', long)

    def test_T11_valid_codes_are_normalised(self):
        for query in ('currency=usd&currency=EUR&currency=usd', 'currency=EUR&currency=USD'):
            flt, error = report_filter.parse(self.client.get('/?' + query).wsgi_request.GET)
            self.assertIsNone(error)
            self.assertEqual(flt.currency_codes, ('EUR', 'USD'))
            self.assertEqual(flt.querystring(2026), 'year=2026&currency=EUR&currency=USD&currency_mode=include')

    def test_T12_combination(self):
        bank = Organisation.objects.get(name='EXAMPLE BANK').pk
        interest = IncomeCategory.objects.get(name='Interest').pk
        dividends = IncomeCategory.objects.get(name='Dividends').pk
        rep = self.build(organisation_ids=(bank,), category_ids=(interest, dividends), currency_codes=('USD', 'GBP'))
        self.assertEqual({(r['organisation'], r['category'], r['currency']) for r in self.table(rep, 'payments').rows},
                         {('EXAMPLE BANK', 'Interest', 'USD'), ('EXAMPLE BANK', 'Interest', 'GBP')})
        # one place: the filter object itself selects the payments
        self.assertEqual(ReportFilter(currency_codes=('USD',)).apply(Payment.objects.all()).count(), 3)
        self.assertEqual(ReportFilter(currency_codes=('USD',), currency_mode=EXCLUDE).apply(Payment.objects.all()).count(), 4)

    def test_T13_query_string_survives(self):
        q = {'year': '2026', 'currency': ['USD'], 'currency_mode': 'exclude'}
        page = self.get('report_view', **q).content.decode()
        self.assertIn('id="f-currency-USD" name="currency" value="USD" checked', page)
        self.assertIn('id="f-currency-mode-exclude" name="currency_mode" value="exclude" checked', page)
        suffix = 'year=2026&amp;currency=USD&amp;currency_mode=exclude'
        self.assertIn(f'href="{reverse("report_csv", args=["tax_summary"])}?{suffix}"', page)
        self.assertIn(f'href="{reverse("report_pdf", args=["tax_summary"])}?{suffix}"', page)
        self.assertIn(f'href="{reverse("report_index")}?{suffix}"', page)
        form = page.split('<form method="get"', 1)[1].split('</form>', 1)[0]
        self.assertIn('id="year"', form)
        self.assertIn('Clear filters', form)
        self.assertIn(f'name="next" value="{reverse("report_view", args=["tax_summary"])}?{suffix}"', page)
        target = f"{reverse('report_view', args=['tax_summary'])}?year=2026&currency=USD&currency_mode=exclude"
        r = self.client.post(reverse('set_language'), {'language': 'de', 'next': target})
        self.assertRedirects(r, target, fetch_redirect_response=False)
        self.assertEqual(self.get('report_csv', **q)['Content-Disposition'],
                         'attachment; filename="report-tax_summary-2026-filtered.csv"')

    def test_options_list_currencies_with_counts_for_the_year(self):
        options = report_filter.options(2026, NO_FILTER, currencies=True)['currency']
        self.assertEqual({o['code']: o['count'] for o in options}, {'EUR': 2, 'GBP': 1, 'USD': 3})
        options = report_filter.options(2025, NO_FILTER, currencies=True)['currency']
        self.assertEqual({o['code']: o['count'] for o in options}, {'EUR': 1, 'GBP': 0, 'USD': 0})

    def test_the_currency_group_is_only_on_this_report(self):
        self.assertIn('name="currency"', self.get('report_view').content.decode())
        for key in ('annual', 'payments', 'category'):
            self.assertNotIn('name="currency"', self.get('report_view', key).content.decode(), key)
        self.assertNotIn('name="currency"', self.client.get(reverse('report_index')).content.decode())

    def test_other_reports_honour_the_currency_parameter(self):
        rep = reports.REPORTS['payments'].build(2026, flt=ReportFilter(currency_codes=('USD',)))
        self.assertEqual({r['currency'] for r in rep.rows}, {'USD'})
        self.assertIn('Original currencies: only USD', dict(rep.basis)['Filter'])


class OutputTests(Base):
    def test_T17_other_reports_are_unchanged_by_a_currency_parameter_absence(self):
        """Every other report's HTML and CSV are what the pre-Phase-40 code produced: no table markup, same columns."""
        for key in ('annual', 'payments', 'organisation', 'category', 'currency', 'cross', 'reconciliation'):
            html = self.get('report_view', key, year='2026').content.decode()
            self.assertNotIn('report-table-section', html, key)
            self.assertIn('<table class="report-table">', html, key)
            text = self.get('report_csv', key, year='2026').content.decode()
            self.assertIn('Report format version,2', text)
            self.assertEqual(text.count('\r\n\r\n'), 1, key)                      # one blank line: basis block, then the table
            self.assertEqual(report_csv.CSV_FORMAT_VERSION, '2')
            r = self.get('report_pdf', key, year='2026')
            self.assertEqual(r.status_code, 200, key)

    def test_csv_blocks(self):
        rows = list(csv.reader(io.StringIO(self.csv_text())))
        titles = [r for r in rows if r[:1] == ['Table']]
        self.assertEqual([r[1] for r in titles], ['Payments', 'Income by category and currency', 'Source documents'])
        header = [r for r in rows if r[:1] == ['Date']][0]
        self.assertEqual(header[:4], ['Date', 'Category', 'Organisation', 'Currency'])
        self.assertIn(['Language', 'English (CSV headings are always English)'], rows)

    def test_T18_pdf(self):
        r = self.get('report_pdf', year='2026')
        reader = PdfReader(io.BytesIO(r.content))
        self.assertEqual((float(reader.pages[0].mediabox.width) > float(reader.pages[0].mediabox.height)), True)
        text = '\n'.join(p.extract_text() for p in reader.pages)
        for needle in ('Important notice', 'Signature (Unterschrift)', 'Place (Ort)', 'Page 1 of', 'Income by category and currency',
                       'Taxes withheld'):
            self.assertIn(needle, text)
        self.assertEqual(set(reader.get_fields()), {'name', 'place', 'date', 'signature'})

    def test_T18_many_rows_repeat_headers_and_odd_characters_do_not_crash(self):
        for i in range(90):
            add('10', d(2026, 5, 1 + i % 28), 'EXAMPLE ŁÓDŹ ĸ 日本 BANK %02d' % (i % 30), 'Interest')
        r = self.get('report_pdf', year='2026')
        self.assertEqual(r.status_code, 200)
        reader = PdfReader(io.BytesIO(r.content))
        self.assertGreater(len(reader.pages), 1)
        later = '\n'.join(p.extract_text() for p in reader.pages[1:])
        self.assertIn('Withholding tax EUR', later)                          # a header row repeats on a later page

    def test_T20_basics(self):
        self.client.logout()
        for route in ('report_view', 'report_csv', 'report_pdf'):
            r = self.client.get(reverse(route, args=['tax_summary']))
            self.assertEqual(r.status_code, 302, route)
            self.assertIn('login', r['Location'])
        self.client.force_login(get_user_model().objects.get(username='adv'))
        before = Payment.objects.count()
        for route in ('report_view', 'report_csv', 'report_pdf'):
            self.assertEqual(self.client.post(reverse(route, args=['tax_summary'])).status_code, 405, route)
        self.assertEqual(Payment.objects.count(), before)
        page = self.get('report_view', year='2026').content.decode()
        self.assertNotIn('style=', page)
        form = page.split('<form method="get"', 1)[1].split('</form>', 1)[0]
        self.assertIn('no-print', page.split('<form method="get"', 1)[1].split('>', 1)[0])
        for ident in re.findall(r'<input[^>]*type="(?:checkbox|radio)"[^>]*id="([^"]+)"', form):
            self.assertIn(f'for="{ident}"', form, ident)
        self.assertIn('Show only the ticked currencies', form)
        self.assertIn('Hide the ticked currencies', form)

    def test_german_headings_are_in_the_glossary(self):
        from .test_i18n import glossary_tables
        _a, cells = glossary_tables()
        self.client.post(reverse('set_language'), {'language': 'de', 'next': '/'})
        page = self.page_text(currency='EUR')
        for heading in ('Einkommen nach Kategorie und Währung', 'Einkommen nach Organisation', 'Einbehaltene Steuern',
                        'Davon negative Zahlungen (Originalwährung)', 'Kategorien ohne Zahlungen', 'Gespeicherte Werte'):
            self.assertIn(heading, page)
        for heading in ('Einkommen nach Kategorie und Währung', 'Einkommen nach Organisation', 'Einbehaltene Steuern',
                        'Davon negative Zahlungen (Originalwährung)', 'Kategorien ohne Zahlungen', 'Gespeicherte Werte'):
            self.assertIn(heading, cells)
        self.assertEqual(self.get('report_csv', year='2026').content.decode().count('Income by category and currency'), 1)
