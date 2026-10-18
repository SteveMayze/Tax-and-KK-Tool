"""EUR conversion of payments. Originals are never modified; the rate used is stored and audited."""
import datetime
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction

from core.currencies import BASE_CURRENCY
from core.models import ExchangeRateRecord, Payment

from .money import MoneyError, to_decimal
from .rates import RateError, RateProvider


class ConversionError(Exception):
    """Conversion failed; the payment was left untouched."""

    def __init__(self, message, manual_rate_possible=True):
        super().__init__(message)
        self.manual_rate_possible = manual_rate_possible


@dataclass(frozen=True)
class Conversion:
    rate: Decimal
    rate_date: datetime.date
    provider: str
    is_manual: bool
    notes: str
    gross_eur: Decimal
    net_eur: Decimal | None


def eur_amount(amount: Decimal | None, rate: Decimal) -> Decimal | None:
    """EUR amount = original amount x rate, at full Decimal precision (no rounding)."""
    return None if amount is None else amount * rate


STORAGE_QUANTUM = Decimal(1).scaleb(-6)  # matches Payment.gross_eur/net_eur decimal_places


def for_storage(amount: Decimal | None) -> Decimal | None:
    """Quantise a EUR amount to the column precision (6 dp, sub-micro-cent). This is storage
    precision, not display rounding; the exact value stays reproducible from original x rate."""
    return None if amount is None else amount.quantize(STORAGE_QUANTUM, rounding=ROUND_HALF_UP)


def compute_conversion(payment: Payment, provider: RateProvider | None = None, manual_rate=None,
                       manual_rate_date: datetime.date | None = None, manual_note: str = '') -> Conversion:
    """Work out the conversion without touching the database."""
    if payment.currency == BASE_CURRENCY:
        rate, rate_date, source, manual, notes = Decimal(1), payment.payment_date, 'identity', False, ''
    elif manual_rate is not None:
        try:
            rate = to_decimal(manual_rate)
        except MoneyError as e:
            raise ConversionError(f'Invalid manual rate: {e}') from e
        if rate <= 0:
            raise ConversionError('Manual rate must be positive.')
        rate_date = manual_rate_date or payment.payment_date
        source, manual = 'manual', True
        notes = manual_note or 'Manually entered rate.'
    else:
        if provider is None:
            raise ConversionError('No rate provider configured.')
        try:
            quote = provider.get_rate(payment.currency, payment.payment_date)
        except RateError as e:
            raise ConversionError(f'Could not obtain {payment.currency} rate for {payment.payment_date}: {e}') from e
        if quote.rate <= 0:
            raise ConversionError(f'Provider returned an invalid rate ({quote.rate}).')
        rate, rate_date, source, manual = quote.rate, quote.rate_date, quote.provider, False
        notes = (f'Rate date {quote.rate_date} differs from payment date {quote.requested_date} '
                 f'(supplied by provider).' if quote.date_differs else '')
    return Conversion(rate, rate_date, source, manual, notes,
                      for_storage(eur_amount(payment.gross_amount, rate)),
                      for_storage(eur_amount(payment.net_amount, rate)))


@transaction.atomic
def convert_payment(payment: Payment, provider: RateProvider | None = None, manual_rate=None,
                    manual_rate_date=None, manual_note: str = '', recalculate: bool = False) -> Payment:
    """Convert and save a payment.

    A payment that is already converted is left alone unless recalculate=True (an explicit action).
    On failure nothing is saved or changed, so the caller can offer manual entry and keep form input.
    Every rate applied is appended as an ExchangeRateRecord, so earlier rates stay on record.
    """
    if payment.conversion_status == Payment.ConversionStatus.CONVERTED and not recalculate:
        raise ConversionError('Payment already converted; recalculation must be requested explicitly.',
                              manual_rate_possible=False)
    c = compute_conversion(payment, provider, manual_rate, manual_rate_date, manual_note)
    record = ExchangeRateRecord.objects.create(
        currency=payment.currency, rate_date=c.rate_date, rate=c.rate, provider=c.provider,
        is_manual=c.is_manual, notes=c.notes)
    payment.rate, payment.rate_date, payment.rate_source, payment.rate_record = c.rate, c.rate_date, c.provider, record
    payment.gross_eur, payment.net_eur, payment.conversion_notes = c.gross_eur, c.net_eur, c.notes
    payment.conversion_status = Payment.ConversionStatus.CONVERTED
    payment.save()
    return payment
