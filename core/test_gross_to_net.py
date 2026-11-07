"""Phase 43 (ADR 0043): the "Gross to net by category and currency" table of the tax information summary.

Synthetic data only. Dataset (2026; manual rates, so EUR = original x rate):
    id  category       ccy  gross  net   withholding  expenses  rate   gross EUR  net EUR  wh EUR  exp EUR
    a   Rental         AUD  1000   700   0            300       0.5    500        350      0       150
    b   Rental         AUD  200    200   0            0         0.5    100        100      0       0
    c   Interest       USD  100    85    15           0         0.5    50         42.5     7.5     0
    d   Interest       EUR  50     none  0            0         1      50         (no net) 0       0
    e   Interest       GBP  10     10    0            0         (not converted)
    f   Capital gains  USD  -40    -40   0            0         0.5    -20        -20      0       0
"""
import csv
import datetime
import io
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from pypdf import PdfReader

from core.models import IncomeCategory, Payment
from core.services import report_csv, reports
from core.services.conversion import convert_payment
from core.services.report_filter import ReportFilter

from .test_helpers import make_payment

d = datetime.date
TITLE = 'Gross to net by category and currency'


def add(gross, net, ccy, category, rate=None, withholding='0', expenses='0', org='EXAMPLE ORG', date=d(2026, 3, 10)):
    p = make_payment(gross=gross, net=net, currency=ccy, category=category, org=org, date=date,
                     withholding_tax=D(withholding), expenses=D(expenses))
    p.save()
    if ccy == 'EUR':
        convert_payment(p)
    elif rate is not None:
        convert_payment(p, manual_rate=D(rate), manual_note='test')
    return p


class GrossToNetTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user('adv', password='pw-for-tests-123'))
        IncomeCategory.objects.get_or_create(name='Capital gains')
        IncomeCategory.objects.filter(name='Capital gains').update(may_be_negative=True)
        self.a = add('1000', '700', 'AUD', 'Rental', '0.5', expenses='300', org='EXAMPLE AGENT')
        self.b = add('200', '200', 'AUD', 'Rental', '0.5', org='EXAMPLE AGENT')
        self.c = add('100', '85', 'USD', 'Interest', '0.5', withholding='15')
        self.d = add('50', None, 'EUR', 'Interest')
        self.e = add('10', '10', 'GBP', 'Interest')
        self.f = add('-40', '-40', 'USD', 'Capital gains', '0.5')

    def report(self, **flt):
        return reports.REPORTS['tax_summary'].build(2026, flt=ReportFilter(**flt) if flt else None)

    def table(self, report=None):
        return {t.key: t for t in (report or self.report()).tables}['gross_to_net']

    def rows(self, report=None):
        return {(r['category'], r['currency']): r for r in self.table(report).rows}

    def test_position_and_columns(self):
        keys = [t.key for t in self.report().tables]
        self.assertEqual(keys, ['category_currency', 'gross_to_net', 'organisation', 'withholding', 'payments', 'sources'])
        self.assertEqual([c.key for c in self.table().columns],
                         ['category', 'currency', 'payments', 'gross', 'withholding', 'expenses', 'net', 'unallocated',
                          'gross_eur', 'withholding_eur', 'expenses_eur', 'net_eur'])

    def test_other_tables_are_unchanged(self):
        t = {t.key: t for t in self.report().tables}
        self.assertEqual([c.key for c in t['category_currency'].columns],
                         ['category', 'currency', 'payments', 'gross', 'negative', 'withholding', 'gross_eur', 'withholding_eur', 'unconverted'])
        self.assertEqual([c.key for c in t['payments'].columns],
                         ['date', 'category', 'organisation', 'currency', 'gross', 'withholding', 'rate', 'rate_date', 'rate_source',
                          'gross_eur', 'withholding_eur', 'kind', 'source', 'comment'])

    def test_group_figures(self):
        rows = self.rows()
        rental = rows[('Rental', 'AUD')]
        self.assertEqual((rental['payments'], rental['gross'], rental['withholding'], rental['expenses'], rental['net'], rental['unallocated']),
                         (2, D('1200'), D('0'), D('300'), D('900'), D('0')))
        self.assertEqual((rental['gross_eur'], rental['withholding_eur'], rental['expenses_eur'], rental['net_eur']),
                         (D('600'), D('0'), D('150'), D('450')))
        usd = rows[('Interest', 'USD')]
        self.assertEqual((usd['gross'], usd['withholding'], usd['net'], usd['net_eur'], usd['withholding_eur']),
                         (D('100'), D('15'), D('85'), D('42.5'), D('7.5')))
        loss = rows[('Capital gains', 'USD')]
        self.assertEqual((loss['gross'], loss['net'], loss['net_eur']), (D('-40'), D('-40'), D('-20')))
        for r in rows.values():
            if r['net'] is not None:
                self.assertEqual(r['gross'] - r['net'] - r['withholding'] - r['expenses'], r['unallocated'])

    def test_no_net_is_blank_not_zero(self):
        eur = self.rows()[('Interest', 'EUR')]
        self.assertEqual(eur['gross'], D('50'))
        self.assertIsNone(eur['net'])
        self.assertIsNone(eur['unallocated'])
        self.assertIsNone(eur['net_eur'])
        self.assertIn('1 payment(s) have no net amount recorded', self.table().note)

    def test_unconverted_payment_adds_nothing_to_eur(self):
        gbp = self.rows()[('Interest', 'GBP')]
        self.assertEqual((gbp['gross'], gbp['net']), (D('10'), D('10')))
        self.assertEqual((gbp['gross_eur'], gbp['expenses_eur'], gbp['withholding_eur']), (D('0'), D('0'), D('0')))
        self.assertIsNone(gbp['net_eur'])

    def test_totals_are_eur_only_sums_of_the_rows(self):
        t = self.table()
        self.assertEqual(t.totals['gross_eur'], D('500') + D('100') + D('50') + D('50') - D('20'))
        self.assertEqual(t.totals['expenses_eur'], D('150'))
        self.assertEqual(t.totals['withholding_eur'], D('7.5'))
        self.assertEqual(t.totals['net_eur'], D('350') + D('100') + D('42.5') - D('20'))     # the payment with no net adds nothing
        self.assertEqual(t.totals['payments'], 6)
        for r in t.rows:
            self.assertNotIn('_total', r)

    def test_a_broken_breakdown_is_shown_and_flagged(self):
        Payment.objects.filter(pk=self.b.pk).update(net_amount=D('150'))          # gross 200 - net 150 = 50 not allocated
        r = self.rows()[('Rental', 'AUD')]
        self.assertEqual(r['unallocated'], D('50'))
        self.assertIn('Unallocated = gross - net - withholding tax - expenses', self.table().note)

    def test_no_flag_when_everything_adds_up(self):
        Payment.objects.filter(pk=self.d.pk).update(net_amount=D('50'))
        self.assertEqual(self.table().note, '')

    def test_filter_applies(self):
        rep = self.report(organisation_ids=(self.a.organisation_id,))
        got = {(r['category'], r['currency']) for r in self.table(rep).rows}
        self.assertEqual(got, {('Rental', 'AUD')})
        self.assertEqual(self.table(rep).totals['net_eur'], D('450'))
        self.assertGreater(len(self.rows()), 1)

    def test_basis_wording(self):
        text = dict(self.report().basis)['Gross/net']
        self.assertNotIn('not shown', text)
        self.assertIn('gross = net + withholding tax + expenses', text)
        self.assertIn('not a deduction', text)
        for word in ('werbungskosten', 'anlage', 'section', '§', 'deductible'):
            self.assertNotIn(word, text.lower())

    def get(self, name):
        return self.client.get(reverse(name, args=['tax_summary']), {'year': '2026'})

    def test_html_shows_the_table(self):
        body = self.get('report_view').content.decode()
        self.assertIn(TITLE, body)
        self.assertIn('id="table-gross_to_net"', body)
        self.assertLess(body.index('id="table-category_currency"'), body.index('id="table-gross_to_net"'))
        self.assertLess(body.index('id="table-gross_to_net"'), body.index('id="table-organisation"'))

    def test_csv_has_the_table_and_version_3(self):
        self.assertEqual(report_csv.CSV_FORMAT_VERSION, '3')
        text = self.get('report_csv').content.decode()
        rows = list(csv.reader(io.StringIO(text)))
        self.assertIn(['Report format version', '3'], rows)
        i = rows.index(['Table', TITLE])
        self.assertEqual(rows[i + 1], ['Category', 'Currency', 'Payments', 'Gross', 'Withholding tax', 'Expenses', 'Net', 'Unallocated',
                                       'Gross EUR', 'Withholding tax EUR', 'Expenses EUR', 'Net EUR'])
        rental = [r for r in rows[i + 2:] if r[:2] == ['Rental', 'AUD']][0]
        self.assertEqual(rental[2:], ['2', '1200.00', '0.00', '300.00', '900.00', '0.00', '600.00', '0.00', '150.00', '450.00'])
        nonet = [r for r in rows[i + 2:] if r[:2] == ['Interest', 'EUR']][0]
        self.assertEqual((nonet[6], nonet[7], nonet[11]), ('', '', ''))                 # blank, not 0.00
        tables = [r[1] for r in rows if r[:1] == ['Table']]
        self.assertEqual(tables, ['Payments', 'Income by category and currency', TITLE, 'Source documents'])

    def test_csv_is_formula_safe(self):
        add('10', '10', 'EUR', '=SUM(1+1)')
        text = self.get('report_csv').content.decode()
        self.assertIn("'=SUM(1+1)", text)
        self.assertNotIn(',=SUM', text)

    def test_pdf_has_the_table_without_broken_headers(self):
        r = self.get('report_pdf')
        self.assertEqual(r.status_code, 200)
        text = '\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(r.content)).pages)
        self.assertIn(TITLE, text)
        for broken in ('Withholdin\n', 'Expense\ns', 'Payment\ns'):
            self.assertNotIn(broken, text)
        self.assertIn('gross, withholding tax, expenses and net', text.replace('\n', ' '))

    def test_other_reports_keep_their_tables(self):
        for key in ('annual', 'payments', 'category', 'tax_checks', 'sbk'):
            rep = reports.REPORTS[key].build(2026)
            self.assertNotIn('gross_to_net', [t.key for t in rep.tables or []])


class PdfTitleTests(TestCase):
    def test_a_table_title_is_preceded_by_a_conditional_page_break(self):
        from reportlab.platypus import CondPageBreak
        from core.services import report_pdf
        flow = report_pdf._grid(['A'], [[('x', '')]], None, 200, title='T')
        self.assertIsInstance(flow[0], CondPageBreak)
        self.assertEqual(len(report_pdf._grid(['A'], [[('x', '')]], None, 200)), 1)        # no title, no break
