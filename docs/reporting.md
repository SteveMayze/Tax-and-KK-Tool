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
| `currency` | Original-currency summary | per currency: original gross/net (all payments) next to EUR gross/net (converted payments) | Actual |
| `normalised` | Normalised monthly recurring income (needs a year) | per month: sum of monthly equivalents of recurring payments, recurring count, one-offs excluded | Normalised |
| `sbk` | SBK contribution estimate (needs a year; 2026 only) | month by month: base per SBK income type, assessed base, health, care, total | Estimate (docs/rules) |
| `tax_summary` | Tax information summary | income type x organisation country | Information only |
| `tax_checks` | Tax checks (verified rules, needs a year) | Sparer-Pauschbetrag usage, private-sale Freigrenze, flat-tax reference | Rule checks |
| `reconciliation` | Missing data and reconciliation | one row per flagged payment and issue (same checks as the Reconciliation page) | Data quality |

Period: a specific calendar year or all years (reports marked "needs a year" require one). Year is the reporting year of the payment (its payment date's year).

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

## CSV format
UTF-8, comma-separated, CRLF line ends. Layout: rows of `label,value` (Report, Generated (UTC), the basis items, Notes), one blank row, the column header row, the data rows, then a totals row where the report has one. Amounts have 2 decimals, a dot as decimal separator and no thousands separator; rates are at stored precision; dates are ISO; empty means not applicable or missing.
Text cells that begin with `=`, `+`, `-`, `@`, tab or CR are prefixed with an apostrophe so spreadsheets do not run them as formulas; numeric cells are never altered. (A text value that really starts with one of those characters will therefore show an extra leading apostrophe.)
Exports contain personal financial data: they are generated on demand for the logged-in user, sent with `Cache-Control: no-store`, and **not written to disk or exposed at any public URL**. Where you save a download is up to you; keep it out of the repository (`local/exports/` is git-ignored for this purpose).

## Tests
`core/test_reports.py` checks every report against figures worked out by hand from a fixed synthetic dataset (documented at the top of the file, including a reversal, a one-off, quarterly and half-yearly items, an unconverted payment, a payment without net, and another year). It also covers the basis text, CSV structure and formatting, single rounding of totals, formula-injection handling, login/method/year validation, reproducibility and read-only behaviour.
