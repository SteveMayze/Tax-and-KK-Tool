# ADR 0018: E*TRADE client statements

> Superseded in part by ADR 0033: fund income is category Interest and the organisation has the prefix `E*Trade `.

Status: accepted (Phase 18, 2026-10-20; owner answers: money-market-fund income is category Dividends; January items "reportable for the prior year" keep the printed payment date with a comment; sales are only a notice).

## Context
14 client statements (8 or 10 pages) for January 2025 to September 2026, one or two calendar months each, no gaps. Income sits in "Cash Flow Activity by Date": monthly money-market-fund `Dividend` lines (a wrapped second line "DIV PAYMENT" in most) and quarterly `Qualified Dividend` lines, each followed by a `Tax Withholding` line with the same date and description. A sweep table invests the net cash in the fund. The account summary and the income and distribution summary repeat the totals. The messages section after the sweep table contains sensitive text.

## Decisions
1. **Reader `etrade_client`, `needs_layout=True`** (the default mode splits the multi-column summary pages). Recognition by structure, not by names.
2. **Event rows:** `Dividend` = fund (monthly), `Qualified Dividend` = company stock (quarterly); withholding is paired by date and description; stock dividends without a withholding line refuse the statement (never assumed); anything else refuses naming the type; `Bought`/`Sold`/`Journal` lines and a securities purchased/sold section are notices.
3. **Reconciliation** against the statement's own totals: cash-flow net, sweep table, income summary by class, tax withholdings. In the samples all four close for all 14 files. Prior-year items are excluded from the income summary comparison because the statement excludes them.
4. **Organisation** from the printed description through the shared tidy function; custodian in the comment.
5. **Messages never read:** the line list is cut at the "MESSAGES" heading before any parsing, so nothing after it can reach a row, provenance, notice or log.
6. **Fingerprint:** period and ending total value.
7. **Test fixtures** now encode with Windows-1252 and declare WinAnsiEncoding, so a dash or euro sign survives in a synthetic PDF (earlier fixtures only used characters common to Latin-1).

## Consequences
All 14 real files are staged (28 rows: 21 monthly fund dividends, two of them January items marked for the prior year, and 7 quarterly stock dividends with withholding), none refused, no period gaps, no file-name period mismatches; the owner's checked rows go in the git-ignored `local/samples/expected/etrade.csv`. German classification and credit of the US tax are open (rules README item 15). The 1042-S cross-check is Phase 20.
