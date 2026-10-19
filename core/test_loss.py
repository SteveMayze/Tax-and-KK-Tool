"""Phase 11: capital loss. Synthetic data only."""
import datetime
import shutil
import tempfile
from decimal import Decimal as D
from pathlib import Path
from unittest import mock

from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from core.models import IncomeCategory, Payment, ReportingMonth
from core.services import imports as svc
from core.services import report_csv, reports
from core.services.aggregation import actual_totals
from core.services.policies import sbk, tax

from .test_helpers import make_payment
from .test_imports import csv_bytes, prov
from .test_policies_sbk import add, map_categories
from .test_views import DAY, AuthedTestCase, payment_post


def allow_loss(*names):
    IncomeCategory.objects.filter(name__in=names).update(may_be_negative=True)


class EntryTests(AuthedTestCase):
    def setUp(self):
        super().setUp()
        ReportingMonth.for_date(DAY)
        self.url = reverse('payment_add', args=[2024, 3])

    def test_loss_saves_in_a_flagged_category(self):
        allow_loss('Capital gains')
        r = self.client.post(self.url, payment_post(category_name='Capital gains', gross_amount='-500.00', frequency='one_off'))
        p = Payment.objects.get()
        self.assertRedirects(r, reverse('payment_detail', args=[p.pk]))
        self.assertEqual((p.gross_amount, p.gross_eur, p.kind), (D('-500'), D('-500'), 'normal'))

    def test_loss_in_an_unflagged_category_is_refused_naming_it(self):
        r = self.client.post(self.url, payment_post(category_name='Salary', gross_amount='-500.00'))
        self.assertContains(r, 'category &quot;Salary&quot; is not')
        self.assertEqual(Payment.objects.count(), 0)

    def test_loss_in_a_new_category_is_refused(self):
        r = self.client.post(self.url, payment_post(category_name='Brand New', gross_amount='-5'))
        self.assertContains(r, 'does not exist yet')
        self.assertFalse(IncomeCategory.objects.filter(name='Brand New').exists())

    def test_zero_is_still_refused(self):
        allow_loss('Interest')
        r = self.client.post(self.url, payment_post(category_name='Interest', gross_amount='0'))
        self.assertContains(r, 'must be positive')

    def test_flag_can_be_set_on_the_category_form(self):
        c = IncomeCategory.objects.get(name='Interest')
        r = self.client.post(reverse('category_edit', args=[c.pk]), {'name': 'Interest', 'active': 'on', 'may_be_negative': 'on',
                                                                       'sbk_treatment': '', 'tax_income_type': ''})
        c.refresh_from_db()
        self.assertTrue(c.may_be_negative)
        self.assertContains(self.client.get(reverse('category_list')), 'May be negative')

    def test_model_guards_every_save(self):
        p = make_payment(gross='-5', category='Salary')
        with self.assertRaises(ValidationError) as ctx:
            p.save()
        self.assertIn('Salary', str(ctx.exception))

    def test_loss_with_breakdown_still_balances(self):
        allow_loss('Interest')
        p = make_payment(gross='-100', net='-80', category='Interest', withholding_tax=D('-15'), expenses=D('-5'))
        p.save()
        self.assertEqual(p.unallocated, D('0'))

    def test_reversals_and_corrections_are_unchanged(self):
        orig = make_payment(); orig.save()
        rev = make_payment(gross='-1000', kind='reversal', corrects=orig); rev.save()
        self.assertEqual(rev.kind, 'reversal')


class ImportTests(TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._ov = override_settings(UPLOAD_DIR=self._tmp)
        self._ov.enable()
        self.addCleanup(self._ov.disable)
        self.addCleanup(shutil.rmtree, self._tmp, True)

    def stage(self, category):
        header = 'payment_date,organisation,category,currency,gross_amount,frequency'
        return svc.stage_batch(csv_bytes(f'2024-03-15,Broker,{category},EUR,-500.00,one_off', header=header), 'f.csv', prov())

    def test_negative_row_valid_only_for_flagged_category(self):
        row = self.stage('Salary').rows.get()
        self.assertEqual(row.status, 'invalid')
        self.assertTrue(any('"Salary"' in e and 'may be negative' in e for e in row.errors))
        allow_loss('Capital gains')
        b = self.stage('Capital gains')
        self.assertEqual(b.rows.get().status, 'valid')
        svc.commit_batch(b)
        self.assertEqual(Payment.objects.get().gross_eur, D('-500'))


class ReportTests(TestCase):
    def setUp(self):
        allow_loss('Interest')
        add(300, datetime.date(2026, 2, 1), 'Interest', 'Bank')
        add(-500, datetime.date(2026, 6, 1), 'Interest', 'Bank')
        add(100, datetime.date(2026, 7, 1), 'Dividends', 'Broker')

    def test_annual_summary_shows_gains_and_losses_separately(self):
        rep = reports.annual_summary(2026)
        row = rep.rows[0]
        self.assertEqual((row['gains_eur'], row['losses_eur'], row['gross_eur']), (D('400'), D('-500'), D('-100')))
        text = report_csv.render(rep)
        self.assertIn('Losses EUR (signed)', text)
        self.assertIn('-500.00', text)

    def test_category_report_gives_signed_net_per_category(self):
        rows = {r['name']: r for r in reports.by_category(2026).rows}
        self.assertEqual((rows['Interest']['gains_eur'], rows['Interest']['losses_eur'], rows['Interest']['gross_eur']),
                         (D('300'), D('-500'), D('-200')))
        self.assertEqual(rows['Dividends']['gross_eur'], D('100'))          # no netting across categories

    def test_gains_losses_adjustments_add_up_to_gross(self):
        orig = make_payment(gross='50', date=datetime.date(2026, 8, 1)); orig.save()
        from core.services.conversion import convert_payment
        convert_payment(orig)
        rev = make_payment(gross='-50', date=datetime.date(2026, 8, 2), kind='reversal', corrects=orig); rev.save()
        convert_payment(rev)
        t = actual_totals(Payment.objects.all())
        self.assertEqual(t.gains_eur + t.losses_eur + t.adjustments_eur, t.gross_eur)
        self.assertEqual(t.adjustments_eur, D('-50'))                       # a reversal is not a loss


class SbkTests(TestCase):
    def estimate(self):
        a = sbk.assess_year(2026)
        return [(m.assessed, m.kv, m.pflege) for m in a.months], a

    def test_negative_capital_surplus_equals_zero_capital_income(self):
        map_categories(Interest='capital', Dividends='pension')
        allow_loss('Interest')
        add(1000, datetime.date(2026, 3, 1), 'Dividends', 'Fund')
        baseline, _ = self.estimate()
        add(-800, datetime.date(2026, 6, 1), 'Interest', 'Bank')
        with_loss, a = self.estimate()
        self.assertEqual(with_loss, baseline)

    def test_basis_block_has_the_run_specific_not_netted_note(self):
        map_categories(Interest='capital')
        allow_loss('Interest')
        add(-800, datetime.date(2026, 6, 1), 'Interest', 'Bank')
        rep = reports.REPORTS['sbk'].build(2026)
        excluded = dict(rep.basis)['Excluded / missing']
        self.assertIn('Loss recorded in Capital income', excluded)
        self.assertIn('not netted against other income types or carried over', excluded)

    def test_no_note_without_a_loss(self):
        map_categories(Interest='capital')
        add(800, datetime.date(2026, 6, 1), 'Interest', 'Bank')
        self.assertNotIn('Loss recorded', dict(reports.REPORTS['sbk'].build(2026).basis)['Excluded / missing'])


class TaxTests(TestCase):
    def test_capital_loss_in_one_category_is_not_netted_against_another(self):
        IncomeCategory.objects.filter(name__in=['Interest', 'Dividends']).update(tax_income_type='capital', may_be_negative=True)
        add(1000, datetime.date(2026, 3, 1), 'Dividends', 'Fund')
        add(-400, datetime.date(2026, 5, 1), 'Interest', 'Bank')
        first = tax.tax_checks(2026)[0]
        self.assertEqual(first.amount, D('1000'))                           # the Interest loss is not subtracted
        self.assertIn('NOT offset', first.note)

    def test_summary_shows_losses_separately(self):
        IncomeCategory.objects.filter(name='Interest').update(tax_income_type='capital', may_be_negative=True)
        add(100, datetime.date(2026, 3, 1), 'Interest', 'Bank')
        add(-400, datetime.date(2026, 5, 1), 'Interest', 'Bank')
        rows, _ = tax.tax_summary_rows(2026)
        self.assertEqual((rows[0]['gross_eur'], rows[0]['losses_eur']), (D('-300'), D('-400')))
        self.assertTrue(any('not netted across categories' in t for t in tax.NOT_APPLIED))


class RulesDocTests(TestCase):
    def test_loss_offset_rules_are_registered_as_unverified(self):
        root = Path(__file__).resolve().parent.parent
        text = (root / 'docs/rules/income-tax-rules.md').read_text()
        row = [l for l in text.splitlines() if l.startswith('| TAX-11')][0]
        self.assertIn('Loss-offset rules', row)
        self.assertIn('UNVERIFIED', row)


class MigrationTests(TransactionTestCase):
    before = [('core', '0006_payment_withholding_tax_expenses')]
    after = [('core', '0007_incomecategory_may_be_negative')]

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def test_flag_set_from_the_owners_mapping_and_reversible(self):
        old = self.migrate(self.before)
        Cat = old.get_model('core', 'IncomeCategory')
        Cat.objects.create(name='M-Cap', tax_income_type='capital')
        Cat.objects.create(name='M-Sale', tax_income_type='private_sale')
        Cat.objects.create(name='M-Sbk', sbk_treatment='capital')
        Cat.objects.create(name='M-Plain', sbk_treatment='employment', tax_income_type='employment')
        Cat.objects.create(name='M-Blank')
        new = self.migrate(self.after)
        flags = dict(new.get_model('core', 'IncomeCategory').objects.filter(name__startswith='M-').values_list('name', 'may_be_negative'))
        self.assertEqual(flags, {'M-Cap': True, 'M-Sale': True, 'M-Sbk': True, 'M-Plain': False, 'M-Blank': False})
        back = self.migrate(self.before)
        self.assertEqual(back.get_model('core', 'IncomeCategory').objects.filter(name__startswith='M-').count(), 5)
        self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())
