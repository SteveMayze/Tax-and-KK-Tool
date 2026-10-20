"""What does a folder of PDF statements contain? (Phase 15, ADR 0015)

Reads every PDF with the same readers as the import, touches no database, and reports structure only: masked file
name, reader, period, row and notice counts, outcome and flags. It never reports amounts or names from the documents."""
import datetime
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import pdf_text, statement_readers

MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']


@dataclass
class Entry:
    name: str                       # masked
    reader: str = ''
    period: tuple | None = None
    rows: int = 0
    notices: int = 0
    outcome: str = ''
    flags: list[str] = field(default_factory=list)
    _raw_name: str = ''
    _text_hash: str = ''
    _fingerprint: str = ''


def name_months(name: str) -> set[tuple[int, int]]:
    """Year-month pairs a file name seems to contain (2025-03, 202503, Mar-2025, March 2025). A heuristic for a flag only."""
    found = set()
    for m in re.finditer(r'(?<!\d)(20\d{2})[-_. ]?(0[1-9]|1[0-2])(?!\d)', name):
        found.add((int(m.group(1)), int(m.group(2))))
    for m in re.finditer(r'(?i)(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[-_. ]*(20\d{2})(?!\d)', name):
        found.add((int(m.group(2)), MONTHS.index(m.group(1).lower()) + 1))
    return found


def _months_between(start, end):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield (y, m)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def inventory(folder, recursive=False) -> list[Entry]:
    folder = Path(folder)
    paths = sorted((p for p in (folder.rglob('*') if recursive else folder.glob('*'))
                    if p.is_file() and p.suffix.lower() == '.pdf' and not p.name.startswith('.')), key=lambda p: str(p).lower())
    entries = []
    for path in paths:
        raw = path.read_bytes()
        entry = Entry(name=pdf_text.mask_digit_runs(str(path.relative_to(folder))), _raw_name=path.name)
        outcome = statement_readers.read_statement(raw)
        entry._text_hash = outcome.text_hash
        entry.reader = outcome.reader_id or ''
        result = outcome.result
        if result is None:
            entry.outcome = 'refused: ' + outcome.error
        else:
            entry.period, entry.rows, entry.notices = result.period, len(result.rows), len(result.notices)
            entry._fingerprint = result.fingerprint
            entry.outcome = 'staged' if result.rows else 'recognised, not imported' if result.not_imported else 'nothing to import'
        entries.append(entry)
    _flag(entries)
    return entries


def _flag(entries):
    first_with = {}
    for e in entries:
        keys = [('text', e._text_hash)] if e._text_hash else []
        if e._fingerprint:
            keys.append(('fingerprint', e.reader, e._fingerprint))
        for key in keys:
            if key in first_with:
                e.flags.append(f'same content as {first_with[key].name}')
                break
            first_with[key] = e
        if e.period:
            wanted = name_months(e._raw_name)
            if wanted and not wanted & set(_months_between(*e.period)):
                e.flags.append('file name period differs from the period read')
    by_reader = {}
    for e in entries:
        if e.period and not any(f.startswith('same content') for f in e.flags):
            by_reader.setdefault(e.reader, []).append(e)
    for items in by_reader.values():
        items.sort(key=lambda e: e.period)
        for prev, cur in zip(items, items[1:]):
            gap = (cur.period[0] - prev.period[1]).days - 1
            if gap > 0:
                cur.flags.append(f'period gap of {gap} day(s) after {prev.name}')
            elif gap < 0:
                cur.flags.append(f'period overlaps {prev.name}')


def format_period(period):
    return f'{period[0].isoformat()}..{period[1].isoformat()}' if period else '-'


def render(entries) -> str:
    """A plain-text table. File names are masked; nothing else comes from the documents except reader ids and refusal reasons."""
    lines = ['file | reader | period | income rows | notices | outcome | flags']
    for e in entries:
        lines.append(' | '.join([e.name, e.reader or 'unrecognised', format_period(e.period), str(e.rows), str(e.notices),
                                 e.outcome, '; '.join(e.flags) or '-']))
    counts = {}
    for e in entries:
        counts[e.outcome.split(':')[0]] = counts.get(e.outcome.split(':')[0], 0) + 1
    lines.append(f'{len(entries)} PDF file(s): ' + ', '.join(f'{n} {k}' for k, n in sorted(counts.items())))
    return '\n'.join(lines)
