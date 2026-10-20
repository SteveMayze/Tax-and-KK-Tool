"""MECU account statements (AUD): interest, bonus interest and term-deposit interest with the overseas withholding tax shown
in the memo lines (Phase 22, ADR 0022).

Read in layout mode, after pdf_text has opened the file (the cross-reference repair is in pdf_text). Recognised by structure:
account sections with Effective / Posted / Description / Debit / Credit / Balance columns, an opening and a closing balance
per account and a statement number. The bank's name, address and branch text are never used and no account number is kept.

* Dates carry no year: the year comes from the "Statement Date" (a December date in a January statement is last year's).
* The statement prints one amount column: whether a row is a credit or a debit is derived from the running balance, which must
  be proved for every row, and opening + credits - debits must equal the closing balance of every account (M9).
* Interest rows: "Interest Credit" and "Bonus Interest" (separate rows), and the term-deposit "Interest Payment ... ($x)"
  that is paid out by transfer. The memo lines under them ("Overseas Withholding Tax ($x)", "Gross Interest. ($x)") give
  withholding and gross; gross - withholding must equal the credit or the statement is refused (M4).
* Double appearance (M5): the receiving "Interest Credit ... Transfer" credit of a savings account is a transfer when it
  matches a term-deposit interest payment of the same date and amount in the same statement; interest is staged once, from
  the term-deposit section. A receiving credit without such a partner refuses the statement.
* Any other booking text refuses the statement naming its first words (a fee, for example).
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

READER_ID = 'mecu_account'
AMT = r'-?[\d,]+\.\d{2}'
MON = {m: i for i, m in enumerate(['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'], 1)}
MONTHS_LONG = {m: i for i, m in enumerate(['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october',
                                           'november', 'december'], 1)}
ENTRY = re.compile(r'^(\d{1,2}) ([A-Za-z]{3}) (\d{1,2}) ([A-Za-z]{3}) (.*)$')
OPENING = re.compile(r'^(\d{1,2}) ([A-Za-z]{3}) Opening Balance (' + AMT + r')$')
CLOSING = re.compile(r'^(\d{1,2}) ([A-Za-z]{3}) Closing Balance (' + AMT + r')$')
TAIL = re.compile(r'^(.*?) ?(?:(' + AMT + r') )?(' + AMT + r')$')
PAREN = re.compile(r'^(.*?) ?\(\$(' + AMT + r')\)$')
MEMO_TAX = re.compile(r'^Overseas Withholding Tax$')
MEMO_GROSS = re.compile(r'^Gross Interest\.?$')
NOT_INCOME = ('Direct Credit', 'BPAY Payment', 'Osko Payment', 'Net Tfr', 'Transfer To', 'Transfer From', 'Received From', 'Internet', 'Member',
              'Visa', 'Deposit', 'POS', 'Ext Tfr', 'ATM')
# Rows that only restate the balance (no amount moves): accepted only when the single figure equals the running balance.
INFORMATION = ('Dormant Account', 'Balance Enquiry', 'Invalid Pin')
SECTION = re.compile(r'^Account: (\d+)\b(.*)$')
HEADER_COLUMNS = re.compile(r'Effective Posted Description Debit Credit Balance')


def _lines(pages):
    return [(n, squeeze_spaces(l)) for n, page in enumerate(pages, start=1) for l in page.splitlines() if l.strip()]


def recognises(pages) -> bool:
    lines = _lines(pages)
    text = {l for _p, l in lines}
    return (any(HEADER_COLUMNS.search(l) for l in text) and any(OPENING.match(l) for l in text) and any(CLOSING.match(l) for l in text)
            and any(re.match(r'^Statement Number \d+$', l) for l in text))


def _words(text, n=2):
    return ' '.join(re.sub(r'[\d$()]', '', text).split()[:n])[:30]


def _statement_date(lines):
    for _p, l in lines:
        m = re.match(r'^Statement Date (\d{1,2}) ([A-Za-z]+) (\d{4})$', l)
        if m and m.group(2).lower() in MONTHS_LONG:
            try:
                return datetime.date(int(m.group(3)), MONTHS_LONG[m.group(2).lower()], int(m.group(1)))
            except ValueError:
                break
    raise UnsupportedStatement(gettext('The statement date could not be found.'))


def _day(day, mon, end):
    """A date printed without a year: the latest such date that is not after the statement date (M2)."""
    month = MON.get(mon.lower())
    if not month:
        raise UnsupportedStatement(gettext('A date in the statement could not be read.'))
    for year in (end.year, end.year - 1):
        try:
            d = datetime.date(year, month, int(day))
        except ValueError:
            continue
        if d <= end:
            return d
    raise UnsupportedStatement(gettext('A date in the statement could not be read.'))


def _amount(text):
    return parse_amount_us(text)


def _entries(lines, start, end):
    """Date-started entries of a section, each joined over its wrapped lines: [{'page', 'lines', 'eff', 'posted', 'text'}]."""
    out, i = [], start
    while i < end:
        page, line = lines[i]
        m = ENTRY.match(line)
        if not m or m.group(2).lower() not in MON or m.group(4).lower() not in MON:
            i += 1
            continue
        parts, j = [m.group(5)], i
        while not (re.search(r'\(\$' + AMT + r'\)$', parts[-1]) or re.search(AMT + r' ' + AMT + r'$', ' '.join(parts))
                   or parts[0].startswith(INFORMATION) and re.search(AMT + r'$', ' '.join(parts))):
            j += 1
            if j >= end or len(parts) >= 4 or ENTRY.match(lines[j][1]) or OPENING.match(lines[j][1]) or CLOSING.match(lines[j][1]):
                raise UnsupportedStatement(gettext('A row of an account could not be read (%(kind)s).') % {'kind': _words(parts[0])})
            parts.append(lines[j][1])
        out.append({'page': page, 'lines': [lines[k][1] for k in range(i, j + 1)], 'eff': (m.group(1), m.group(2)), 'posted': (m.group(3), m.group(4)),
                    'text': ' '.join(parts)})
        i = j + 1
    return out


def parse(pages: list[str]) -> st.StatementResult:
    lines = _lines(pages)
    end = _statement_date(lines)
    number = next((m.group(1) for _p, l in lines if (m := re.match(r'^Statement Number (\d+)$', l))), None)
    starts = [i for i, (_p, l) in enumerate(lines) if SECTION.match(l)]
    if not starts:
        raise UnsupportedStatement(gettext('No account section was found.'))
    bounds = list(zip(starts, starts[1:] + [len(lines)]))

    # An account can continue on the next page ("Account: <same number> ... continued", no opening balance): its blocks are one account.
    accounts, order = {}, []
    for a, b in bounds:
        number_key = SECTION.match(lines[a][1]).group(1)
        header = SECTION.match(lines[a][1]).group(2)
        acc = accounts.get(number_key)
        if acc is None:
            acc = accounts[number_key] = {'blocks': [], 'td': False, 'opening': None, 'closing': None}
            order.append(number_key)
        acc['td'] = acc['td'] or 'Term Deposit' in header or 'Term Deposit' in ' '.join(l for _p, l in lines[a:a + 3])
        acc['blocks'].append((a, b))
        opening = next((OPENING.match(l) for _p, l in lines[a:b] if OPENING.match(l)), None)
        closing = next((CLOSING.match(l) for _p, l in lines[a:b] if CLOSING.match(l)), None)
        if opening:
            if acc['opening'] is not None:
                raise UnsupportedStatement(gettext('An account has two opening balances.'))
            acc['opening'] = (_amount(opening.group(3)), _day(opening.group(1), opening.group(2), end))
        if closing:
            acc['closing'] = _amount(closing.group(3))
    period_start = None
    for key in order:
        acc = accounts[key]
        if acc['opening'] is None or acc['closing'] is None:
            raise UnsupportedStatement(gettext('An account section has no opening or closing balance.'))
        period_start = acc['opening'][1] if period_start is None else min(period_start, acc['opening'][1])
    if end - period_start > datetime.timedelta(days=45):
        raise UnsupportedStatement(gettext('The statement period could not be read with certainty.'))

    interest, closings = [], Decimal(0)
    for key in order:
        acc = accounts[key]
        balance, previous = acc['opening'][0], None
        entries = [e for a, b in acc['blocks'] for e in _entries(lines, a + 1, b)]
        for entry in entries:
            eff, posted = _day(*entry['eff'], end), _day(*entry['posted'], end)
            if posted < period_start or eff < period_start - datetime.timedelta(days=7):
                raise UnsupportedStatement(gettext('A date in the statement is outside the statement period.'))
            text = entry['text']
            memo = PAREN.match(text)
            if memo and (MEMO_TAX.match(memo.group(1)) or MEMO_GROSS.match(memo.group(1))):
                if previous is None:
                    raise UnsupportedStatement(gettext('A memo line has no interest row above it.'))
                memo_key = 'tax' if MEMO_TAX.match(memo.group(1)) else 'gross'
                if memo_key in previous['memos']:
                    raise UnsupportedStatement(gettext('An interest row has the same memo line twice.'))
                previous['memos'][memo_key] = _amount(memo.group(2))
                previous['lines'] += entry['lines']
                continue
            if memo and memo.group(1).startswith('Interest Payment'):         # a term-deposit payment paid out by transfer
                row = {'kind': 'td_payment', 'amount': _amount(memo.group(2)), 'eff': eff, 'posted': posted, 'memos': {}, 'td': True,
                       'lines': list(entry['lines']), 'page': entry['page']}
                interest.append(row)
                previous = row
                continue
            if text.startswith(INFORMATION):
                shown = re.search(AMT + r'$', text)
                if not shown or _amount(shown.group(0)) != balance:
                    raise UnsupportedStatement(gettext('A row of an account could not be read (%(kind)s).') % {'kind': _words(text)})
                previous = None
                continue
            tail = TAIL.match(text)
            if not tail or not tail.group(2):
                raise UnsupportedStatement(gettext('A row of an account could not be read (%(kind)s).') % {'kind': _words(text)})
            description, amount, new_balance = tail.group(1), _amount(tail.group(2)), _amount(tail.group(3))
            if balance + amount == new_balance:
                direction = 'credit'
            elif balance - amount == new_balance:
                direction = 'debit'
            else:
                raise UnsupportedStatement(gettext('The running balance of an account does not add up (%(kind)s).') % {'kind': _words(description)})
            balance = new_balance
            previous = None
            if description.startswith(('Interest Credit', 'Bonus Interest')):
                if direction != 'credit':
                    raise UnsupportedStatement(gettext('An interest row is a debit, which is not expected.'))
                row = {'kind': 'bonus' if description.startswith('Bonus') else 'credit', 'amount': amount, 'eff': eff, 'posted': posted, 'memos': {},
                       'td': acc['td'], 'lines': list(entry['lines']), 'page': entry['page'], 'description': description}
                interest.append(row)
                previous = row
            elif description.startswith(NOT_INCOME):
                continue
            else:
                raise UnsupportedStatement(gettext('A booking is a type this importer does not read ("%(kind)s"), so nothing was staged.')
                                           % {'kind': _words(description)})
        if balance != acc['closing']:
            raise UnsupportedStatement(gettext('The rows of an account do not add up to its closing balance.'))
        closings += acc['closing']

    # M5: a receiving "Interest Credit ... Transfer" without memo lines is the other side of a term-deposit payment
    payments = [r for r in interest if r['kind'] == 'td_payment']
    rows_to_stage = []
    for r in interest:
        if r['kind'] == 'credit' and not r['memos'] and 'Transfer' in r['description']:
            partner = next((p for p in payments if p['amount'] == r['amount'] and p['eff'] == r['eff'] and not p.get('matched')), None)
            if partner is None:
                raise UnsupportedStatement(gettext('An interest credit paid by transfer has no matching term-deposit interest payment.'))
            partner['matched'] = True
            continue
        rows_to_stage.append(r)

    out = []
    for r in rows_to_stage:
        memos, net = r['memos'], r['amount']
        withholding = memos.get('tax', Decimal(0))
        gross = memos.get('gross', net)
        if gross - withholding != net:
            raise UnsupportedStatement(gettext('The gross interest and the withholding tax do not agree with the amount credited.'))
        kind = (gettext('Term-deposit interest') if r['td'] else gettext('Bonus interest') if r['kind'] == 'bonus' else gettext('Interest'))
        where = gettext('term deposit') if r['td'] else gettext('savings account')
        comment = gettext('%(kind)s (%(where)s), posted %(posted)s (PDF import).') % {'kind': kind, 'where': where, 'posted': r['posted'].isoformat()}
        data = {c: '' for c in COLUMNS}
        data.update(payment_date=r['eff'].isoformat(), organisation=BANK_ORGANISATIONS[READER_ID], category='Interest', currency='AUD',
                    gross_amount=format(gross, 'f'), net_amount=format(net, 'f'), withholding_tax=format(withholding, 'f'), expenses='0',
                    frequency='monthly', comment=comment)
        evidence = (r['page'], ' / '.join(r['lines']))
        out.append(st.StatementRow(data, {'payment_date': evidence, 'gross_amount': evidence, 'net_amount': evidence, 'withholding_tax': evidence}))

    meta = {}
    summary = _payment_summary(lines)
    if summary:
        meta['payment_summary'] = summary
    return st.StatementResult(rows=out, fingerprint=st.short_hash(READER_ID, number, end, closings), period=(period_start, end), meta=meta)


def _payment_summary(lines):
    """The annual "Payment Summary for Withholding Tax" of the June statement: the period and the totals of interest and
    non-resident withholding tax (used only to cross-check the staged rows, M6)."""
    for i, (_p, l) in enumerate(lines):
        m = re.match(r'^Payment Summary for Withholding Tax (\d{1,2})/(\d{1,2})/(\d{2}) - (\d{1,2})/(\d{1,2})/(\d{2})$', l)
        if not m:
            continue
        try:
            start = datetime.date(2000 + int(m.group(3)), int(m.group(2)), int(m.group(1)))
            finish = datetime.date(2000 + int(m.group(6)), int(m.group(5)), int(m.group(4)))
        except ValueError:
            return None
        interest = withheld = Decimal(0)
        found = False
        for _q, row in lines[i + 1:i + 14]:
            if row.startswith('Account summary'):
                break
            r = re.match(r'^\d{6,12} (' + AMT + r') (' + AMT + r') (' + AMT + r')', row)
            if r:
                interest += _amount(r.group(1))
                withheld += _amount(r.group(3))
                found = True
        return {'start': start, 'end': finish, 'interest': interest, 'withheld': withheld} if found else None
    return None


def settle(items):
    """Cross-check (M6, warnings only): when the upload contains a statement with the annual summary and the staged rows of that
    financial year, compare gross interest and withholding with the summary."""
    warnings = []
    for label, result in items:
        summary = result.meta.get('payment_summary')
        if not summary:
            continue
        periods = [r.period for _l, r in items if r.period]
        covered = sorted(periods)
        # the summary can only be compared when the statements of the whole year are in the upload
        months = {(p[1].year, p[1].month) for p in periods}
        needed = {(summary['start'].year + (summary['start'].month + k - 1) // 12, (summary['start'].month + k - 1) % 12 + 1) for k in range(12)}
        if not needed <= months:
            warnings.append(gettext('The annual payment summary in %(file)s was not compared: the upload does not cover the whole financial year.')
                            % {'file': label})
            continue
        gross = withheld = Decimal(0)
        for _l, r in items:
            for row in r.rows:
                d = datetime.date.fromisoformat(row.data['payment_date'])
                if summary['start'] <= d <= summary['end']:
                    gross += Decimal(row.data['gross_amount'])
                    withheld += Decimal(row.data['withholding_tax'])
        if gross != summary['interest'] or withheld != summary['withheld']:
            warnings.append(gettext('The annual payment summary in %(file)s does not agree with the staged interest rows of the financial year.')
                            % {'file': label})
    return warnings
