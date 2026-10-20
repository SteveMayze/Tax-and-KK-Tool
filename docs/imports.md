# CSV import (Phase 5)

One file format, modelled on the app's own payment fields. There are no per-institution profiles: prepare the CSV by hand (e.g. in a spreadsheet) in this format. PDF dividend statements are described in the section "PDF statements" below.

Nothing is imported at upload. Every row is reviewed, problems are fixed or excluded, and an explicit confirmation creates all payments in one transaction.

## File format
- The format is the same whatever the interface language is (comma, decimal point, ISO dates, English column names).
- UTF-8 text (a BOM is accepted), comma-separated, first row = column names. Column order is free; names are case-insensitive. Fully blank rows are ignored. Quoted cells may contain commas and line breaks.
- Dates `YYYY-MM-DD`. Amounts are plain numbers with a decimal point (`1234.56`), at most 4 decimal places, no thousands separators, currency symbols or exponents.
- Maximum 2 MB and 5,000 data rows (`IMPORT_MAX_BYTES`, `IMPORT_MAX_ROWS` in settings).

| Column | Required | Notes |
|---|---|---|
| `payment_date` | yes | Determines the reporting month |
| `organisation` | yes | Matched ignoring case/extra spaces; unknown names are created on commit (flagged as *new* in the review) |
| `category` | yes | Same matching as organisation |
| `currency` | yes | EUR, GBP, AUD or USD |
| `gross_amount` | yes | Must be positive, or negative (a loss) only when the row's category exists and is marked *may be negative*; otherwise the row is invalid and names the category. Corrections/reversals are entered in the app, not imported |
| `frequency` | yes | `monthly`, `quarterly`, `half_yearly`, `yearly`, `one_off` (case and `-`/space variants accepted) |
| `net_amount` | no | Same sign rules as the payment form |
| `withholding_tax`, `expenses` | no | Non-negative, in the row's currency; empty means 0. With these columns in the file, a row that has a `net_amount` must satisfy gross = net + withholding_tax + expenses exactly, otherwise the row is invalid and the message shows the three numbers. A file **without** either column (the format before Phase 10) still imports: a gross/net difference is then imported as *unallocated* and flagged with a note on the row; editing the row in the preview applies the strict rule |
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

## PDF statements (Phase 14, ADR 0014)
Select one or more PDFs (not mixed with a CSV) on the Imports page, or use "a whole folder" to upload a folder together with all its subfolders in one go (hidden files such as `.DS_Store` are ignored; up to 300 files per upload). A file chooser cannot select files across several folders, so the folder option is the way to upload a tree like `Securities/<issuer>/...`. They are read into the same review as a CSV: one row per statement, per-row edit and exclude, the duplicate rule, a confirmation page, an atomic commit that cannot run twice, history, and a protected download of the original (a single PDF, or a zip of the staged originals).

**What is read.** Text PDFs of Australian dividend and distribution advices whose amounts are in Australian dollars. Per statement: payment date, the payer, recorded as the organisation "<company name> (<ASX code>)" (the name is used only when the statement itself prints it next to its ABN; otherwise just the ASX code; nothing is looked up externally; change it in the review if you prefer another name), the dividend paid (the total payment: this is *gross*), the amount paid (*net*) and the tax withheld. Category `Dividends`, currency `AUD`, frequency `one_off` (dividends are irregular and never treated as recurring); the exchange rate is proposed exactly like for CSV rows. Franked/unfranked amounts and franking credits are Australian-tax information and are deliberately not read.

**Withholding tax is never assumed.** It is `gross - net`, and a non-zero difference is accepted only if a withholding-tax line on the statement states that same amount; otherwise the statement is refused. (In all 54 supplied statements the difference is 0.)

**Where each value came from.** Every row lists, per field, the page and the source line (long digit runs such as reference numbers are hidden). Values that several parts of a statement must agree on (the amount paid, the total payment) are refused when they disagree.

**Refused with a reason, nothing staged:** not a PDF, damaged, password-protected, no text layer (a scan; OCR is out of scope), not a dividend advice, amounts not in AUD, payment date or amounts missing or ambiguous, gross and net not explained. Recognised but not importable as a dividend: *scheme consideration* payments (shares sold in a takeover: record as a sale) and *bonus share plan* statements (shares instead of cash). A dividend reinvestment plan statement (for example Woolworths) is staged with a comment "reinvested ... (no cash received)", because the dividend is still paid; exclude the row in the review if you do not want it. Statements that were uploaded together but not recognised are listed as warnings, the others are staged.

**Revolut "Flexible Cash Funds" statements** (the interest-bearing Revolut account: a money-market fund) are read too, one statement per month. Per statement: gross = *Total Earned Return*, expenses = *Total Fees* (the service fee charged), net = gross - expenses, withholding 0 (none is shown), payment date = last day of the period, category `Interest`, frequency `monthly`, currency from the statement (EUR: rate 1). The daily "Return PAID" and "Service Fee Charged" lines must add up exactly to the summary totals, otherwise the statement is refused. The ordinary Revolut *account statement* (transfers and card payments) contains no income and is refused as "not recognised". Whether this fund return is "interest" or a fund distribution for German tax is an open question (`docs/rules/README.md`, item 12); the app records it as Interest, which the owner can change per row.

**Layouts.** The registries (Computershare, MUFG, Automic and company-specific advices) print the same figures in different arrangements, and the PDF text order differs: labels first and values later, values one per line, column headings with a totals row. The reader looks for the same few anchors in all of them (a labelled net payment, the largest amount of the holding table, labelled withholding, labelled payment date, the ASX code) instead of one parser per company, and requires them to agree. Statements of other kinds (bank account statements such as Revolut, broker interest statements) are not income advices in this sense and are refused as "not recognised".

## PDF statements: readers, multi-row results and the inventory tool (Phase 15, ADR 0015)
**Readers.** `core/services/statement_readers.py` holds an ordered list of readers (`READERS`). Each has an id, `recognises(pages)`, `parse(pages)` and a flag `needs_layout` (such a reader is given pypdf's layout-mode text, which keeps table cells on one line). Exactly one reader may claim a file. A file claimed by two is refused with a message naming both reader ids; a file claimed by none is refused as not recognised. Registered now: `revolut_flexible_cash_funds` and `au_dividend_advice` (the Phase 14 readers, unchanged). A reader that recognises a file and then cannot read it safely refuses it with its own reason.

**Results.** A reader returns a result with `rows` (the import columns plus, per field, the page and source line), `notices` (information for the review; never amounts or names from the document beyond the figures shown), a `fingerprint` and, if known, the statement `period`. Every row is staged with its own source file name and provenance; line numbers run 1, 2, 3 ... across the whole batch. Three outcomes are not errors: **staged**; **nothing to import** (recognised, no income); **recognised and not imported** (for example a stock sale; shown as a notice). They are reported as one summary line each with a count ("12 statements recognised, no income."), not one warning per file. An upload in which every file is of these kinds creates **no batch** and shows that message. A file that is refused (or unrecognised) is still listed as "Not staged ... (reason)". The Phase 14 behaviour is kept: sorted processing, same-file detection by hash, atomic creation, the stored original (a single PDF or a zip), the warning about a batch already committed.

**Fingerprints.** Two files in one upload with the same reader id and the same non-empty fingerprint are one statement: the first is staged, the other is listed as "same statement as <file>". This catches re-issued statements whose bytes differ. Each reader decides its fingerprint; it must be built only from identity fields of the statement. Revolut Flexible Cash Funds: currency, period end, total earned return and total fees. Australian dividend advices: none (an advice has no statement number that is read, and two holdings can pay equal amounts on one day), so the existing row duplicate rule is the safeguard.

**Displayed file names.** Digit runs of six or more in a file name (account or statement numbers) are masked as `######` in the review, the history and the batch name; the stored original keeps its own generated name and bytes.

**Amount conventions** (`core/services/amounts.py`, used by the later bank and broker readers): `parse_amount_us` ("1,234.56", "$1,234.56", "(1,234.56)" negative, a dash or em dash is zero), `parse_amount_uk` ("1,234.56", "£1,234.56", "-3.10"), `parse_amount_de_with_hs` ("1.234,56 H" credit, "1.234,56 S" debit; the H or S is required). Anything else raises ValueError, so a reader refuses the statement.

**Encrypted PDFs.** A PDF encrypted only against editing (empty user password) is opened if pypdf can. AES-encrypted files need the optional `cryptography` package, which is not installed: such a file is refused with a message saying so (not "password-protected").

**Inventory tool.** `.venv/bin/python tools/pdf_inventory.py <folder> [--recursive]` reads every PDF with the same readers and prints one line per file: masked name, reader id or "unrecognised", the statement period if the reader found one, number of income rows, number of notices, outcome (staged / nothing to import / recognised, not imported / refused with the reason) and flags: *same content as <file>* (same extracted text or same reader fingerprint), *period gap of N day(s)* or *period overlaps* against the previous statement of the same reader, *file name period differs from the period read*. It prints no amounts and no names from the documents, does not touch the database, and ends with a count per outcome.

## Security and privacy
- Login required on every import view; the stored file is served only through a login-protected download with a generated name, `Content-Disposition: attachment` and `nosniff`; stored paths are checked to stay inside `UPLOAD_DIR`.
- Cell contents and amounts are never logged. Cell text is HTML-escaped when displayed.
- Only the currency and payment date are sent to the exchange-rate service (see exchange-rates.md).
- Tests and the template use synthetic data only. PDF tests build their own PDFs (`core/test_pdf_support.py`); the owner's real statements stay in the git-ignored `local/samples/` and are only read by an optional local test that prints nothing.
- PDFs are read inside the app (pypdf); no document or text is sent to any external service.
