"""Frequency normalisation. A monthly equivalent is amount / 1, 3, 6 or 12; one-off items have none."""
from decimal import Decimal

from core.models import Frequency

MONTHS_PER_PERIOD = {
    Frequency.MONTHLY: 1,
    Frequency.QUARTERLY: 3,
    Frequency.HALF_YEARLY: 6,
    Frequency.YEARLY: 12,
}


def is_recurring(frequency: str) -> bool:
    return frequency in MONTHS_PER_PERIOD


def monthly_equivalent(amount: Decimal | None, frequency: str) -> Decimal | None:
    """Amount per month if recurring; None for one-off/irregular, unknown frequency or missing amount."""
    if amount is None:
        return None
    divisor = MONTHS_PER_PERIOD.get(frequency)
    return None if divisor is None else amount / Decimal(divisor)
