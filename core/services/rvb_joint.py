"""RVB joint current-account statements, EUR: rent received straight from the tenant (Phases 25 and 26, ADRs 0025 and 0026).

The same bank and layout as rvb_account (Phase 17), a different account and a different job. The joint account is
identified by its printed account number, which must equal the setting JOINT_RENTAL_ACCOUNT (digit for digit); with the
setting empty this reader claims nothing. rvb_account steps aside for exactly that account (rvb_account.recognises), so
one reader claims a file (ADR 0015). The number is never stored, logged or shown unmasked.

Phase 25 reads the statement grammar and proves the arithmetic; Phase 26 stages the rent rows (see parse):

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
from .imports import COLUMNS
from .pdf_text import mask_digit_runs

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


FIGURE = r'(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?)'
LABELLED = {label: re.compile(r'\b' + label + r'\b[^\d]{0,12}?' + FIGURE) for label in ('kaution', 'miete')}
MONTH_NAMES = ('januar', 'februar', 'maerz', 'april', 'mai', 'juni', 'juli', 'august', 'september', 'oktober', 'november', 'dezember')
MONTH_SHOWN = {'maerz': 'März'}
COMMENT = {
    statement_rules.KIND_TENANT_RENT: 'Rent received directly from tenant, joint account, whole amount (PDF import).',
    statement_rules.KIND_SERVICE_CHARGE: 'Service-charge settlement paid by the tenant (kind: service-charge settlement), joint account, '
                                         'whole amount (PDF import).',
}


def _german_figure(text):
    return Decimal(text.replace('.', '').replace(',', '.'))


def split_deposit(purpose, credit):
    """J8. The purpose names a deposit (Kaution). -> (rent figure, deposit figure) when it states both a Kaution and a
    Miete figure, each once, and the two sum to the credit; otherwise None (the credit cannot be split)."""
    text = statement_rules.normalise(purpose)
    figures = {}
    for label, rx in LABELLED.items():
        found = rx.findall(text)
        if len(found) != 1:
            return None
        figures[label] = _german_figure(found[0])
    if figures['kaution'] <= 0 or figures['miete'] <= 0 or figures['kaution'] + figures['miete'] != credit:
        return None
    return figures['miete'], figures['kaution']


def _month_comment(purpose):
    """Q26.3: the month the purpose names, only when it names exactly one. Never derived from the payment date."""
    text = statement_rules.normalise(purpose)
    named = {m for m in MONTH_NAMES if re.search(r'\b' + m + r'\b', text)}
    if len(named) != 1:
        return ''
    name = named.pop()
    return ' ' + gettext('Purpose names the month: %(month)s.') % {'month': MONTH_SHOWN.get(name, name.capitalize())}


def _evidence(b):
    return mask_digit_runs(' / '.join(x for x in (b.counterparty, b.purpose) if x))


def _row(b, rule, amount, extra=''):
    data = {c: '' for c in COLUMNS}
    rent = rule.kind == statement_rules.KIND_TENANT_RENT
    comment = gettext(COMMENT[rule.kind]) + extra + _month_comment(b.purpose)
    data.update(payment_date=b.booking_date.isoformat(), organisation=rule.organisation, category=settings.JOINT_RENTAL_CATEGORY,
                currency='EUR', gross_amount=format(amount.quantize(Decimal('0.01')), 'f'), net_amount=format(amount.quantize(Decimal('0.01')), 'f'), withholding_tax='0', expenses='0',
                frequency='monthly' if rent else 'one_off', comment=comment)
    evidence = (b.page, mask_digit_runs(b.line) + ' / ' + _evidence(b))
    provenance = {'payment_date': (b.page, mask_digit_runs(b.line)), 'gross_amount': evidence, 'organisation': (b.page, _evidence(b))}
    return st.StatementRow(data, provenance)


def _check_category():
    from core.models import IncomeCategory
    name = settings.JOINT_RENTAL_CATEGORY
    category = IncomeCategory.objects.filter(name__iexact=name).first()
    if category is None or not category.active:
        raise UnsupportedStatement(gettext(
            'Rent was found, but the income category "%(name)s" (setting DJANGO_JOINT_RENTAL_CATEGORY) does not exist or is '
            'inactive. Create or reactivate it on the Categories page, then upload again. Nothing was staged.') % {'name': name})


def parse(pages: list[str]) -> st.StatementResult:
    """Phase 26: one row per tenant-rent credit and per service-charge back-payment; a deposit part, an unresolvable
    credit, a possible rent no rule matched and a rule conflict are notices. Debits (costs, charges, interest) and
    everything else are ignored, counted in `meta['ignored']`. Nothing is skipped silently."""
    statement = read_statement(pages)
    rules = statement_rules.load_rules()
    rows, notices, ignored, conflicts = [], [], 0, 0

    def shown(b, amount=None):
        return {'date': b.booking_date.isoformat(), 'amount': format(b.amount if amount is None else amount, 'f')}

    for b in statement.bookings:
        if not b.is_credit:
            ignored += 1                                    # J10, J18: a debit never makes income; costs are out of scope
            continue
        try:
            rule = statement_rules.match_credit(rules, b.booking_date, b.counterparty, b.purpose)
        except statement_rules.RuleConflict:
            conflicts += 1
            continue
        if rule is None:
            if re.search(r'\bmiete\b', statement_rules.normalise(b.purpose)):         # J12
                notices.append(gettext('Credit of %(date)s (%(amount)s EUR): possible rent not matched by any rule, not staged.') % shown(b))
            else:
                ignored += 1                                # J13
            continue
        if re.search(r'\bkaution\b', statement_rules.normalise(b.purpose)):           # J8
            parts = split_deposit(b.purpose, b.amount) if rule.kind == statement_rules.KIND_TENANT_RENT else None
            if parts is None:
                notices.append(gettext('Credit of %(date)s (%(amount)s EUR) mentions a deposit and could not be split into deposit '
                                       'and rent, so it was not staged. Handle it manually.') % shown(b))
                continue
            rent, deposit = parts
            notices.append(gettext('Credit of %(date)s: the deposit part (%(deposit)s EUR) is not income and was not staged.')
                           % {'date': b.booking_date.isoformat(), 'deposit': format(deposit, 'f')})
            rows.append(_row(b, rule, rent, ' ' + gettext('Rent part of a combined credit of %(total)s EUR with a deposit.') % {'total': format(b.amount, 'f')}))
            continue
        rows.append(_row(b, rule, b.amount))
    if conflicts:
        notices.append(gettext('%(n)s credit(s) match rules that disagree (different kinds or tenants), so they cannot be read.') % {'n': conflicts})
    if rows:
        _check_category()
    fingerprint = st.short_hash(READER_ID, statement.number, statement.year, statement.closing)
    continuity = st.Continuity(series=st.short_hash(READER_ID, statement.account), sequence=None, opening=statement.opening,
                               closing=statement.closing, start=statement.start, end=statement.end)
    return st.StatementResult(rows=rows, notices=notices, fingerprint=fingerprint, period=(statement.start, statement.end),
                              continuity=continuity, meta={'ignored': ignored})
