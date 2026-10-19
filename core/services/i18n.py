"""Language-aware helpers for presentation. Calculations never use these (Decimal values stay untouched)."""
from decimal import Decimal

from django.utils import formats
from django.utils.dates import MONTHS

from .money import round_for_display


def month_name(n: int) -> str:
    """Month name in the active language (not the operating system's locale)."""
    return str(MONTHS[n])


def number(value, places=2) -> str:
    """Rounded for display and formatted for the active language: 1,234.50 (en) / 1.234,50 (de)."""
    return formats.number_format(round_for_display(Decimal(value), places), decimal_pos=places,
                                 use_l10n=True, force_grouping=True)


def percent(fraction, places=1) -> str:
    return number(Decimal(fraction) * 100, places) + '%'


def plain_decimal(value) -> str:
    """A rate at stored precision, trailing zeros trimmed, with the active language's decimal separator."""
    text = f'{Decimal(value):f}'
    text = text.rstrip('0').rstrip('.') if '.' in text else text
    return text.replace('.', formats.get_format('DECIMAL_SEPARATOR', use_l10n=True))


def date_text(value) -> str:
    return formats.date_format(value, 'DATE_FORMAT')
