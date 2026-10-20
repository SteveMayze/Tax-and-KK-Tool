"""RVB joint current-account statements, EUR: rent received straight from the tenant (Phase 25 skeleton, ADR 0025).

The same bank and layout as rvb_account (Phase 17), a different account and a different job. The joint account is
identified by its printed account number, which must equal the setting JOINT_RENTAL_ACCOUNT (digit for digit); with the
setting empty this reader claims nothing. rvb_account steps aside for exactly that account (rvb_account.recognises), so
one reader claims a file (ADR 0015). The number is never stored, logged or shown unmasked.

Phase 25 reads the statement grammar and proves the arithmetic; it stages nothing yet (Phase 26 adds the rent rows):

* every booking parses: Bu-Tag, Wert, type text, "PN:" code, amount with H/S, then detail lines (the first is the
  counterparty, the rest the purpose; reference blocks EREF/MREF/IBAN/BIC/... are dropped);
* the page carry lines "Übertrag auf Blatt n" / "Übertrag von Blatt n-1" are not bookings and must agree with the running
  balance and with each other;
* alter Kontostand + credits - debits = neuer Kontostand.

A line that does not parse, a carry that disagrees or a balance that does not close refuses the statement, naming the page
and booking position, never figures. A booking that parses but matches no rule is simply not rental. Headers may be
letter-spaced ("K ontonummer"): the fixed words are matched tolerantly (G8, J17).
"""
import datetime
import re
from dataclasses import dataclass, field
from decimal import Decimal

from django.conf import settings
from django.utils.translation import gettext

from . import statement_rules, statement_types as st
from .amounts import parse_amount_de_with_hs, squeeze_spaces
from .dividend_statements import UnsupportedStatement

READER_ID = 'rvb_joint'
DE = r'\d{1,3}(?:\.\d{3})*,\d{2}'


def loose(phrase):
    """A regular expression for a fixed phrase that tolerates letter-spacing inside words ("K ontonummer")."""
    return ' +'.join(' ?'.join(map(re.escape, word)) for word in phrase.split())


BALANCE = re.compile(r'^(?:(' + loose('alter') + r')|(' + loose('neuer') + r')) ' + loose('Kontostand') + ' ' + loose('vom')
                     + r' (\d{2})\.(\d{2})\.(\d{4}) (' + DE + r') ([HS])$')
BOOKING_START = re.compile(r'^\d{2}\.\d{2}\. \d{2}\.\d{2}\. ')
BOOKING = re.compile(r'^(\d{2})\.(\d{2})\. (\d{2})\.(\d{2})\. (.+?) PN:(\d+) (' + DE + r') ([HS])$')
CARRY = re.compile(r'^' + loose('Übertrag') + r' (' + loose('auf') + '|' + loose('von') + r') ' + loose('Blatt') + r' (\d+) (' + DE + r') ([HS])$')
ACCOUNT = re.compile(loose('Kontonummer') + r' +(\d{6,12})\b')
STATEMENT_NO = re.compile(loose('Kontoauszug') + r' +' + loose('Nr.') + r' *(\d+)/(\d{4})')
REFERENCE_LINE = re.compile(r'^(?:EREF|MREF|CRED|KREF|SVWZ\+?|IBAN|BIC|ABWA|ABWE)\b[:+]?')


@dataclass
class Booking:
    number: int                     # position in the statement (1-based), for messages
    page: int
    line: str                       # the booking line as printed (page and line are shown in review only for rows)
    booking_date: datetime.date
    value_date: datetime.date | None    # None when the printed value date is not a calendar date
    text: str                       # the booking type text (Gutschrift, Dauerauftrag, ...)
    amount: Decimal                 # signed: credit positive
    counterparty: str               # first detail line
    purpose: str                    # the remaining detail lines joined by a space, reference blocks dropped
    details: list = field(default_factory=list)

    @property
    def is_credit(self):
        return self.amount > 0


@dataclass
class JointStatement:
    number: str
    year: str
    opening: Decimal
    closing: Decimal
    start: datetime.date
    end: datetime.date
    bookings: list
    account: str = ''


def _lines(pages):
    return [(n, squeeze_spaces(l)) for n, page in enumerate(pages, start=1) for l in page.splitlines() if l.strip()]


def account_number(pages):
    """The printed account number: the first one on the first page that has one (digits only), or ''."""
    for _p, l in _lines(pages):
        if (m := ACCOUNT.search(l)):
            return m.group(1)
    return ''


def mask_account(number):
    """Display form: at most the last two digits."""
    return '*' * 4 + number[-2:] if len(number) > 2 else '*' * 4


def has_balance_rows(pages):
    found = {'alter' if m.group(1) else 'neuer' for _p, l in _lines(pages) if (m := BALANCE.match(l))}
    return found == {'alter', 'neuer'}


def is_joint_account(pages):
    """True only when a joint account is configured and this statement prints exactly that account number."""
    configured = settings.JOINT_RENTAL_ACCOUNT
    return bool(configured) and account_number(pages) == configured


def recognises(pages) -> bool:
    return is_joint_account(pages) and has_balance_rows(pages)


def _amount(amount, sign):
    return parse_amount_de_with_hs(f'{amount} {sign}')


def _date(d, m, y):
    try:
        return datetime.date(int(y), int(m), int(d))
    except ValueError:
        raise UnsupportedStatement(gettext('A date in the statement could not be read.'))


def _resolve(day, month, near):
    """A date printed without a year, placed in the year that puts it closest to `near` (statements span year ends)."""
    best = None
    for year in (near.year - 1, near.year, near.year + 1):
        try:
            d = datetime.date(year, int(month), int(day))
        except ValueError:
            continue
        if best is None or abs((d - near).days) < abs((best - near).days):
            best = d
    if best is None:
        raise UnsupportedStatement(gettext('A date in the statement could not be read.'))
    return best


def read_statement(pages) -> JointStatement:
    """The grammar and the arithmetic. Raises UnsupportedStatement (a reason without figures or document text)."""
    lines = _lines(pages)
    balances = [(i, m) for i, (_p, l) in enumerate(lines) if (m := BALANCE.match(l))]
    if len(balances) != 2 or not balances[0][1].group(1) or not balances[1][1].group(2):
        raise UnsupportedStatement(gettext('The opening and closing balance rows could not be found exactly once each.'))
    (a_idx, a), (n_idx, n) = balances
    opening, closing = _amount(a.group(6), a.group(7)), _amount(n.group(6), n.group(7))
    start, end = _date(a.group(3), a.group(4), a.group(5)), _date(n.group(3), n.group(4), n.group(5))

    # Walk the lines between the two balance rows: bookings (with their detail lines) and the page carries.
    bookings, balance, pending_carry, current = [], opening, None, None
    for i in range(a_idx + 1, n_idx):
        page, line = lines[i]
        if (c := CARRY.match(line)):
            direction = 'auf' if re.sub(' ', '', c.group(1)) == 'auf' else 'von'
            sheet, carried = int(c.group(2)), _amount(c.group(3), c.group(4))
            current = None
            if direction == 'auf':
                if pending_carry is not None:
                    raise UnsupportedStatement(gettext('Page %(page)s: a page carry follows another page carry.') % {'page': page})
                if carried != balance:
                    raise UnsupportedStatement(gettext('Page %(page)s: the carry to the next sheet does not match the running balance after booking %(n)s.')
                                               % {'page': page, 'n': len(bookings)})
                pending_carry = (carried, sheet)
            else:
                if pending_carry is None or pending_carry[1] != sheet + 1 or pending_carry[0] != carried:
                    raise UnsupportedStatement(gettext('Page %(page)s: the carry from the previous sheet does not match the carry to this sheet.')
                                               % {'page': page})
                pending_carry = None
        elif BOOKING_START.match(line):
            m = BOOKING.match(line)
            if not m:
                raise UnsupportedStatement(gettext('Page %(page)s: booking %(n)s could not be read.') % {'page': page, 'n': len(bookings) + 1})
            if pending_carry is not None:
                raise UnsupportedStatement(gettext('Page %(page)s: booking %(n)s stands between a page carry and its continuation.')
                                           % {'page': page, 'n': len(bookings) + 1})
            amount = _amount(m.group(7), m.group(8))
            balance += amount
            booking_date = _resolve(m.group(1), m.group(2), end)
            try:
                value_date = _resolve(m.group(3), m.group(4), booking_date)
            except UnsupportedStatement:
                value_date = None       # the bank dates interest and charges on 30-day months (a Wert of "30.02."); unused for rent
            current = Booking(number=len(bookings) + 1, page=page, line=line, booking_date=booking_date,
                              value_date=value_date, text=m.group(5), amount=amount,
                              counterparty='', purpose='')
            bookings.append(current)
        elif current is not None:
            current.details.append(line)
    if pending_carry is not None:
        raise UnsupportedStatement(gettext('A page carry to the next sheet has no continuation.'))
    if balance != closing:
        raise UnsupportedStatement(gettext('The bookings do not add up to the new balance (alter Kontostand + credits - debits).'))
    for b in bookings:
        kept = [d for d in b.details if not REFERENCE_LINE.match(d)]
        b.counterparty = kept[0] if kept else ''
        b.purpose = ' '.join(kept[1:])

    full_text = '\n'.join(l for _p, l in lines)
    number = STATEMENT_NO.search(full_text)
    return JointStatement(number=number.group(1) if number else '', year=number.group(2) if number else str(end.year),
                          opening=opening, closing=closing, start=start, end=end, bookings=bookings, account=account_number(pages))


def parse(pages: list[str]) -> st.StatementResult:
    """Phase 25: the statement is proved and read, nothing is staged. A credit that matches rules of different kinds
    is reported (RuleConflict); rent rows come in Phase 26."""
    statement = read_statement(pages)
    rules = statement_rules.load_rules()
    conflicts = 0
    for b in statement.bookings:
        if b.is_credit:
            try:
                statement_rules.match_credit(rules, b.booking_date, b.counterparty, b.purpose)
            except statement_rules.RuleConflict:
                conflicts += 1
    notices = []
    if conflicts:
        notices.append(gettext('%(n)s credit(s) match rules that disagree (different kinds or tenants), so they cannot be read.') % {'n': conflicts})
    fingerprint = st.short_hash(READER_ID, statement.number, statement.year, statement.closing)
    continuity = st.Continuity(series=st.short_hash(READER_ID, statement.account), sequence=None, opening=statement.opening,
                               closing=statement.closing, start=statement.start, end=statement.end)
    return st.StatementResult(rows=[], notices=notices, fingerprint=fingerprint, period=(statement.start, statement.end),
                              continuity=continuity)
