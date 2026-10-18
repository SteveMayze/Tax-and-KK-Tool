# CSV import (Phase 5)

One file format, modelled on the app's own payment fields. There are no per-institution profiles: prepare the CSV by hand (e.g. in a spreadsheet) in this format. PDF extraction is deferred to a later phase.

Nothing is imported at upload. Every row is reviewed, problems are fixed or excluded, and an explicit confirmation creates all payments in one transaction.

## File format
- UTF-8 text (a BOM is accepted), comma-separated, first row = column names. Column order is free; names are case-insensitive. Fully blank rows are ignored. Quoted cells may contain commas and line breaks.
- Dates `YYYY-MM-DD`. Amounts are plain numbers with a decimal point (`1234.56`), at most 4 decimal places, no thousands separators, currency symbols or exponents.
- Maximum 2 MB and 5,000 data rows (`IMPORT_MAX_BYTES`, `IMPORT_MAX_ROWS` in settings).

| Column | Required | Notes |
|---|---|---|
| `payment_date` | yes | Determines the reporting month |
| `organisation` | yes | Matched ignoring case/extra spaces; unknown names are created on commit (flagged as *new* in the review) |
| `category` | yes | Same matching as organisation |
| `currency` | yes | EUR, GBP, AUD or USD |
| `gross_amount` | yes | Must be positive. Corrections/reversals are entered in the app, not imported |
| `frequency` | yes | `monthly`, `quarterly`, `half_yearly`, `yearly`, `one_off` (case and `-`/space variants accepted) |
| `net_amount` | no | Same sign rules as the payment form |
| `income_period_start`, `income_period_end` | no | End must not precede start |
| `comment` | no | Free text |
| `exchange_rate` | no | EUR per 1 unit of `currency`. Stored as a **manual** rate. Not allowed for EUR rows. Leave empty to have the ECB rate looked up |
| `rate_date` | no | Date the typed rate applies to; defaults to the payment date; only valid with `exchange_rate` |

Unknown columns are ignored with a warning. A downloadable template with synthetic rows is on the Imports page (`/imports/template.csv`).

Rows are validated with the same rules as the payment form: the CSV row is turned into an unsaved `Payment` and run through the model's `full_clean`, so import and manual entry cannot disagree. Inactive organisations/categories make a row invalid.

## Workflow
1. **Upload** (`/imports/`). The original file is stored under `UPLOAD_DIR` (default `local/uploads/imports/`, git-ignored, owner-only permissions) with a generated name; the user's file name is only displayed. Rows are staged; no payment, organisation, category, month or rate record is created. Uploading a file with the same SHA-256 as a committed import shows a warning.
2. **Review** (`/imports/<id>/`). Each row shows its status, messages, new-organisation/category flags and a **proposed conversion** (rate, rate date, source, EUR amount, or "no rate" with the reason). Weekend/holiday rate dates are labelled as in manual entry. Rates are requested once per distinct currency and date (and reuse rates already stored).
3. **Fix**: edit a row (re-checked immediately; the uploaded values stay on record), exclude/include a row, keep a flagged duplicate, or ask for exchange rates again.
4. **Confirm** (`/imports/<id>/commit/`): a summary of payments to create (with/without a rate), duplicates skipped/kept, excluded and invalid rows, and any new organisations/categories. Import is blocked while any non-excluded row is invalid.
5. **Commit**: all payments are created in one transaction or none are. The rates saved are exactly the ones shown in the review (no second lookup). Each payment links to its `ImportBatch` and `SourceDocument` and gets an initial conversion event ("Import batch #n, line m") with full rate provenance. Rows without a rate are saved **unconverted** and appear in Reconciliation. Submitting twice imports once.
6. **History**: batches, status, counts and a login-protected download of the original file. Discarding a not-yet-imported batch deletes its staged rows and the stored file.

## Duplicate rule
A row is a possible duplicate when another payment, or an earlier non-excluded row in the same file, has the same **payment date, organisation, currency and gross amount** (organisation compared ignoring case/spacing; amount to 4 dp). Duplicates are never dropped silently: they are skipped on commit unless you choose "Keep anyway". Excluding the earlier row stops it counting as the original. Category, net amount and comment are not part of the rule.

## Errors and edge cases
- File-level problems (not UTF-8, binary data, missing required columns, duplicate header names, no data rows, too large, too many rows) are reported on the upload page and create no batch.
- A row with more cells than the header is invalid until edited.
- If a rate lookup fails, the row stays valid, shows "No rate: ...", and would import unconverted; you can retry with "Request exchange rates again", add `exchange_rate` in the row, or accept unconverted.
- If data changes between review and commit so a row is no longer valid (e.g. an organisation was deactivated), the commit is refused and nothing is imported.

## Security and privacy
- Login required on every import view; the stored file is served only through a login-protected download with a generated name, `Content-Disposition: attachment` and `nosniff`; stored paths are checked to stay inside `UPLOAD_DIR`.
- Cell contents and amounts are never logged. Cell text is HTML-escaped when displayed.
- Only the currency and payment date are sent to the exchange-rate service (see exchange-rates.md).
- Tests and the template use synthetic data only.
