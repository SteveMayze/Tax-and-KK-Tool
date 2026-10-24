"""The payments page (Phase 31, ADR 0032, spike): the payments of one year (or all years), optionally one month,
limited by the Phase 30 organisation and category filter. Read only; nothing is stored.

The filter is applied once, in `queryset`. Totals are computed over exactly the payments listed, in Python
Decimals (`aggregation`), never in a template and never across currencies.
"""
import datetime
import re
from dataclasses import dataclass
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.utils.translation import gettext as _

from core.models import Payment, ReportingYear

from . import aggregation, i18n, report_filter

ZERO = Decimal(0)
NUMBER = re.compile(r'[0-9]{1,9}')


def current_year():
    """The current calendar year in Europe/Berlin (the project's time zone setting is UTC)."""
    return datetime.datetime.now(ZoneInfo('Europe/Berlin')).year


def parse_period(get):
    """(year or None, month or None, error text or None). An absent year means the current calendar year; `all` or
    an empty value means every year. A year that is not a reporting year is an error, except the current year, which
    lists nothing. A month is 1 to 12, or empty/`all`. Errors echo at most 10 characters of the input."""
    today = current_year()
    years, months = get.getlist('year'), get.getlist('month')
    year = month = None
    if not years:
        year = today
    elif len(years) > 1:
        return None, None, _('Unknown year "%(year)s".') % {'year': ','.join(years)[:10]}
    else:
        raw = years[0].strip()
        if raw != 'all' and raw != '':
            if not NUMBER.fullmatch(raw) or not (int(raw) == today or ReportingYear.objects.filter(year=int(raw)).exists()):
                return None, None, _('Unknown year "%(year)s".') % {'year': raw[:10]}
            year = int(raw)
    if len(months) > 1:
        return None, None, _('Unknown month "%(month)s".') % {'month': ','.join(months)[:10]}
    if months:
        raw = months[0].strip()
        if raw not in ('', 'all'):
            if not NUMBER.fullmatch(raw) or not 1 <= int(raw) <= 12:
                return None, None, _('Unknown month "%(month)s".') % {'month': raw[:10]}
            month = int(raw)
    return year, month, None


def queryset(year, month, flt):
    qs = Payment.objects.select_related('organisation', 'category', 'month__year')
    if year:
        qs = qs.filter(month__year__year=year)
        if month:
            qs = qs.filter(month__month=month)
    return flt.apply(qs).order_by('payment_date', 'organisation__name', 'id')


@dataclass
class CurrencyTotals:
    currency: str
    count: int
    gross: Decimal
    net: Decimal
    net_missing_count: int
    withholding: Decimal


def currency_totals(payments):
    """Gross, net and withholding in each original currency, as reported (converted or not). Never summed across
    currencies; net counts only payments that have a net amount."""
    by = {}
    for p in payments:
        by.setdefault(p.currency, []).append(p)
    result = []
    for ccy in sorted(by):
        group = by[ccy]
        with_net = [p for p in group if p.net_amount is not None]
        result.append(CurrencyTotals(
            ccy, len(group), sum((p.gross_amount for p in group), ZERO), sum((p.net_amount for p in with_net), ZERO),
            len(group) - len(with_net), sum((p.withholding_tax or ZERO for p in group), ZERO)))
    return result


def basis(year, month, flt, ignored_month=False):
    rows = []
    if year is None:
        period = _('All years')
        if ignored_month:
            period += ' ' + _('(the month is ignored: a month without a year is meaningless)')
    elif month:
        period = _('%(month)s %(year)s (reporting month of the payment date)') % {'month': i18n.month_name(month), 'year': year}
    else:
        period = _('%(year)s, all months (reporting year of the payment date)') % {'year': year}
    rows.append((_('Period'), period))
    if flt.is_active:
        rows.append((_('Filter'), flt.describe()))
    rows.append((_('Amounts'), _('Original amounts in each payment\'s own currency, never added across currencies; EUR totals '
                                 'at each payment\'s stored rate, payments not converted are left out and counted. Actual '
                                 'payments, gross and net as stored; withholding tax in the original currency.')))
    return rows


def build(year, month, flt):
    """(payments list, original-currency totals, EUR totals, option lists). One pass over the same payments."""
    payments = list(queryset(year, month, flt))
    return payments, currency_totals(payments), aggregation.actual_totals(payments), report_filter.options(year, flt, month)
