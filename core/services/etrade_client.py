"""E*TRADE client statements (Morgan Stanley stock-plan account, USD): dividends and the tax withheld on them
(Phase 18, ADR 0018).

Read in layout mode. Recognised by structure: "CLIENT STATEMENT", "For the Period ...", the "CASH FLOW ACTIVITY BY DATE"
table and the "INCOME AND DISTRIBUTION SUMMARY". The period (one or two calendar months, possibly across a year end)
supplies the year of the "m/d" dates.

* An income event is a "Dividend" (money-market fund, monthly) or "Qualified Dividend" (company stock, quarterly) line.
  A "Tax Withholding" line with the same date and the same description belongs to it (one payment: gross, withholding,
  net). A withholding line without an event, two for one event, a company-stock dividend without a withholding line, or
  any other activity type refuses the statement naming the type.
* Reconciliation, each a refusal when it fails: the lines add up to "NET CREDITS/(DEBITS)"; the sweep table (automatic
  investments of the cash into the fund) adds up to the same net; the income summary's period totals by class equal the
  sums of the lines by class; the account summary's tax withholdings equal the sum of the withholding lines.
* A fund dividend that the statement marks "Transaction Reportable for the Prior Year" is received in the new year but
  reported for the previous one; it is recorded with its printed date and the remark in the comment, and the statement's
  own period totals leave it out, so the reconciliation does too.
* Nothing after the "MESSAGES" heading is ever read (it can contain sensitive text); nothing of it is kept or logged.
"""
import datetime
import re
from decimal import Decimal

from django.utils.translation import gettext

from . import statement_types as st
from .amounts import parse_amount_us, squeeze_spaces
from .dividend_statements import UnsupportedStatement
from .imports import COLUMNS
from .organisations import ETRADE, broker_category, broker_organisation, tidy_security_name

READER_ID = 'etrade_client'
AMT = r'\(?\$?\d[\d,]*\.\d{2}\)?|—'
TAIL = re.compile(r'^(.*?)\s*(' + AMT + r')$')
ROW = re.compile(r'^(\d{1,2})/(\d{1,2})(?: \d{1,2}/\d{1,2})? (.*)$')
PERIOD = re.compile(r'For the Period ([A-Za-z]+) (\d{1,2})\s*-\s*(?:([A-Za-z]+) )?(\d{1,2}), (\d{4})')
MONTHS = {m: i for i, m in enumerate(['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september',
                                      'october', 'november', 'december'], 1)}
PRIOR_YEAR = re.compile(r'\s*Transaction Reportable for the Prior Year\.?', re.I)
TYPES = ('Qualified Dividend', 'Dividend', 'Tax Withholding')
NOT_IMPORTED = ('Bought', 'Sold', 'Journal')


def _lines(pages):
    out = []
    for number, page in enumerate(pages, start=1):
        for line in page.splitlines():
            line = squeeze_spaces(line)
            if line:
                out.append((number, line))
    cut = next((i for i, (_p, l) in enumerate(out) if l == 'MESSAGES'), len(out))        # E8: nothing after this is read
    return out[:cut]


def recognises(pages) -> bool:
    text = re.sub(r'[ \t]+', ' ', '\n'.join(pages))
    return all(k in text for k in ('CLIENT STATEMENT', 'For the Period', 'CASH FLOW ACTIVITY BY DATE', 'INCOME AND DISTRIBUTION SUMMARY'))


def _period(lines):
    for _p, line in lines:
        m = PERIOD.search(line)
        if m:
            start_month = MONTHS.get(m.group(1).lower())
            end_month = MONTHS.get((m.group(3) or m.group(1)).lower())
            if not start_month or not end_month:
                break
            end_year = int(m.group(5))
            start_year = end_year - 1 if start_month > end_month else end_year
            try:
                start = datetime.date(start_year, start_month, int(m.group(2)))
                end = datetime.date(end_year, end_month, int(m.group(4)))
            except ValueError:
                break
            if end < start or (end - start).days > 62:
                break
            return start, end
    raise UnsupportedStatement(gettext('The statement period could not be read.'))


def _date(month, day, period):
    start, end = period
    for year in {start.year, end.year}:
        try:
            d = datetime.date(year, int(month), int(day))
        except ValueError:
            continue
        if start <= d <= end:
            return d
    raise UnsupportedStatement(gettext('A date in the activity table is outside the statement period.'))


def _amount(text):
    try:
        return parse_amount_us(text)
    except ValueError:
        raise UnsupportedStatement(gettext('An amount in the activity table could not be read.'))


def _section(lines, start_pred, end_pred, what):
    start = next((i for i, (_p, l) in enumerate(lines) if start_pred(l)), None)
    if start is None:
        raise UnsupportedStatement(gettext('The %(what)s could not be found.') % {'what': what})
    end = next((i for i in range(start + 1, len(lines)) if end_pred(lines[i][1])), None)
    return start, end


def _summary_value(lines, label):
    """This-period value of a row of the income and distribution summary ("Qualified Dividends $a $b ..."); None if absent."""
    found = [m for _p, l in lines if (m := re.match(r'^' + re.escape(label) + r' (' + AMT + r')(?=\s|$)', l))]
    if len(found) > 1:
        raise UnsupportedStatement(gettext('A row of the income summary appears more than once.'))
    return _amount(found[0].group(1)) if found else None


def parse(pages: list[str]) -> st.StatementResult:
    lines = _lines(pages)
    period = _period(lines)
    a, b = _section(lines, lambda l: l == 'CASH FLOW ACTIVITY BY DATE', lambda l: l.startswith('NET ') and 'CREDITS' in l.upper(),
                    gettext('cash flow activity table'))
    rows, net_line = [], None
    stop = b if b is not None else len(lines)
    for i in range(a + 1, stop):
        page, line = lines[i]
        m = ROW.match(line)
        if not m:
            continue
        t = TAIL.match(m.group(3))
        if not t:
            raise UnsupportedStatement(gettext('A row of the activity table has no amount.'))
        kind = next((k for k in TYPES if t.group(1).startswith(k)), None)
        if kind is None:
            words = ' '.join(re.sub(r'\d', '', t.group(1)).split()[:2])
            other = next((n for n in NOT_IMPORTED if words.startswith(n)), None)
            if other:
                rows.append({'kind': 'other', 'type': other, 'date': _date(m.group(1), m.group(2), period), 'amount': _amount(t.group(2)),
                             'page': page, 'line': line})
                continue
            raise UnsupportedStatement(gettext('The activity table has a type this importer does not read ("%(kind)s"), so nothing was staged.')
                                       % {'kind': words[:30]})
        description = PRIOR_YEAR.sub('', t.group(1)[len(kind):]).strip()
        rows.append({'kind': kind, 'date': _date(m.group(1), m.group(2), period), 'description': description, 'amount': _amount(t.group(2)),
                     'prior': bool(PRIOR_YEAR.search(t.group(1))), 'page': page, 'line': line})
    total = sum((r['amount'] for r in rows), Decimal(0))
    if b is None:
        if rows:
            raise UnsupportedStatement(gettext('The net credits/(debits) line of the activity table could not be found.'))
        net = Decimal(0)
    else:
        nm = TAIL.match(lines[b][1])
        if not nm:
            raise UnsupportedStatement(gettext('The net credits/(debits) line could not be read.'))
        net = _amount(nm.group(2))
    if total != net:
        raise UnsupportedStatement(gettext('The activity lines do not add up to the net credits/(debits).'))

    notices = []
    sweep = next((i for i, (_p, l) in enumerate(lines) if l.startswith('MONEY MARKET FUND')), None)
    if sweep is None:
        notices.append(gettext('No sweep table in this statement; the sweep check was skipped.'))
    else:
        end = next((i for i in range(sweep + 1, len(lines)) if lines[i][1].startswith('NET ACTIVITY')), None)
        swept = Decimal(0)
        for _p, line in lines[sweep + 1:end if end is not None else len(lines)]:
            m = ROW.match(line)
            if m and m.group(3).startswith('Automatic Investment'):
                t = TAIL.match(m.group(3))
                swept += _amount(t.group(2)) if t else Decimal(0)
        if swept != net:
            raise UnsupportedStatement(gettext('The automatic investments of the sweep table do not add up to the net credits.'))

    events = [r for r in rows if r['kind'] in ('Dividend', 'Qualified Dividend')]
    withholdings = [r for r in rows if r['kind'] == 'Tax Withholding']
    payments, used = [], set()
    for event in events:
        matches = [w for w in withholdings if (w['date'], w['description']) == (event['date'], event['description'])]
        if len(matches) > 1:
            raise UnsupportedStatement(gettext('Two withholding lines belong to one dividend.'))
        if matches:
            if matches[0]['amount'] > 0:
                raise UnsupportedStatement(gettext('A withholding line is a credit, which is not expected.'))
            used.add(id(matches[0]))
        elif event['kind'] == 'Qualified Dividend':
            raise UnsupportedStatement(gettext('A company-stock dividend has no withholding line, so it cannot be recorded with certainty.'))
        if event['amount'] <= 0:
            raise UnsupportedStatement(gettext('A dividend line is not a credit.'))
        payments.append((event, matches[0] if matches else None))
    if any(id(w) not in used for w in withholdings):
        raise UnsupportedStatement(gettext('A withholding line has no matching dividend line (same date and description).'))

    # E7: the statement's own totals, which leave out items marked as reportable for the prior year.
    qualified = sum((e['amount'] for e in events if e['kind'] == 'Qualified Dividend'), Decimal(0))
    other = sum((e['amount'] for e in events if e['kind'] == 'Dividend' and not e['prior']), Decimal(0))
    shown_q, shown_o = _summary_value(lines, 'Qualified Dividends'), _summary_value(lines, 'Other Dividends')
    shown_total = _summary_value(lines, 'TOTAL INCOME AND DISTRIBUTIONS')
    if (shown_q or Decimal(0)) != qualified or (shown_o or Decimal(0)) != other or (shown_total or Decimal(0)) != qualified + other:
        raise UnsupportedStatement(gettext('The income and distribution summary does not agree with the dividend lines.'))
    taxes = sum((w['amount'] for w in withholdings), Decimal(0))
    tax_row = re.search(r'Tax Withholdings? (' + AMT + r')(?=\s|$)', '\n'.join(l for _p, l in lines))
    if tax_row is None:
        notices.append(gettext('The tax withholding total of the account summary was not found; that check was skipped.'))
    elif _amount(tax_row.group(1)) != taxes:
        raise UnsupportedStatement(gettext('The tax withholdings of the account summary do not agree with the withholding lines.'))
    for r in rows:
        if r['kind'] == 'other':
            notices.append(gettext('%(type)s on %(date)s is not imported.') % {'type': r['type'], 'date': r['date'].isoformat()})
    if any(re.fullmatch(r'SECURITIES (PURCHASED|SOLD)', l) for _p, l in lines):
        notices.append(gettext('A securities purchased/sold section is present; it is not imported.'))

    out = []
    for event, wh in payments:
        withholding = Decimal(0) - wh['amount'] if wh else Decimal(0)
        fund = event['kind'] == 'Dividend'
        comment = (gettext('Fund dividend') if fund else gettext('Qualified dividend')) + ' ' + gettext('via E*TRADE.')
        if event['prior']:
            comment += ' ' + gettext('The statement marks this transaction as reportable for the prior year.')
        data = {c: '' for c in COLUMNS}
        data.update(payment_date=event['date'].isoformat(), organisation=broker_organisation(ETRADE, tidy_security_name(event['description'])),
                    category=broker_category(fund),
                    currency='USD', gross_amount=format(event['amount'], 'f'), net_amount=format(event['amount'] - withholding, 'f'),
                    withholding_tax=format(withholding, 'f'), expenses='0', frequency='monthly' if fund else 'quarterly', comment=comment)
        evidence = (event['page'], event['line'])
        provenance = {'payment_date': evidence, 'organisation': evidence, 'gross_amount': evidence}
        if wh:
            provenance['withholding_tax'] = (wh['page'], wh['line'])
        out.append(st.StatementRow(data, provenance))

    text = '\n'.join(l for _p, l in lines)
    ending = re.search(r'Ending Total Value \(as of [\d/]+\) \$([\d,]+\.\d\d)', text)
    closing = ending.group(1) if ending else ''
    return st.StatementResult(rows=out, notices=notices, fingerprint=st.short_hash(READER_ID, period[0], period[1], closing), period=period)
