"""Types shared by the statement readers (Phase 15/16): rows, results and the data that chains consecutive statements."""
import datetime
import hashlib
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class StatementRow:
    data: dict                      # the import columns (see imports.COLUMNS)
    provenance: dict                # field -> (page number, source line)
    extra: dict = field(default_factory=dict)       # reader-private working data (for example for settlement across statements)


@dataclass
class Posting:
    """A tax posting that belongs to an income event, possibly booked in a later statement than the event (Fidelity)."""
    name: tuple[str, ...]           # the security name as normalised tokens
    date: datetime.date             # the date of the event the posting belongs to
    amount: Decimal                 # signed as printed: withholding negative, reversal positive
    page: int
    line: str
    flagged: bool = False


@dataclass
class Continuity:
    """What is needed to chain consecutive statements of one account (balances and a running sheet number)."""
    series: str                     # identifies the account (a hash; never shown)
    sequence: int | None            # the statement's own running number, if it prints one
    opening: Decimal
    closing: Decimal
    start: datetime.date | None
    end: datetime.date | None


@dataclass
class StatementResult:
    rows: list[StatementRow]
    notices: list[str] = field(default_factory=list)    # informational; never document text beyond figures shown in the review
    fingerprint: str = ''           # identity of the statement (see docs/imports.md); '' = the reader has none
    period: tuple[datetime.date, datetime.date] | None = None
    not_imported: bool = False      # recognised, deliberately not imported (for example a stock sale): a notice, not an error
    continuity: Continuity | None = None
    postings: list = field(default_factory=list)


def short_hash(*parts) -> str:
    return hashlib.sha256('\x1f'.join(str(p) for p in parts).encode()).hexdigest()[:16]
