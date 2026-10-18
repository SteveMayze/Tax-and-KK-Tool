# Financial calculations (Phase 2)

Code: `core/services/` (`money`, `rates`, `conversion`, `normalisation`, `aggregation`). No calculation logic lives in templates.

## Conversion
- `EUR amount = original amount x rate`, rate = EUR per 1 unit of original currency. EUR uses rate 1 (source `identity`, no provider call).
- The rate comes from a `RateProvider` for the payment date. `FakeRateProvider` exists for tests; Frankfurter/ECB arrives in Phase 4 behind the same interface.
- A provider returns the date its rate applies to. If that differs from the payment date, the difference is recorded in `conversion_notes`; nothing is substituted silently.
- Failure (provider error, no rate, invalid manual rate) raises `ConversionError` and leaves the payment unchanged, so the caller can show the error, offer manual entry and keep form input. A manual rate must be positive and is stored with source `manual`.
- Each applied rate is appended as an `ExchangeRateRecord`. Converting an already-converted payment fails unless `recalculate=True`, which is an explicit action and leaves earlier records intact.
- EUR results are computed exactly, then quantised to 6 dp for storage only.

## Normalisation
Monthly equivalent = amount / 1 (monthly), 3 (quarterly), 6 (half-yearly), 12 (yearly), at full precision. One-off/irregular items, unknown frequencies and missing amounts give `None`; one-offs are never treated as recurring.

## Aggregation (EUR, stored rates)
Two modes, always labelled in the result's `basis`:
- **Actual**: sum of stored gross/net EUR of payments in the month/year. Reversals and corrections are included as signed amounts.
- **Normalised**: sum of monthly equivalents of recurring payments, one-offs excluded and counted. Designed for one month's payments; applying it to a whole year would over-count repeated monthly payments.
- `year_average_of_actuals` = annual actual / 12, labelled as an average of actuals, not a recurring figure.

Gross and net are summed separately. Net totals include only payments that have a net amount; `net_missing_count` reports the rest. Payments without a stored conversion are excluded from all sums and reported as `unconverted_count`. Nothing is treated as zero silently.

## Opening-page monthly figure (decided)
The estimated monthly figure per year is the annual actual total / 12, shown for gross and net separately and labelled "annual total / 12 (average of actuals)". This mirrors how the health insurance assessment is understood to work (annual income / 12). The divisor is always 12, even for a partial year; the UI shows how many months contain payments. It is not a recurring-income figure and not an official SBK calculation (legal rules are Phase 7). The normalised per-month view remains available separately.
