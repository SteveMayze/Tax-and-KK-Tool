"""Phase 10: gross = net + withholding tax + expenses. Synthetic data only; rates from fakes."""
import datetime
import shutil
import tempfile
from decimal import Decimal as D
from unittest import mock

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from core.models import ConversionEvent, Payment, ReportingMonth
from core.services import imports as svc
from core.services import report_csv, reports
from core.services.aggregation import actual_totals
from core.services.conversion import convert_payment
from core.services.policies import tax

from .test_helpers import make_payment
from .test_imports import D1, csv_bytes, prov
from .test_views import DAY, PROVIDER, AuthedTestCase, fake, payment_post

BREAKDOWN_HEADER = ('payment_date,organisation,category,currency,gross_amount,net_amount,withholding_tax,expenses,'
                    'frequency,comment,exchange_rate,rate_date')


class FormTests(AuthedTestCase):
    def setUp(self):
        super().setUp()
        ReportingMonth.for_date(DAY)
        self.url = reverse('payment_add', args=[2024, 3])

    def post(self, **over):
        with mock.patch(PROVIDER, return_value=fake()):
            return self.client.post(self.url, payment_post(currency='GBP', gross_amount='1000.00', **over))

    def test_full_breakdown_saves_with_zero_unallocated(self):
        r = self.post(net_amount='800.00', withholding_tax='150.00', expenses='50.00')
        p = Payment.objects.get()
        self.assertRedirects(r, reverse('payment_detail', args=[p.pk]))
        self.assertEqual((p.withholding_tax, p.expenses, p.unallocated), (D('150'), D('50'), D('0')))
        self.assertContains(self.client.get(reverse('payment_detail', args=[p.pk])), 'unallocated 0.00')

    def test_gap_is_refused_with_the_three_numbers(self):
        r = self.post(net_amount='800.00', withholding_tax='0', expenses='0')
        self.assertEqual(Payment.objects.count(), 0)
        for text in ('Gross 1,000.00', 'net 800.00', 'withholding tax 0.00', 'expenses 0.00', '200.00 GBP is unallocated'):
            self.assertContains(r, text)

    def test_empty_fields_mean_zero_and_gross_only_needs_no_identity(self):
        self.post(net_amount='')
        p = Payment.objects.get()
        self.assertEqual((p.withholding_tax, p.expenses, p.unallocated), (D('0'), D('0'), None))

    def test_negative_values_refused_for_normal_payment(self):
        r = self.post(net_amount='1200', withholding_tax='-100', expenses='-100')
        self.assertContains(r, 'cannot be negative')
        self.assertEqual(Payment.objects.count(), 0)

    def test_form_page_has_live_unallocated_display(self):
        r = self.client.get(self.url)
        self.assertContains(r, 'id="unallocated"')
        self.assertContains(r, 'unallocated.js')


class ConversionTests(AuthedTestCase):
    def test_new_amounts_use_the_payments_own_rate_record(self):
        p = make_payment(currency='GBP', gross='1000', net='800', date=DAY, withholding_tax=D('150'), expenses=D('50'))
        p.save()
        convert_payment(p, fake())
        p.refresh_from_db()
        self.assertEqual((p.rate, p.withholding_tax_eur, p.expenses_eur), (D('1.2'), D('180'), D('60')))
        self.assertEqual(p.unallocated, D('0'))
        event = ConversionEvent.objects.get(payment=p)
        self.assertEqual(event.rate_record_id, p.rate_record_id)           # one rate record for all four amounts
        self.assertEqual(p.gross_eur - p.net_eur - p.withholding_tax_eur - p.expenses_eur, D('0'))

    def test_editing_amounts_reapplies_the_stored_rate_not_a_new_one(self):
        p = make_payment(currency='GBP', gross='1000', net='800', date=DAY, withholding_tax=D('150'), expenses=D('50'))
        p.save()
        convert_payment(p, fake())
        record = p.rate_record_id
        with mock.patch(PROVIDER, return_value=fake()):
            self.client.post(reverse('payment_edit', args=[p.pk]), payment_post(
                currency='GBP', gross_amount='1000', net_amount='800', withholding_tax='100', expenses='100'))
        p.refresh_from_db()
        self.assertEqual((p.rate_record_id, p.withholding_tax_eur, p.expenses_eur), (record, D('120'), D('120')))

    def test_eur_payment_uses_rate_one(self):
        p = make_payment(gross='100', net='85', withholding_tax=D('10'), expenses=D('5'))
        p.save()
        convert_payment(p)
        self.assertEqual((p.withholding_tax_eur, p.expenses_eur), (D('10'), D('5')))


class ExistingPaymentTests(AuthedTestCase):
    """A payment from before Phase 10 (gross 1000, net 800, nothing allocated)."""

    def setUp(self):
        super().setUp()
        self.p = make_payment(currency='GBP', gross='1000', net='800', date=DAY)
        self.p.save()
        convert_payment(self.p, fake())

    def test_it_opens_and_shows_its_unallocated_difference(self):
        r = self.client.get(reverse('payment_detail', args=[self.p.pk]))
        self.assertContains(r, 'unallocated 200.00 GBP')

    def test_rate_correction_still_works_without_fixing_the_gap(self):
        from core.services.conversion import correct_rate_manually
        correct_rate_manually(self.p, '1.3', 'bank statement')
        self.p.refresh_from_db()
        self.assertEqual(self.p.rate, D('1.3'))

    def test_saving_it_unchanged_is_refused_until_allocated(self):
        url = reverse('payment_edit', args=[self.p.pk])
        same = payment_post(currency='GBP', gross_amount='1000', net_amount='800')
        with mock.patch(PROVIDER, return_value=fake()):
            r = self.client.post(url, same)
            self.assertContains(r, '200.00 GBP is unallocated')
            r = self.client.post(url, {**same, 'expenses': '200'})
        self.assertRedirects(r, reverse('payment_detail', args=[self.p.pk]))
        self.p.refresh_from_db()
        self.assertEqual((self.p.expenses, self.p.expenses_eur), (D('200'), D('240')))


class SignedAdjustmentTests(TestCase):
    def test_reversal_carries_negative_breakdown(self):
        orig = make_payment(gross='100', net='80', withholding_tax=D('15'), expenses=D('5'))
        orig.save()
        rev = make_payment(gross='-100', net='-80', withholding_tax=D('-15'), expenses=D('-5'),
                           kind='reversal', corrects=orig)
        rev.save()
        self.assertEqual(rev.unallocated, D('0'))

    def test_wrong_sign_on_reversal_is_refused(self):
        from django.core.exceptions import ValidationError
        orig = make_payment(); orig.save()
        rev = make_payment(gross='-100', net='-80', withholding_tax=D('15'), kind='reversal', corrects=orig)
        with self.assertRaises(ValidationError):
            rev.save()


class ImportTests(TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._ov = override_settings(UPLOAD_DIR=self._tmp)
        self._ov.enable()
        self.addCleanup(self._ov.disable)
        self.addCleanup(shutil.rmtree, self._tmp, True)

    def stage(self, *rows, header=BREAKDOWN_HEADER):
        return svc.stage_batch(csv_bytes(*rows, header=header), 'f.csv', prov())

    def test_round_trip_with_the_new_columns(self):
        b = self.stage('2024-03-15,Bank AU,Interest,GBP,1000.00,800.00,150.00,50.00,one_off,,,')
        row = b.rows.get()
        self.assertEqual(row.status, 'valid')
        svc.commit_batch(b)
        p = Payment.objects.get()
        self.assertEqual((p.withholding_tax, p.expenses, p.withholding_tax_eur, p.expenses_eur), (D('150'), D('50'), D('180'), D('60')))

    def test_gap_with_the_new_columns_is_an_invalid_row(self):
        row = self.stage('2024-03-15,Bank AU,Interest,GBP,1000.00,800.00,0,0,one_off,,,').rows.get()
        self.assertEqual(row.status, 'invalid')
        self.assertTrue(any('breakdown' in e and '200.00' in e for e in row.errors))

    def test_old_file_without_the_columns_still_imports_and_shows_the_gap_as_unallocated(self):
        old_header = 'payment_date,organisation,category,currency,gross_amount,net_amount,frequency,comment,exchange_rate,rate_date'
        b = self.stage('2024-03-15,Old Co,Salary,EUR,1000.00,700.00,monthly,,,', header=old_header)
        row = b.rows.get()
        self.assertEqual(row.status, 'valid')
        self.assertTrue(any('imported as unallocated' in n for n in row.notes))
        svc.commit_batch(b)
        p = Payment.objects.get()
        self.assertEqual((p.withholding_tax, p.expenses, p.unallocated), (D('0'), D('0'), D('300')))

    def test_template_file_stages_cleanly(self):
        b = svc.stage_batch(svc.TEMPLATE_CSV.encode(), 't.csv', prov())
        self.assertEqual([r.status for r in b.rows.order_by('line_number')], ['valid', 'valid', 'valid'])


class ReportTests(TestCase):
    def setUp(self):
        p = make_payment(currency='GBP', gross='1000', net='800', date=DAY, withholding_tax=D('150'), expenses=D('50'),
                         org='Bank AU', category='Interest')
        p.save()
        convert_payment(p, fake())
        q = make_payment(gross='100', net='90', date=DAY, org='Old Co')    # older payment with a 10 gap
        q.save()
        convert_payment(q)

    def test_totals(self):
        t = actual_totals(Payment.objects.all())
        self.assertEqual((t.gross_eur, t.net_eur, t.withholding_eur, t.expenses_eur, t.unallocated_eur),
                         (D('1300'), D('1050'), D('180'), D('60'), D('10')))

    def test_every_gross_net_report_has_the_columns_on_screen_and_in_csv(self):
        for key in ('annual', 'monthly', 'organisation', 'category', 'payments', 'currency'):
            rep = reports.REPORTS[key].build(2024)
            labels = [c.label for c in rep.columns]
            for needed in ('Withholding tax', 'Expenses', 'Unallocated'):
                self.assertTrue(any(l.startswith(needed) for l in labels), (key, needed))
            self.assertIn('gross = net + withholding tax + expenses + unallocated', dict(rep.basis)['Gross/net'])
            self.assertIn('Withholding tax', report_csv.render(rep))
            self.assertEqual(rep.basis and dict(rep.basis)['Gross/net'].count('Identity'), 1)

    def test_values_in_the_organisation_report(self):
        rep = reports.by_organisation(2024)
        row = {r['name']: r for r in rep.rows}['Bank AU']
        self.assertEqual((row['withholding_eur'], row['expenses_eur'], row['unallocated_eur']), (D('180'), D('60'), D('0')))
        self.assertEqual(rep.totals['unallocated_eur'], D('10'))

    def test_reports_render_on_screen(self):
        from django.contrib.auth import get_user_model
        self.client.force_login(get_user_model().objects.create_user('t', password='pw-for-tests-123'))
        r = self.client.get(reverse('report_view', args=['category']) + '?year=2024')
        self.assertContains(r, 'Withholding tax EUR')
        r = self.client.get(reverse('report_csv', args=['category']) + '?year=2024')
        self.assertContains(r, 'Report format version,2')

    def test_tax_summary_shows_withholding_as_information_not_credited(self):
        rows, _ = tax.tax_summary_rows(2024)
        self.assertEqual(sum(r['withholding_eur'] for r in rows), D('180'))
        self.assertTrue(any('NOT credited' in t and 'treaty and foreign-tax-credit' in t for t in tax.NOT_APPLIED))

    def test_reconciliation_lists_the_gap(self):
        rows = reports.reconciliation(2024).rows
        self.assertEqual([r['organisation'] for r in rows if 'unallocated' in r['issue']], ['Old Co'])


class MigrationTests(TransactionTestCase):
    """Apply and reverse migration 0006 on a database holding payments from before it."""
    before = [('core', '0005_assessment_mappings_and_inputs')]
    after = [('core', '0006_payment_withholding_tax_expenses')]

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def test_apply_gives_zero_and_reverse_drops_the_columns(self):
        old = self.migrate(self.before)
        Org, Cat, Year, Month, Pay = (old.get_model('core', n) for n in
                                      ('Organisation', 'IncomeCategory', 'ReportingYear', 'ReportingMonth', 'Payment'))
        org = Org.objects.create(name='Mig Co')
        cat = Cat.objects.create(name='Mig Cat')
        month = Month.objects.create(year=Year.objects.create(year=2023), month=5)
        common = dict(month=month, organisation=org, category=cat, payment_date=datetime.date(2023, 5, 2), currency='GBP',
                      gross_amount=D('100'), net_amount=D('80'), frequency='monthly')
        Pay.objects.create(conversion_status='converted', rate=D('1.2'), rate_date=datetime.date(2023, 5, 2),
                           gross_eur=D('120'), net_eur=D('96'), **common)
        Pay.objects.create(conversion_status='pending', **common)
        new = self.migrate(self.after)
        converted, pending = new.get_model('core', 'Payment').objects.order_by('id')
        self.assertEqual((converted.withholding_tax, converted.expenses, converted.withholding_tax_eur, converted.expenses_eur),
                         (D('0'), D('0'), D('0'), D('0')))
        self.assertEqual((pending.withholding_tax, pending.withholding_tax_eur), (D('0'), None))
        self.assertEqual((converted.gross_amount, converted.net_amount, converted.gross_eur), (D('100'), D('80'), D('120')))
        back = self.migrate(self.before)
        self.assertFalse(hasattr(back.get_model('core', 'Payment'), 'withholding_tax'))
        self.assertEqual(back.get_model('core', 'Payment').objects.count(), 2)
        self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())     # leave the schema at the latest state
