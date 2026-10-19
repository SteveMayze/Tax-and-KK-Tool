"""Reading Australian dividend and distribution advices from PDF text (Phase 14).

Only what the owner records is extracted (decision 2026-10-19): the payment date, the payer (ASX code), the dividend
paid (the total payment, gross) and the tax withheld. Franking details (franked/unfranked amount, franking credit) are
Australian-tax-system information that is irrelevant for the German use case and is deliberately NOT read.

Every figure comes with the page and the text line it was taken from, so the owner can check it in the review. A value
is never guessed: when the layout is not recognised, two readings disagree, or the arithmetic does not close, the
statement is refused with a reason (UnsupportedStatement) and nothing is staged.

Supported: text PDFs whose amounts are in Australian dollars. The registries' layouts differ in detail; rather than one
parser per company this module looks for the same few anchors (labelled net payment, the total column of the holding
table, labelled withholding, payment date, ASX code) and requires them to agree. See docs/imports.md.
"""
import datetime
import re
from dataclasses import dataclass, field
from decimal import Decimal

from django.utils.translation import gettext

MONTHS = {m: i for i, m in enumerate(
    ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november',
     'december'], start=1)}
DATE = r'(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})'
MONEY = re.compile(r'(?<![\w.,])(?:A\$|AU\$|AUD\s?|\$)\s?(\d{1,3}(?:,\d{3})+\.\d{2}|\d+\.\d{2})(?![\d])')
PURE_MONEY_LINE = re.compile(r'^(?:A\$|AU\$|AUD\s?|\$)\s?(?:\d{1,3}(?:,\d{3})+\.\d{2}|\d+\.\d{2})$')
CODE_STOPWORDS = {'TFN', 'ABN', 'AUS', 'HIN', 'SRN', 'BSB', 'ACC', 'THE', 'AND', 'ASX', 'AUD', 'USD', 'N/A', 'NIL'}


class UnsupportedStatement(Exception):
    """The statement is not one this importer can read safely. The text is shown to the owner (no document content)."""


@dataclass
class Dividend:
    code: str
    payment_date: datetime.date
    gross: Decimal
    net: Decimal
    withholding: Decimal
    record_date: datetime.date | None = None
    issuer: str = ''                 # the company's name when the statement prints it next to its ABN, else ''
    reinvested: bool = False
    evidence: dict = field(default_factory=dict)      # field -> (page number, source line)

    def row_data(self, columns):
        """The import-row fields for this statement. Organisation: "<company name> (<ASX code>)" when the statement prints
        the name next to its ABN, else just the code (nothing is looked up)."""
        data = {c: '' for c in columns}
        comment = gettext('Dividend (PDF import).')
        if self.reinvested:
            comment += ' ' + gettext('Reinvested under a dividend reinvestment plan (no cash received).')
        organisation = f'{self.issuer} ({self.code})' if self.issuer else self.code
        data.update(payment_date=self.payment_date.isoformat(), organisation=organisation, category='Dividends',
                    currency='AUD', gross_amount=format(self.gross, 'f'), net_amount=format(self.net, 'f'),
                    withholding_tax=format(self.withholding, 'f'), expenses='0', frequency='one_off', comment=comment)
        return data

    def provenance_items(self):
        items = dict(self.evidence)
        if self.reinvested:
            items['reinvested'] = (1, gettext('Dividend reinvestment plan wording found in the statement.'))
        return items


def _decimal(text):
    return Decimal(text.replace(',', ''))


def _money(line):
    return [_decimal(m) for m in MONEY.findall(line)]


def _parse_date(day, month, year):
    number = MONTHS.get(month.lower()) or MONTHS.get(next((m for m in MONTHS if m.startswith(month.lower()[:3])), ''))
    if not number:
        return None
    try:
        return datetime.date(int(year), number, int(day))
    except ValueError:
        return None


def _lines(pages):
    return [(n, ' '.join(raw.split())) for n, page in enumerate(pages, start=1) for raw in page.splitlines()
            if raw.strip()]


# ---------------------------------------------------------------- the individual anchors

def _payment_date(lines):
    inline = [
        re.compile(r'(?i)\bpayment\s+date\s*:?\s*' + DATE), re.compile(r'(?i)\bdate\s+payable\s*:?\s*' + DATE),
        re.compile(r'(?i)\bpayable\s+date\s*:?\s*' + DATE), re.compile(r'(?i)\bdate\s+credited\s*:?\s*' + DATE),
        re.compile(r'(?i)^date\s*:\s*' + DATE),
    ]
    found = {}
    for pattern in inline:
        for page, line in lines:
            m = pattern.search(line)
            if m:
                d = _parse_date(*m.groups())
                if d:
                    found.setdefault(d, (page, line))
    if len(found) == 1:
        d, evidence = next(iter(found.items()))
        return d, evidence, _record_date(lines)
    if len(found) > 1:
        raise UnsupportedStatement(gettext('The payment date is ambiguous (several different dates are labelled as payment dates).'))
    # Layout where the labels come first and the dates later, in the same order ("RECORD DATE PAYMENT DATE", then
    # two dates). The dates are the first standalone dates after the labels; their order follows the labels.
    label_re = re.compile(r'\b(record|payment|payable) date\b')
    labels, first_label, last_label = [], None, None
    for index, (page, line) in enumerate(lines):
        low = line.lower().replace(':', ' ')
        if label_re.search(low) and not re.search(r'\d', low) and len(low.split()) <= 8 and not line.endswith('.'):
            labels += [m.group(1) for m in label_re.finditer(low)]
            first_label = index if first_label is None else first_label
            last_label = index
    if labels and labels.count('record') <= 1 and (labels.count('payment') + labels.count('payable')) == 1:
        def standalone_dates(chunk):
            found = []
            for page, line in chunk:
                if re.fullmatch(r'(?:' + DATE + r'\s*)+', line):
                    found += [(page, line, _parse_date(*m.groups())) for m in re.finditer(DATE, line)]
            return found
        found_dates = standalone_dates(lines[last_label + 1:])
        if len(found_dates) < len(labels):                  # some layouts print the dates above their labels
            found_dates = standalone_dates(lines[:first_label])[-len(labels):]
        if len(found_dates) >= len(labels) and all(d[2] for d in found_dates[:len(labels)]):
            position = next(i for i, label in enumerate(labels) if label in ('payment', 'payable'))
            page, line, d = found_dates[position]
            record = found_dates[labels.index('record')][2] if 'record' in labels else None
            return d, (page, line), record
    raise UnsupportedStatement(gettext('The payment date could not be found with certainty.'))


def _record_date(lines):
    for page, line in lines:
        m = re.search(r'(?i)\brecord\s+date\s*:?\s*' + DATE, line)
        if m:
            return _parse_date(*m.groups())
    return None


def _code(lines):
    for page, line in lines:                                  # Computershare: "T 0012345 000 BHP"
        m = re.search(r'\bT\s+[0-9X*]+\s+000\s+([A-Z0-9]{2,5})\b', line)
        if m:
            return m.group(1), (page, line)
    for page, line in lines:
        m = re.search(r'(?i)\b(?:ASX|issuer)\s+code\s*:?\s+([A-Z0-9]{2,5})\b', line)
        if m and m.group(1) not in CODE_STOPWORDS:
            return m.group(1), (page, line)
    for index, (page, line) in enumerate(lines):             # label first, value on a later line
        if re.fullmatch(r'(?i)(?:asx|issuer) code\s*:?', line):
            for _p, later in lines[index + 1:index + 14]:
                if re.fullmatch(r'[A-Z][A-Z0-9]{1,4}', later) and later not in CODE_STOPWORDS:
                    return later, (page, line)
    for page, line in lines:                                  # holding table row beginning with the code
        m = re.match(r'^([A-Z][A-Z0-9]{1,4}) (?:- |[\d,]+ )', line)
        if m and m.group(1) not in CODE_STOPWORDS:
            return m.group(1), (page, line)
    for page, line in lines:
        m = re.match(r'^([A-Z][A-Z0-9]{1,4}) (?:INTERIM|FINAL|SPECIAL) (?:DIVIDEND|DISTRIBUTION)', line)
        if m:
            return m.group(1), (page, line)
    raise UnsupportedStatement(gettext('The security (ASX code) could not be found.'))


NET_PATTERNS = [
    re.compile(r'(?i)\bnet\s+(?:payment|amount|dividend\s+amount|dividend\s+payment)\b\W{0,3}(?:AUD|A\$|AU\$|\$)\s?(\d[\d,]*\.\d{2})'),
    re.compile(r'(?i)\b(?:amount\s+paid|payment\s+amount|amount\s+deposited)\b\s*:?\s*(?:AUD|A\$|AU\$|\$)\s?(\d[\d,]*\.\d{2})'),
    re.compile(r'(?i)\bdirect\s+credit\s+amount\s+AUD\s?(\d[\d,]*\.\d{2})'),
    re.compile(r'(?i)\bthe\s+amount\s+of\s+AUD\s?(\d[\d,]*\.\d{2})\s+was\s+deposited'),
]


LABEL_FIRST_NET = re.compile(r'(?i)^(?:net dividend payment|net payment|amount deposited)\s*:?$')


def _net(lines):
    candidates = []
    for index, (page, line) in enumerate(lines):
        for pattern in NET_PATTERNS:
            m = pattern.search(line)
            if m:
                candidates.append((_decimal(m.group(1)), (page, line)))
        if LABEL_FIRST_NET.match(line):                      # label first, the amount some lines later
            for _p, later in lines[index + 1:index + 41]:
                if PURE_MONEY_LINE.match(later):
                    candidates.append((_money(later)[0], (page, f'{line} ... {later}')))
                    break
    values = {c[0] for c in candidates}
    if not values:
        raise UnsupportedStatement(gettext('The amount paid (net payment) could not be found.'))
    if len(values) > 1:
        raise UnsupportedStatement(gettext('Several different amounts are labelled as the amount paid.'))
    return candidates[0]


def _column_layout(lines):
    """Layouts whose column headings name gross, tax and net/paid: (gross, tax, net, evidence) or None."""
    text = ' '.join(line for _p, line in lines).lower()
    if 'gross dividend' in text and 'australian tax deducted' in text and 'dividend paid' in text:
        marker = 3                     # AMP: gross dividend, Australian tax deducted, dividend paid
    elif 'total gross distribution' in text and 'total australian' in text and 'total net distribution' in text:
        marker = 3                     # Scentre: total gross, total Australian tax withheld, total net
    else:
        return None
    best = None
    for page, line in lines:
        values = _money(line)
        if re.search(r'\b[\d,]+\s+(?:[\d.]+ cents?|\$?0\.\d{3,})|^[\w ]+ [\d,]+ \S+ (?:A?U?\$)', line) and len(values) >= marker \
                and values[0] - values[1] == values[2]:
            if best is None or values[0] > best[0]:        # the totals row is the one with the largest gross
                best = (values[0], values[1], values[2], (page, line))
    if best:
        return best
    return None


def _total(lines):
    """The largest amount in the holding table: the total payment is never smaller than its franked/unfranked parts."""
    best = None
    runs, run = [], []
    for page, line in lines:
        if PURE_MONEY_LINE.match(line):
            run.append((page, line))
            continue
        if len(run) >= 3:
            runs.append(run)
        run = []
    if len(run) >= 3:
        runs.append(run)
    rows = [(page, line, _money(line)) for page, line in lines if len(_money(line)) >= 3]
    rows += [(r[0][0], ' '.join(x[1] for x in r), [v for x in r for v in _money(x[1])]) for r in runs]
    for page, line, values in rows:
        top = max(values)
        if best is None or top > best[0]:
            best = (top, (page, line))
    return best


def _withholding(lines):
    found = []
    for index, (page, line) in enumerate(lines):
        if re.search(r'(?i)withholding\s+tax|tax\s+withheld', line):
            values = _money(line)
            if not values and index + 1 < len(lines) and PURE_MONEY_LINE.match(lines[index + 1][1]):
                values = _money(lines[index + 1][1])
            found += [(v, (page, line)) for v in values]
    return found


COMPANY_WORDS = re.compile(r'(?i)\b(?:limited|ltd|group|corporation|corp|trust|holdings|bank|company|pty|plc|fund|inc)\b')
ABN_NUMBER = r'ABN[: ]\s*\d{2} \d{3} \d{3} \d{3}'
SMALL_WORDS = {'LTD': 'Ltd', 'PTY': 'Pty', 'AND': 'and', 'OF': 'of', 'THE': 'the', 'CO': 'Co', 'INC': 'Inc', 'PLC': 'Plc',
               'CORP': 'Corp'}


def _tidy_name(name):
    name = re.sub(r'^\S*_V\d+', '', name)                       # a reference printed in front of the name
    name = re.sub(r'[|,;:]+$', '', name.strip('| ')).strip()
    if name.isupper():                                          # "ENDEAVOUR GROUP LIMITED" -> "Endeavour Group Limited"
        name = ' '.join(SMALL_WORDS.get(w, w if len(w) <= 3 or re.search(r'\d', w) else w.capitalize()) for w in name.split())
    return name


def _issuer(lines):
    """The issuing company's name as printed next to its ABN; '' when the statement does not print one (no guess)."""
    for index, (page, line) in enumerate(lines):
        m = re.search(r'^(.*?)\s*\|?\s*' + ABN_NUMBER, line)
        if not m:
            continue
        name = _tidy_name(m.group(1))
        if not name and index:                                  # the name is on the line above the ABN
            name = _tidy_name(lines[index - 1][1])
        if name and COMPANY_WORDS.search(name) and len(name) <= 70 and not re.search(r'(?i)registry|computershare|mufg|investor', name):
            return name
    return ''


def _reinvested(lines):
    return any(re.search(r'(?i)dividend reinvestment plan amount|shares allotted|cost of shares allotted', line)
               for _p, line in lines)


# ---------------------------------------------------------------- the entry point

def parse(pages: list[str]) -> Dividend:
    lines = _lines(pages)
    text = '\n'.join(line for _p, line in lines)
    if re.search(r'(?i)scheme consideration', text) and not re.search(r'(?i)permitted dividend payment date', text):
        raise UnsupportedStatement(gettext(
            'This is a payment for shares sold under a scheme of arrangement (scheme consideration), not a dividend. '
            'Record it manually as a sale (capital gain rules are not implemented).'))
    if re.search(r'(?i)bonus share plan', text):
        raise UnsupportedStatement(gettext(
            'This is a bonus share plan statement: shares were allotted instead of a cash payment. Not imported; '
            'record it manually if it is income for you.'))
    if not re.search(r'(?i)dividend|distribution', text):
        raise UnsupportedStatement(gettext('This is not recognised as a dividend or distribution advice.'))
    if not re.search(r'(?i)\bABN\b|australian dollar|AUD|A\$|AU\$', text):
        raise UnsupportedStatement(gettext('The amounts are not recognisably in Australian dollars.'))

    payment_date, date_evidence, record_date = _payment_date(lines)
    if record_date and record_date > payment_date:
        raise UnsupportedStatement(gettext('The record date is after the payment date; the dates could not be read reliably.'))
    code, code_evidence = _code(lines)
    columns = _column_layout(lines)
    if columns:
        gross, tax, net, row = columns
        largest = _total(lines)
        if largest and largest[0] != gross:
            raise UnsupportedStatement(gettext('The total payment is ambiguous (the table shows a larger amount than the totals row).'))
        gross_evidence = net_evidence = row
        withheld = [(tax, row)] if tax else []
    else:
        net, net_evidence = _net(lines)
        total = _total(lines)
        gross, gross_evidence = (total if total else (net, net_evidence))
        withheld = _withholding(lines)
    if gross < net:
        raise UnsupportedStatement(gettext('The total payment is smaller than the amount paid; the figures do not agree.'))
    withholding = gross - net
    if withholding:
        if not any(v == withholding for v, _e in withheld):
            raise UnsupportedStatement(gettext(
                'The total payment and the amount paid differ, but no withholding-tax line explains the difference.'))
    elif any(v for v, _e in withheld):
        raise UnsupportedStatement(gettext('A withholding-tax amount is shown but the totals do not reflect it.'))
    evidence = {'payment_date': date_evidence, 'organisation': code_evidence, 'gross_amount': gross_evidence,
                'net_amount': net_evidence}
    if withheld:
        evidence['withholding_tax'] = withheld[0][1]
    return Dividend(code=code, payment_date=payment_date, gross=gross, net=net, withholding=withholding,
                    record_date=record_date, issuer=_issuer(lines), reinvested=_reinvested(lines), evidence=evidence)
