import datetime
from decimal import Decimal as D
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import ExchangeRateRecord, IncomeCategory, Organisation, Payment, ReportingMonth, ReportingYear
from core.services.rates import FakeRateProvider

from .test_helpers import make_payment

PROVIDER = 'core.views_payments.get_provider'
DAY = datetime.date(2024, 3, 15)


def fake(**kw):
    return FakeRateProvider({('GBP', DAY): D('1.2')}, **kw)


@override_settings(RATE_PROVIDER='core.services.rates.ManualOnlyProvider')
class AuthedTestCase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('tester', password='pw-for-tests-123')
        self.client.force_login(self.user)


class LoginRequiredTests(TestCase):
    def test_every_financial_view_requires_login(self):
        p = make_payment(); p.save()
        urls = [
            reverse('home'), reverse('year_add'), reverse('year_detail', args=[2024]),
            reverse('year_notes', args=[2024]), reverse('year_delete', args=[2024]),
            reverse('month_add', args=[2024, 3]), reverse('month_detail', args=[2024, 3]),
            reverse('month_delete', args=[2024, 3]), reverse('payment_add', args=[2024, 3]),
            reverse('payment_detail', args=[p.pk]), reverse('payment_edit', args=[p.pk]),
            reverse('payment_delete', args=[p.pk]), reverse('payment_recalculate', args=[p.pk]),
            reverse('organisation_list'), reverse('organisation_add'), reverse('category_list'),
            reverse('category_add'),
        ]
        for url in urls:
            for method in (self.client.get, self.client.post):
                r = method(url)
                self.assertEqual(r.status_code, 302, url)
                self.assertTrue(r.url.startswith(reverse('login')), url)
        self.assertEqual(Payment.objects.count(), 1)


class YearMonthTests(AuthedTestCase):
    def test_add_year_and_validation(self):
        r = self.client.post(reverse('year_add'), {'year': 2024, 'notes': 'n'})
        self.assertRedirects(r, reverse('year_detail', args=[2024]))
        r = self.client.post(reverse('year_add'), {'year': 2024})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'already exists')
        r = self.client.post(reverse('year_add'), {'year': 1500})
        self.assertContains(r, 'greater than or equal to 1900')
        self.assertEqual(ReportingYear.objects.count(), 1)

    def test_year_page_shows_twelve_months_including_empty(self):
        ReportingYear.objects.create(year=2024)
        r = self.client.get(reverse('year_detail', args=[2024]))
        for name in ('January', 'June', 'December'):
            self.assertContains(r, name)
        self.assertEqual(r.content.decode().count('aria-label="Add month"'), 12)

    def test_add_and_delete_month_with_confirmation(self):
        ReportingYear.objects.create(year=2024)
        self.client.post(reverse('month_add', args=[2024, 5]))
        self.assertTrue(ReportingMonth.objects.filter(year__year=2024, month=5).exists())
        self.assertEqual(self.client.post(reverse('month_add', args=[2024, 13])).status_code, 302)
        self.assertEqual(ReportingMonth.objects.count(), 1)
        # GET only asks for confirmation
        self.assertContains(self.client.get(reverse('month_delete', args=[2024, 5])), 'Yes, delete')
        self.assertEqual(ReportingMonth.objects.count(), 1)
        self.client.post(reverse('month_delete', args=[2024, 5]))
        self.assertEqual(ReportingMonth.objects.count(), 0)

    def test_delete_year_cascades_after_confirmation(self):
        p = make_payment(); p.save()
        r = self.client.get(reverse('year_delete', args=[2024]))
        self.assertContains(r, '1 payment(s)')
        self.assertEqual(Payment.objects.count(), 1)
        self.client.post(reverse('year_delete', args=[2024]))
        self.assertEqual((Payment.objects.count(), ReportingYear.objects.count()), (0, 0))

    def test_home_totals_and_labels(self):
        from core.services.conversion import convert_payment
        p = make_payment(gross='1200', net='900'); p.save(); convert_payment(p)
        q = make_payment(gross='50'); q.save()  # unconverted
        r = self.client.get(reverse('home'))
        self.assertContains(r, '1,200.00')
        self.assertContains(r, '100.00')  # 1200 / 12
        self.assertContains(r, '÷ 12')
        self.assertContains(r, '1 unconverted')
        self.assertContains(r, '1 of 12 months')


class MonthPageTests(AuthedTestCase):
    def test_payment_table_columns(self):
        from core.services.conversion import convert_payment
        a = make_payment(gross='1200', net='900', frequency='quarterly', comment='bonus-ish'); a.save(); convert_payment(a)
        b = make_payment(gross='500', frequency='one_off', category='Capital gains'); b.save(); convert_payment(b)
        r = self.client.get(reverse('month_detail', args=[2024, 3]))
        self.assertContains(r, 'Acme Test GmbH')
        self.assertContains(r, '400.00')            # 1200 / 3
        self.assertContains(r, 'n/a (one-off)')
        self.assertContains(r, 'bonus-ish')
        self.assertContains(r, 'Normalised monthly')

    def test_unconverted_payment_is_flagged(self):
        p = make_payment(currency='GBP'); p.save()
        r = self.client.get(reverse('month_detail', args=[2024, 3]))
        self.assertContains(r, 'not converted')


class LookupManagementTests(AuthedTestCase):
    def test_add_edit_deactivate_organisation(self):
        self.client.post(reverse('organisation_add'), {'name': 'Foo Ltd', 'country': 'gb', 'active': 'on'})
        org = Organisation.objects.get(name='Foo Ltd')
        self.assertEqual(org.country, 'GB')
        self.client.post(reverse('organisation_edit', args=[org.pk]), {'name': 'Foo Ltd', 'country': 'GB'})
        org.refresh_from_db()
        self.assertFalse(org.active)

    def test_duplicate_spelling_rejected(self):
        Organisation.objects.create(name='Foo Ltd')
        r = self.client.post(reverse('organisation_add'), {'name': 'foo  ltd', 'active': 'on'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Organisation.objects.count(), 1)

    def test_delete_unused_and_blocked_when_used(self):
        free = Organisation.objects.create(name='Unused')
        self.client.post(reverse('organisation_delete', args=[free.pk]))
        self.assertFalse(Organisation.objects.filter(name='Unused').exists())
        p = make_payment(); p.save()
        r = self.client.get(reverse('category_delete', args=[p.category.pk]))
        self.assertNotContains(r, 'Yes, delete')
        self.client.post(reverse('category_delete', args=[p.category.pk]))
        self.assertTrue(IncomeCategory.objects.filter(pk=p.category.pk).exists())

    def test_category_list_shows_seeds(self):
        self.assertContains(self.client.get(reverse('category_list')), 'Capital gains')


def payment_post(**over):
    data = {'payment_date': '2024-03-15', 'organisation_name': 'New Corp', 'category_name': 'Salary',
            'currency': 'EUR', 'gross_amount': '1000.00', 'net_amount': '', 'frequency': 'monthly',
            'comment': ''}
    data.update(over)
    return data


class PaymentFlowTests(AuthedTestCase):
    def setUp(self):
        super().setUp()
        ReportingMonth.for_date(DAY)
        self.add_url = reverse('payment_add', args=[2024, 3])

    def test_add_eur_payment_shows_confirmation(self):
        r = self.client.post(self.add_url, payment_post(net_amount='700', withholding_tax='300'), follow=True)
        p = Payment.objects.get()
        self.assertRedirects(r, reverse('payment_detail', args=[p.pk]))
        self.assertContains(r, 'Original amount')
        self.assertContains(r, '1 EUR per 1 EUR')
        self.assertContains(r, 'Gross 1,000.00 EUR')
        self.assertEqual((p.gross_eur, p.net_eur, p.conversion_status), (D('1000'), D('700'), 'converted'))
        self.assertEqual(Organisation.objects.filter(name='New Corp').count(), 1)  # new name created

    def test_existing_names_reused_case_insensitively(self):
        Organisation.objects.create(name='Existing Co')
        self.client.post(self.add_url, payment_post(organisation_name='existing  co', category_name='SALARY'))
        self.assertEqual(Organisation.objects.count(), 1)
        self.assertEqual(IncomeCategory.objects.filter(name__iexact='salary').count(), 1)

    def test_validation_errors_keep_input_and_save_nothing(self):
        r = self.client.post(self.add_url, payment_post(gross_amount='-5', comment='keep me', organisation_name='Ghost'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Gross amount must be positive')
        self.assertContains(r, 'keep me')
        self.assertEqual(Payment.objects.count(), 0)
        self.assertFalse(Organisation.objects.filter(name='Ghost').exists())

    def test_field_validation_messages(self):
        for bad, text in [({'gross_amount': 'abc'}, 'Enter a number'), ({'gross_amount': '1.00001'}, 'decimal places'),
                          ({'payment_date': 'x'}, 'valid date'), ({'currency': 'JPY'}, 'valid choice'),
                          ({'organisation_name': '  '}, 'required'),
                          ({'income_period_start': '2024-03-31', 'income_period_end': '2024-03-01'}, 'before its start')]:
            r = self.client.post(self.add_url, payment_post(**bad))
            self.assertEqual(r.status_code, 200, bad)
            self.assertContains(r, text, msg_prefix=str(bad))
        self.assertEqual(Payment.objects.count(), 0)

    def test_inactive_organisation_rejected(self):
        Organisation.objects.create(name='Old Co', active=False)
        r = self.client.post(self.add_url, payment_post(organisation_name='Old Co'))
        self.assertContains(r, 'is inactive')
        self.assertEqual(Payment.objects.count(), 0)

    def test_foreign_payment_uses_provider_rate(self):
        with mock.patch(PROVIDER, return_value=fake()):
            r = self.client.post(self.add_url, payment_post(currency='GBP', gross_amount='1000'), follow=True)
        p = Payment.objects.get()
        self.assertEqual((p.rate, p.gross_eur, p.rate_source), (D('1.2'), D('1200'), 'fake'))
        self.assertContains(r, '1.2 EUR per 1 GBP')
        self.assertContains(r, '1,200.00 EUR')

    def test_provider_failure_shows_error_keeps_input_offers_manual(self):
        with mock.patch(PROVIDER, return_value=fake(fail=True)):
            r = self.client.post(self.add_url, payment_post(currency='GBP', comment='precious input', organisation_name='Brand New'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'nothing was saved')
        self.assertContains(r, 'manual rate')
        self.assertContains(r, 'precious input')
        self.assertContains(r, '<details open>', html=False)
        self.assertEqual((Payment.objects.count(), ExchangeRateRecord.objects.count()), (0, 0))
        self.assertFalse(Organisation.objects.filter(name='Brand New').exists())

    def test_full_manual_workflow_default_provider(self):
        # Phase 3 default provider has no automatic source: foreign currency needs a manual rate.
        r = self.client.post(self.add_url, payment_post(currency='USD', gross_amount='200', comment='c'))
        self.assertContains(r, 'No automatic exchange-rate source')
        self.assertEqual(Payment.objects.count(), 0)
        r = self.client.post(self.add_url, payment_post(
            currency='USD', gross_amount='200', comment='c', manual_rate='0.95', manual_note='bank statement'), follow=True)
        p = Payment.objects.get()
        self.assertEqual((p.gross_eur, p.rate_source, p.rate), (D('190'), 'manual', D('0.95')))
        self.assertEqual(p.rate_date, DAY)
        self.assertContains(r, '0.95 EUR per 1 USD')
        self.assertContains(r, 'Gross 200.00 USD')
        self.assertContains(r, '190.00 EUR')
        self.assertEqual(ExchangeRateRecord.objects.get().notes, 'bank statement')
        # appears on the month page and in totals
        r = self.client.get(reverse('month_detail', args=[2024, 3]))
        self.assertContains(r, '190.00')

    def test_invalid_manual_rates_rejected(self):
        for bad in ('0', '-1', 'abc'):
            r = self.client.post(self.add_url, payment_post(currency='USD', manual_rate=bad))
            self.assertContains(r, 'nothing was saved', msg_prefix=bad)
        self.assertEqual(Payment.objects.count(), 0)

    def test_manual_rate_rejected_for_eur(self):
        r = self.client.post(self.add_url, payment_post(manual_rate='1.1'))
        self.assertContains(r, 'always use rate 1')
        self.assertEqual(Payment.objects.count(), 0)

    def test_payment_date_in_other_month_goes_to_its_month(self):
        self.client.post(self.add_url, payment_post(payment_date='2024-04-02'))
        p = Payment.objects.get()
        self.assertEqual(str(p.month), '2024-04')


class PaymentEditDeleteTests(AuthedTestCase):
    def setUp(self):
        super().setUp()
        with mock.patch(PROVIDER, return_value=fake()):
            self.client.post(reverse('payment_add', args=[2024, 3]) if ReportingMonth.for_date(DAY) else '', payment_post(
                currency='GBP', gross_amount='1000', net_amount='800', withholding_tax='200'))
        self.p = Payment.objects.get()
        self.edit_url = reverse('payment_edit', args=[self.p.pk])

    def test_edit_form_prefilled(self):
        r = self.client.get(self.edit_url)
        self.assertContains(r, 'value="New Corp"')
        self.assertContains(r, 'Stored rate: 1.2')

    def test_amount_edit_keeps_stored_rate_without_provider_call(self):
        prov = fake()
        with mock.patch(PROVIDER, return_value=prov):
            self.client.post(self.edit_url, payment_post(currency='GBP', gross_amount='2000', net_amount='1500', withholding_tax='500'))
        self.p.refresh_from_db()
        self.assertEqual((self.p.gross_amount, self.p.gross_eur, self.p.net_eur, self.p.rate), (D('2000'), D('2400'), D('1800'), D('1.2')))
        self.assertEqual(prov.calls, [])
        self.assertEqual(ExchangeRateRecord.objects.count(), 1)

    def test_original_amount_edits_do_not_touch_rate_even_if_provider_changed(self):
        changed = FakeRateProvider({('GBP', DAY): D('9.9')})
        with mock.patch(PROVIDER, return_value=changed):
            self.client.post(self.edit_url, payment_post(currency='GBP', comment='only a comment'))
        self.p.refresh_from_db()
        self.assertEqual(self.p.rate, D('1.2'))

    def test_manual_rate_on_unchanged_basis_is_refused(self):
        r = self.client.post(self.edit_url, payment_post(currency='GBP', gross_amount='1000', net_amount='800', withholding_tax='200', manual_rate='2'))
        self.assertContains(r, 'Use &quot;Recalculate&quot;')
        self.p.refresh_from_db()
        self.assertEqual(self.p.rate, D('1.2'))

    def test_currency_change_requires_new_rate_and_failure_saves_nothing(self):
        r = self.client.post(self.edit_url, payment_post(currency='USD'))
        self.assertContains(r, 'nothing was saved')
        self.p.refresh_from_db()
        self.assertEqual((self.p.currency, self.p.rate), ('GBP', D('1.2')))
        self.client.post(self.edit_url, payment_post(currency='USD', gross_amount='1000', net_amount='800', withholding_tax='200', manual_rate='0.9'))
        self.p.refresh_from_db()
        self.assertEqual((self.p.currency, self.p.rate, self.p.gross_eur), ('USD', D('0.9'), D('900')))
        self.assertEqual(ExchangeRateRecord.objects.count(), 2)

    def test_date_change_moves_month_and_requires_rate(self):
        newday = datetime.date(2024, 5, 3)
        prov = FakeRateProvider({('GBP', newday): D('1.3')})
        with mock.patch(PROVIDER, return_value=prov):
            self.client.post(self.edit_url, payment_post(currency='GBP', payment_date='2024-05-03', net_amount='800', withholding_tax='200'))
        self.p.refresh_from_db()
        self.assertEqual((str(self.p.month), self.p.rate), ('2024-05', D('1.3')))

    def test_explicit_recalculation_from_source(self):
        url = reverse('payment_recalculate', args=[self.p.pk])
        self.assertContains(self.client.get(url), 'Current stored rate: 1.2')
        # failure leaves everything unchanged and points to manual entry
        with mock.patch(PROVIDER, return_value=fake(fail=True)):
            r = self.client.post(url, {})
        self.assertContains(r, 'Nothing was changed')
        self.p.refresh_from_db()
        self.assertEqual(self.p.rate, D('1.2'))
        # success replaces the rate; the old one stays on record
        newer = FakeRateProvider({('GBP', DAY): D('1.25')})
        with mock.patch(PROVIDER, return_value=newer):
            r = self.client.post(url, {'reason': 'ECB revised'}, follow=True)
        self.assertContains(r, 'rate 1.2 -&gt; 1.25')
        self.p.refresh_from_db()
        self.assertEqual((self.p.rate, self.p.gross_eur), (D('1.25'), D('1250')))
        self.assertEqual(sorted(ExchangeRateRecord.objects.values_list('rate', flat=True)), [D('1.2'), D('1.25')])

    def test_manual_correction_requires_reason_and_is_audited(self):
        url = reverse('payment_correct_rate', args=[self.p.pk])
        r = self.client.post(url, {'rate': '1.5', 'reason': '  '})
        self.assertContains(r, 'This field is required')
        r = self.client.post(url, {'rate': '-1', 'reason': 'x'})
        self.assertContains(r, 'must be positive')
        self.p.refresh_from_db()
        self.assertEqual(self.p.rate, D('1.2'))
        self.client.post(url, {'rate': '1.5', 'reason': 'rate on bank statement'})
        self.p.refresh_from_db()
        self.assertEqual((self.p.rate, self.p.gross_eur, self.p.rate_source), (D('1.5'), D('1500'), 'manual'))
        r = self.client.get(reverse('payment_detail', args=[self.p.pk]))
        self.assertContains(r, 'Manual rate correction')
        self.assertContains(r, 'rate on bank statement')
        self.assertContains(r, 'Initial conversion')
        ev = list(self.p.conversion_events.all())
        self.assertEqual([e.kind for e in ev], ['initial', 'manual_correction'])
        self.assertEqual((ev[1].previous_rate, ev[1].previous_gross_eur), (D('1.2'), D('1200')))

    def test_eur_payment_has_no_recalculate_or_correction_pages(self):
        make_payment().save()
        eur = Payment.objects.get(currency='EUR')
        for name in ('payment_recalculate', 'payment_correct_rate'):
            self.assertRedirects(self.client.get(reverse(name, args=[eur.pk])),
                                 reverse('payment_detail', args=[eur.pk]), fetch_redirect_response=False)

    def test_delete_requires_confirmation(self):
        url = reverse('payment_delete', args=[self.p.pk])
        self.assertContains(self.client.get(url), 'Yes, delete')
        self.assertEqual(Payment.objects.count(), 1)
        r = self.client.post(url)
        self.assertRedirects(r, reverse('month_detail', args=[2024, 3]))
        self.assertEqual(Payment.objects.count(), 0)

    def test_corrected_payment_delete_blocked_with_message(self):
        make_payment(kind='reversal', gross='-1000', currency='GBP', corrects=self.p).save()
        r = self.client.post(reverse('payment_delete', args=[self.p.pk]), follow=True)
        self.assertContains(r, 'cannot be deleted')
        self.assertTrue(Payment.objects.filter(pk=self.p.pk).exists())


class EditConvertedPaymentRegressionTests(AuthedTestCase):
    """Editing a converted payment must not validate the form against its stale stored conversion."""

    def setUp(self):
        super().setUp()
        ReportingMonth.for_date(DAY)
        with mock.patch(PROVIDER, return_value=fake()):
            # converted without a net amount
            self.client.post(reverse('payment_add', args=[2024, 3]),
                             payment_post(currency='GBP', gross_amount='1000', net_amount=''))
        self.p = Payment.objects.get()
        self.url = reverse('payment_edit', args=[self.p.pk])
        self.assertIsNone(self.p.net_eur)

    def test_adding_net_amount_uses_stored_rate(self):
        prov = fake()
        with mock.patch(PROVIDER, return_value=prov):
            r = self.client.post(self.url, payment_post(currency='GBP', gross_amount='1000', net_amount='800', withholding_tax='200'))
        self.assertEqual(r.status_code, 302)
        self.p.refresh_from_db()
        self.assertEqual((self.p.net_amount, self.p.net_eur, self.p.rate), (D('800'), D('960'), D('1.2')))
        self.assertEqual(prov.calls, [])
        self.assertEqual(self.p.conversion_events.last().kind, 'amounts_edited')

    def test_removing_net_amount(self):
        self.client.post(self.url, payment_post(currency='GBP', gross_amount='1000', net_amount='800', withholding_tax='200'))
        self.client.post(self.url, payment_post(currency='GBP', gross_amount='1000', net_amount=''))
        self.p.refresh_from_db()
        self.assertEqual((self.p.net_amount, self.p.net_eur), (None, None))

    def test_changing_currency_to_eur(self):
        r = self.client.post(self.url, payment_post(currency='EUR', gross_amount='1000'))
        self.assertEqual(r.status_code, 302)
        self.p.refresh_from_db()
        self.assertEqual((self.p.currency, self.p.rate, self.p.gross_eur), ('EUR', D('1'), D('1000')))
        self.assertEqual(self.p.conversion_events.last().kind, 'basis_changed')

    def test_changing_currency_from_eur_to_foreign(self):
        eur = make_payment(date=DAY, gross='100'); eur.save()
        from core.services.conversion import convert_payment
        convert_payment(eur)
        with mock.patch(PROVIDER, return_value=fake()):
            r = self.client.post(reverse('payment_edit', args=[eur.pk]),
                                 payment_post(currency='GBP', gross_amount='100', organisation_name='Acme Test GmbH'))
        self.assertEqual(r.status_code, 302)
        eur.refresh_from_db()
        self.assertEqual((eur.currency, eur.rate, eur.gross_eur), ('GBP', D('1.2'), D('120')))

    def test_failed_basis_change_keeps_stored_data_and_note(self):
        r = self.client.post(self.url, payment_post(currency='USD', gross_amount='1000'))  # manual-only provider
        self.assertContains(r, 'nothing was saved')
        self.assertContains(r, 'Stored rate: 1.2')   # edit page still describes the stored rate
        self.p.refresh_from_db()
        self.assertEqual((self.p.currency, self.p.rate, self.p.gross_eur), ('GBP', D('1.2'), D('1200')))

    def test_form_never_raises_for_non_form_model_errors(self):
        # Every combination of editing a converted payment should return 200/302, never 500.
        for cur in ('EUR', 'GBP', 'USD'):
            for net in ('', '500'):
                for date in ('2024-03-15', '2024-04-01'):
                    with mock.patch(PROVIDER, return_value=FakeRateProvider(
                            {(c, datetime.date.fromisoformat(d)): D('1.1') for c in ('GBP', 'USD')
                             for d in ('2024-03-15', '2024-04-01')})):
                        r = self.client.post(self.url, payment_post(currency=cur, net_amount=net, payment_date=date))
                    self.assertIn(r.status_code, (200, 302), (cur, net, date))
