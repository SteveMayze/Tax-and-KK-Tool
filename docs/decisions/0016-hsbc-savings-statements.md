# ADR 0016: HSBC UK savings statements

Status: accepted (Phase 16, 2026-10-20; owner answers: payment date = credit date as printed in the date column; no fee line known on this or the non-interest account; income period: only the end date is printed).

## Context
Three Flexible Saver statements (GBP, 3 to 8 pages, 6 to 9 months each, irregular periods) hold a monthly "GROSS INTEREST" credit, each followed by a "TO <date>" line, plus occasional internet transfers. pypdf's default text mode separates dates from amounts and repeats rows; layout mode keeps each table row on one line, and the amount and balance sit on the "TO" line.

## Decisions
1. **Reader `hsbc_savings`, `needs_layout=True`**, recognised by structure (brought/carried-forward rows, paid out / paid in / balance columns matched with spaces removed, pound sign, an interest or transfer row), not by letter-spaced headings.
2. **Rows:** payment date = credit date (two-digit year); `income_period_end` = TO date, start empty (the model accepts an end without a start); GBP, Interest, monthly; organisation from `organisations.BANK_ORGANISATIONS['hsbc_savings']`; gross = credit; expenses 0; net = gross; withholding 0 because the running balance proves full payment.
3. **Arithmetic closes or the statement is refused:** per-row balance check, chained balances across parts, opening/closing from the marker rows, optional summary-block check. Refusal reasons name the row position, never figures.
4. **Direction of transfers** is inferred from the balance (exactly one direction must fit); transfers are checked and not staged.
5. **Unknown rows refuse** the statement, naming the type text with digits removed (G12). A fee is therefore refused until a fee layout is supplied.
6. **Undated rows are not rows.** A credit without a date would be skipped by the row finder; the balance check then fails and the statement is refused, so nothing is lost silently. (HSBC may omit repeated dates; none occurs in the samples.)
7. **Continuity** is a batch-level warning computed by `statement_readers.continuity_notes` from sheet number and balances (reader-neutral, reusable by later bank readers). In the samples the sheet number skips (90, 91, 93) while the balances connect, so a skip alone is reported as informational ("balances connect, so no money movement is missing"), and as "a statement may be missing" only when the balances also do not connect.
8. **Fingerprint:** sheet number, closing balance, period end.

## Consequences
All three real statements are staged (22 interest rows); hand-checked expected rows go in the git-ignored `local/samples/expected/hsbc.csv` for the owner to verify. The tax treatment of the interest is an open question (rules README item 13). Sheet numbers are not a reliable statement counter; the balance chain is the real continuity check.
