# ADR 0001: Decimal precision and SQLite

Status: accepted (Phase 2)

## Context
CLAUDE.md requires `Decimal` throughout and full precision internally, rounding only for display. SQLite has no native decimal type: Django stores DecimalFields with NUMERIC affinity, so non-integer values may be held as 64-bit floats (about 15-17 significant digits). SQL `SUM()` on such columns is floating point.

## Decision
- Original amounts: 4 dp, 16 digits (reported amounts are normally 2 dp). Values with more than 4 dp are rejected, not rounded.
- Rates: 10 dp, 20 digits.
- Stored EUR amounts: 6 dp, 20 digits. The exact product (original x rate) is computed in `Decimal`, then quantised half-up to 6 dp only to fit the column. Original amount and rate are stored too, so the exact value is reproducible.
- All calculations (conversion, normalisation, aggregation) run in Python `Decimal`; aggregation fetches rows and sums in Python, never with SQL `SUM`.
- Display/export rounding (`round_for_display`) is separate and must not feed back into calculations.
- Floats are rejected by `to_decimal`.

## Consequences
Values stay well inside float-exact range (at most 14 significant digits) for realistic personal incomes. A move to PostgreSQL would remove the float caveat without code changes.
