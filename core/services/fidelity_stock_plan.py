"""Fidelity Stock Plan Services reports (USD): dividends and the tax withheld on them (Phase 19, ADR 0019).

Read in layout mode. One payment per "Dividend Received" line of the "Dividends, Interest & Other Income" table.
Tax is in a separate "Taxes Withheld" table ("Non-Resident Tax" negative, "Adj Non-Resident Tax" positive, a reversal),
and a posting can be booked in a later statement than the dividend (or carry a date of the previous month or year). The
withholding that finally applies to an event is therefore the sum of ALL its postings across the statements of the
upload (settle()); a posting for an event outside the upload is counted in a warning, and a row that a statement outside
the upload could still revise is marked in its comment.

Refused (nothing staged): any income description other than "Dividend Received", any tax description other than the two
above, a total that does not reconcile (income lines against "Total Dividends, Interest & Other Income" and the income
summary; tax lines against "Total Federal Taxes Withheld" by absolute value, because that total changes sign), or a tax
posting that matches two different events. Stock deliveries, sales and journals are listed as notices (date only), never
imported. Core-fund cash movements are never income.
"""
import datetime
import re
from decimal import Decimal

from django.utils.translation import gettext, ngettext

from . import statement_types as st
from .amounts import parse_amount_us, squeeze_spaces
from .dividend_statements import UnsupportedStatement
from .imports import COLUMNS
from .organisations import tidy_security_name

READER_ID = 'fidelity_stock_plan'
AMOUNT = r'-?\$?-?[\d,]+\.\d{2}'
MONTHS = {m: i for i, m in enumerate(['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september',
                                      'october', 'november', 'december'], 1)}
PERIOD = re.compile(r'^([A-Za-z]+) (\d{1,2}), (\d{4}) - ([A-Za-z]+) (\d{1,2}), (\d{4})$')
DATE = re.compile(r'^(\d{2})/(\d{2}) ')
TAX_TYPES = {'Non-Resident Tax': -1, 'Adj Non-Resident Tax': 1}
REVISE_NOTE = 'Withholding may be revised by a later statement.'


def _lines(pages):
    return [(n, squeeze_spaces(l)) for n, page in enumerate(pages, start=1) for l in page.splitlines() if l.strip()]


def recognises(pages) -> bool:
    lines = _lines(pages)
    text = '\n'.join(l for _p, l in lines)
    return ('STOCK PLAN SERVICES REPORT' in text and any(PERIOD.match(l) for _p, l in lines)
            and any(l.startswith('Account Summary') for _p, l in lines))


def _period(lines):
    for _p, l in lines:
        m = PERIOD.match(l)
        if m and m.group(1).lower() in MONTHS and m.group(4).lower() in MONTHS:
            try:
                start = datetime.date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
                end = datetime.date(int(m.group(6)), MONTHS[m.group(4).lower()], int(m.group(5)))
            except ValueError:
                break
            if end >= start and (end - start).days <= 62:
                return start, end
            break
    raise UnsupportedStatement(gettext('The statement period could not be read.'))


def _amount(text):
    try:
        return parse_amount_us(text)
    except ValueError:
        raise UnsupportedStatement(gettext('An amount in a table could not be read.'))


def _caps(token):
    """Security names are printed in capitals; descriptions are in ordinary case."""
    return not re.search(r'[a-z]', token)


def _section(lines, start, stop):
    """Index of the first line matching `start` and of the next line matching `stop` after it (None, None if no heading)."""
    a = next((i for i, (_p, l) in enumerate(lines) if start(l)), None)
    if a is None:
        return None, None
    b = next((i for i in range(a + 1, len(lines)) if stop(lines[i][1])), None)
    if b is None:
        raise UnsupportedStatement(gettext('A table of the statement has no total line.'))
    return a, b


def _event_date(month, day, period):
    start, end = period
    for year in sorted({start.year, end.year}):
        try:
            d = datetime.date(year, int(month), int(day))
        except ValueError:
            continue
        if start <= d <= end:
            return d
    raise UnsupportedStatement(gettext('A date in the income table is outside the statement period.'))


def _posting_date(month, day, period):
    """A tax posting carries the date of its event, which can be in an earlier month or the previous year."""
    end = period[1]
    try:
        d = datetime.date(end.year, int(month), int(day))
    except ValueError:
        raise UnsupportedStatement(gettext('A date in the tax table could not be read.'))
    return d if d <= end else d.replace(year=end.year - 1)


def _rows(lines, a, b):
    """Rows between two lines: dicts with page, line, date parts, leading capitals tokens (the name), the other tokens,
    whether a flag letter precedes the date, and the wrapped continuation of the name (F1) appended to the name."""
    rows = []
    for i in range(a + 1, b):
        page, line = lines[i]
        tokens = line.split(' ')
        flagged = False
        if len(tokens) > 1 and re.fullmatch(r'[A-Za-z]', tokens[0]) and DATE.match(' '.join(tokens[1:]) + ' '):
            flagged, tokens = True, tokens[1:]
        m = DATE.match(' '.join(tokens) + ' ')
        if m:
            rest = tokens[1:]
            name = []
            while rest and _caps(rest[0]):
                name.append(rest.pop(0))
            rows.append({'page': page, 'line': line, 'month': m.group(1), 'day': m.group(2), 'name': name, 'first_name': list(name),
                         'rest': rest, 'flagged': flagged, 'continuation': []})
        elif rows and tokens and all(_caps(t) for t in tokens) and not re.search(r'\$|\d{2}/\d{2}', line):
            rows[-1]['name'] += tokens
            rows[-1]['continuation'].append(line)
    return rows


def _norm(tokens):
    return tuple(t for t in (re.sub(r'[^A-Z0-9]', '', x.upper()) for x in tokens) if t)


def _compatible(a, b):
    """Two normalised security names are the same security when one starts with the other (the tax table can print a
    longer form of a wrapped fund name)."""
    return bool(a) and bool(b) and (a[:len(b)] == b or b[:len(a)] == a)


def parse(pages: list[str]) -> st.StatementResult:
    lines = _lines(pages)
    period = _period(lines)
    notices = []

    # --- income table
    events = []
    a, b = _section(lines, lambda l: l == 'Dividends, Interest & Other Income', lambda l: l.startswith('Total Dividends, Interest & Other Income'))
    if a is not None:
        for r in _rows(lines, a, b):
            rest = r['rest']
            if len(rest) < 4 or not re.fullmatch(AMOUNT, rest[-1]) or not re.fullmatch(r'-|[\d,.]+', rest[-2]) or not re.fullmatch(r'-|\$?[\d,.]+', rest[-3]):
                raise UnsupportedStatement(gettext('A row of the income table could not be read.'))
            description = ' '.join(rest[:-3])
            if description != 'Dividend Received':
                raise UnsupportedStatement(gettext('The income table has a description this importer does not read ("%(kind)s"), so nothing was staged.')
                                           % {'kind': re.sub(r'\d', '', description)[:40]})
            # the first line holds "<name> <code>": the code (CUSIP or ticker) is its last capitals token; the wrapped
            # remainder of the name follows on the next line
            if len(r['first_name']) < 2:
                raise UnsupportedStatement(gettext('The security name of an income row could not be read.'))
            name = r['first_name'][:-1] + r['name'][len(r['first_name']):]
            r.update(name=name, amount=_amount(rest[-1]), date=_event_date(r['month'], r['day'], period))
            events.append(r)
    income_total = sum((e['amount'] for e in events), Decimal(0))
    if a is not None:
        shown = re.search(r'(' + AMOUNT + r')$', lines[b][1])
        if not shown or _amount(shown.group(1)) != income_total:
            raise UnsupportedStatement(gettext('The income lines do not add up to the total of the income table.'))
    summary_total = None
    for i, (_p, l) in enumerate(lines):
        if l.endswith('Income Summary'):
            summary_total = next((_amount(m.group(1)) for _q, x in lines[i:i + 12] if (m := re.match(r'^Total (' + AMOUNT + r')(?: |$)', x))), None)
            break
    if summary_total is not None and summary_total != income_total:
        raise UnsupportedStatement(gettext('The income summary does not agree with the income lines.'))
    if summary_total is None:
        notices.append(gettext('The income summary was not found; that check was skipped.'))

    # --- tax table
    postings = []
    a, b = _section(lines, lambda l: l == 'Taxes Withheld', lambda l: l.startswith('Total Taxes Withheld'))
    if a is not None:
        for r in _rows(lines, a, b):
            rest = r['rest']
            if not rest or not re.fullmatch(AMOUNT, rest[-1]):
                raise UnsupportedStatement(gettext('A row of the tax table could not be read.'))
            description = ' '.join(rest[:-1])
            if description not in TAX_TYPES:
                raise UnsupportedStatement(gettext('The tax table has a description this importer does not read ("%(kind)s"), so nothing was staged.')
                                           % {'kind': re.sub(r'\d', '', description)[:40]})
            amount = _amount(rest[-1])
            if amount * TAX_TYPES[description] < 0:
                raise UnsupportedStatement(gettext('A tax posting has an unexpected sign.'))
            postings.append(st.Posting(name=_norm(r['name']), date=_posting_date(r['month'], r['day'], period), amount=amount,
                                       page=r['page'], line=' / '.join([r['line'], *r['continuation']]), flagged=r['flagged']))
        total_lines = [l for _p, l in lines[a:b + 1] if l.startswith('Total Federal Taxes Withheld')]
        lines_total = sum((p.amount for p in postings), Decimal(0))
        if total_lines:
            printed = _amount(total_lines[0].split(' ')[-1])
            if abs(printed) != abs(lines_total):               # F4: the printed total changes sign; compare absolute values
                raise UnsupportedStatement(gettext('The tax lines do not add up to the printed total of federal taxes withheld.'))
        elif postings:
            notices.append(gettext('The total of federal taxes withheld was not found; that check was skipped.'))

    # --- core fund activity: a security named in the core fund activity table is a core fund (cash movements are never income, F6/F10)
    core_names = []
    a, b = _section(lines, lambda l: l.startswith('Core Fund Activity'), lambda l: l.startswith('Total Core Fund Activity'))
    if a is not None:
        for _p, line in lines[a + 1:b]:
            m = re.match(r'^\d{2}/\d{2} [A-Z]+ (?:Reinvestment|You Bought|You Sold|Transferred)(.*)$', line)
            if m:
                core_names.append(_norm(t for t in m.group(1).split(' ') if _caps(t) and not re.fullmatch(r'[-\d,.$@]+', t)))

    # --- sales, deliveries and journals: recognised, listed, never imported (F7)
    for heading in ('Securities Bought & Sold', 'Other Activity In', 'Other Activity Out'):
        a = next((i for i, (_p, l) in enumerate(lines) if l == heading), None)
        if a is None:
            continue
        b = next((i for i in range(a + 1, len(lines)) if lines[i][1].startswith(('Total ', 'Net '))), len(lines))
        for _p, line in lines[a + 1:b]:
            m = DATE.match(line + ' ')
            if m:
                what = (gettext('shares bought (a delivery or purchase)') if 'You Bought' in line else gettext('shares sold') if 'You Sold' in line
                        else gettext('other activity (a journal)'))
                notices.append(gettext('Not imported: %(what)s on %(date)s.') % {'what': what, 'date': f'{m.group(1)}/{m.group(2)}'})

    # --- rows
    ending = next((m.group(1) for _p, l in lines if (m := re.match(r'^Ending Account Value .*?(\$[\d,]+\.\d{2})$', l))), '')
    rows = []
    for e in events:
        key = _norm(e['name'])
        is_fund = any(_compatible(c, key) for c in core_names)
        attached = [p for p in postings if p.date == e['date'] and _compatible(p.name, key)]
        withholding = max(Decimal(0) - sum((p.amount for p in attached), Decimal(0)), Decimal(0))
        comment = (gettext('Fund dividend') if is_fund else gettext('Dividend')) + ' ' + gettext('via Fidelity.')
        data = {c: '' for c in COLUMNS}
        data.update(payment_date=e['date'].isoformat(), organisation=tidy_security_name(' '.join(e['name'])), category='Dividends', currency='USD',
                    gross_amount=format(e['amount'], 'f'), net_amount=format(e['amount'] - withholding, 'f'),
                    withholding_tax=format(withholding, 'f'), expenses='0', frequency='monthly' if is_fund else 'quarterly', comment=comment)
        evidence = (e['page'], ' / '.join([e['line'], *e['continuation']]))
        rows.append(st.StatementRow(data, {'payment_date': evidence, 'organisation': evidence, 'gross_amount': evidence},
                                    extra={'name': key, 'date': e['date'], 'base_comment': comment}))
    return st.StatementResult(rows=rows, notices=notices, fingerprint=st.short_hash(READER_ID, period[0], period[1], ending), period=period,
                              postings=postings)


def settle(items):
    """items: [(label, StatementResult)] of ALL the Fidelity statements of one upload (also those without rows). Sets each
    row's withholding to the sum of every posting for its event, across statements, and returns the batch warnings."""
    events = [(label, result, row) for label, result in items for row in result.rows]
    attached = {id(row): [] for _l, _r, row in events}
    unmatched = 0
    for label, result in items:
        for p in result.postings:
            matches = [row for _l, _r, row in events if row.extra['date'] == p.date and _compatible(p.name, row.extra['name'])]
            if not matches:
                unmatched += 1
            elif len(matches) > 1:
                raise UnsupportedStatement(gettext('A tax posting matches more than one dividend, so the withholding cannot be settled.'))
            else:
                attached[id(matches[0])].append((label, p))
    warnings = []
    if unmatched:
        warnings.append(gettext('Tax postings for events not in this upload: %(n)s (not staged).') % {'n': unmatched})
    latest = max((r.period[1] for _l, r, _row in events if r.period), default=None)
    negative = 0
    for _label, result, row in events:
        posted = attached[id(row)]
        net_tax = Decimal(0) - sum((p.amount for _l, p in posted), Decimal(0))
        comment, withholding = row.extra['base_comment'], net_tax
        if net_tax < 0:
            negative += 1
            withholding = Decimal(0)
            comment += ' ' + gettext('The postings for this dividend are a net refund; withholding is recorded as 0.')
        if len(posted) > 1:
            comment += ' ' + gettext('Withholding is the sum of %(n)s postings (%(reversals)s reversal(s)).') % {
                'n': len(posted), 'reversals': sum(1 for _l, p in posted if p.amount > 0)}
        if latest and result.period and result.period[1] >= latest:
            comment += ' ' + gettext('Withholding may be revised by a later statement.')
        gross = Decimal(row.data['gross_amount'])
        row.data.update(withholding_tax=format(withholding, 'f'), net_amount=format(gross - withholding, 'f'), comment=comment)
        if posted:
            row.provenance['withholding_tax'] = (posted[0][1].page, ' / '.join(f'{lbl}: {p.line}' for lbl, p in posted))
        else:
            row.provenance.pop('withholding_tax', None)
    if negative:
        warnings.append(ngettext('%(n)s dividend has a net tax refund; its withholding is recorded as 0.',
                                 '%(n)s dividends have a net tax refund; their withholding is recorded as 0.', negative) % {'n': negative})
    return warnings
