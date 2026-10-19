"""EUR conversion of payments. Originals are never modified; every rate applied is stored with
provenance and every change is appended to the payment's audit trail (ConversionEvent)."""
import datetime
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils.translation import gettext

from core.currencies import BASE_CURRENCY
from core.models import ConversionEvent, ExchangeRateRecord, Payment

from .money import MoneyError, to_decimal
from .rates import RateError, RateProvider, RateQuote

STORAGE_QUANTUM = Decimal(1).scaleb(-6)  # matches Payment.gross_eur/net_eur decimal_places


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
    source_url: str = ''
    raw_response: str = ''
    withholding_tax_eur: Decimal = Decimal(0)
    expenses_eur: Decimal = Decimal(0)


def for_storage(amount: Decimal | None) -> Decimal | None:
    """Quantise a EUR amount to the column precision (6 dp, sub-micro-cent). This is storage
    precision, not display rounding; the exact value stays reproducible from original x rate."""
    return None if amount is None else amount.quantize(STORAGE_QUANTUM, rounding=ROUND_HALF_UP)


def eur_amount(amount: Decimal | None, rate: Decimal) -> Decimal | None:
    """EUR amount = original amount x rate, at full Decimal precision (no rounding)."""
    return None if amount is None else amount * rate


def breakdown_eur(payment: Payment, rate: Decimal) -> tuple[Decimal, Decimal]:
    """Withholding tax and expenses in EUR with the payment's own rate (the same one as gross and net)."""
    return (for_storage(eur_amount(payment.withholding_tax or Decimal(0), rate)),
            for_storage(eur_amount(payment.expenses or Decimal(0), rate)))


def stored_quote(provider: RateProvider, currency, on_date) -> RateQuote | None:
    """A rate this provider already returned for exactly this currency and requested date.
    Reusing it means repeat requests don't hit the service again."""
    rec = (ExchangeRateRecord.objects
           .filter(provider=provider.name, currency=currency, requested_date=on_date, is_manual=False)
           .order_by('-created_at', '-id').first())
    if rec is None:
        return None
    return RateQuote(currency, on_date, rec.rate_date, rec.rate, rec.provider, rec.source_url, rec.raw_response)


def quote_notes(quote: RateQuote) -> str:
    """Label a provider rate whose date differs from the requested date."""
    return (f'Rate date {quote.rate_date} differs from payment date {quote.requested_date} '
            f'(nearest earlier rate supplied by provider).' if quote.date_differs else '')


def compute_conversion(payment: Payment, provider: RateProvider | None = None, manual_rate=None,
                       manual_rate_date: datetime.date | None = None, manual_note: str = '',
                       refresh: bool = False) -> Conversion:
    """Work out the conversion without saving. `refresh` bypasses previously retrieved rates."""
    if payment.currency == BASE_CURRENCY:
        wh, ex = breakdown_eur(payment, Decimal(1))
        return Conversion(Decimal(1), payment.payment_date, 'identity', False, '',
                          for_storage(payment.gross_amount), for_storage(payment.net_amount),
                          withholding_tax_eur=wh, expenses_eur=ex)
    if manual_rate is not None:
        try:
            rate = to_decimal(manual_rate)
        except MoneyError as e:
            raise ConversionError(gettext('Invalid manual rate: %(error)s') % {'error': e}) from e
        if rate <= 0:
            raise ConversionError(gettext('Manual rate must be positive.'))
        wh, ex = breakdown_eur(payment, rate)
        return Conversion(
            rate, manual_rate_date or payment.payment_date, 'manual', True,
            manual_note or 'Manually entered rate.',
            for_storage(eur_amount(payment.gross_amount, rate)), for_storage(eur_amount(payment.net_amount, rate)),
            withholding_tax_eur=wh, expenses_eur=ex)

    if provider is None:
        raise ConversionError(gettext('No rate provider configured.'))
    quote = None if refresh else stored_quote(provider, payment.currency, payment.payment_date)
    if quote is None:
        try:
            quote = provider.get_rate(payment.currency, payment.payment_date)
        except RateError as e:
            raise ConversionError(gettext('Could not obtain %(ccy)s rate for %(date)s: %(error)s') % {
                'ccy': payment.currency, 'date': payment.payment_date, 'error': e}) from e
    if quote.rate <= 0:
        raise ConversionError(gettext('Provider returned an invalid rate (%(rate)s).') % {'rate': quote.rate})
    wh, ex = breakdown_eur(payment, quote.rate)
    return Conversion(
        quote.rate, quote.rate_date, quote.provider, False, quote_notes(quote),
        for_storage(eur_amount(payment.gross_amount, quote.rate)),
        for_storage(eur_amount(payment.net_amount, quote.rate)), quote.source_url, quote.raw_response,
        withholding_tax_eur=wh, expenses_eur=ex)


def _record_for(payment: Payment, c: Conversion) -> ExchangeRateRecord:
    """Append a manual record; reuse an identical provider record rather than duplicating it."""
    fields = dict(currency=payment.currency, rate_date=c.rate_date, requested_date=payment.payment_date,
                  rate=c.rate, provider=c.provider, is_manual=c.is_manual)
    defaults = dict(notes=c.notes, source_url=c.source_url, raw_response=c.raw_response)
    if c.is_manual:
        return ExchangeRateRecord.objects.create(**fields, **defaults)
    rec = ExchangeRateRecord.objects.filter(**fields).order_by('id').first()
    return rec or ExchangeRateRecord.objects.create(**fields, **defaults)


def _log(payment, kind, record, previous, reason):
    ConversionEvent.objects.create(
        payment=payment, kind=kind, rate_record=record, rate=payment.rate, rate_date=payment.rate_date,
        gross_eur=payment.gross_eur, net_eur=payment.net_eur,
        previous_rate=previous[0], previous_gross_eur=previous[1], previous_net_eur=previous[2], reason=reason)


def _snapshot(payment):
    return (payment.rate, payment.gross_eur, payment.net_eur)


@transaction.atomic
def convert_payment(payment: Payment, provider: RateProvider | None = None, manual_rate=None,
                    manual_rate_date=None, manual_note: str = '', recalculate: bool = False,
                    refresh: bool = False, kind: str | None = None, reason: str = '') -> Payment:
    """Convert and save a payment, appending an audit event.

    An already-converted payment is left alone unless recalculate=True (an explicit action).
    On failure nothing is saved or changed, so the caller can offer manual entry and keep form input.
    `refresh` re-requests the rate from the provider instead of reusing one already retrieved.
    A manual rate on an already-converted payment is a correction and needs a reason.
    """
    converted = payment.conversion_status == Payment.ConversionStatus.CONVERTED
    if converted and not recalculate:
        raise ConversionError(gettext('Payment already converted; recalculation must be requested explicitly.'),
                              manual_rate_possible=False)
    if kind is None:
        if not converted:
            kind = ConversionEvent.Kind.INITIAL
        elif manual_rate is not None:
            kind = ConversionEvent.Kind.MANUAL_CORRECTION
        else:
            kind = ConversionEvent.Kind.RECALCULATED
    reason = (reason or '').strip()
    if kind == ConversionEvent.Kind.MANUAL_CORRECTION and not reason:
        raise ConversionError(gettext('A reason is required when manually correcting a stored rate.'))

    previous = _snapshot(payment)
    c = compute_conversion(payment, provider, manual_rate, manual_rate_date, manual_note,
                           refresh=refresh or (recalculate and manual_rate is None))
    record = _record_for(payment, c)
    payment.rate, payment.rate_date, payment.rate_source, payment.rate_record = c.rate, c.rate_date, c.provider, record
    payment.gross_eur, payment.net_eur, payment.conversion_notes = c.gross_eur, c.net_eur, c.notes
    payment.withholding_tax_eur, payment.expenses_eur = c.withholding_tax_eur, c.expenses_eur
    payment.conversion_status = Payment.ConversionStatus.CONVERTED
    payment.save()
    _log(payment, kind, record, previous if converted else (None, None, None), reason or c.notes)
    return payment


def correct_rate_manually(payment: Payment, rate, reason: str, rate_date=None) -> Payment:
    """Explicit manual correction of a stored rate. A reason is mandatory; the old rate stays on record."""
    return convert_payment(payment, manual_rate=rate, manual_rate_date=rate_date, manual_note=reason,
                           recalculate=True, kind=ConversionEvent.Kind.MANUAL_CORRECTION, reason=reason)


@transaction.atomic
def reapply_stored_rate(payment: Payment) -> Payment:
    """After amounts change (same currency and payment date), recompute EUR with the STORED rate.
    The rate itself is not replaced; the change is logged."""
    if payment.conversion_status != Payment.ConversionStatus.CONVERTED or payment.rate is None:
        raise ConversionError(gettext('Payment has no stored rate to reapply.'))
    previous = _snapshot(payment)
    payment.gross_eur = for_storage(eur_amount(payment.gross_amount, payment.rate))
    payment.net_eur = for_storage(eur_amount(payment.net_amount, payment.rate))
    before_breakdown = (payment.withholding_tax_eur, payment.expenses_eur)
    payment.withholding_tax_eur, payment.expenses_eur = breakdown_eur(payment, payment.rate)
    payment.save()
    if (payment.gross_eur, payment.net_eur) != previous[1:] or before_breakdown != (
            payment.withholding_tax_eur, payment.expenses_eur):
        _log(payment, ConversionEvent.Kind.AMOUNTS_EDITED, payment.rate_record, previous, 'Amounts edited; stored rate kept.')
    return payment


def convert_pending(provider: RateProvider, payments) -> list[tuple[Payment, str | None]]:
    """Try the automatic provider for each unconverted payment. Failures leave that payment pending."""
    results = []
    for p in payments:
        try:
            convert_payment(p, provider)
            results.append((p, None))
        except ConversionError as e:
            results.append((p, str(e)))
    return results
