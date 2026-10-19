from decimal import Decimal

from django import template

from core.services import i18n

register = template.Library()


@register.filter
def money(value, places=2):
    """Display rounding only; None shows as a dash."""
    if value is None or value == '':
        return '—'
    return i18n.number(Decimal(value), int(places))


@register.filter
def rate(value):
    """Rates are shown at stored precision, trailing zeros trimmed."""
    if value is None:
        return '—'
    return i18n.plain_decimal(value)
