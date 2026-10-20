"""RVB (German cooperative bank) current-account statements, EUR: quarterly interest and the tax booked on it
(Phase 17, ADR 0017).

Read in layout mode. Recognised by structure only: an "alter Kontostand" row and a "neuer Kontostand" row with German
amounts (H credit / S debit). The bank's name, address and header wording are never used (the name changed and is
sometimes rendered as noise).

* Ordinary statement: no interest closing, so no rows ("nothing to import"). The running balance is still proved
  (alter + credits - debits = neuer), so a damaged statement is not reported as empty. Bookings are classified by their
  text only to say they are not income; a prize credit (savings lottery) adds a notice; any other booking text refuses
  the statement naming it.
* Closing statement: the booking "Abschluss lt. Anlage 1" plus the Anlage 1 block (period, HABENZINSEN lines, booked
  tax, "Summe Abschlussposten"). Gross is the sum of the interest lines and must equal the booked closing amount (and
  the Summe line); the booked tax lines (Kapitalertragsteuer, Solidaritaetszuschlag, Kirchensteuer if present) are the
  withholding and must agree with the tax lines of the block. The stated tax base is written to the comment.
"""
import datetime
import re
from decimal import Decimal

from django.utils.translation import gettext

from . import statement_types as st
from .amounts import parse_amount_de_with_hs, squeeze_spaces
from .dividend_statements import UnsupportedStatement
from .imports import COLUMNS
from .organisations import BANK_ORGANISATIONS
from .pdf_text import mask_digit_runs

READER_ID = 'rvb_giro'
DE = r'\d{1,3}(?:\.\d{3})*,\d{2}'
BALANCE = re.compile(r'^(alter|neuer) Kontostand vom (\d{2})\.(\d{2})\.(\d{4}) (' + DE + r') ([HS])$')
BOOKING = re.compile(r'^(\d{2})\.(\d{2})\. (\d{2})\.(\d{2})\. (.+?) PN:\d+ (' + DE + r') ([HS])$')
STATEMENT_NO = re.compile(r'Kontoauszug Nr\. (\d+)/(\d{4})')
ACCOUNT = re.compile(r'Kontonummer (\d{6,12})')
PERIOD = re.compile(r'^Kontoabschluss vom (\d{2})\.(\d{2})\.(\d{4}) bis (\d{2})\.(\d{2})\.(\d{4})')
INTEREST_LINE = re.compile(r'^[\d,]+% HABENZINSEN bis (\d{2})\.(\d{2})\. (' + DE + r') H$')
SUMME = re.compile(r'^Summe Abschlussposten .*?EUR (' + DE + r') ([HS])$')
BLOCK_TAX = re.compile(r'^> (Kapitalertragsteuer|Solidaritätszuschlag|Kirchensteuer) (' + DE + r') S$')
BLOCK_BASE = re.compile(r'^> aus (' + DE + r') Habenzins$')
BASE_LINE = re.compile(r'^EUR (' + DE + r')(?:-KapSt| Habenzins)\b')
TAX_KINDS = (('Kapitalertragsteuer', re.compile(r'^Kapitalertragsteuer\b')),
             ('Solidaritätszuschlag', re.compile(r'^Solid(?:aritäts)?\.?-?[Zz]uschlag\b')),
             ('Kirchensteuer', re.compile(r'^Kirchensteuer\b')))
NOT_INCOME = re.compile(r'^(?:Gutschrift|Umbuchung|Dauerauftrag|[\w-]*[Üü]berweisung)\b')
PRIZE = re.compile(r'Gewinn|\bLos\b')


def _lines(pages):
    return [(n, squeeze_spaces(l)) for n, page in enumerate(pages, start=1) for l in page.splitlines() if l.strip()]


def recognises(pages) -> bool:
    found = {m.group(1) for _p, l in _lines(pages) if (m := BALANCE.match(l))}
    return found == {'alter', 'neuer'}


def _amount(amount, sign):
    return parse_amount_de_with_hs(f'{amount} {sign}')


def _kind(text):
    for name, rx in TAX_KINDS:
        if rx.match(text):
            return name
    return None


def _resolve(day, month, near):
    """A date printed without a year, placed in the year that puts it closest to `near`."""
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


def _date(d, m, y):
    try:
        return datetime.date(int(y), int(m), int(d))
    except ValueError:
        raise UnsupportedStatement(gettext('A date in the statement could not be read.'))


def _words(text):
    return re.sub(r'\s+', ' ', mask_digit_runs(re.sub(r'\d', '', text))).strip()[:40]


def parse(pages: list[str]) -> st.StatementResult:
    lines = _lines(pages)
    balances = [(i, m) for i, (_p, l) in enumerate(lines) if (m := BALANCE.match(l))]
    if len(balances) != 2 or balances[0][1].group(1) != 'alter' or balances[1][1].group(1) != 'neuer':
        raise UnsupportedStatement(gettext('The opening and closing balance rows could not be found exactly once each.'))
    (a_idx, a), (n_idx, n) = balances
    opening, closing = _amount(a.group(5), a.group(6)), _amount(n.group(5), n.group(6))
    start, end = _date(a.group(2), a.group(3), a.group(4)), _date(n.group(2), n.group(3), n.group(4))

    # bookings between the two balance rows, each with its detail lines
    bookings, i = [], a_idx + 1
    while i < n_idx:
        m = BOOKING.match(lines[i][1])
        if not m:
            i += 1
            continue
        j = i + 1
        while j < n_idx and not BOOKING.match(lines[j][1]):
            j += 1
        bookings.append({'page': lines[i][0], 'line': lines[i][1], 'm': m, 'details': [l for _p, l in lines[i + 1:j]]})
        i = j
    balance = opening
    interest_booking, taxes, prizes, other_credits = None, [], 0, 0
    for number, b in enumerate(bookings, start=1):
        m = b['m']
        amount = _amount(m.group(6), m.group(7))
        balance += amount
        text = m.group(5)
        if text.startswith('Abschluss lt. Anlage'):
            if interest_booking or amount <= 0:
                raise UnsupportedStatement(gettext('The interest closing booking is not unique or not a credit.'))
            interest_booking = (b, amount)
        elif _kind(text):
            if amount >= 0:
                raise UnsupportedStatement(gettext('A tax booking is a credit, which is not expected (row %(n)s).') % {'n': number})
            taxes.append((_kind(text), -amount, b))
        elif NOT_INCOME.match(text):
            if text.startswith('Gutschrift'):
                if PRIZE.search(' '.join(b['details'])):
                    prizes += 1
                else:
                    other_credits += 1
        else:
            raise UnsupportedStatement(gettext('Booking %(n)s is a type this importer does not read ("%(kind)s"), so nothing was staged.')
                                       % {'n': number, 'kind': _words(text)})
    if balance != closing:
        raise UnsupportedStatement(gettext('The bookings do not add up to the new balance (alter Kontostand + credits - debits).'))

    notices = []
    if prizes:
        notices.append(gettext('Savings-lottery prize credit, not imported.') if prizes == 1 else
                       gettext('Savings-lottery prize credits (%(n)s), not imported.') % {'n': prizes})
    if other_credits:
        notices.append(gettext('A credit (Gutschrift) that is not interest, not imported.') if other_credits == 1 else
                       gettext('Credits (Gutschrift) that are not interest (%(n)s), not imported.') % {'n': other_credits})

    full_text = '\n'.join(l for _p, l in lines)
    number = STATEMENT_NO.search(full_text)
    account = ACCOUNT.search(full_text)
    fingerprint = st.short_hash(READER_ID, number.group(1) if number else '', number.group(2) if number else '', closing, end)
    continuity = st.Continuity(series=st.short_hash(account.group(1)) if account else '', sequence=None, opening=opening,
                               closing=closing, start=start, end=end) if account else None
    common = dict(notices=notices, fingerprint=fingerprint, period=(start, end), continuity=continuity)

    if not interest_booking:
        if taxes:
            raise UnsupportedStatement(gettext('Tax was booked but no interest closing ("Abschluss lt. Anlage") was found.'))
        return st.StatementResult(rows=[], **common)

    # ---- the closing: the Anlage block
    booking, booked = interest_booking
    period_idx = next((k for k, (_p, l) in enumerate(lines) if PERIOD.match(l)), None)
    summe_idx = next((k for k, (_p, l) in enumerate(lines) if SUMME.match(l)), None)
    if period_idx is None or summe_idx is None or summe_idx < period_idx:
        raise UnsupportedStatement(gettext('The interest closing booking has no readable Anlage 1 block (period and total).'))
    p = PERIOD.match(lines[period_idx][1])
    period_start, period_end = _date(p.group(1), p.group(2), p.group(3)), _date(p.group(4), p.group(5), p.group(6))
    interest, block_taxes, block_bases, evidence_interest = [], [], [], []
    for k in range(period_idx + 1, summe_idx):
        page, line = lines[k]
        if (m := INTEREST_LINE.match(line)):
            interest.append(_amount(m.group(3), 'H'))
            evidence_interest.append((page, line))
        elif (m := BLOCK_TAX.match(line)):
            block_taxes.append((m.group(1), _amount(m.group(2), 'H')))
        elif (m := BLOCK_BASE.match(line)):
            block_bases.append((_amount(m.group(1), 'H'), (page, line)))
        elif re.search(DE + r' [HS]$', line):
            raise UnsupportedStatement(gettext('The interest closing block has a line this importer does not read ("%(kind)s"), so nothing was staged.')
                                       % {'kind': _words(line)})
    if not interest:
        raise UnsupportedStatement(gettext('The interest closing block has no interest (HABENZINSEN) line.'))
    summe = SUMME.match(lines[summe_idx][1])
    gross = sum(interest, Decimal(0))
    if summe.group(2) != 'H' or _amount(summe.group(1), 'H') != booked or gross != booked:
        raise UnsupportedStatement(gettext('The interest lines, the total of the closing block and the booked closing amount do not agree.'))
    if sorted(block_taxes) != sorted((kind, amount) for kind, amount, _b in taxes):
        raise UnsupportedStatement(gettext('The tax lines of the closing block do not agree with the tax bookings.'))

    order = [name for name, _rx in TAX_KINDS]
    taxes.sort(key=lambda t: order.index(t[0]))
    withholding = sum((amount for _k, amount, _b in taxes), Decimal(0))
    base = None
    if len(block_bases) > 1:
        raise UnsupportedStatement(gettext('The closing block states the interest base more than once.'))
    if block_bases:
        base = block_bases[0][0]
        if base > gross:
            raise UnsupportedStatement(gettext('The tax base stated is larger than the interest.'))
    if taxes and base is None:
        raise UnsupportedStatement(gettext('Tax was booked but the interest base it was charged on could not be read.'))
    for kind, amount, b in taxes:           # the line under each tax booking states its base
        for detail in b['details']:
            if (bm := BASE_LINE.match(detail)):
                stated = _amount(bm.group(1), 'H')
                expected = base if 'Habenzins' in detail else next((a for k_, a, _b in taxes if k_ == 'Kapitalertragsteuer'), None)
                if stated != expected:
                    raise UnsupportedStatement(gettext('The base stated under a tax booking does not agree with the closing block.'))
    booking_m = booking['m']
    payment_date = _resolve(booking_m.group(1), booking_m.group(2), end)
    value_date = _resolve(booking_m.group(3), booking_m.group(4), payment_date)
    comment = gettext('Quarterly interest (PDF import). Value date %(value)s.') % {'value': value_date.isoformat()}
    if taxes:
        parts = ' + '.join(f'{kind} {format(amount, "f")}' for kind, amount, _b in taxes)
        comment += ' ' + gettext('Withholding as booked: %(parts)s. Tax charged on %(base)s of the %(gross)s interest.') % {
            'parts': parts, 'base': format(base, 'f'), 'gross': format(gross, 'f')}
    data = {c: '' for c in COLUMNS}
    data.update(payment_date=payment_date.isoformat(), organisation=BANK_ORGANISATIONS[READER_ID], category='Interest', currency='EUR',
                gross_amount=format(gross, 'f'), net_amount=format(gross - withholding, 'f'), withholding_tax=format(withholding, 'f'),
                expenses='0', frequency='quarterly', income_period_start=period_start.isoformat(),
                income_period_end=period_end.isoformat(), comment=comment)
    joined = ' / '.join(l for _p, l in evidence_interest)
    provenance = {'payment_date': (booking['page'], booking['line']), 'gross_amount': (evidence_interest[0][0], joined),
                  'income_period_start': (lines[period_idx][0], lines[period_idx][1]), 'income_period_end': (lines[period_idx][0], lines[period_idx][1]),
                  'net_amount': (lines[summe_idx][0], lines[summe_idx][1])}
    if taxes:
        provenance['withholding_tax'] = (taxes[0][2]['page'], ' / '.join(b['line'] for _k, _a, b in taxes))
    return st.StatementResult(rows=[st.StatementRow(data, provenance)], **common)
