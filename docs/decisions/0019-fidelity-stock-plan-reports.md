# ADR 0019: Fidelity Stock Plan Services reports and withholding settlement

> Superseded in part by ADR 0033: fund income is category Interest and the organisation has the prefix `Fidelity `.

Status: accepted (Phase 19, 2026-10-20; owner answers: fund income is category Dividends; January remark as in Phase 18; withholding settled by summing every posting for an event across the upload; stock deliveries and sales stay out of scope).

## Context
16 reports (8 or 10 pages, one or two months each, January 2025 to September 2026, no gaps) show income in "Dividends, Interest & Other Income" and tax in a separate "Taxes Withheld" table. The tax table holds "Non-Resident Tax" (negative), "Adj Non-Resident Tax" (positive: a reversal), flag letters for prior-period items and dates of the event the posting belongs to, so a January report contains December postings; the printed "Total Federal Taxes Withheld" changes sign. One report holds an RSU delivery, a sale and a journal. The core fund changed during the period.

## Decisions
1. **Reader `fidelity_stock_plan`, `needs_layout=True`.** Security names are the capitals tokens that follow the date; descriptions are in ordinary case, so the description starts at the first token with a lowercase letter. The code column is dropped; a wrapped name is rejoined.
2. **Settlement across the upload** is a new optional `settle` hook of the reader registry, called by the staging after every file is read and before rows are stored. It receives the results of all Fidelity files (also those without rows, which may hold the postings of an earlier event). Postings are matched to events by (date, normalised name; one name must be the start of the other, because the tax table prints a longer form of a wrapped fund name). A posting that matches no event is counted in a batch warning and staged as nothing; a posting matching two events refuses the upload.
3. **Withholding** = minus the sum of all postings of the event; a net refund records 0 with a comment and a warning. The rows of the latest statement of the upload are marked "may be revised by a later statement", since a statement outside the upload could still book a posting.
4. **Reconciliation:** income lines against the table total and the income summary; tax lines against the printed federal total by absolute value (the sign is never used). The core-fund table is used only to tell the core fund (monthly) from stock (quarterly) and is never income. A quantity reconciliation is not possible: only the ending quantity is printed.
5. **Not imported:** "Securities Bought & Sold" and "Other Activity" lines become notices (kind and date), nothing else.
6. **Fingerprint:** period and ending account value. Provenance of the withholding lists every posting with its file name, so the display limit of a provenance text was raised from 160 to 400 characters.

## Consequences
All 16 real files are staged; with the whole folder in one upload there are 29 rows, one warning ("Tax postings for events not in this upload: 4") for postings of the previous year, and withholding of two events revised by reversals and re-bookings. The owner's checked rows go in the git-ignored `local/samples/expected/fidelity.csv`. The result depends on the upload: importing the files in separate uploads would settle each event only with the postings present; staging warns and marks such rows. Sales and deliveries remain unrecorded by decision (rules README item 16).
