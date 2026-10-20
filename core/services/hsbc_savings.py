"""HSBC UK savings statements (Flexible Saver, GBP): one payment per "GROSS INTEREST" credit (Phase 16, ADR 0016).

The statement is read in pypdf's layout mode, which keeps the cells of a table row on one line (the default mode
separates dates from amounts). The reader anchors on the structure of the transaction table and on arithmetic, never on
headings (some are letter-spaced) or logos:

* a "BALANCE BROUGHT FORWARD" row and a "BALANCE CARRIED FORWARD" row bound each part of the table (a table that
  continues on another page has one pair per part; the balances must chain);
* a row starts with a date ("05 Jan 25"); its description and amounts may continue on the next lines;
* interest: "GROSS INTEREST" followed by "TO <ddMONyyyy>", paid in, balance;
* internet transfers (either direction, never income) are checked and skipped;
* any other row type refuses the statement, naming the type text.

Every row must satisfy previous balance +/- amount = balance. Withholding is 0 only because the balance proves the credit
was paid in full (an interest credit that did not raise the balance by its amount is refused). No fee line occurs in the
samples, so none is understood: a fee is an unknown row type and refuses the statement.
"""
import datetime
import re
from decimal import Decimal

from django.utils.translation import gettext

from . import statement_types as sr
from .imports import COLUMNS
from .amounts import parse_amount_uk, squeeze_spaces
from .dividend_statements import UnsupportedStatement
from .organisations import BANK_ORGANISATIONS
from .pdf_text import mask_digit_runs

READER_ID = 'hsbc_savings'
AMT = r'\d{1,3}(?:,\d{3})*\.\d{2}'
MONTHS = {m: i for i, m in enumerate(['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'], 1)}
DATE_START = re.compile(r'^(\d{1,2}) ([A-Za-z]{3}) (\d{2})(?!\d)\s*')
BROUGHT = re.compile(r'^(?:(\d{1,2} [A-Za-z]{3} \d{2}) )?BALANCE BROUGHT FORWARD (' + AMT + r')\.?$')
CARRIED = re.compile(r'^(?:(\d{1,2} [A-Za-z]{3} \d{2}) )?BALANCE CARRIED FORWARD (' + AMT + r')\.?$')
TAIL = re.compile(r'^(.*?)\s*(' + AMT + r')\s+(' + AMT + r')$')
INTEREST = re.compile(r'^(?:\S{1,4} )?GROSS INTEREST TO (\d{2})([A-Z]{3})(\d{4})$')
SHEET = re.compile(r'(?:^|\s)\d{2}-\d{2}-\d{2} (\d{8}) (\d{1,4})$')


def _lines(pages):
    return [(number, squeeze_spaces(line)) for number, page in enumerate(pages, start=1) for line in page.splitlines()
            if line.strip()]


def recognises(pages) -> bool:
    text = '\n'.join(pages)
    compact = re.sub(r'\s+', '', text)
    structure = (any(BROUGHT.match(l) for _p, l in _lines(pages)) and any(CARRIED.match(l) for _p, l in _lines(pages))
                 and all(word in compact for word in ('Paidout', 'Paidin', 'Balance', '£')))
    return structure and bool(re.search(r'GROSS INTEREST|INTERNET TRANSFER', text))


def _date(text, what):
    m = re.fullmatch(r'(\d{1,2}) ([A-Za-z]{3}) (\d{2})', text)
    try:
        return datetime.date(2000 + int(m.group(3)), MONTHS[m.group(2).upper()], int(m.group(1)))
    except (AttributeError, KeyError, ValueError):
        raise UnsupportedStatement(gettext('A date in the table could not be read (%(what)s).') % {'what': what})


def _segments(lines):
    """Parts of the table: [(brought-forward index, carried-forward index)]. They must alternate."""
    marks = [(i, 'B' if BROUGHT.match(l) else 'C') for i, (_p, l) in enumerate(lines) if BROUGHT.match(l) or CARRIED.match(l)]
    if not marks or len(marks) % 2 or any(kind != ('B', 'C')[n % 2] for n, (_i, kind) in enumerate(marks)):
        raise UnsupportedStatement(gettext('The balance brought forward and balance carried forward rows do not pair up.'))
    return [(marks[n][0], marks[n + 1][0]) for n in range(0, len(marks), 2)]


def _entries(lines, start, end):
    """Rows between two marker lines: [(page, first line, joined text)]. Lines that belong to no row are page furniture
    (repeated headings, address blocks); a row that was skipped here breaks the running balance and is caught there."""
    entries, i = [], start + 1
    while i < end:
        page, line = lines[i]
        m = DATE_START.match(line)
        if not m or m.group(2).upper() not in MONTHS:
            i += 1
            continue
        parts, j = [line[m.end():]], i
        date_text = f'{m.group(1)} {m.group(2)} {m.group(3)}'
        while not TAIL.match(' '.join(parts)):
            j += 1
            if j >= end or len(parts) >= 4 or DATE_START.match(lines[j][1]):
                raise UnsupportedStatement(gettext('A row of the table could not be read (row %(n)s).') % {'n': len(entries) + 1})
            parts.append(lines[j][1])
        entries.append((page, date_text, ' '.join(parts), [lines[k] for k in range(i, j + 1)]))
        i = j + 1
    return entries


def _summary(lines, label):
    found = [m.group(1) for _p, l in lines if (m := re.fullmatch(label + r'\s*£\s*(' + AMT + ')', l))]
    return parse_amount_uk(found[0]) if len(found) == 1 else None


def parse(pages: list[str]) -> sr.StatementResult:
    lines = _lines(pages)
    segments = _segments(lines)
    opening = parse_amount_uk(BROUGHT.match(lines[segments[0][0]][1]).group(2))
    closing = parse_amount_uk(CARRIED.match(lines[segments[-1][1]][1]).group(2))
    balance = opening
    rows, paid_in, paid_out, number = [], Decimal(0), Decimal(0), 0
    start_date = end_date = None
    for index, (b, c) in enumerate(segments):
        brought = BROUGHT.match(lines[b][1])
        if parse_amount_uk(brought.group(2)) != balance:
            raise UnsupportedStatement(gettext('The balance brought forward does not continue from the previous part of the table.'))
        if brought.group(1) and start_date is None:
            start_date = _date(brought.group(1), 'brought forward')
        for page, date_text, text, source in _entries(lines, b, c):
            number += 1
            m = TAIL.match(text)
            description, amount, new_balance = m.group(1), parse_amount_uk(m.group(2)), parse_amount_uk(m.group(3))
            interest = INTEREST.match(description)
            if interest:
                if balance + amount != new_balance:
                    raise UnsupportedStatement(gettext('The running balance does not add up at row %(n)s of the table.') % {'n': number})
                paid_in += amount
                if interest.group(2) not in MONTHS:
                    raise UnsupportedStatement(gettext('The "TO" date of the interest credit at row %(n)s could not be read.') % {'n': number})
                try:
                    period_end = datetime.date(int(interest.group(3)), MONTHS[interest.group(2)], int(interest.group(1)))
                except ValueError:
                    raise UnsupportedStatement(gettext('The "TO" date of the interest credit at row %(n)s could not be read.') % {'n': number})
                evidence = (page, ' / '.join(l for _p, l in source))
                data = {c_: '' for c_ in COLUMNS}
                data.update(payment_date=_date(date_text, f'row {number}').isoformat(), organisation=BANK_ORGANISATIONS[READER_ID],
                            category='Interest', currency='GBP', gross_amount=format(amount, 'f'), net_amount=format(amount, 'f'),
                            withholding_tax='0', expenses='0', frequency='monthly', income_period_end=period_end.isoformat(),
                            comment=gettext('Gross interest (PDF import).'))
                rows.append(sr.StatementRow(data, {'payment_date': evidence, 'gross_amount': evidence, 'income_period_end': evidence}))
            elif 'INTERNET TRANSFER' in description:
                if balance + amount == new_balance:
                    paid_in += amount
                elif balance - amount == new_balance:
                    paid_out += amount
                else:
                    raise UnsupportedStatement(gettext('The running balance does not add up at row %(n)s of the table.') % {'n': number})
            else:
                kind = re.sub(r'\s+', ' ', mask_digit_runs(re.sub(r'\d', '', description))).strip()[:40]
                raise UnsupportedStatement(gettext('Row %(n)s of the table is a type this importer does not read ("%(kind)s"), so nothing was staged.')
                                           % {'n': number, 'kind': kind})
            balance = new_balance
        carried = CARRIED.match(lines[c][1])
        if parse_amount_uk(carried.group(2)) != balance:
            raise UnsupportedStatement(gettext('The balance carried forward does not match the running balance.'))
        if index == len(segments) - 1 and carried.group(1):
            end_date = _date(carried.group(1), 'carried forward')

    # Optional second check: the summary block, used only where each of its four figures is readable.
    for label, value in (('Opening Balance', opening), ('Closing Balance', closing), ('Payments In', paid_in), ('Payments Out', paid_out)):
        shown = _summary(lines, label)
        if shown is not None and shown != value:
            raise UnsupportedStatement(gettext('The summary block does not agree with the table (%(label)s).') % {'label': label})

    sheet = account = None
    for _p, line in lines:
        m = SHEET.search(line)
        if m:
            account, sheet = m.group(1), int(m.group(2))
            break
    period = (start_date, end_date) if start_date and end_date else None
    notices = []
    fingerprint = sr.short_hash(READER_ID, sheet, closing, end_date) if end_date else sr.short_hash(READER_ID, sheet, closing, number)
    continuity = sr.Continuity(series=sr.short_hash(account) if account else '', sequence=sheet, opening=opening, closing=closing,
                               start=start_date, end=end_date) if account else None
    return sr.StatementResult(rows=rows, notices=notices, fingerprint=fingerprint, period=period, continuity=continuity)
