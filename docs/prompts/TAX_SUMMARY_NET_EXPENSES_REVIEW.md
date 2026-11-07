# Claude Code prompt: show expenses and net next to gross on the "Tax information summary" (investigate and propose, do not implement yet)

Read CLAUDE.md, docs/reporting.md, ADR 0010 (gross = net + withholding + expenses), ADR 0034 (PDF export) and
ADR 0036 (Tax information summary as recorded) first. Then read core/services/tax_income_report.py,
core/services/policy_reports.py (`tax_info_summary`), core/services/reports.py (`Report`, `Table`, `Column`),
core/services/report_pdf.py (`_widths`, `_grid`), core/services/report_csv.py, core/services/report_package.py and
core/templates/core/report.html. Follow CLAUDE.md for rules: no personal data in tracked files, figures are computed in
services (never in templates or the PDF layer), Decimal only, ORM only, nothing is coded as a tax or SBK rule.

This is an INVESTIGATION. Produce a written proposal and stop for the owner's approval. Do not change application code,
migrations, tests or the database in this session. The only file you add is the proposal document (section 5).

## 0. Git branch (do this before anything else)

1. Run `git status` and `git branch --show-current`. The branch `fix/tax-summary-net-expenses` was created from `main`
   (commit 5fd73cf) by the owner's assistant and is where this work lives. The only untracked file should be this prompt.
   If anything else is uncommitted, stop and ask the owner.
2. Stay on that branch. Do not touch `main`. Do not push, open a pull request or merge unless the owner asks.
3. Do not commit `local/db.sqlite3`, uploads, backups or exports (git-ignored). Review `git diff --staged` before any commit
   and end commit messages with the attribution lines given by the session. Commit the proposal document only when the
   owner agrees.
4. Read `local/db.sqlite3` only read-only (for example `sqlite3 'file:local/db.sqlite3?mode=ro&immutable=1'` or the Django
   ORM in a test settings run against a copy). Ask before changing anything in it; make a backup with the existing backup
   command first if a change is ever needed.

## 1. Background (facts, from the owner)

- On 2026-11-06 SBK sent a provisional contribution notice (Beitragsmitteilung, see docs/sbk-letters/2026-11-06.md). SBK
  applied the owner's rental income as GROSS: the letter's 1,950.68 EUR x 12 = 23,408.16 EUR, while the development database
  holds 23,408.14 EUR of gross 2025 rent (Rental AUD 13,775.35 + Rental (joint) 9,632.79) and 4,406.05 EUR of recorded
  expenses on the Australian rent. Only the "Tax information summary" was sent to SBK; it shows gross and withholding tax
  but NOT expenses and NOT net.
- The owner will ask SBK whether only gross values are considered or also net (after costs). To make that question and the
  answer unambiguous, he wants the report to state, for every group, gross, withholding tax, expenses and net side by side.
- ADR 0036 deliberately left expenses and net out ("rental costs are deferred"), and the basis row "Gross/net" says
  "Net amounts and expenses are not shown." The owner now asks to reverse that decision for PRESENTATION only. This is not
  a change of any calculation: the SBK estimate, the tax checks, the category mappings, `policies/` and the letter
  reconciliation stay untouched.
- The model already stores `net_amount`, `withholding_tax`, `expenses` and their EUR counterparts (`net_eur`,
  `withholding_tax_eur`, `expenses_eur`), with `gross = net + withholding_tax + expenses` enforced for new and edited
  payments and a computed `unallocated` for old ones (Payment.unallocated). The report currently reads only gross and
  withholding.

## 2. Investigation tasks

### A. Which database were yesterday's figures from? (answer with evidence)
The review of 2026-11-06 (docs/prompts/SBK_LETTER_REVIEW.md, section 2) quotes figures "in local/db.sqlite3", the
DEVELOPMENT database. The owner says most, but not all, data was loaded into development and that production may differ.
1. Produce a comparison table "development vs production" with: payment count per year, highest payment id, number of
   payments not yet converted, per category and currency for 2025: gross, withholding, expenses, net (original currency and
   EUR), plus the AssessmentSettings row. Development values known on 2026-11-07: 186 payments (2024: 11, 2025: 105,
   2026: 70), highest id 381, 8 not converted, last update 2026-11-05 13:33. The backup `backup-20261106-153611` in
   local/backups has `app_version: dev` and identical payment data, so it is NOT a copy of production.
2. For production, do NOT connect to the server on your own. Ask the owner to either (a) run `make fetch-backup` and
   restore it to a temporary location with `restore_backup --target-db /tmp/x/db.sqlite3 --target-uploads /tmp/x/up`
   (verification only), or (b) run the figures through `~/bin/tax-healthcare-tool-manage` on the server. Then fill in the
   production column. If production is not available, say so in the proposal and mark every figure "development only".
3. State for each figure in the proposal which database it came from. List every difference between the two databases and
   what it would change in the report and in the SBK reconciliation.

### B. What does the data look like for gross, withholding, expenses and net?
For 2025 (and 2026 for comparison), per category x organisation x currency, in both databases:
1. gross, withholding, expenses, net, in original currency and in EUR, and the check `gross - net - withholding - expenses`.
2. Payments where `net_amount` is NULL, where `unallocated` is not zero, and payments not converted (their EUR net is
   missing, as for gross). Two 2025 AUD dividend payments are among the unconverted ones; say how the report would show them.
3. Which categories actually carry expenses (known so far: only "Rental" in AUD, 4,406.05 EUR) and withholding.
4. Whether net as stored equals the statement's net for imported payments (spot-check three per organisation against the
   source documents behind the report's Documents column).

### C. Can the extra columns fit, on screen and on the A4 landscape PDF?
Measured by the owner's assistant on 2026-11-07 with reportlab 5.0.1, the `_widths` algorithm and the 2025 development
rows for table 2 ("Income by organisation"); usable width is 273 mm (297 mm minus 2 x 12 mm margins):

| Layout of table 2 | Columns | Font used by `_grid` today | Natural width |
|---|---|---|---|
| Today | 11 | 7 pt | 205 mm |
| Add expenses and net, original and EUR, keep all existing columns | 15 | 6 pt | 225 mm (8 pt: 290 mm, 7 pt: 258 mm) |
| Add the four columns, drop "Of which negative" and "Unconverted payments" from the tables | 13 | 6 pt | 198 mm (7 pt: 227 mm) |
| Same 13 columns with short headers (Gross, Withh., Expenses, Net, Ccy, Pmts) | 13 | 6 pt | 175 mm (7 pt: 200 mm) |

So the columns fit on the PDF at 6 to 7 pt, but 6 pt is small. Verify this with the real pipeline:
1. Render the current "Tax information summary" for 2025 to PDF (HTML, CSV and PDF routes) from a copy of the database and
   look at it. Then render each candidate layout (prototype in a scratch branch or a throw-away script; do not leave
   prototype code in the proposal branch). Report for each: font size, whether any header wraps badly or a number is
   truncated, page count, and a rendered image of page 1 (convert the PDF to PNG and look at it).
2. Check tables 1, 2 and 4 separately. Table 4 ("Payments") already has 14 columns at 6 pt; adding expenses and net for
   every payment may be too much there. Evaluate: net and expenses only in tables 1 and 2 plus a per-payment "net" only,
   or expenses and net EUR only, or a second line inside the amount cell.
3. Evaluate the options and recommend one: (a) 13 columns as above, moving "of which negative" and "unconverted payments"
   into a note or into table 4 only; (b) a separate new small table "Gross to net" per category and currency with columns
   gross, withholding, expenses, net, unallocated, original currency and EUR, leaving tables 1 and 2 unchanged; (c) two-line
   cells (original currency over EUR); (d) hide a column when it is zero for the whole report (for example expenses when
   none are recorded) with a basis line saying so. Weigh readability, the audit trail to the source documents, and the risk
   to the "PDF with source documents" package.
4. HTML on screen: check the page at 1280 px and 1440 px width. State which columns would overflow and whether the existing
   layout scrolls horizontally; propose a fix that keeps the first columns (category, organisation) visible.
5. CSV: the tax summary CSV carries the tables named in `Report.csv_tables`. Adding columns changes the layout of this CSV
   under `CSV_FORMAT_VERSION = 2`, which is one global constant and was kept at 2 by the owner for ADR 0036. Ask whether the
   version should be bumped now, and keep the export formula-injection safe.

### D. Wording, labels and the basis block
1. The basis row "Gross/net" must change (it says net and expenses are not shown). Propose English wording and a German
   wording flagged "proposed, needs owner review" (docs/glossary.md section E is where these terms are recorded).
2. Define "net" in the report text as the net amount recorded on the payment, with the identity
   `gross = net + withholding tax + expenses` in the basis block; say that nothing is re-derived and that a payment edited
   after its import may differ from its statement. Do not use tax-office or SBK vocabulary, no "Werbungskosten", no
   "section", no "Anlage" (owner's decision of 2026-11-04: the tool does not map categories to tax policy).
3. Expenses are shown as recorded, in the payment's original currency and in EUR at the payment's stored rate. The report
   must not say that expenses are deductible or that SBK or the tax office accept them.
4. Decide how a payment with no net is shown (blank, not zero) and how "unallocated" is flagged when it is not zero.

### E. Check what must NOT change
List the tests and outputs that must stay identical (other reports' HTML, CSV and PDF text compared against `main` over a
synthetic data set, as ADR 0036 did), and which existing tests assert the current tables
(core/test_adviser_report.py, test_report_pdf.py, test_report_package.py, test_reports.py, test_report_sources.py,
test_visual.py, test_assessment_views.py) and would have to change.

## 3. Questions for the owner (list at the end of the proposal, do not code answers)
- Which layout (3C options a to d)? Is a 6 pt PDF acceptable, or should the less important columns go?
- Show net and expenses for every payment in table 4, or only in the summary tables?
- Bump `CSV_FORMAT_VERSION` or keep 2?
- Should the report show a "net total" line per category and in EUR, given that the owner will ask SBK whether net or gross
  counts? (Present it as information only.)
- Is production the reference for the figures sent to SBK? If so, please fetch a backup (see A.2).

## 4. Constraints
- No change to calculations, `policies/`, the SBK estimate, the tax checks, category mappings, models or migrations.
- All figures are computed in `core/services/tax_income_report.py` (or a sibling service), Decimal, ORM, no raw SQL. The PDF
  layer receives finished display cells.
- Every other report's output stays byte-identical. New strings go through gettext with German proposed and flagged.
- Next ADR number: check `docs/decisions/` (0042 is the latest on 2026-11-07, so 0043 is expected); the implementation
  would amend or supersede the "Not done" paragraph of ADR 0036 rather than rewrite history.

## 5. Deliverable
Write `docs/proposals/tax-summary-net-expenses.md` (create the folder) with: the database comparison (A), the data findings
(B), the layout measurements with pictures described and the recommended layout (C), the proposed wording (D), the list of
tests and docs that would change (E), a numbered implementation plan with small tasks (service columns, HTML, PDF, CSV,
i18n, tests, docs/ADR), a mock of the recommended table filled with the real 2025 figures, and the owner questions (3).
Then report: branch name, `git status`, files added, the key findings in ten lines, and stop for approval. Do not implement.
