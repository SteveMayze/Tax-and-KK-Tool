from decimal import Decimal

from django import template

from core.services.money import round_for_display

register = template.Library()


@register.filter
def money(value, places=2):
    """Display rounding only; None shows as a dash."""
    if value is None or value == '':
        return '—'
    return f'{round_for_display(Decimal(value), int(places)):,.{int(places)}f}'


@register.filter
def rate(value):
    """Rates are shown at stored precision, trailing zeros trimmed."""
    if value is None:
        return '—'
    text = f'{Decimal(value):f}'
    return text.rstrip('0').rstrip('.') if '.' in text else text
