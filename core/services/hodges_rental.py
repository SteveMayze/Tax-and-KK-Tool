"""Rental statements of a managing agent ("Tax Invoice" with Money In, Money Out and You Received), AUD (Phase 21, ADR 0021).

Recognised by structure only (a Tax Invoice with "Statement #", Money In, Money Out and You Received); the agency name,
address and logo text are never used. One row per statement:

* gross = the rent received (the amounts of the rent entries, "Rent paid to <date> ..." with their Money In amount);
* expenses = every cost line listed before "Total" (management fee, repairs, rates ...) plus the sundry fees printed after it;
* withholding 0; net = gross - expenses, which must equal "You Received";
* payment date = the statement date; income period = the day after "previously paid to" up to "paid to".

The statement must close (G9): In - Out = Received; the cost lines add up to the "Total" line; costs + sundry fees = Money Out;
the rent amounts = Money In. The printed "Total" excludes the sundry fee (A5), so it is only one of these checks, never the
only one. The owner withdrawal (a payout of money already received) is never an expense or income: it is noted and not
staged. A money-in entry that is not rent (arrears, advance, bond ...) and any unrecognised line after "Total" refuses the
statement naming the label. Lines flagged * include GST: they are counted in the comment, with no GST split. The
organisation comes from the setting RENTAL_ORGANISATION, never from code.
"""
import datetime
import re
from decimal import Decimal

from django.conf import settings
from django.utils.translation import gettext

from . import statement_types as st
from .amounts import parse_amount_us, squeeze_spaces
from .dividend_statements import UnsupportedStatement
from .imports import COLUMNS

READER_ID = 'hodges_rental'
AMT = r'\$([\d,]+\.\d{2})'
NOT_RENT = re.compile(r'(?i)\b(arrears|paid in advance|advance rent|rent in advance|prepaid)\b')
MONTHS = {m: i for i, m in enumerate(['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'], 1)}
ENTRY_START = re.compile(r'^\d{1,2}/\d{2} ')
STATEMENT_DATE = re.compile(r'^(\d{1,2}) ([A-Za-z]{3}) (\d{4})$')


def _lines(pages):
    return [(n, squeeze_spaces(l)) for n, page in enumerate(pages, start=1) for l in page.splitlines() if l.strip()]


def _single(lines, label):
    found = [m.group(1) for _p, l in lines if (m := re.match(r'^' + label + r' ' + AMT + r'$', l))]
    if len(found) != 1:
        raise UnsupportedStatement(gettext('The "%(label)s" figure could not be found exactly once.') % {'label': label})
    return parse_amount_us(found[0])


def recognises(pages) -> bool:
    lines = _lines(pages)
    text = {l for _p, l in lines}
    return ('Tax Invoice' in text and any(re.match(r'^Statement #\d+$', l) for l in text)
            and all(any(re.match('^' + label + ' ' + AMT + '$', l) for l in text) for label in ('Money In', 'Money Out', 'You Received')))


def _words(text):
    return re.sub(r'\s+', ' ', re.sub(r'[\d$*]', '', text)).strip()[:30]


def _date(text):
    d, m, y = text.split('/')
    try:
        return datetime.date(int(y), int(m), int(d))
    except ValueError:
        raise UnsupportedStatement(gettext('A date in the statement could not be read.'))


def parse(pages: list[str]) -> st.StatementResult:
    organisation = (settings.RENTAL_ORGANISATION or '').strip()
    if not organisation:
        raise UnsupportedStatement(gettext('The organisation for the rental is not set (setting DJANGO_RENTAL_ORGANISATION).'))
    lines = _lines(pages)
    money_in, money_out, received = _single(lines, 'Money In'), _single(lines, 'Money Out'), _single(lines, 'You Received')
    number = next((m.group(1) for _p, l in lines if (m := re.match(r'^Statement #(\d+)$', l))), None)
    index = next(i for i, (_p, l) in enumerate(lines) if re.match(r'^Statement #\d+$', l))
    statement_date = next((STATEMENT_DATE.match(l) for _p, l in lines[index:index + 5] if STATEMENT_DATE.match(l)), None)
    if not statement_date or statement_date.group(2).lower() not in MONTHS:
        raise UnsupportedStatement(gettext('The statement date could not be found.'))
    payment_date = datetime.date(int(statement_date.group(3)), MONTHS[statement_date.group(2).lower()], int(statement_date.group(1)))
    if money_in - money_out != received:
        raise UnsupportedStatement(gettext('Money In minus Money Out does not equal You Received.'))

    balances = [i for i, (_p, l) in enumerate(lines) if re.match(r'^Balance .*' + AMT + r'$', l)]
    totals = [i for i, (_p, l) in enumerate(lines) if re.match(r'^Total ' + AMT + ' ' + AMT + r'$', l)]
    if not balances or len(totals) != 1 or totals[0] < balances[0]:
        raise UnsupportedStatement(gettext('The money in/out table could not be found (balance and total lines).'))
    total_row = re.match(r'^Total ' + AMT + ' ' + AMT + r'$', lines[totals[0]][1])
    total_costs, total_in = parse_amount_us(total_row.group(1)), parse_amount_us(total_row.group(2))

    # --- rent entries and cost lines between the opening balance and "Total"
    rent, costs, starred, evidence, current, more = [], [], 0, [], None, False
    for page, line in lines[balances[0] + 1:totals[0]]:
        if current is None and more and line.startswith('Rent paid to'):          # a second receipt in the same entry (A6)
            current = {'page': page, 'lines': []}
        elif current is None and not costs and not rent and ENTRY_START.match(line):
            current = {'page': page, 'lines': [line]}
            continue
        more = False
        if current is not None:
            current['lines'].append(line)
            # the amount of a receipt is alone on its last line, or ends the line that closes "(previously paid to ... + $x)"
            m = re.match(r'^' + AMT + r'$', line) or (re.search(r'previously paid to', ' '.join(current['lines']))
                                                      and re.search(r'\)\s*' + AMT + r'$', line))
            if m:
                text = ' '.join(current['lines'])
                if 'Rent paid to' not in text:
                    raise UnsupportedStatement(gettext('A money-in entry is not rent ("%(kind)s"), so nothing was staged.')
                                               % {'kind': _words(' '.join(current['lines'][1:3]))})
                rent.append((parse_amount_us(m.group(1)), text, current['page'], current['lines']))
                current, more = None, True
            continue
        if NOT_RENT.search(line):
            raise UnsupportedStatement(gettext('The statement has a line this importer does not read ("%(kind)s"), so nothing was staged.')
                                       % {'kind': _words(line)})
        if (m := re.search(AMT + r'$', line)):
            costs.append(parse_amount_us(m.group(1)))
            starred += 1 if '*' in line else 0
            evidence.append((page, line))
    if current is not None or not rent:
        raise UnsupportedStatement(gettext('The rent entry of the statement could not be read.'))

    # --- after "Total": sundry fees, the owner withdrawal, the balance and the GST summary
    sundry, withdrawals, extra_starred = [], 0, 0
    for page, line in lines[totals[0] + 1:]:
        if NOT_RENT.search(line):
            raise UnsupportedStatement(gettext('The statement has a line this importer does not read ("%(kind)s"), so nothing was staged.')
                                       % {'kind': _words(line)})
        if re.match(r'^Sundry fee\b.*' + AMT + r'$', line):
            sundry.append(parse_amount_us(re.search(AMT + r'$', line).group(1)))
            extra_starred += 1 if '*' in line else 0
            evidence.append((page, line))
        elif re.match(r'^Withdrawal\b.*' + AMT + r'$', line):
            withdrawals += 1
        elif re.match(r'^(Balance|Total Tax)\b.*' + AMT + r'$', line):
            continue
        elif re.search(AMT + r'$', line):
            raise UnsupportedStatement(gettext('The statement has a line this importer does not read ("%(kind)s"), so nothing was staged.')
                                       % {'kind': _words(line)})

    rent_total = sum((r[0] for r in rent), Decimal(0))
    expenses = sum(costs, Decimal(0)) + sum(sundry, Decimal(0))
    if rent_total != money_in or total_in != money_in:
        raise UnsupportedStatement(gettext('The rent entries do not add up to Money In.'))
    if sum(costs, Decimal(0)) != total_costs:
        raise UnsupportedStatement(gettext('The cost lines do not add up to the Total line.'))
    if expenses != money_out:
        raise UnsupportedStatement(gettext('The cost lines and sundry fees do not add up to Money Out.'))

    texts = ' '.join(r[1] for r in rent)
    paid_to = [_date(m.group(1)) for m in re.finditer(r'Rent paid to (\d{2}/\d{2}/\d{4})', texts)]
    before = [_date(m.group(1)) for m in re.finditer(r'previously paid to (\d{2}/\d{2}/\d{4})', texts)]
    if not paid_to:
        raise UnsupportedStatement(gettext('The "paid to" date of the rent could not be read.'))
    period_end = max(paid_to)
    period_start = min(before) + datetime.timedelta(days=1) if before else None
    if period_start and period_start > period_end:
        raise UnsupportedStatement(gettext('The rent period is not in order.'))

    comment = gettext('Rental statement (PDF import).')
    flagged = starred + extra_starred
    if flagged:
        comment += ' ' + gettext('%(n)s cost line(s) flagged * include GST (no GST split recorded).') % {'n': flagged}
    data = {c: '' for c in COLUMNS}
    data.update(payment_date=payment_date.isoformat(), organisation=organisation, category='Rental', currency='AUD',
                gross_amount=format(money_in, 'f'), net_amount=format(money_in - expenses, 'f'), withholding_tax='0',
                expenses=format(expenses, 'f'), frequency='monthly',
                income_period_start=period_start.isoformat() if period_start else '', income_period_end=period_end.isoformat(), comment=comment)
    rent_evidence = (rent[0][2], ' / '.join(rent[0][3]))
    provenance = {'payment_date': (1, lines[index][1]), 'gross_amount': rent_evidence, 'income_period_end': rent_evidence,
                  'net_amount': (1, f'You Received {format(received, ",.2f")}')}
    if period_start:
        provenance['income_period_start'] = rent_evidence
    if evidence:
        provenance['expenses'] = (evidence[0][0], ' / '.join(l for _p, l in evidence))
    notices = []
    if withdrawals:
        notices.append(gettext('Owner withdrawal not imported (%(n)s, statement dated %(date)s).') % {'n': withdrawals, 'date': payment_date.isoformat()})
    return st.StatementResult(rows=[st.StatementRow(data, provenance)], notices=notices,
                              fingerprint=st.short_hash(READER_ID, number, period_end, received), period=(period_start or payment_date, period_end))
