"""Amount parsing for statement text (Phase 15, corner case G6). Pure functions on strings; Decimal only.

Each convention is a separate function because the same characters mean different things: "1.234" is one thousand two
hundred thirty-four in German and 1.234 in English. A text that does not match its convention exactly raises ValueError,
so a reader refuses the statement instead of guessing."""
import re
from decimal import Decimal

DASHES = '-‐‑‒–—−'
_US = re.compile(r'(?P<open>\()?(?P<sign>-)?\$?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?P<close>\))?')
_UK = re.compile(r'(?P<sign>-)?£?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)')
_DE = re.compile(r'(?P<num>\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?)\s*(?P<hs>[HS])')


def squeeze_spaces(text: str) -> str:
    """Runs of spaces (layout mode pads columns) become one space; the ends are trimmed."""
    return re.sub(r'[ \t ]+', ' ', text).strip()


def parse_amount_us(text: str) -> Decimal:
    """US/UK-style statements: "1,234.56", "$1,234.56", "(1,234.56)" and "-1,234.56" are negative, a lone dash or em dash is zero."""
    t = squeeze_spaces(text)
    if t and all(c in DASHES for c in t):
        return Decimal(0)
    m = _US.fullmatch(t)
    if not m or bool(m['open']) != bool(m['close']) or (m['open'] and m['sign']):
        raise ValueError('not a US-style amount')
    value = Decimal(m['num'].replace(',', ''))
    return -value if m['open'] or m['sign'] else value


def parse_amount_uk(text: str) -> Decimal:
    """UK bank statements: "1,234.56", "£1,234.56", "-1,234.56". Parentheses and trailing letters are not accepted."""
    m = _UK.fullmatch(squeeze_spaces(text))
    if not m:
        raise ValueError('not a UK-style amount')
    value = Decimal(m['num'].replace(',', ''))
    return -value if m['sign'] else value


def parse_amount_de_with_hs(text: str) -> Decimal:
    """German bank statements: "1.234,56 H" (Haben, credit: positive) or "1.234,56 S" (Soll, debit: negative).
    The H or S is required: an amount without it is refused, never assumed."""
    m = _DE.fullmatch(squeeze_spaces(text))
    if not m:
        raise ValueError('not a German amount with H or S')
    value = Decimal(m['num'].replace('.', '').replace(',', '.'))
    return value if m['hs'] == 'H' else -value
