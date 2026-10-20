"""Cash Management Trust statements of a broker (AUD): quarterly interest with its overseas withholding tax (Phase 23, ADR 0023).

Read in layout mode. Recognised by structure: a Date / Description / Debit / Credit / Balance table with a "Brought Forward" row
and a running balance; neither the broker's name nor its address is used. Monthly statements and financial-year statements
overlap (the June-quarter interest exists only in the financial-year file), so rows are not made per statement: each statement
returns the interest and withholding lines it holds (meta['events']), and settle(), the batch step, drops exact repeats across
statements (same kind, date and amount; first seen wins; the repeats are listed), pairs each withholding debit with the interest
credit of the same calendar quarter, and creates the rows.

* O1: the table prints one amount column. Credit or debit comes from the running balance only and is proved for every row; a row
  whose direction cannot be proved refuses the statement.
* Dividend credits (also covered by the share advices, O5), tax-office refunds, BPAY, transfers, direct debits and transfers to the
  holder's own bank account are recognised and not staged. Share-scheme consideration, a stock-sale proceeds transfer and a large
  credit with no dividend reference (a property sale or similar) add a notice with the date only. Any other booking text refuses
  the statement naming its first words.
* The taxation summary of the financial-year statements (gross interest and non-resident withholding per quarter) is a cross-check
  that gives warnings only.
"""
import datetime
import re
from decimal import Decimal

from django.utils.translation import gettext

from . import statement_types as st
from .amounts import parse_amount_us, squeeze_spaces
from .dividend_statements import UnsupportedStatement
from .imports import COLUMNS
from .organisations import BANK_ORGANISATIONS

READER_ID = 'ordminnett_cmt'
VALUATION_ID = 'ordminnett_valuation'
AMT = r'[\d,]+\.\d{2}'
MON = {m: i for i, m in enumerate(['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'], 1)}
MONTHS_LONG = {m: i for i, m in enumerate(['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october',
                                           'november', 'december'], 1)}
HEADER = re.compile(r'^Date Description .*Balance \(\$\)$')
ENTRY = re.compile(r'^(\d{1,2}) ([A-Za-z]{3}) (\d{2}) (.*)$')
TAIL = re.compile(r'^(.*?) ?(' + AMT + r') (' + AMT + r')$')
FORWARD = re.compile(r'^Brought Forward (' + AMT + r')$')
PERIOD = re.compile(r'^(\d{1,2}) ([A-Za-z]+) (\d{4}) to (\d{1,2}) ([A-Za-z]+) (\d{4})$')
DIVIDEND_REFERENCE = re.compile(r'[A-Z]{2,4}\d{2,3}/\d{8}|DIVIDEND|\b\d{12}\b')
LARGE_CREDIT = Decimal('20000')


def _lines(pages):
    return [(n, squeeze_spaces(l)) for n, page in enumerate(pages, start=1) for l in page.splitlines() if l.strip()]


def recognises(pages) -> bool:
    lines = _lines(pages)
    return (any(HEADER.match(l) for _p, l in lines)
            and any(re.match(r'^\d{1,2} [A-Za-z]{3} \d{2} Brought Forward ' + AMT + '$', l) for _p, l in lines))


def recognises_valuation(pages) -> bool:
    text = '\n'.join(pages)
    return 'Portfolio Valuation' in text and bool(re.search(r'Code Description Units', re.sub(r'[ \t]+', ' ', text)))


def parse_valuation(pages) -> st.StatementResult:
    return st.StatementResult(rows=[])


def _words(text, n=2):
    return ' '.join(re.sub(r'[\d$()]', '', text).split()[:n])[:30]


def _date(day, mon, yy):
    try:
        return datetime.date(2000 + int(yy), MON[mon.lower()], int(day))
    except (KeyError, ValueError):
        raise UnsupportedStatement(gettext('A date in the statement could not be read.'))


def quarter_of(d):
    start_month = 3 * ((d.month - 1) // 3) + 1
    start = datetime.date(d.year, start_month, 1)
    end = (datetime.date(d.year + (start_month == 10), (start_month + 3 - 1) % 12 + 1, 1)) - datetime.timedelta(days=1)
    return start, end


def parse(pages: list[str]) -> st.StatementResult:
    lines = _lines(pages)
    period = None
    for _p, l in lines:
        m = PERIOD.match(l)
        if m and m.group(2).lower() in MONTHS_LONG and m.group(5).lower() in MONTHS_LONG:
            try:
                period = (datetime.date(int(m.group(3)), MONTHS_LONG[m.group(2).lower()], int(m.group(1))),
                          datetime.date(int(m.group(6)), MONTHS_LONG[m.group(5).lower()], int(m.group(4))))
            except ValueError:
                pass
            break
    if not period or period[1] < period[0]:
        raise UnsupportedStatement(gettext('The statement period could not be read.'))

    balance, closing, events, notices, first = None, None, [], [], True
    for page, line in lines:
        m = ENTRY.match(line)
        if not m or m.group(2).lower() not in MON:
            continue
        date = _date(m.group(1), m.group(2), m.group(3))
        text = m.group(4)
        forward = FORWARD.match(text)
        if forward:
            if not first:
                raise UnsupportedStatement(gettext('A statement has more than one brought-forward row.'))
            balance, first = parse_amount_us(forward.group(1)), False
            continue
        if first:
            raise UnsupportedStatement(gettext('The first row of the table is not the brought-forward balance.'))
        tail = TAIL.match(text)
        if not tail:
            raise UnsupportedStatement(gettext('A row of the table could not be read (%(kind)s).') % {'kind': _words(text)})
        description, amount, new_balance = tail.group(1), parse_amount_us(tail.group(2)), parse_amount_us(tail.group(3))
        if balance + amount == new_balance:
            direction = 'credit'
        elif balance - amount == new_balance:
            direction = 'debit'
        else:
            raise UnsupportedStatement(gettext('The direction of a row could not be proved from the running balance (%(kind)s).') % {'kind': _words(description)})
        balance = closing = new_balance
        if not (period[0] - datetime.timedelta(days=3) <= date <= period[1] + datetime.timedelta(days=3)):
            raise UnsupportedStatement(gettext('A date in the statement is outside the statement period.'))
        if description == 'Interest':
            if direction != 'credit':
                raise UnsupportedStatement(gettext('An interest row is a debit, which is not expected.'))
            events.append({'kind': 'interest', 'date': date, 'amount': amount, 'page': page, 'line': line})
        elif description == 'Overseas Withholding Tax':
            if direction != 'debit':
                raise UnsupportedStatement(gettext('A withholding tax row is a credit, which is not expected.'))
            events.append({'kind': 'withholding', 'date': date, 'amount': amount, 'page': page, 'line': line})
        elif description.startswith('Direct Credit'):
            if direction != 'credit':
                raise UnsupportedStatement(gettext('A direct credit is a debit, which is not expected.'))
            if 'SCHEME' in description:
                notices.append(gettext('Share-scheme consideration credit on %(date)s is not imported.') % {'date': date.isoformat()})
            elif amount >= LARGE_CREDIT and not DIVIDEND_REFERENCE.search(description) and 'ATO' not in description:
                notices.append(gettext('A large credit on %(date)s (a property sale or similar) is not imported.') % {'date': date.isoformat()})
        elif description.startswith(('Direct Debit', 'BPay')):
            continue
        elif description.startswith('Transferred'):
            if 'SELL' in description and direction == 'credit':
                notices.append(gettext('Stock-sale proceeds transfer on %(date)s is not imported (sales are not recorded).') % {'date': date.isoformat()})
        elif re.search(r'BSB \d{3}-\d{3}', description):
            continue
        else:
            raise UnsupportedStatement(gettext('A booking is a type this importer does not read ("%(kind)s"), so nothing was staged.')
                                       % {'kind': _words(description)})
    if first or closing is None and balance is None:
        raise UnsupportedStatement(gettext('The brought-forward balance could not be found.'))
    closing = balance

    summary = []
    for _p, l in lines:
        m = re.match(r'^(\d{1,2}) ([A-Za-z]{3}) (\d{4}) ([\d.]+) (' + AMT + r') (' + AMT + r') (' + AMT + r')$', l)
        if m and m.group(2).lower() in MON:
            summary.append({'date': datetime.date(int(m.group(3)), MON[m.group(2).lower()], int(m.group(1))),
                            'gross': parse_amount_us(m.group(5)), 'resident': parse_amount_us(m.group(6)), 'nonresident': parse_amount_us(m.group(7))})
    return st.StatementResult(rows=[], notices=notices, period=period, fingerprint=st.short_hash(READER_ID, period[0], period[1], closing),
                              meta={'events': events, 'summary': summary})


def settle(items):
    """items: [(label, StatementResult)] of all CMT statements of one upload. Creates the interest rows (see the module docstring)
    and returns the batch warnings."""
    warnings, seen, interest, withholding, repeats = [], {}, [], [], []
    for label, result in items:
        occurrence = {}
        for e in result.meta.get('events', []):
            base = (e['kind'], e['date'], e['amount'])
            occurrence[base] = occurrence.get(base, 0) + 1
            key = base + (occurrence[base],)          # two identical lines inside ONE statement are two payments, not a repeat
            if key in seen:
                repeats.append((label, seen[key], e))
                continue
            seen[key] = label
            e = dict(e, label=label, result=result)
            (interest if e['kind'] == 'interest' else withholding).append(e)
    if repeats:
        warnings.append(gettext('%(n)s line(s) repeated in overlapping statements were staged once (the first statement wins): %(list)s') % {
            'n': len(repeats), 'list': '; '.join(f"{e['kind']} {e['date'].isoformat()} in {lbl} (also in {first})" for lbl, first, e in repeats[:8])
            + ('; ...' if len(repeats) > 8 else '')})

    def quarter(e):
        return quarter_of(e['date'])
    unpaired_interest = 0
    for q in sorted({quarter(e) for e in interest}):
        ints = sorted((e for e in interest if quarter(e) == q), key=lambda e: e['date'])
        whs = sorted((e for e in withholding if quarter(e) == q), key=lambda e: e['date'])
        for index, e in enumerate(ints):
            wh = whs[index] if index < len(whs) else None
            if wh is None:
                unpaired_interest += 1
            tax = wh['amount'] if wh else Decimal(0)
            comment = gettext('Interest of the Cash Management Trust for the quarter %(start)s to %(end)s (PDF import).') % {'start': q[0].isoformat(), 'end': q[1].isoformat()}
            if wh:
                comment += ' ' + gettext('Overseas withholding tax debited on %(date)s.') % {'date': wh['date'].isoformat()}
            data = {c: '' for c in COLUMNS}
            data.update(payment_date=e['date'].isoformat(), organisation=BANK_ORGANISATIONS[READER_ID], category='Interest', currency='AUD',
                        gross_amount=format(e['amount'], 'f'), net_amount=format(e['amount'] - tax, 'f'), withholding_tax=format(tax, 'f'), expenses='0',
                        frequency='quarterly', income_period_start=q[0].isoformat(), income_period_end=q[1].isoformat(), comment=comment)
            provenance = {'payment_date': (e['page'], e['line']), 'gross_amount': (e['page'], e['line'])}
            if wh:
                provenance['withholding_tax'] = (wh['page'], wh['line'])
            e['result'].rows.append(st.StatementRow(data, provenance))
    if unpaired_interest:
        warnings.append(gettext('%(n)s interest credit(s) have no overseas withholding debit in their quarter; withholding is recorded as 0.') % {'n': unpaired_interest})
    leftover = 0
    for q in {quarter(e) for e in withholding}:
        leftover += max(0, len([e for e in withholding if quarter(e) == q]) - len([e for e in interest if quarter(e) == q]))
    if leftover:
        warnings.append(gettext('%(n)s overseas withholding debit(s) have no interest credit in their quarter in this upload (not staged).') % {'n': leftover})

    # Taxation summary of the financial-year statements (O4): a cross-check, warnings only.
    by_date = {e['date']: e for e in interest}
    wh_by_quarter = {}
    for e in withholding:
        wh_by_quarter[quarter(e)] = wh_by_quarter.get(quarter(e), Decimal(0)) + e['amount']
    for label, result in items:
        for row in result.meta.get('summary', []):
            e = by_date.get(row['date'])
            if e is None:
                warnings.append(gettext('The taxation summary of %(file)s lists a quarter ending %(date)s with no interest line in this upload.') % {'file': label, 'date': row['date'].isoformat()})
            elif e['amount'] != row['gross'] or wh_by_quarter.get(quarter(e), Decimal(0)) != row['nonresident']:
                warnings.append(gettext('The taxation summary of %(file)s does not agree with the lines of the quarter ending %(date)s.') % {'file': label, 'date': row['date'].isoformat()})
    return warnings
