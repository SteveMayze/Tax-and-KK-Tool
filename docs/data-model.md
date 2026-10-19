# Data model (Phase 2)

All models live in `core/models.py`. Money uses `Decimal` (see decisions/0001-decimal-precision.md).

| Model | Purpose / key rules |
|---|---|
| `ReportingYear` | Unique `year`, `notes`. |
| `ReportingMonth` | FK year, `month` 1-12, unique (year, month). `ReportingMonth.for_date(d)` gets or creates month and year. |
| `Organisation` | `name`, `country` (ISO alpha-2, optional), `active`. Names are whitespace-normalised and unique case-insensitively, which prevents duplicate spellings. |
| `IncomeCategory` | Configurable `name`, `active`. Seeded: Salary, Pension, Rental, Interest, Dividends, Capital gains, Other. Optional user-chosen `sbk_treatment` and `tax_income_type` mappings; blank = unmapped (never guessed). |
| `AssessmentSettings` | Single row: health-insurance rate choice and whether SBK confirmed it, care-insurance rate choice, joint tax assessment. |
| `AnnualInput` | Per year and SBK treatment (self-employed, rental, capital): annual costs in EUR and first/last month earned. |
| `ExchangeRateRecord` | Append-only rate record: currency, requested date, rate date, rate (EUR per 1 unit), provider, `is_manual`, notes, request URL, response body, retrieval time. Reused for identical provider requests; manual records are always new. |
| `ConversionEvent` | Append-only audit trail per payment: kind (initial, recalculated, manual correction, currency/date edited, amounts edited), the rate record, rate, rate date and EUR amounts that took effect, the values they replaced, and a reason. Deleted with its payment (records are kept). |
| `SourceDocument` | An original file a payment came from: name (display only), SHA-256. |
| `ImportBatch` | One CSV upload: file name, SHA-256, stored path (relative to `UPLOAD_DIR`), status (preview / committed / discarded), warnings, imported/skipped/unconverted counts, link to its `SourceDocument`. |
| `ImportRow` | A staged CSV row: line number, editable and original cell values (JSON), status (valid / invalid / duplicate), errors, notes, excluded / keep-duplicate flags, duplicate reference, the proposed conversion shown in the review (applied at commit), and the payment it created. Deleted with the batch. |
| `Payment` | See below. |

## Payment
- Original transaction: `currency`, `gross_amount`, optional `net_amount`, `withholding_tax` and `expenses` (Phase 10, default 0, original currency; gross = net + withholding tax + expenses, see ADR 0010), `frequency` (monthly, quarterly, half_yearly, yearly, one_off). Never modified by conversion.
- Dates: `payment_date` (determines the reporting month) and optional `income_period_start/end` (end must not precede start).
- Conversion (stored per payment): `conversion_status` (pending/converted), `rate`, `rate_date`, `rate_source`, `rate_record`, `gross_eur`, `net_eur`, `withholding_tax_eur`, `expenses_eur` (all four converted with the same stored rate; the last two are NULL until converted), `conversion_notes`. Computed (not stored): `unallocated = gross - net - withholding_tax - expenses` (None when there is no net amount).
- Corrections/reversals: `kind` (normal/correction/reversal) and `corrects` (FK to the original). Normal gross must be > 0; reversal < 0; correction non-zero; net must share gross's sign; corrections/reversals must reference an original in the same currency. A payment that has corrections cannot be deleted (PROTECT).
- Every `save()` runs `full_clean()`, including the month/date consistency check, so invariants hold outside forms too. Editing `payment_date` into another month requires re-assigning `month` (`ReportingMonth.for_date`); otherwise validation fails.

## Deletion behaviour
- Deleting a `ReportingYear` deletes its months and their payments (cascade). UI confirmation is Phase 3.
- Deleting a `ReportingMonth` deletes its payments (cascade).
- `Organisation` and `IncomeCategory` referenced by payments cannot be deleted (PROTECT); deactivate instead.
- Deleting a `SourceDocument` or `ImportBatch` keeps payments (FK set to null). `ImportRow`s are deleted with their batch. Discarding a pending batch deletes its rows and stored file but keeps the batch record in history.
- `ExchangeRateRecord` referenced by a payment or conversion event cannot be deleted (PROTECT).
- Deleting a payment deletes its `ConversionEvent` history.

## Currencies
`core/currencies.py`: EUR, GBP, AUD, USD. Currency is a validated 3-letter code on the row (not a table), so adding one needs no schema change.
