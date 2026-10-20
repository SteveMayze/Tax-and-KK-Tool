"""Reading Revolut "Flexible Cash Funds" monthly statements (Phase 14, second statement type).

The interest-bearing Revolut product is a money-market fund. Its monthly statement shows a summary (Total Earned Return,
Total Fees, ...) and one "Return PAID" and one "Service Fee Charged" line per day. What is recorded per statement:

* gross  = Total Earned Return (the return the fund paid out in the month)
* expenses = Total Fees (the service fee charged in the month, shown as a positive amount)
* net    = gross - expenses
* no tax is withheld on these statements, so withholding is 0
* payment date = last day of the statement period; currency from the "Value, EUR" heading

The summary figures are checked against the daily lines: if the daily returns or fees do not add up to the summary the
statement is refused (nothing is guessed). Whether this return counts as interest or as a fund distribution for German
tax is an open question (docs/rules/README.md); the app records the value as category "Interest" as the owner calls it.
"""
import datetime
import re
from dataclasses import dataclass, field
from decimal import Decimal

from django.utils.translation import gettext

from .dividend_statements import UnsupportedStatement, _lines, _decimal

ORGANISATION = 'Revolut Securities Europe UAB (Flexible Cash Funds)'
MONTHS = {m: i for i, m in enumerate(['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'], 1)}
MONEY4 = r'(-?\d[\d,]*(?:\.\d+)?)'


def recognises(pages) -> bool:
    text = '\n'.join(pages[:1])
    return bool(re.search(r'Flexible Cash Funds Statement', text) and re.search(r'Total Earned Return', '\n'.join(pages)))


@dataclass
class FundReturn:
    payment_date: datetime.date
    currency: str
    gross: Decimal
    expenses: Decimal
    net: Decimal
    days: int
    evidence: dict = field(default_factory=dict)
    category: str = 'Interest'
    frequency: str = 'monthly'
    period_start: datetime.date | None = None

    def row_data(self, columns):
        data = {c: '' for c in columns}
        data.update(payment_date=self.payment_date.isoformat(), organisation=ORGANISATION, category=self.category,
                    currency=self.currency, gross_amount=format(self.gross, 'f'), net_amount=format(self.net, 'f'),
                    withholding_tax='0', expenses=format(self.expenses, 'f'), frequency=self.frequency,
                    comment=gettext('Flexible Cash Funds return (PDF import).'))
        return data

    def provenance_items(self):
        return self.evidence


def _date(text):
    m = re.fullmatch(r'([A-Za-z]{3})[a-z]* (\d{1,2}), (\d{4})', text.strip())
    if not m or m.group(1).lower() not in MONTHS:
        return None
    try:
        return datetime.date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
    except ValueError:
        return None


def _labelled(lines, label):
    found = []
    for page, line in lines:
        m = re.fullmatch(re.escape(label) + r'\s+' + MONEY4, line)
        if m:
            found.append((_decimal(m.group(1)), (page, line)))
    return found


def parse(pages: list[str]) -> FundReturn:
    lines = _lines(pages)
    period = next(((page, line, re.fullmatch(r'Period (.+?) - (.+)', line)) for page, line in lines if line.startswith('Period ')), None)
    if not period or not period[2]:
        raise UnsupportedStatement(gettext('The statement period could not be found.'))
    start, end = _date(period[2].group(1)), _date(period[2].group(2))
    if not start or not end or end < start or (end - start).days > 31:
        raise UnsupportedStatement(gettext('The statement period is not a single month.'))
    currency = next((m.group(1) for _p, line in lines if (m := re.fullmatch(r'Value, ([A-Z]{3})', line))), None)
    if not currency:
        raise UnsupportedStatement(gettext('The statement currency could not be found.'))

    earned, fees = _labelled(lines, 'Total Earned Return'), _labelled(lines, 'Total Fees')
    if len(earned) != 1 or len(fees) != 1:
        raise UnsupportedStatement(gettext('The summary figures (total earned return, total fees) could not be found.'))
    gross, earned_evidence = earned[0]
    fee_total, fee_evidence = fees[0]
    if gross <= 0:
        raise UnsupportedStatement(gettext('No return was earned in this period, so there is nothing to import.'))
    if fee_total > 0:
        raise UnsupportedStatement(gettext('The total fees have an unexpected sign; the figures could not be read reliably.'))

    paid = fee_sum = Decimal(0)
    days = 0
    for index, (_page, line) in enumerate(lines):
        kind = 'return' if line.startswith('Return PAID') else 'fee' if line.startswith('Service Fee Charged') else None
        if not kind:
            continue
        follower = lines[index + 1][1] if index + 1 < len(lines) else ''
        m = re.fullmatch(r'[A-Z]{2}[A-Z0-9]{10}\s+' + MONEY4, follower)
        if not m:
            raise UnsupportedStatement(gettext('A daily line of the statement could not be read; the figures are not reliable.'))
        if kind == 'return':
            paid += _decimal(m.group(1))
            days += 1
        else:
            fee_sum += _decimal(m.group(1))
    if paid != gross or fee_sum != fee_total:
        raise UnsupportedStatement(gettext('The daily returns and fees do not add up to the summary totals; nothing was staged.'))

    expenses = -fee_total
    evidence = {'payment_date': (period[0], period[1]), 'gross_amount': earned_evidence, 'expenses': fee_evidence,
                'net_amount': fee_evidence}
    return FundReturn(payment_date=end, currency=currency, gross=gross, expenses=expenses, net=gross - expenses,
                      days=days, evidence=evidence, period_start=start)
