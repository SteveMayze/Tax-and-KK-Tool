# Reporting (Phase 6)

Reports are general financial summaries from saved data. They are **not** an official SBK assessment or tax calculation (legal rules are Phase 7). Code: `core/services/reports.py` (data), `core/services/report_csv.py` (CSV), `core/views_reports.py` (pages). Pages: `/reports/`, `/reports/<key>/?year=`, `/reports/<key>.csv?year=`.

## Reports
| Key | Report | Rows | Mode |
|---|---|---|---|
| `annual` | Annual summary (this is also the EUR gross/net summary) | one per year: payments, months with payments, gross EUR, net EUR, gross/12, net/12 | Actual |
| `monthly` | Monthly breakdown (needs a year) | all 12 months incl. empty, plus year total | Actual |
| `payments` | Payment-level detail | every payment: original amount and currency, rate, rate date and source, gross/net EUR, monthly equivalent (recurring only), income period, import batch, comment | Actual |
| `organisation` | By organisation | payments, gross, net, share of gross; largest first | Actual |
| `category` | By category | same | Actual |
| `cross` | Organisation by category (Phase 30) | one row per organisation, one column per category: signed gross EUR per pairing (blank = no payment), row and column totals | Actual |
| `currency` | Original-currency summary | per currency: original gross/net (all payments) next to EUR gross/net (converted payments) | Actual |
| `normalised` | Normalised monthly recurring income (needs a year) | per month: sum of monthly equivalents of recurring payments, recurring count, one-offs excluded | Normalised |
| `sbk` | SBK contribution estimate (needs a year; 2026 only) | month by month: base per SBK income type, assessed base, health, care, total | Estimate (docs/rules) |
| `tax_summary` | Tax information summary | income type x organisation country | Information only |
| `tax_checks` | Tax checks (verified rules, needs a year) | Sparer-Pauschbetrag usage, private-sale Freigrenze, flat-tax reference | Rule checks |
| `reconciliation` | Missing data and reconciliation | one row per flagged payment and issue (same checks as the Reconciliation page) | Data quality |

Period: a specific calendar year or all years (reports marked "needs a year" require one). Year is the reporting year of the payment (its payment date's year).

## Filters (Phase 30, ADR 0031)
Reports can be limited by **organisation** and by **category** as well as by year, with two groups of check boxes (any number ticked) on every report page and on the reports index.
- **Semantics:** within a group the ticked items are combined with OR, the two groups with AND; a group with nothing ticked does not restrict. Ticking everything equals ticking nothing (the basis row still states the filter).
- **Which reports:** annual, monthly, payment-level, by organisation, by category, organisation by category, original-currency, normalised, reconciliation and the tax information summary. **Not** the SBK contribution estimate and the tax checks: they are whole-person assessments computed from all income, so an estimate over part of it would look right and be wrong. On those pages the form is replaced by a note; a filter in the URL is ignored, the page shows a message and a `Filter: Not applied to this report` basis row, and the CSV has the same row.
- **URL parameters:** `year`, and repeated `organisation=<id>` and `category=<id>` (primary keys, sorted; duplicates collapse). Non-numeric, unknown or wrongly cased parameters give the same error and redirect as an unknown year (at most 10 characters of the input are echoed).
- **Basis:** an active filter adds one `Filter` row after `Period`, naming the ticked organisations and categories as stored and the AND/OR rule. It is also in the CSV's `label,value` block and prints. Unfiltered reports have no such row. Every count, exclusion, share and total is computed over the same filtered payment set (`reports._payments`); shares are relative to the filtered total.
- **Empty result:** the message "No payments match this filter" and a CSV with header, basis and no data rows (monthly and normalised still list their 12 empty months).
- **CSV:** same file name unless a filter is active (`report-<key>-<year or all>-filtered.csv`). The format version stays **2**: an unfiltered file is byte-for-byte unchanged and a filtered file only adds one labelled row. Column headings and filter names that start with `=`, `+`, `-`, `@` are protected like other text cells.
- **Options listed:** every organisation and category with at least one payment in any year (inactive ones marked), each with its payment count for the selected period.

## Payments page (Phase 31, ADR 0032, spike on branch `spike/payments-page`)
`payments/` lists payments with the month page's edit, view and delete controls, limited by **year** (default: the current calendar year in Europe/Berlin; `all` = every year), **month** (default: all; ignored with all years, stated in the basis) and the Phase 30 organisation and category check boxes (same semantics, same URL parameters). Basis block above the table: period, filter, amounts. Totals above the table, over exactly the listed payments: per original currency (count, gross, net, withholding tax; never added across currencies) and EUR gross and net at each payment's stored rate, with unconverted payments left out and counted; negative payments and corrections/reversals are listed and totalled as on the month page. Sorted by payment date, organisation, id; no pagination. Bad parameters are an error message and a redirect to the bare page (at most 10 characters echoed). Read only (GET); edit and delete started from here return to this page with the same query string (`next`, accepted only for this page's own path). Not a report: no CSV, and the SBK estimate and tax checks are unaffected.

## Basis block (on every report page and at the top of every CSV)
Period; currency; basis (actual vs normalised); gross/net treatment; exchange-rate basis (counts of EUR, ECB and manual rates, and how many used the nearest earlier ECB rate); excluded/missing items; rounding. Exclusions state the number of unconverted payments with their original gross per currency, converted payments without a net amount, and the number of correction/reversal entries included.

## Rules
- **Currency:** EUR at each payment's stored rate. No rate is looked up while reporting.
- **Gross vs net:** separate columns, never mixed. Net totals include only payments with a net amount; the number without is shown.
- **Unconverted payments** contribute nothing to EUR figures and are reported as exclusions. Original-currency columns do include them.
- **Corrections/reversals** are included as signed amounts.
- **Actual vs normalised** are never combined. The normalised report has no year total (it would count repeated payments again); for an annual figure use the annual summary's "/ 12", which is the annual actual total divided by 12 (always 12) and is an average of actuals, not a recurring figure.
- **Rounding:** all sums are exact `Decimal` over stored values. Amounts are rounded half-up to 2 decimals only when displayed or exported, and totals are rounded once from the unrounded sum, so a total can differ by a cent from the sum of its rounded rows. Percentages show 1 decimal.
- **Reproducible:** a report is a pure function of the saved data (nothing cached or stored). The same data gives the same figures; only the "generated" time changes.

## Gains and losses (Phase 11)
The annual summary and the by-category and by-organisation reports show **Gains EUR** (normal payments above 0), **Losses EUR** (normal payments below 0, signed), **Corrections / reversals EUR** (signed) and **Gross EUR (signed sum)**, which is their sum. A reversal is never counted as a loss. The tax information summary shows losses in their own column and nets nothing across categories; the SBK estimate adds a run-specific note to its basis block when a loss was recorded. No loss-offset rule is applied (unverified, `docs/rules/`).

## Layout (Phase 13)
Each report page shows the title, period selector and CSV button, then the **Basis** block directly above the table, the table with its totals row, and only then the descriptive **Notes**. The SBK estimate's 14 column headings carry an (i) button that opens a popup with the glossary text (label, explanation, source, status) in the selected language; popups and icons never appear in the CSV, and printing hides them but keeps the table and the notes.

## Language (Phase 12)
The interface language (English or German, one setting in the page header) changes headings, notes, labels, number and date formats **on screen**. CSV downloads ignore it: English headings and labels, comma separator, dot decimals, ISO dates, plus `Language` and `Format` rows. German terms come from `docs/glossary.md`.

## CSV format
**Report format version 2** (Phase 10; version 1 had gross and net only): the file starts with a `Report format version` row, and the gross/net reports add `Withholding tax EUR`, `Expenses EUR` and `Unallocated EUR` columns (the original-currency summary and payment-level reports also add the original-currency amounts). The basis block's `Gross/net` row states the identity gross = net + withholding tax + expenses + unallocated. Reconciliation lists payments whose gross differs from net + withholding tax + expenses. The tax information summary shows withholding tax EUR as information only, labelled as not credited.

UTF-8, comma-separated, CRLF line ends. Layout: rows of `label,value` (Report, Generated (UTC), the basis items, Notes), one blank row, the column header row, the data rows, then a totals row where the report has one. Amounts have 2 decimals, a dot as decimal separator and no thousands separator; rates are at stored precision; dates are ISO; empty means not applicable or missing.
Text cells that begin with `=`, `+`, `-`, `@`, tab or CR are prefixed with an apostrophe so spreadsheets do not run them as formulas; numeric cells are never altered. (A text value that really starts with one of those characters will therefore show an extra leading apostrophe.)
Exports contain personal financial data: they are generated on demand for the logged-in user, sent with `Cache-Control: no-store`, and **not written to disk or exposed at any public URL**. Where you save a download is up to you; keep it out of the repository (`local/exports/` is git-ignored for this purpose).

## Tests
`core/test_reports.py` checks every report against figures worked out by hand from a fixed synthetic dataset (documented at the top of the file, including a reversal, a one-off, quarterly and half-yearly items, an unconverted payment, a payment without net, and another year). It also covers the basis text, CSV structure and formatting, single rounding of totals, formula-injection handling, login/method/year validation, reproducibility and read-only behaviour.
