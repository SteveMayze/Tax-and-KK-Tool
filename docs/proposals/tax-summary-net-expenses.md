# Proposal: show expenses and net next to gross on the "Tax information summary"

Status: **approved by the owner on 2026-11-07 (new table, CSV version 3, refresh the development database, spot check); implemented, see ADR 0043.**

**Decisions and outcomes (2026-11-07)**
- Layout: option (b), the new "Gross to net by category and currency" table. Option (d) (hide empty expense columns) was *not* applied: a fixed layout keeps the CSV stable. Table 4 is unchanged.
- `CSV_FORMAT_VERSION` is now 3. Table 2 was not added to the CSV.
- German terms follow `docs/glossary.md` ("Ausgaben", "Nicht zugeordnet"), not the "Kosten" used in section D below.
- Development database refreshed from production backup `backup-20261107-022314` (a backup `pre-refresh` was taken first; the old files are in `local/backups/*.before-restore-*`).
- Spot check B.4 (done): all 246 payments that were created by an import (every payment except the 11 entered by hand) were compared with a fresh re-read of their stored original statement by the current readers: date, gross, net, withholding tax and expenses match on every one (0 differences). Two import batches (15 and 16) have no stored original, but no payment links to them. This proves the stored values equal what the readers extract from the stored statements today; it is not an independent check of the readers against the printed statements.
- The page-wide sideways scroll (question 8) is fixed in the same change (C.4).

Original status line: proposal, awaiting approval. Branch `fix/tax-summary-net-expenses`
(from `main` 5fd73cf). Written 2026-11-07. Presentation change only: no calculation, policy, model or migration changes.

Privacy: this file holds category-level figures only. Organisation names, account holders and addresses are left out on
purpose. The full organisation-level renderings used for the measurements are in the git-ignored scratch area, not in the repo.

## 0. Sources of the figures

| Label | Database |
|---|---|
| **DEV** | `local/db.sqlite3` (copied read-only to scratch before use) |
| **PROD** | `local/backups/backup-20261107-022314.tar.gz` (MANIFEST `app_version` 5fd73cf1dc4e, created 2026-11-07 02:23 UTC), extracted to scratch and used as a copy |

Both were read through the Django ORM on copies. Neither original was changed.
Rendering used the real views (HTML, CSV, PDF routes) on a copy of PROD.

## A. Development vs production

| Item | DEV | PROD |
|---|---|---|
| Payments | 186 | 257 |
| Per year 2024 / 2025 / 2026 | 11 / 105 / 70 | 16 / 139 / 102 |
| Highest payment id | 381 | 345 |
| Not yet converted | 8 | 0 |
| Last payment update (UTC) | 2026-11-05 13:33 | 2026-11-05 13:59 |
| Payments with net empty | 0 | 0 |
| Payments with gross - net - withholding - expenses != 0 | 0 | 0 |
| Corrections / reversals | 0 / 0 | 0 / 0 |
| Payments without source document and without import batch | 0 | 11 (hand-entered: 2024 and 2025 AUD dividends and one capital gain, 2026 dividends) |
| AssessmentSettings | kv_rate `reduced`, confirmed, childless, joint, `en` | kv_rate **`general`**, confirmed, childless, joint, `en` |

**What the comparison shows**
1. PROD is a superset of DEV by content. Matching on (date, currency, gross), DEV has 0 payments that PROD lacks; PROD has 71 more.
   Payment ids diverge from id 196 on (the two databases were filled in different orders), so ids must never be compared across them.
2. The 2025 rental figures behind the SBK letter are identical in both: Rental (AUD) 13,775.35 EUR gross and 4,406.05 EUR expenses,
   Rental (joint) 9,632.79 EUR, together 23,408.14 EUR. The letter reconciliation does not change.
3. PROD has 2025 data DEV lacks: 11 more dividend payers, one capital loss (AUD, -739.01 EUR), and a EUR interest source that
   carries expenses (fees, 117.87 EUR in 2025). **The "only Rental carries expenses" statement is true for DEV only.**
4. The two 2025 AUD dividend payments that are unconverted in DEV are converted in PROD (AGL 221.40 EUR in total for the year
   instead of 113.00, BHP 293.41 instead of 154.65).
5. The assessment setting differs (`reduced` in DEV, `general` in PROD). It affects the SBK estimate only, not this report.

**2025 EUR totals** (converted payments; gross / withholding / expenses / net): DEV 43,290.09 / 1,188.60 / 4,406.05 / 37,695.45;
PROD 47,661.74 / 1,188.60 / 4,523.92 / 41,949.22. The EUR identity gross - net - withholding - expenses holds to 0.000001 on every converted payment in both.

**Recommendation:** treat PROD as the reference for anything sent to SBK or an adviser. Do not send DEV-based reports (they miss payments).

## B. Data findings (2025; PROD unless stated)

Per category and currency, original currency and EUR (EUR = sum of the stored per-payment EUR amounts):

| Category | Ccy | Pmts | Gross | Withholding | Expenses | Net | Gross EUR | Withholding EUR | Expenses EUR | Net EUR |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Capital gains | AUD | 1 | -1,313.74 | 0.00 | 0.00 | -1,313.74 | -739.01 | 0.00 | 0.00 | -739.01 |
| Dividends | AUD | 37 | 13,137.88 | 0.00 | 0.00 | 13,137.88 | 7,405.62 | 0.00 | 0.00 | 7,405.62 |
| Dividends | USD | 8 | 5,776.50 | 866.48 | 0.00 | 4,910.02 | 5,104.49 | 765.68 | 0.00 | 4,338.81 |
| Interest | AUD | 17 | 7,279.59 | 725.10 | 0.00 | 6,554.49 | 4,149.62 | 413.34 | 0.00 | 3,736.28 |
| Interest | EUR | 16 | 484.59 | 2.60 | 117.87 | 364.12 | 484.59 | 2.60 | 117.87 | 364.12 |
| Interest | GBP | 12 | 32.15 | 0.00 | 0.00 | 32.15 | 37.64 | 0.00 | 0.00 | 37.64 |
| Interest | USD | 25 | 8,766.45 | 7.26 | 0.00 | 8,759.19 | 7,810.64 | 6.98 | 0.00 | 7,803.66 |
| Rental | AUD | 11 | 24,120.67 | 0.00 | 7,739.27 | 16,381.40 | 13,775.35 | 0.00 | 4,406.05 | 9,369.30 |
| Rental (joint) | EUR | 12 | 9,632.79 | 0.00 | 0.00 | 9,632.79 | 9,632.79 | 0.00 | 0.00 | 9,632.79 |
| **Total (EUR only)** | | 139 | | | | | **47,661.74** | **1,188.60** | **4,523.92** | **41,949.22** |

(DEV 2025 has no capital loss line, fewer dividend payers and no EUR-interest expenses; see A.)

1. Check `gross - net - withholding - expenses` is 0.00 for every group in both databases; 0 payments have a null net; 0 have
   an unallocated amount. The "net empty" and "unallocated" display rules (D.4) are therefore not exercised by today's data but are needed
   for older or hand-edited payments.
2. Unconverted payments: none in PROD. In DEV two 2025 AUD dividend payments are unconverted; they would show their original
   gross/net and leave EUR cells blank, counted in an "unconverted" note (see layout option d).
3. Categories carrying expenses in PROD 2025: Rental (AUD, 7,739.27 AUD) and Interest (EUR, 117.87). Withholding: Dividends (USD),
   Interest (AUD, EUR, USD). Everything else has none recorded.
4. Net as stored vs statement net: **not done.** This needs the stored originals opened and read by hand. The only evidence so far is
   structural: net is derived by the importers as gross - withholding - expenses and the identity holds for all 257 payments.
   Question for the owner (see section G, item 6).

Other observations: the total EUR net (41,949.22) differs by one cent from the sum of the rounded category rows (41,949.21); that is
the documented "rounded once from unrounded sums" rule and the report already states it.

## C. Layout measurements (real pipeline, PROD copy, 2025)

Method: a throw-away script in scratch wraps `tax_income_report.tables()` to add columns, then the normal views render HTML, CSV and PDF.
PDF pages converted to PNG with Ghostscript and looked at. HTML measured in headless Chrome at 1280 px and 1440 px. No prototype code is in the repo.

### C.1 Today (baseline)
PDF: 12 pages (table 4 is most of it). Table 1 (9 columns) is set at 7 pt, table 2 (11 columns) at 7 pt, table 4 (14 columns) at 6 pt;
all are readable and headers do not wrap badly. Existing defect found: the heading "Income by organisation" is left alone at the bottom of page 1
(its table starts on page 2).

### C.2 Candidates for tables 1 and 2

| Variant | Columns table 2 | Font | PDF result | Pages |
|---|---:|---|---|---:|
| a15: add 4 columns, keep all | 15 | 6 pt | fits one page width but headers break mid-word ("Withholdin g tax", "Payment s", "Expense s", "Unconverte d"); "Of which negative" header 6 lines tall | 12 |
| a13: add 4, drop "Of which negative" and "Unconverted", long headers | 13 | 6 pt | clean, headers wrap at word boundaries into 3 lines | 12 |
| a13s: same with short headers (Gross, Withh., Expenses, Net, Ccy, Pmts) | 13 | 6 pt | cleanest; one line headers except two | 12 |
| b: tables 1 and 2 unchanged plus a new table "Gross to net by category and currency" (11 columns) | 11 | 7 pt | readable, no wrapping problems | 13 |

`_grid` picks 8 pt for up to 8 columns, 7 pt up to 12, else 6 pt, so any variant above 12 columns drops to 6 pt. At 6 pt the numbers are legible on the page but small when printed.
The owner's assistant measured natural widths (a13 198 mm at 6 pt, 227 mm at 7 pt, usable 273 mm): **a13 with 12 columns would be set at 7 pt**, so merging "Documents" out (or dropping Payments) is the way to get 7 pt back; not prototyped.

### C.3 Table 4 (Payments), all 14 columns at 6 pt today
| Variant | Result |
|---|---|
| Add net (original) and net EUR (16 columns) | dates break ("2025-02-2 / 8"), "Normal" breaks ("Norma / l"), "frankfurter-ec / b" already breaks today |
| Add expenses and net, original and EUR, and drop rate date and rate source (16 columns) | same wrapping |
| Add net and net EUR and merge rate with rate date in one cell (15 columns) | dates and "Normal" still break |

Conclusion: **table 4 cannot take more columns on landscape A4 without wrapping dates.** Options in G: leave it as is, or add one column and
shorten "Kind"/rate source.

### C.4 HTML on screen
`main` is limited to 72 rem (1152 px). Tables have no scroll container.

| | width of table 2 | page scrollWidth at 1280 / 1440 px viewport |
|---|---:|---|
| Today | 1,837 px | 1,894 / 1,974 (already scrolls the whole page sideways) |
| a15 | 2,486 px | 2,543 / 2,623 |
| a13s | 1,165 px | table 2 fits; the page still scrolls because table 4 is 1,617 px |

So today's page already overflows horizontally (not caused by this change). Proposed fix, same for all variants: wrap each report table in a
`<div class="table-scroll" tabindex="0" role="region" aria-label="...">` with `overflow-x: auto`, and make the first two columns (category, organisation)
`position: sticky; left: 0` with an opaque token background. Only CSS tokens, no inline `style=` (Phase 13 rule).

### C.5 CSV
`Report.csv_tables` for the tax summary is `('payments', 'category_currency', 'sources')`. New columns change the layout of tables 1 and 4 under
`CSV_FORMAT_VERSION = '2'`. Cells go through `fmt`/`safe_text`, so the new columns inherit the formula-injection guard. Question in G: bump the constant to 3?
The constant is global (one value for every report), so a bump is visible in every CSV; table 2 is not in the CSV at all today, so it would be a good
candidate to add (with the new columns) if the owner wants organisation-level figures in the CSV.

### C.6 Option assessment

| Option | Readability | Audit trail to source docs | Risk |
|---|---|---|---|
| (a) 13 columns, negative and unconverted moved to notes / table 4 | good at 6 pt, short headers needed | keeps Documents | removes two columns users may rely on; counts must move to a note |
| (b) new "Gross to net" table, tables 1 and 2 unchanged | best (7 pt) | tables 1, 2 stay byte-identical, Documents stay | one more table, some repetition of gross and withholding; smallest regression risk |
| (c) two-line cells (original over EUR) | worse: mixes currencies visually, harder to copy into a spreadsheet | unchanged | PDF layer would receive multi-line text; changes the "display cells" contract |
| (d) hide a column that is zero for the whole report | cleanest when nothing recorded | unchanged | the same report shows different columns in different years; needs a basis line to say so. Combine with (a) or (b) for "Expenses" and "Unconverted" only |

**Recommendation: (b), with (d) applied to the Expenses columns of the new table.**
Reasons: it answers the owner's SBK question directly (gross, withholding, expenses, net side by side per category and currency, original and EUR),
leaves tables 1, 2, 3, 4 and their CSV untouched (so the "PDF with source documents" package and `report_sources` are not at risk),
stays at 7 pt, and needs no change to the 14-column payments table. An extra "net per organisation" level can be added to the new table later
(it is the same service function with a different grouping). If the owner prefers net and expenses in the existing organisation table, use (a) with short headers.

### C.7 Mock of the recommended new table (PROD, 2025; EUR only totals)

Title: **Gross to net by category and currency**

The table is exactly the one in section B, plus an "Unallocated" column (blank when no net, `0.00` otherwise) and a basis line.
Total line: Gross EUR 47,661.74, Withholding tax EUR 1,188.60, Expenses EUR 4,523.92, Net EUR 41,949.22.

## D. Wording (English; German proposed, needs owner review)

Basis row "Gross/net" (replaces the sentence that says net and expenses are not shown):

- EN: "Gross, withholding tax, expenses and net as recorded on each payment, with gross = net + withholding tax + expenses. Nothing is re-derived here; a payment edited after its import may differ from its statement. Expenses are shown as recorded, in the payment's original currency and in EUR at the payment's stored rate; they are not a deduction and no one has accepted them as one."
- DE (proposed): "Brutto, einbehaltene Steuer, Kosten und Netto wie auf jeder Zahlung erfasst, mit Brutto = Netto + einbehaltene Steuer + Kosten. Nichts wird hier neu berechnet; eine nach dem Import bearbeitete Zahlung kann von ihrer Abrechnung abweichen. Kosten werden wie erfasst angezeigt, in der Originalwährung der Zahlung und in EUR zum gespeicherten Kurs; sie sind kein Abzug, und niemand hat sie als solchen anerkannt."

Column labels (EN / DE proposed): Expenses (original currency) / Kosten (Originalwährung); Net (original currency) / Netto (Originalwährung);
Expenses EUR / Kosten EUR; Net EUR / Netto EUR; Unallocated / Nicht zugeordnet; Gross to net by category and currency / Von Brutto zu Netto nach Kategorie und Währung.
Existing terms stay as in `docs/glossary.md` section E. No "Werbungskosten", "Anlage" or "section" anywhere (decision of 2026-11-04).

Display rules: a payment with no net shows a blank net cell, never 0; a group's net is the sum of recorded nets and the row says
"n without net" in a note when any exist. Unallocated is shown only when it is not zero, with a basis line "n payment(s) have an amount that is not allocated".

Also change the notes: the existing note "No tax amount is calculated." stays. The PDF boxed notice says "It shows the gross income as recorded"; this should become
"gross income, withholding tax, expenses and net as recorded" (wording to approve), because the notice is part of what is sent.

## E. What must not change, and tests affected

Must stay byte-identical against `main` (compare HTML, CSV, PDF text over the synthetic data set, as ADR 0036 did): every report except the tax summary
(`annual`, `monthly`, `payments`, `organisation`, `category`, `currency`, `eur`, `normalised`, `reconciliation`, `cross`, `sbk`, `tax_checks`); and for the
tax summary under option (b): tables 1, 2, 3, 4 and 5 and the CSV of the three CSV tables.

Tests that touch the tax summary (13 modules reference it): `core/test_adviser_report.py`, `test_report_pdf.py`, `test_report_package.py`,
`test_report_sources.py`, `test_report_filters.py`, `test_visual.py`, `test_assessment_views.py`, `test_breakdown.py` (T18 repeats headers; the
"every other report is unchanged" test around lines 326-343), plus `test_reports.py` (other reports' columns). Under (b) only tests that assert the
table count or order, the basis row text, the PDF disclaimer text and the CSV table list need to change; under (a) the column assertions in
`test_adviser_report.py` and the PDF header tests would also change. I did not run the suite (investigation only); the exact list should be produced by running it after the first change.

Docs: `docs/reporting.md`, `docs/glossary.md` section E, ADR 0036 ("Not done" paragraph is amended, not rewritten), new ADR 0043, `core/locale/de` (.po and .mo).

## F. Implementation plan (small tasks, each committed with its tests)

1. Service: `tax_income_report.gross_to_net_table(payments)` returning a `Table` (category x currency; sums of gross, withholding, expenses, net, unallocated, and the four EUR figures from the stored per-payment EUR amounts; no EUR for unconverted; Decimal only). Unit tests including negative payments, null net, unconverted, mixed currencies and the filter.
2. Basis rows and notes (D) with gettext; keep the old strings' tests green.
3. Wire the table into `tax_info_summary` after table 1; do not touch the other tables. HTML renders it through the existing generic loop.
4. PDF: nothing to change in `report_pdf._grid` for 11 columns (7 pt); add a regression test for no mid-word header break (reportlab text extraction), and fix the orphaned table heading by keeping it with the first rows (small, separate commit).
5. CSV: add the table key to `csv_tables` (decide the version bump, G3). Test the new table's CSV cells and formula safety.
6. Page layout: `.table-scroll` wrapper with sticky first columns, token colours, contrast check via `tools/check_contrast.py`; keyboard focus test in `test_visual.py`.
7. i18n: `makemessages`, German proposed and flagged, `msgfmt`, commit `.po` and `.mo`.
8. Regression: compare all other reports against `main` over a synthetic data set (HTML, CSV, PDF text).
9. Docs and ADR 0043 (amend ADR 0036 "Not done"), update `docs/reporting.md`, glossary section E, CLAUDE.md line on the tax summary.
10. End-of-phase report with real test results; stop for approval.

## G. Questions for the owner

1. Layout: (a) 13 columns, (b) new "Gross to net" table (recommended), (c) two-line cells, or (d) hide empty columns? Is 6 pt acceptable on the PDF if (a) is chosen?
2. Table 4 (Payments): leave as it is (recommended; adding any column wraps dates), or add one net column and shorten "Kind"/"Rate source"?
3. Bump `CSV_FORMAT_VERSION` to 3, or keep 2? Add table 2 (organisation) to the CSV?
4. Show an "information only" net total line per category and in EUR (yes in the mock above, last column and total line)? Should the PDF notice be reworded as in D?
5. Use PROD as the reference for what is sent to SBK? PROD has 71 payments DEV lacks and the figures above differ (47,661.74 vs 43,290.09 EUR gross in 2025). Should the DEV database be refreshed from PROD (`restore_backup`, with a backup first)?
6. Spot-check "net as stored equals the statement" (three per organisation against stored originals): do it now by hand with you, or accept the structural evidence?
7. German wording in D: approve or correct.
8. Is the existing page-wide sideways scroll of the HTML report to be fixed together with this (C.4), or separately?
