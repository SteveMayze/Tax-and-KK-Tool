"""Totals over stored payments (EUR). Sums are done in Python Decimals, not SQL, because SQLite
aggregates DECIMAL columns as floating point.

Two separate, always-labelled views:
  * actual   - payments received in the period (gross and net as stored).
  * normalised - monthly equivalents of recurring payments (one-off items excluded).
Gross and net are never mixed: net totals only include payments that have a net amount and
report how many were missing it. Unconverted payments are excluded and counted.
"""
from dataclasses import dataclass
from decimal import Decimal

from core.models import Payment, ReportingMonth

from .normalisation import is_recurring, monthly_equivalent

ZERO = Decimal(0)


@dataclass
class ActualTotals:
    basis: str
    payment_count: int
    gross_eur: Decimal
    net_eur: Decimal
    net_missing_count: int      # converted payments with no net amount (not in net_eur)
    unconverted_count: int      # payments without a stored EUR conversion (excluded from all sums)
    withholding_eur: Decimal = ZERO     # withholding tax, converted with each payment's own rate
    expenses_eur: Decimal = ZERO
    unallocated_eur: Decimal = ZERO     # gross - net - withholding - expenses, over payments that have a net amount
    # gross_eur = gains + losses + adjustments (Phase 11): normal payments above 0, normal payments below 0 (a loss,
    # signed), and corrections/reversals (signed). Nothing is netted away: gross_eur is the signed sum.
    gains_eur: Decimal = ZERO
    losses_eur: Decimal = ZERO
    adjustments_eur: Decimal = ZERO


@dataclass
class NormalisedTotals:
    basis: str
    gross_monthly_eur: Decimal
    net_monthly_eur: Decimal
    recurring_count: int
    one_off_excluded_count: int
    net_missing_count: int
    unconverted_count: int


def _split(payments):
    converted = [p for p in payments if p.conversion_status == Payment.ConversionStatus.CONVERTED]
    return converted, len(payments) - len(converted)


def unallocated_eur(p):
    """gross - net - withholding - expenses from the stored EUR amounts of one converted payment with a net amount."""
    return p.gross_eur - p.net_eur - (p.withholding_tax_eur or ZERO) - (p.expenses_eur or ZERO)


def actual_totals(payments) -> ActualTotals:
    payments = list(payments)
    converted, unconverted = _split(payments)
    gross = sum((p.gross_eur for p in converted), ZERO)
    with_net = [p for p in converted if p.net_eur is not None]
    net = sum((p.net_eur for p in with_net), ZERO)
    withholding = sum((p.withholding_tax_eur or ZERO for p in converted), ZERO)
    expenses = sum((p.expenses_eur or ZERO for p in converted), ZERO)
    unallocated = sum((unallocated_eur(p) for p in with_net), ZERO)
    normal = [p for p in converted if p.kind == Payment.Kind.NORMAL]
    gains = sum((p.gross_eur for p in normal if p.gross_eur > 0), ZERO)
    losses = sum((p.gross_eur for p in normal if p.gross_eur < 0), ZERO)
    adjustments = sum((p.gross_eur for p in converted if p.kind != Payment.Kind.NORMAL), ZERO)
    return ActualTotals('actual payments received, EUR, stored rates', len(payments), gross, net,
                        len(converted) - len(with_net), unconverted, withholding, expenses, unallocated,
                        gains, losses, adjustments)


def normalised_monthly_totals(payments) -> NormalisedTotals:
    """Sum of monthly equivalents of the given recurring payments.

    Intended for a single month's payments. For a whole year this would over-count
    repeated monthly payments, so use `year_average_of_actuals` for annual / 12.
    """
    payments = list(payments)
    converted, unconverted = _split(payments)
    recurring = [p for p in converted if is_recurring(p.frequency)]
    gross = sum((monthly_equivalent(p.gross_eur, p.frequency) for p in recurring), ZERO)
    with_net = [p for p in recurring if p.net_eur is not None]
    net = sum((monthly_equivalent(p.net_eur, p.frequency) for p in with_net), ZERO)
    return NormalisedTotals(
        'normalised recurring monthly equivalents, EUR, stored rates; one-off items excluded',
        gross, net, len(recurring), len(converted) - len(recurring),
        len(recurring) - len(with_net), unconverted)


def month_payments(month: ReportingMonth):
    return Payment.objects.filter(month=month)


def year_payments(year):
    return Payment.objects.filter(month__year=year)


def month_actual(month: ReportingMonth) -> ActualTotals:
    return actual_totals(month_payments(month))


def month_normalised(month: ReportingMonth) -> NormalisedTotals:
    return normalised_monthly_totals(month_payments(month))


def year_actual(year) -> ActualTotals:
    return actual_totals(year_payments(year))


def average_of_actuals(t: ActualTotals) -> dict:
    """Annual actual total / 12, the figure shown on the opening page. The divisor is always 12,
    even for a partial year. An average of actuals, NOT a recurring monthly figure, and not an
    official SBK calculation."""
    return {
        'basis': 'annual actual total / 12 (average of actuals, not a recurring figure)',
        'gross_eur': t.gross_eur / 12,
        'net_eur': t.net_eur / 12,
        'net_missing_count': t.net_missing_count,
        'unconverted_count': t.unconverted_count,
    }


def year_average_of_actuals(year) -> dict:
    return average_of_actuals(year_actual(year))
