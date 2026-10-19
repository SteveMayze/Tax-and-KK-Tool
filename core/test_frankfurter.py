"""Frankfurter provider, stored-rate reuse, audit trail and reconciliation. All HTTP is mocked."""
import datetime
import socket
from decimal import Decimal as D
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from core.models import ConversionEvent, ExchangeRateRecord, Payment
from core.services import frankfurter
from core.services.conversion import (
    ConversionError, convert_payment, convert_pending, correct_rate_manually, reapply_stored_rate)
from core.services.frankfurter import FrankfurterProvider
from core.services.rates import ProviderError, RateUnavailable
from core.services.reconciliation import build_report

from .test_helpers import make_payment

HTTP = 'core.services.frankfurter._http_get'
FRI = datetime.date(2024, 3, 15)
SAT = datetime.date(2024, 3, 16)


def body(date='2024-03-15', base='GBP', quote='EUR', rate='1.1708'):
    return f'{{"date":"{date}","base":"{base}","quote":"{quote}","rate":{rate}}}'


def provider(**kw):
    return FrankfurterProvider(base_url='https://api.example.test', timeout=3, **kw)


class NetworkGuardTests(SimpleTestCase):
    def test_real_network_is_blocked_in_tests(self):
        s = socket.socket()
        try:
            with self.assertRaises(AssertionError):
                s.connect(('93.184.216.34', 443))
        finally:
            s.close()


class FrankfurterProviderTests(SimpleTestCase):
    def test_request_url_is_provider_scoped_dated_and_never_latest(self):
        with mock.patch(HTTP, return_value=(200, body())) as m:
            q = provider().get_rate('GBP', FRI)
        url, timeout = m.call_args.args
        self.assertEqual(url, 'https://api.example.test/v2/providers/ECB/rate/GBP/EUR?date=2024-03-15')
        self.assertEqual(timeout, 3)
        self.assertEqual((q.rate, q.rate_date, q.requested_date, q.provider), (D('1.1708'), FRI, FRI, 'frankfurter-ecb'))
        self.assertFalse(q.date_differs)
        self.assertEqual(q.source_url, url)
        self.assertIn('1.1708', q.raw_response)

    def test_rate_parsed_exactly_not_via_binary_float(self):
        with mock.patch(HTTP, return_value=(200, body(base='AUD', rate='0.60317000000001'))):
            self.assertEqual(provider().get_rate('AUD', FRI).rate, D('0.60317000000001'))
        with mock.patch(HTTP, return_value=(200, body(rate='1'))):  # integer JSON number
            self.assertEqual(provider().get_rate('GBP', FRI).rate, D('1'))

    def test_weekend_uses_previous_business_day_and_is_flagged(self):
        with mock.patch(HTTP, return_value=(200, body(date='2024-03-15'))):
            q = provider().get_rate('GBP', SAT)
        self.assertEqual((q.requested_date, q.rate_date), (SAT, FRI))
        self.assertTrue(q.date_differs)

    def test_holiday_gap_within_limit_accepted(self):
        # 2024-01-01 (holiday) -> 2023-12-29 is 3 days earlier
        with mock.patch(HTTP, return_value=(200, body(date='2023-12-29', rate='1.1507'))):
            q = provider().get_rate('GBP', datetime.date(2024, 1, 1))
        self.assertEqual(q.rate_date, datetime.date(2023, 12, 29))

    def test_rate_too_old_is_unavailable_not_substituted(self):
        with mock.patch(HTTP, return_value=(200, body(date='2024-03-01'))):
            with self.assertRaises(RateUnavailable) as cm:
                provider().get_rate('GBP', FRI)
        self.assertIn('14 days', str(cm.exception))
        with mock.patch(HTTP, return_value=(200, body(date='2024-03-08'))):
            provider(max_lookback_days=7).get_rate('GBP', FRI)           # exactly 7 days: ok
            with self.assertRaises(RateUnavailable):
                provider(max_lookback_days=6).get_rate('GBP', FRI)

    def test_future_data_never_accepted(self):
        with mock.patch(HTTP, return_value=(200, body(date='2024-03-18'))):
            with self.assertRaises(ProviderError):
                provider().get_rate('GBP', FRI)

    def test_http_statuses(self):
        cases = [(404, '{"status":404,"message":"not found"}', RateUnavailable),
                 (422, '{"status":422,"message":"invalid currency: ZZZ"}', RateUnavailable),
                 (429, '{}', ProviderError), (500, 'oops', ProviderError), (503, '', ProviderError)]
        for status, text, exc in cases:
            with mock.patch(HTTP, return_value=(status, text)):
                with self.assertRaises(exc, msg=status):
                    provider().get_rate('GBP', FRI)

    def test_422_message_is_surfaced(self):
        with mock.patch(HTTP, return_value=(422, '{"message":"invalid currency: ZZZ"}')):
            with self.assertRaises(RateUnavailable) as cm:
                provider().get_rate('GBP', FRI)
        self.assertIn('invalid currency: ZZZ', str(cm.exception))

    def test_transport_failures_become_provider_errors(self):
        for exc in (TimeoutError('timed out'), ConnectionError('refused'), OSError('dns')):
            with mock.patch(HTTP, side_effect=exc):
                with self.assertRaises(ProviderError):
                    provider().get_rate('GBP', FRI)

    def test_malformed_responses_rejected(self):
        bad = ['not json', '[]', '{}', body(rate='"x"'), body(rate='0'), body(rate='-1'),
               body(date='soon'), body(base='USD'), body(quote='USD'), '{"date":"2024-03-15"}']
        for text in bad:
            with mock.patch(HTTP, return_value=(200, text)):
                with self.assertRaises(ProviderError, msg=text):
                    provider().get_rate('GBP', FRI)

    def test_invalid_inputs_make_no_request(self):
        with mock.patch(HTTP) as m:
            for ccy in ('EUR', 'gbp', 'GB', '', None, 'GBP/../x'):
                with self.assertRaises(RateUnavailable):
                    provider().get_rate(ccy, FRI)
        m.assert_not_called()

    def test_https_required(self):
        with self.assertRaises(ProviderError):
            FrankfurterProvider(base_url='http://api.example.test')
        with self.assertRaises(ProviderError):
            FrankfurterProvider(base_url='file:///etc/passwd')

    def test_real_http_helper_never_reached_without_mock(self):
        # Safety net: the un-mocked helper would hit the blocked network and fail as ProviderError.
        with self.assertRaises(ProviderError):
            provider().get_rate('GBP', FRI)


@override_settings(RATE_PROVIDER='core.services.frankfurter.FrankfurterProvider')
class ConversionWithFrankfurterTests(TestCase):
    def convert(self, p, **kw):
        return convert_payment(p, provider(), **kw)

    def test_provenance_persisted(self):
        p = make_payment(gross='1000', net='800', currency='GBP', date=FRI); p.save()
        with mock.patch(HTTP, return_value=(200, body())):
            self.convert(p)
        p.refresh_from_db()
        self.assertEqual((p.rate, p.gross_eur, p.net_eur, p.rate_source), (D('1.1708'), D('1170.8'), D('936.64'), 'frankfurter-ecb'))
        rec = p.rate_record
        self.assertEqual((rec.requested_date, rec.rate_date, rec.provider, rec.is_manual), (FRI, FRI, 'frankfurter-ecb', False))
        self.assertIn('/v2/providers/ECB/rate/GBP/EUR?date=2024-03-15', rec.source_url)
        self.assertIn('"rate":1.1708', rec.raw_response)
        self.assertEqual(p.conversion_notes, '')

    def test_weekend_payment_labelled(self):
        p = make_payment(currency='GBP', date=SAT); p.save()
        with mock.patch(HTTP, return_value=(200, body(date='2024-03-15'))):
            self.convert(p)
        self.assertEqual((p.payment_date, p.rate_date), (SAT, FRI))
        self.assertIn('differs from payment date', p.conversion_notes)
        self.assertEqual(p.rate_record.requested_date, SAT)
        self.assertEqual([x.pk for x in build_report().date_differs], [p.pk])

    def test_repeat_requests_reuse_stored_rate(self):
        a = make_payment(currency='GBP', date=FRI); a.save()
        b = make_payment(currency='GBP', date=FRI, gross='50'); b.save()
        with mock.patch(HTTP, return_value=(200, body())) as m:
            self.convert(a)
            self.convert(b)
        self.assertEqual(m.call_count, 1)
        self.assertEqual(a.rate_record_id, b.rate_record_id)
        self.assertEqual(ExchangeRateRecord.objects.count(), 1)

    def test_different_date_or_currency_requests_again(self):
        with mock.patch(HTTP, return_value=(200, body())) as m:
            self.convert(self._saved('GBP', FRI))
        with mock.patch(HTTP, return_value=(200, body(date='2024-03-14'))) as m_:
            self.convert(self._saved('GBP', datetime.date(2024, 3, 14)))
        m.call_count += m_.call_count
        with mock.patch(HTTP, return_value=(200, body(base='USD', rate='0.9'))) as m2:
            self.convert(self._saved('USD', FRI))
        self.assertEqual((m.call_count, m2.call_count), (2, 1))

    def _saved(self, ccy, date):
        p = make_payment(currency=ccy, date=date); p.save()
        return p

    def test_failure_is_not_cached_and_leaves_payment_pending(self):
        p = self._saved('GBP', FRI)
        with mock.patch(HTTP, return_value=(500, 'x')):
            with self.assertRaises(ConversionError):
                self.convert(p)
        self.assertEqual((Payment.objects.get(pk=p.pk).conversion_status, ExchangeRateRecord.objects.count(),
                          ConversionEvent.objects.count()), ('pending', 0, 0))
        with mock.patch(HTTP, return_value=(200, body())):
            self.convert(p)  # retry succeeds
        self.assertEqual(p.conversion_status, 'converted')

    def test_recalculation_requests_again_and_keeps_history(self):
        p = self._saved('GBP', FRI)
        with mock.patch(HTTP, return_value=(200, body())):
            self.convert(p)
        with mock.patch(HTTP, return_value=(200, body(rate='1.2000'))) as m:
            self.convert(p, recalculate=True)          # explicit recalculation => fresh request
        self.assertEqual(m.call_count, 1)
        self.assertEqual(p.rate, D('1.2'))
        self.assertEqual(sorted(ExchangeRateRecord.objects.values_list('rate', flat=True)), [D('1.1708'), D('1.2')])
        kinds = list(p.conversion_events.values_list('kind', flat=True))
        self.assertEqual(kinds, ['initial', 'recalculated'])

    def test_recalculation_failure_changes_nothing(self):
        p = self._saved('GBP', FRI)
        with mock.patch(HTTP, return_value=(200, body())):
            self.convert(p)
        with mock.patch(HTTP, side_effect=TimeoutError('t')):
            with self.assertRaises(ConversionError):
                self.convert(p, recalculate=True)
        p.refresh_from_db()
        self.assertEqual(p.rate, D('1.1708'))
        self.assertEqual(p.conversion_events.count(), 1)

    def test_no_silent_recalculation(self):
        p = self._saved('GBP', FRI)
        with mock.patch(HTTP, return_value=(200, body())) as m:
            self.convert(p)
            with self.assertRaises(ConversionError):
                self.convert(p)
        self.assertEqual(m.call_count, 1)

    def test_eur_never_calls_service(self):
        p = self._saved('EUR', FRI)
        with mock.patch(HTTP) as m:
            self.convert(p)
        m.assert_not_called()
        self.assertEqual(p.rate, 1)


class AuditTrailTests(TestCase):
    def setUp(self):
        self.p = make_payment(gross='100', net='80', currency='USD', date=FRI)
        self.p.save()

    def test_manual_initial_then_correction_chain(self):
        convert_payment(self.p, manual_rate='0.9', manual_note='first guess')
        correct_rate_manually(self.p, '0.92', 'statement shows 0.92')
        evs = list(self.p.conversion_events.all())
        self.assertEqual([e.kind for e in evs], ['initial', 'manual_correction'])
        self.assertEqual((evs[0].previous_rate, evs[0].rate, evs[0].gross_eur), (None, D('0.9'), D('90')))
        self.assertEqual((evs[1].previous_rate, evs[1].previous_gross_eur, evs[1].rate, evs[1].gross_eur),
                         (D('0.9'), D('90'), D('0.92'), D('92')))
        self.assertEqual(evs[1].reason, 'statement shows 0.92')
        self.assertEqual(ExchangeRateRecord.objects.filter(is_manual=True).count(), 2)  # both kept

    def test_manual_correction_needs_reason(self):
        convert_payment(self.p, manual_rate='0.9')
        for reason in ('', '   '):
            with self.assertRaises(ConversionError):
                correct_rate_manually(self.p, '0.95', reason)
        self.p.refresh_from_db()
        self.assertEqual(self.p.rate, D('0.9'))
        self.assertEqual(self.p.conversion_events.count(), 1)

    def test_amount_edit_with_stored_rate_is_logged(self):
        convert_payment(self.p, manual_rate='0.9')
        self.p.gross_amount, self.p.net_amount = D('200'), D('150')
        reapply_stored_rate(self.p)
        last = self.p.conversion_events.last()
        self.assertEqual((last.kind, last.previous_gross_eur, last.gross_eur, last.rate), ('amounts_edited', D('90'), D('180'), D('0.9')))

    def test_unchanged_amounts_log_nothing(self):
        convert_payment(self.p, manual_rate='0.9')
        reapply_stored_rate(self.p)
        self.assertEqual(self.p.conversion_events.count(), 1)

    def test_events_deleted_with_payment_but_records_kept(self):
        convert_payment(self.p, manual_rate='0.9')
        self.p.delete()
        self.assertEqual(ConversionEvent.objects.count(), 0)
        self.assertEqual(ExchangeRateRecord.objects.count(), 1)


class ReconciliationTests(TestCase):
    def test_report_categories(self):
        pending = make_payment(currency='GBP', net='1'); pending.save()
        manual = make_payment(currency='USD', net='1'); manual.save()
        convert_payment(manual, manual_rate='0.9')
        eur_no_net = make_payment(); eur_no_net.save(); convert_payment(eur_no_net)
        ok = make_payment(net='5'); ok.save(); convert_payment(ok)
        r = build_report()
        self.assertEqual([p.pk for p in r.pending], [pending.pk])
        self.assertEqual([p.pk for p in r.manual_rates], [manual.pk])
        self.assertEqual([p.pk for p in r.missing_net], [eur_no_net.pk])
        self.assertEqual((r.date_differs, r.inconsistent), ([], []))
        self.assertEqual([p.pk for p in r.unallocated], [pending.pk, manual.pk, ok.pk])   # gross 1000 vs net 1/5, no breakdown
        self.assertEqual(r.issue_count, 6)

    def test_inconsistency_detected(self):
        p = make_payment(currency='USD'); p.save(); convert_payment(p, manual_rate='0.9')
        Payment.objects.filter(pk=p.pk).update(gross_eur=D('1'))   # simulate tampering/bug
        self.assertEqual([x.pk for x in build_report().inconsistent], [p.pk])
        q = make_payment(currency='USD', gross='10'); q.save(); convert_payment(q, manual_rate='0.9')
        ExchangeRateRecord.objects.filter(pk=q.rate_record_id).update(rate=D('2'))
        self.assertIn(q.pk, [x.pk for x in build_report().inconsistent])

    def test_year_filter(self):
        make_payment(currency='GBP', date=datetime.date(2023, 5, 1)).save()
        make_payment(currency='GBP', date=datetime.date(2024, 5, 1)).save()
        self.assertEqual(len(build_report(2023).pending), 1)
        self.assertEqual(len(build_report().pending), 2)

    def test_convert_pending_mixed_results(self):
        from core.services.rates import FakeRateProvider
        a = make_payment(currency='GBP', date=FRI); a.save()
        b = make_payment(currency='AUD', date=FRI); b.save()
        prov = FakeRateProvider({('GBP', FRI): D('1.2')})
        results = convert_pending(prov, [a, b])
        self.assertIsNone(results[0][1])
        self.assertIn('No fake rate', results[1][1])
        self.assertEqual([Payment.objects.get(pk=x.pk).conversion_status for x in (a, b)], ['converted', 'pending'])


@override_settings(RATE_PROVIDER='core.services.rates.ManualOnlyProvider')
class ReconciliationViewTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        self.client.force_login(get_user_model().objects.create_user('t', password='pw-for-tests-123'))

    def test_page_lists_sections(self):
        make_payment(currency='GBP', comment='x').save()
        r = self.client.get(reverse('reconciliation'))
        self.assertContains(r, 'Not converted (1)')
        self.assertContains(r, 'Manually entered rates (0)')
        self.assertContains(r, 'Try automatic conversion')

    def test_bulk_convert_reports_failures_and_successes(self):
        from core.services.rates import FakeRateProvider
        make_payment(currency='GBP', date=FRI).save()
        make_payment(currency='AUD', date=FRI, gross='5').save()
        prov = FakeRateProvider({('GBP', FRI): D('1.2')})
        with mock.patch('core.views_reconciliation.get_provider', return_value=prov):
            r = self.client.post(reverse('convert_pending'), follow=True)
        self.assertContains(r, '1 payment(s) converted')
        self.assertContains(r, 'No fake rate for AUD')
        self.assertEqual(Payment.objects.filter(conversion_status='pending').count(), 1)

    def test_bulk_convert_is_post_only_and_login_protected(self):
        self.assertEqual(self.client.get(reverse('convert_pending')).status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.post(reverse('convert_pending')).status_code, 302)
        self.assertEqual(self.client.get(reverse('reconciliation')).status_code, 302)


@override_settings(RATE_PROVIDER='core.services.frankfurter.FrankfurterProvider',
                   FRANKFURTER_BASE_URL='https://api.example.test')
class EndToEndViewTests(TestCase):
    """The payment form against the real provider class with HTTP mocked."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        from core.models import ReportingMonth
        self.client.force_login(get_user_model().objects.create_user('t', password='pw-for-tests-123'))
        ReportingMonth.for_date(SAT)
        self.url = reverse('payment_add', args=[2024, 3])
        self.data = {'payment_date': '2024-03-16', 'organisation_name': 'Zed Ltd', 'category_name': 'Salary',
                     'currency': 'GBP', 'gross_amount': '1000', 'frequency': 'monthly'}

    def test_weekend_payment_via_form_shows_provenance(self):
        with mock.patch(HTTP, return_value=(200, body(date='2024-03-15'))):
            r = self.client.post(self.url, self.data, follow=True)
        self.assertContains(r, '1.1708 EUR per 1 GBP')
        self.assertContains(r, 'differs from payment date')
        self.assertContains(r, 'frankfurter-ecb')
        self.assertContains(r, '/v2/providers/ECB/rate/GBP/EUR?date=2024-03-16')
        self.assertContains(r, 'Initial conversion')

    def test_service_down_shows_error_keeps_input_then_manual_works(self):
        data = dict(self.data, comment='keep this')
        with mock.patch(HTTP, side_effect=TimeoutError('slow')):
            r = self.client.post(self.url, data)
        self.assertContains(r, 'nothing was saved')
        self.assertContains(r, 'keep this')
        self.assertContains(r, '<details open>')
        self.assertEqual(Payment.objects.count(), 0)
        with mock.patch(HTTP, side_effect=TimeoutError('slow')):
            r = self.client.post(self.url, dict(data, manual_rate='1.17', manual_note='bank'), follow=True)
        self.assertEqual(Payment.objects.get().rate_source, 'manual')

    def test_recalculate_view_refreshes_from_service(self):
        with mock.patch(HTTP, return_value=(200, body(date='2024-03-15'))):
            self.client.post(self.url, self.data)
        p = Payment.objects.get()
        with mock.patch(HTTP, return_value=(200, body(date='2024-03-15', rate='1.1800'))) as m:
            r = self.client.post(reverse('payment_recalculate', args=[p.pk]), {'reason': 'check'}, follow=True)
        self.assertEqual(m.call_count, 1)
        self.assertContains(r, 'rate 1.1708 -&gt; 1.18')
        p.refresh_from_db()
        self.assertEqual(p.gross_eur, D('1180'))
