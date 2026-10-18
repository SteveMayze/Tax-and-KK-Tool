import datetime
from decimal import Decimal as D

from django.test import SimpleTestCase, TestCase

from core.models import ExchangeRateRecord, Payment
from core.services import aggregation as agg
from core.services.conversion import ConversionError, convert_payment
from core.services.money import MoneyError, normalise_currency, round_for_display, to_decimal
from core.services.normalisation import is_recurring, monthly_equivalent
from core.services.rates import FakeRateProvider

from .test_helpers import make_payment

DAY = datetime.date(2024, 3, 15)


class MoneyTests(SimpleTestCase):
    def test_to_decimal(self):
        self.assertEqual(to_decimal(' 12.50 '), D('12.50'))
        for bad in (1.5, 'abc', 'NaN', 'Infinity', None, ''):
            with self.assertRaises(MoneyError, msg=repr(bad)):
                to_decimal(bad)

    def test_currency(self):
        self.assertEqual(normalise_currency(' usd'), 'USD')
        for bad in ('JPY', 'US', '123', None):
            with self.assertRaises(MoneyError):
                normalise_currency(bad)

    def test_display_rounding_half_up_only_for_display(self):
        self.assertEqual(round_for_display(D('2.675')), D('2.68'))
        self.assertEqual(round_for_display(D('-2.675')), D('-2.68'))
        self.assertEqual(round_for_display(D('1.005'), 0), D('1'))


class NormalisationTests(SimpleTestCase):
    def test_divisors(self):
        self.assertEqual(monthly_equivalent(D('1200'), 'monthly'), D('1200'))
        self.assertEqual(monthly_equivalent(D('1200'), 'quarterly'), D('400'))
        self.assertEqual(monthly_equivalent(D('1200'), 'half_yearly'), D('200'))
        self.assertEqual(monthly_equivalent(D('1200'), 'yearly'), D('100'))

    def test_full_precision_kept(self):
        self.assertEqual(monthly_equivalent(D('100'), 'quarterly'), D(100) / D(3))
        self.assertNotEqual(monthly_equivalent(D('100'), 'quarterly'), D('33.33'))

    def test_one_off_missing_and_unknown(self):
        self.assertIsNone(monthly_equivalent(D('500'), 'one_off'))
        self.assertIsNone(monthly_equivalent(None, 'monthly'))
        self.assertIsNone(monthly_equivalent(D('5'), 'weekly'))
        self.assertFalse(is_recurring('one_off'))
        self.assertTrue(is_recurring('yearly'))


class ConversionTests(TestCase):
    def provider(self, **kw):
        return FakeRateProvider({('GBP', DAY): D('1.17'), ('USD', DAY): D('0.9')}, **kw)

    def test_eur_uses_rate_one_without_provider(self):
        p = make_payment(gross='100.5', net='80'); p.save()
        convert_payment(p)
        p.refresh_from_db()
        self.assertEqual((p.rate, p.gross_eur, p.net_eur, p.rate_source), (1, D('100.5'), D('80'), 'identity'))
        self.assertEqual(p.conversion_status, 'converted')

    def test_foreign_conversion_multiplies_and_preserves_original(self):
        prov = self.provider()
        p = make_payment(gross='1000', net='700.50', currency='GBP'); p.save()
        convert_payment(p, prov)
        p.refresh_from_db()
        self.assertEqual(p.gross_eur, D('1170.00'))
        self.assertEqual(p.net_eur, D('819.585'))
        self.assertEqual((p.gross_amount, p.currency), (D('1000'), 'GBP'))  # original untouched
        self.assertEqual((p.rate, p.rate_date, p.rate_source), (D('1.17'), DAY, 'fake'))
        self.assertEqual(p.rate_record.rate, D('1.17'))
        self.assertEqual(prov.calls, [('GBP', DAY)])

    def test_null_net_stays_null(self):
        p = make_payment(currency='GBP'); p.save()
        convert_payment(p, self.provider())
        self.assertIsNone(p.net_eur)

    def test_provider_failure_leaves_payment_untouched(self):
        p = make_payment(currency='GBP'); p.save()
        with self.assertRaises(ConversionError) as cm:
            convert_payment(p, self.provider(fail=True))
        self.assertTrue(cm.exception.manual_rate_possible)
        p.refresh_from_db()
        self.assertEqual(p.conversion_status, 'pending')
        self.assertIsNone(p.rate)
        self.assertEqual(ExchangeRateRecord.objects.count(), 0)

    def test_missing_rate_is_error_not_substitution(self):
        p = make_payment(currency='AUD'); p.save()  # provider has no AUD
        with self.assertRaises(ConversionError):
            convert_payment(p, self.provider())
        self.assertEqual(Payment.objects.get(pk=p.pk).conversion_status, 'pending')

    def test_no_provider_for_foreign_currency(self):
        p = make_payment(currency='USD'); p.save()
        with self.assertRaises(ConversionError):
            convert_payment(p)

    def test_manual_rate_fallback_after_failure(self):
        p = make_payment(gross='200', currency='USD'); p.save()
        with self.assertRaises(ConversionError):
            convert_payment(p, self.provider(fail=True))
        convert_payment(p, manual_rate='0.95', manual_note='from bank statement')
        self.assertEqual(p.gross_eur, D('190.00'))
        self.assertEqual(p.rate_source, 'manual')
        rec = p.rate_record
        self.assertTrue(rec.is_manual)
        self.assertEqual(rec.notes, 'from bank statement')

    def test_invalid_manual_rates_rejected(self):
        p = make_payment(currency='USD'); p.save()
        for bad in ('0', '-1', 'x', 1.2):
            with self.assertRaises(ConversionError, msg=repr(bad)):
                convert_payment(p, manual_rate=bad)
        self.assertEqual(Payment.objects.get(pk=p.pk).conversion_status, 'pending')

    def test_date_difference_is_labelled(self):
        weekend = datetime.date(2024, 3, 16)
        prov = FakeRateProvider({('GBP', weekend): D('1.2')}, date_overrides={('GBP', weekend): DAY})
        p = make_payment(currency='GBP', date=weekend); p.save()
        convert_payment(p, prov)
        self.assertEqual(p.rate_date, DAY)
        self.assertIn('differs from payment date', p.conversion_notes)

    def test_no_silent_recalculation(self):
        prov = self.provider()
        p = make_payment(currency='GBP'); p.save()
        convert_payment(p, prov)
        with self.assertRaises(ConversionError):
            convert_payment(p, prov)
        self.assertEqual(len(prov.calls), 1)

    def test_explicit_recalculation_keeps_audit_trail(self):
        p = make_payment(gross='100', currency='GBP'); p.save()
        convert_payment(p, self.provider())
        first = p.rate_record_id
        convert_payment(p, manual_rate='1.30', recalculate=True)
        self.assertEqual(p.gross_eur, D('130.00'))
        self.assertEqual(ExchangeRateRecord.objects.count(), 2)
        self.assertNotEqual(p.rate_record_id, first)
        self.assertEqual(ExchangeRateRecord.objects.get(pk=first).rate, D('1.17'))  # old rate preserved

    def test_full_precision_before_storage_limit(self):
        prov = FakeRateProvider({('GBP', DAY): D('1.1234567891')})
        p = make_payment(gross='1000.1234', currency='GBP'); p.save()
        convert_payment(p, prov)
        p.refresh_from_db()
        self.assertEqual(p.rate, D('1.1234567891'))
        self.assertEqual(p.gross_eur, (D('1000.1234') * D('1.1234567891')).quantize(D('0.000001')))


class AggregationTests(TestCase):
    def setUp(self):
        self.prov = FakeRateProvider({('GBP', DAY): D('1.2')})

    def add(self, convert=True, **kw):
        p = make_payment(**kw); p.save()
        if convert:
            convert_payment(p, self.prov)
        return p

    def test_actual_totals_gross_net_and_missing_net(self):
        a = self.add(gross='1000', net='700')
        self.add(gross='500', currency='GBP', date=DAY)            # no net, EUR 600
        self.add(gross='50', net='40', convert=False)              # unconverted, excluded
        t = agg.month_actual(a.month)
        self.assertEqual(t.payment_count, 3)
        self.assertEqual(t.gross_eur, D('1600'))
        self.assertEqual(t.net_eur, D('700'))
        self.assertEqual(t.net_missing_count, 1)
        self.assertEqual(t.unconverted_count, 1)

    def test_empty_month(self):
        a = self.add(); other = make_payment(date=datetime.date(2024, 4, 2)).month
        t = agg.month_actual(other)
        self.assertEqual((t.payment_count, t.gross_eur, t.net_eur), (0, 0, 0))
        self.assertIsNotNone(a)

    def test_reversal_nets_out(self):
        a = self.add(gross='1000', net='700')
        r = make_payment(kind='reversal', gross='-1000', net='-700', corrects=a); r.save()
        convert_payment(r)
        t = agg.month_actual(a.month)
        self.assertEqual((t.gross_eur, t.net_eur), (0, 0))

    def test_normalised_excludes_one_off_and_uses_equivalents(self):
        m = self.add(gross='3000', net='2000', frequency='monthly').month
        self.add(gross='1200', net='900', frequency='quarterly')
        self.add(gross='12000', frequency='yearly')
        self.add(gross='9999', net='9000', frequency='one_off', category='Capital gains')
        n = agg.month_normalised(m)
        self.assertEqual(n.gross_monthly_eur, D('3000') + D('400') + D('1000'))
        self.assertEqual(n.net_monthly_eur, D('2000') + D('300'))
        self.assertEqual((n.recurring_count, n.one_off_excluded_count, n.net_missing_count), (3, 1, 1))
        # actual total still includes the one-off
        self.assertEqual(agg.month_actual(m).gross_eur, D('3000') + D('1200') + D('12000') + D('9999'))

    def test_year_actual_and_average_of_actuals(self):
        a = self.add(gross='1000', net='800', date=datetime.date(2024, 1, 10))
        self.add(gross='1000', net='800', date=datetime.date(2024, 7, 10))
        self.add(gross='1000', date=datetime.date(2025, 1, 10))  # other year
        year = a.month.year
        t = agg.year_actual(year)
        self.assertEqual((t.payment_count, t.gross_eur, t.net_eur), (2, D('2000'), D('1600')))
        avg = agg.year_average_of_actuals(year)
        self.assertEqual(avg['gross_eur'], D('2000') / 12)
        self.assertIn('not a recurring figure', avg['basis'])

    def test_average_counts_unconverted_and_missing_net(self):
        a = self.add(gross='1200', net='1000')
        self.add(gross='600')                      # converted, no net
        self.add(gross='50', convert=False)        # unconverted: excluded from sums
        avg = agg.year_average_of_actuals(a.month.year)
        self.assertEqual(avg['gross_eur'], D('1800') / 12)
        self.assertEqual(avg['net_eur'], D('1000') / 12)
        self.assertEqual((avg['net_missing_count'], avg['unconverted_count']), (1, 1))
