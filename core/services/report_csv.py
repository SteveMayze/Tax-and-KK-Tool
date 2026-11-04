"""CSV rendering of a Report: a basis block (key,value rows), a blank row, then the table.

Presentation rounding to 2 decimals happens here. Text cells that could be read as spreadsheet
formulas (leading = + - @ tab or CR) are prefixed with an apostrophe; numeric cells are not touched.
"""
import csv
import io
from decimal import Decimal

from .money import round_for_display

# 1: gross/net columns only (before Phase 10). 2: adds withholding tax, expenses and unallocated columns.
CSV_FORMAT_VERSION = '2'
FORMULA_CHARS = ('=', '+', '-', '@', '\t', '\r')


def safe_text(value) -> str:
    text = '' if value is None else str(value)
    return "'" + text if text.startswith(FORMULA_CHARS) else text


def fmt(value, kind):
    if value is None:
        return ''
    if kind == 'money':
        return f'{round_for_display(Decimal(value), 2):.2f}'
    if kind == 'pct':
        return f'{round_for_display(Decimal(value) * 100, 1):.1f}%'
    if kind == 'rate':
        text = f'{Decimal(value):f}'
        return text.rstrip('0').rstrip('.') if '.' in text else text
    if kind == 'date':
        return value.isoformat()
    if kind == 'int':
        return str(value)
    return safe_text(value)


def render(report) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator='\r\n')
    w.writerow(['Report', report.title])
    w.writerow(['Report format version', CSV_FORMAT_VERSION])
    w.writerow(['Language', 'English (CSV headings are always English)'])
    w.writerow(['Format', 'Comma-separated; decimal point; no thousands separator; ISO dates (YYYY-MM-DD); amounts rounded to 2 decimals'])
    w.writerow(['Generated (UTC)', report.generated_at.strftime('%Y-%m-%d %H:%M:%S')])
    for label, text in report.basis:
        w.writerow([label, safe_text(text)])
    for note in report.notes:
        w.writerow(['Note', safe_text(note)])
    if report.tables or report.csv_tables:
        wanted = [t for k in report.csv_tables for t in report.tables if t.key == k] if report.csv_tables else report.tables
        for t in wanted:
            w.writerow([])
            w.writerow(['Table', safe_text(t.title)])
            _table(w, t.columns, t.rows, t.totals)
        return out.getvalue()
    w.writerow([])
    _table(w, report.columns, report.rows, report.totals)
    return out.getvalue()


def _table(w, columns, rows, totals):
    w.writerow([safe_text(c.label) for c in columns])
    for row in rows:
        w.writerow([fmt(row.get(c.key), c.kind) for c in columns])
    if totals:
        w.writerow([fmt(totals.get(c.key), c.kind) for c in columns])
