"""Reader registry for PDF statements (Phase 15, ADR 0015).

A reader turns the text of one statement into a StatementResult: zero, one or many import rows plus notices. Readers are
listed in READERS; each says whether it recognises a file (recognises) and reads it (parse). Exactly one reader may claim
a file: a file claimed by two is refused naming both reader ids. Adding a reader means adding one Reader to the list; the
others are not edited.

Readers know nothing about the database. Staging is done by core.services.pdf_imports.
"""
import datetime
import hashlib
from dataclasses import dataclass, field
from typing import Callable

from django.utils.translation import gettext

from . import dividend_statements, interest_statements, pdf_text
from .dividend_statements import UnsupportedStatement
from .imports import COLUMNS


@dataclass
class StatementRow:
    data: dict                      # the import columns (see imports.COLUMNS)
    provenance: dict                # field -> (page number, source line)


@dataclass
class StatementResult:
    rows: list[StatementRow]
    notices: list[str] = field(default_factory=list)    # informational; never document text beyond figures shown in the review
    fingerprint: str = ''           # identity of the statement (see docs/imports.md); '' = the reader has none
    period: tuple[datetime.date, datetime.date] | None = None
    not_imported: bool = False      # recognised, deliberately not imported (for example a stock sale): a notice, not an error


@dataclass(frozen=True)
class Reader:
    id: str
    recognises: Callable[[list[str]], bool]
    parse: Callable[[list[str]], StatementResult]
    needs_layout: bool = False


def short_hash(*parts) -> str:
    return hashlib.sha256('\x1f'.join(str(p) for p in parts).encode()).hexdigest()[:16]


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
    Reader('revolut_flexible_cash_funds', interest_statements.recognises, _parse_fund),
    Reader('au_dividend_advice', dividend_statements.recognises, _parse_dividend),
]


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
