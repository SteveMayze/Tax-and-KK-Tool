# Data model (Phase 2)

All models live in `core/models.py`. Money uses `Decimal` (see decisions/0001-decimal-precision.md).

| Model | Purpose / key rules |
|---|---|
| `ReportingYear` | Unique `year`, `notes`. |
| `ReportingMonth` | FK year, `month` 1-12, unique (year, month). `ReportingMonth.for_date(d)` gets or creates month and year. |
| `Organisation` | `name`, `country` (ISO alpha-2, optional), `active`. Names are whitespace-normalised and unique case-insensitively, which prevents duplicate spellings. |
| `IncomeCategory` | Configurable `name`, `active`. Seeded: Salary, Pension, Rental, Interest, Dividends, Capital gains, Other. No taxable/exempt/SBK meaning is attached (Phase 7). |
| `ExchangeRateRecord` | Append-only audit row: currency, rate date, rate (EUR per 1 unit), provider, `is_manual`, notes, created_at. |
| `SourceDocument`, `ImportBatch` | Minimal placeholders so `Payment` can reference them; extended in Phase 5. |
| `Payment` | See below. |

## Payment
- Original transaction: `currency`, `gross_amount`, optional `net_amount`, `frequency` (monthly, quarterly, half_yearly, yearly, one_off). Never modified by conversion.
- Dates: `payment_date` (determines the reporting month) and optional `income_period_start/end` (end must not precede start).
- Conversion (stored per payment): `conversion_status` (pending/converted), `rate`, `rate_date`, `rate_source`, `rate_record`, `gross_eur`, `net_eur`, `conversion_notes`.
- Corrections/reversals: `kind` (normal/correction/reversal) and `corrects` (FK to the original). Normal gross must be > 0; reversal < 0; correction non-zero; net must share gross's sign; corrections/reversals must reference an original in the same currency. A payment that has corrections cannot be deleted (PROTECT).
- Every `save()` runs `full_clean()`, including the month/date consistency check, so invariants hold outside forms too. Editing `payment_date` into another month requires re-assigning `month` (`ReportingMonth.for_date`); otherwise validation fails.

## Deletion behaviour
- Deleting a `ReportingYear` deletes its months and their payments (cascade). UI confirmation is Phase 3.
- Deleting a `ReportingMonth` deletes its payments (cascade).
- `Organisation` and `IncomeCategory` referenced by payments cannot be deleted (PROTECT); deactivate instead.
- Deleting a `SourceDocument` or `ImportBatch` keeps payments (FK set to null).
- `ExchangeRateRecord` referenced by a payment cannot be deleted (PROTECT).

## Currencies
`core/currencies.py`: EUR, GBP, AUD, USD. Currency is a validated 3-letter code on the row (not a table), so adding one needs no schema change.
