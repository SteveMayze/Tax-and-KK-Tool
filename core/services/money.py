"""Money helpers. Decimal only; rounding happens only for display/export."""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from core.currencies import CURRENCY_CODE_RE, SUPPORTED_CURRENCIES


class MoneyError(ValueError):
    pass


def to_decimal(value) -> Decimal:
    """Parse a value to a finite Decimal. Floats are rejected to avoid binary-rounding surprises."""
    if isinstance(value, float):
        raise MoneyError('Floats are not accepted for money; pass a Decimal or string.')
    try:
        d = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        raise MoneyError(f'Not a valid amount: {value!r}')
    if not d.is_finite():
        raise MoneyError(f'Not a finite amount: {value!r}')
    return d


def normalise_currency(code) -> str:
    c = (code or '').strip().upper()
    if not CURRENCY_CODE_RE.match(c):
        raise MoneyError(f'Invalid currency code: {code!r}')
    if c not in SUPPORTED_CURRENCIES:
        raise MoneyError(f'Unsupported currency {c!r}; supported: {", ".join(SUPPORTED_CURRENCIES)}')
    return c


def round_for_display(amount: Decimal, places: int = 2) -> Decimal:
    """Presentation/export rounding only (half-up). Never feed the result back into calculations."""
    return amount.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
