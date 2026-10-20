"""Reader registry for PDF statements (Phase 15, ADR 0015).

A reader turns the text of one statement into a StatementResult: zero, one or many import rows plus notices. Readers are
listed in READERS; each says whether it recognises a file (recognises) and reads it (parse). Exactly one reader may claim
a file: a file claimed by two is refused naming both reader ids. Adding a reader means adding one Reader to the list; the
others are not edited.

Readers know nothing about the database. Staging is done by core.services.pdf_imports.
"""
import datetime
import hashlib
from decimal import Decimal
from dataclasses import dataclass, field
from typing import Callable

from django.utils.translation import gettext

from . import dividend_statements, etrade_client, fidelity_stock_plan, hsbc_savings, interest_statements, pdf_text, rvb_account
from .dividend_statements import UnsupportedStatement
from .imports import COLUMNS
from .statement_types import Continuity, StatementResult, StatementRow, short_hash  # noqa: F401  (re-exported for readers and tests)


@dataclass(frozen=True)
class Reader:
    id: str
    recognises: Callable[[list[str]], bool]
    parse: Callable[[list[str]], StatementResult]
    needs_layout: bool = False
    settle: Callable | None = None     # optional: settles values across all statements of one upload (see fidelity_stock_plan)


def _single(statement, fingerprint='', period=None) -> StatementResult:
    """Adapter: a statement object with row_data() and provenance_items() becomes a one-row result."""
    return StatementResult(rows=[StatementRow(statement.row_data(COLUMNS), statement.provenance_items())],
                           fingerprint=fingerprint, period=period)


def _parse_dividend(pages) -> StatementResult:
    # No fingerprint: an advice carries no statement number that is read, and two holdings can pay the same amount on
    # the same day. The row duplicate rule at staging is the safeguard.
    return _single(dividend_statements.parse(pages))


def _parse_fund(pages) -> StatementResult:
    fund = interest_statements.parse(pages)
    return _single(fund, fingerprint=short_hash('fund', fund.currency, fund.payment_date, fund.gross, fund.expenses),
                   period=(fund.period_start, fund.payment_date))


# Order matters only for reporting; no two readers may claim the same file.
READERS: list[Reader] = [
    Reader(hsbc_savings.READER_ID, hsbc_savings.recognises, hsbc_savings.parse, needs_layout=True),
    Reader(rvb_account.READER_ID, rvb_account.recognises, rvb_account.parse, needs_layout=True),
    Reader(etrade_client.READER_ID, etrade_client.recognises, etrade_client.parse, needs_layout=True),
    Reader(fidelity_stock_plan.READER_ID, fidelity_stock_plan.recognises, fidelity_stock_plan.parse, needs_layout=True,
           settle=fidelity_stock_plan.settle),
    Reader('revolut_flexible_cash_funds', interest_statements.recognises, _parse_fund),
    Reader('au_dividend_advice', dividend_statements.recognises, _parse_dividend),
]


def continuity_notes(items):
    """items: [(label, reader id, Continuity)] -> [(label, text)]. Consecutive statements of one account should have
    consecutive sheet numbers and the opening balance of one equal to the closing balance of the previous. Warnings only;
    the texts contain no amounts."""
    notes, groups = [], {}
    for label, reader_id, c in items:
        if c is not None:
            groups.setdefault((reader_id, c.series), []).append((label, c))
    for entries in groups.values():
        entries.sort(key=lambda e: (e[1].sequence is None, e[1].sequence or 0, e[1].start or datetime.date.min))
        for (label_a, a), (label_b, b) in zip(entries, entries[1:]):
            connected = a.closing == b.opening
            if a.sequence is not None and b.sequence is not None and b.sequence != a.sequence + 1:
                if b.sequence <= a.sequence:
                    what = gettext('sheet numbers overlap (%(a)s, then %(b)s)')
                elif connected:
                    what = gettext('sheet numbers skip from %(a)s to %(b)s, but the balances connect, so no money movement is missing')
                else:
                    what = gettext('sheet numbers skip from %(a)s to %(b)s and the balances do not connect: a statement may be missing')
                notes.append((label_b, gettext('after %(file)s, %(what)s') % {
                    'file': label_a, 'what': what % {'a': a.sequence, 'b': b.sequence}}))
            elif not connected:
                notes.append((label_b, gettext('the opening balance does not match the closing balance of %(file)s') % {'file': label_a}))
    return notes


def reader_by_id(reader_id):
    return next(r for r in READERS if r.id == reader_id)


@dataclass
class ReadOutcome:
    reader_id: str | None = None
    result: StatementResult | None = None
    error: str = ''                 # why the file was refused (safe to show: no document text)
    text_hash: str = ''             # hash of the extracted text: catches re-issued files whose bytes differ


def read_statement(raw: bytes) -> ReadOutcome:
    """Extract, pick the one reader that recognises the file, and read it. Never raises for a bad file: the outcome says why."""
    try:
        plain = pdf_text.extract_pages(raw)
    except pdf_text.PdfError as e:
        return ReadOutcome(error=str(e))
    outcome = ReadOutcome(text_hash=hashlib.sha256('\n'.join(plain).encode()).hexdigest()[:16])
    layout_pages = None
    claimed = []
    for reader in READERS:
        if reader.needs_layout:
            if layout_pages is None:
                try:
                    layout_pages = pdf_text.extract_pages(raw, layout=True)
                except pdf_text.PdfError as e:
                    return ReadOutcome(error=str(e), text_hash=outcome.text_hash)
            pages = layout_pages
        else:
            pages = plain
        if reader.recognises(pages):
            claimed.append((reader, pages))
    if len(claimed) > 1:
        outcome.error = gettext('Two readers claim this file (%(a)s and %(b)s), so it was not read.') % {
            'a': claimed[0][0].id, 'b': claimed[1][0].id}
        return outcome
    if not claimed:
        outcome.error = gettext('This is not recognised as a statement this importer can read '
                                '(Australian dividend or distribution advice, Revolut Flexible Cash Funds statement).')
        return outcome
    reader, pages = claimed[0]
    outcome.reader_id = reader.id
    try:
        outcome.result = reader.parse(pages)
    except UnsupportedStatement as e:
        outcome.error = str(e)
    return outcome
