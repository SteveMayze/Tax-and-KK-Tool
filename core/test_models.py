import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase

from core.models import IncomeCategory, Organisation, Payment, ReportingMonth, ReportingYear

from .test_helpers import make_payment


class SeedAndUniquenessTests(TestCase):
    def test_default_categories_seeded(self):
        names = set(IncomeCategory.objects.values_list('name', flat=True))
        self.assertEqual(names, {'Salary', 'Pension', 'Rental', 'Interest', 'Dividends', 'Capital gains', 'Other'})

    def test_organisation_duplicate_spelling_rejected(self):
        Organisation.objects.create(name='Acme  GmbH')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Organisation.objects.create(name=' acme gmbh')

    def test_year_unique_and_month_unique(self):
        y = ReportingYear.objects.create(year=2024)
        ReportingMonth.objects.create(year=y, month=1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ReportingMonth.objects.create(year=y, month=1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ReportingYear.objects.create(year=2024)

    def test_month_bounds(self):
        m = ReportingMonth(year=ReportingYear.objects.create(year=2024), month=13)
        with self.assertRaises(ValidationError):
            m.full_clean()


class PaymentValidationTests(TestCase):
    def test_valid_payment_saves(self):
        p = make_payment()
        p.save()
        self.assertEqual(p.conversion_status, 'pending')

    def test_currency_normalised_and_validated(self):
        p = make_payment(currency='gbp')
        p.save()
        self.assertEqual(p.currency, 'GBP')
        for bad in ('JPY', 'EU', 'E1R', ''):
            with self.assertRaises(ValidationError, msg=bad):
                make_payment(currency=bad).save()

    def test_month_must_match_payment_date(self):
        p = make_payment()
        p.payment_date = datetime.date(2024, 4, 1)
        with self.assertRaises(ValidationError) as cm:
            p.save()
        self.assertIn('month', cm.exception.message_dict)

    def test_income_period_order(self):
        p = make_payment(income_period_start=datetime.date(2024, 3, 31), income_period_end=datetime.date(2024, 3, 1))
        with self.assertRaises(ValidationError):
            p.save()

    def test_normal_payment_must_be_positive(self):
        for g in ('0', '-5'):
            with self.assertRaises(ValidationError):
                make_payment(gross=g).save()

    def test_net_sign_matches_gross(self):
        with self.assertRaises(ValidationError):
            make_payment(gross='100', net='-1').save()

    def test_amount_precision_validated(self):
        with self.assertRaises(ValidationError):
            make_payment(gross='1.00001').save()  # 5 dp > 4 dp

    def test_reversal_and_correction_rules(self):
        orig = make_payment(); orig.save()
        # reversal must be negative and reference original
        with self.assertRaises(ValidationError):
            make_payment(kind='reversal', gross='10', corrects=orig).save()
        with self.assertRaises(ValidationError):
            make_payment(kind='reversal', gross='-10').save()
        make_payment(kind='reversal', gross='-1000', corrects=orig).save()
        make_payment(kind='correction', gross='25.50', corrects=orig).save()
        with self.assertRaises(ValidationError):
            make_payment(kind='correction', gross='0', corrects=orig).save()
        with self.assertRaises(ValidationError):  # currency must match
            make_payment(kind='reversal', gross='-1', currency='GBP', corrects=orig).save()
        with self.assertRaises(ValidationError):  # normal payment cannot reference another
            make_payment(corrects=orig).save()

    def test_corrected_payment_cannot_be_deleted(self):
        orig = make_payment(); orig.save()
        make_payment(kind='reversal', gross='-1000', corrects=orig).save()
        with self.assertRaises(ProtectedError):
            orig.delete()


class DeletionTests(TestCase):
    def test_deleting_month_and_year_cascades_to_payments(self):
        p = make_payment(); p.save()
        p2 = make_payment(date=datetime.date(2024, 5, 1)); p2.save()
        p.month.delete()
        self.assertEqual(Payment.objects.count(), 1)
        p2.month.year.delete()
        self.assertEqual(Payment.objects.count(), 0)
        self.assertEqual(ReportingMonth.objects.count(), 0)

    def test_referenced_organisation_and_category_protected(self):
        p = make_payment(); p.save()
        with self.assertRaises(ProtectedError):
            p.organisation.delete()
        with self.assertRaises(ProtectedError):
            p.category.delete()


class PrecisionTests(TestCase):
    def test_decimals_round_trip_exactly(self):
        p = make_payment(gross='12345.6789', net='9876.5432'); p.save()
        p.refresh_from_db()
        self.assertEqual(p.gross_amount, Decimal('12345.6789'))
        self.assertEqual(p.net_amount, Decimal('9876.5432'))
