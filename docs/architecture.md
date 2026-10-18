# Architecture (through Phase 3)

Single Django project (`config`) with one app (`core`), SQLite, server-rendered templates, no JavaScript.

## Layers
- `core/models.py`: data and invariants (see data-model.md).
- `core/services/`: calculation and workflow logic, independent of views (`money`, `rates`, `conversion`, `normalisation`, `aggregation`, `lookups`). Templates only display values.
- `core/forms.py`: validation of user input. `core/views*.py`: thin request handlers. `core/templates/core/`: pages.

## Pages (all require login except `/health/`)
| URL | Purpose |
|---|---|
| `/` | Years: totals, annual total / 12 estimate, add year, link to delete |
| `/years/<y>/` | 12 months (existing or "Add month"), year totals, notes, delete year (confirm) |
| `/years/<y>/months/<m>/` | Payments table, actual and normalised totals, add/edit/delete |
| `/payments/<id>/` | Confirmation/detail: original amount, rate, rate date and source, EUR amount |
| `/payments/<id>/recalculate/` | The only way to replace a stored rate |
| `/organisations/`, `/categories/` | List, add, edit (incl. deactivate), delete (only if unused) |
| `/display-currency/` | POST: store display currency in the session |

## Payment save flow
Validate form -> resolve organisation/category (existing, case-insensitive, or new) -> assign month from payment date -> obtain rate (EUR: 1; else manual rate if given; else provider) -> on failure show the error, keep all input, reveal manual-rate fields, save nothing (new organisations/months are rolled back) -> on success save original + rate + EUR amounts and show the confirmation page.

Editing: if only amounts/text change, EUR amounts are recomputed with the stored rate (the rate is untouched). If currency or payment date changes, a new rate is required through the same flow. A manual rate on an edit where the basis is unchanged is refused; use Recalculate.

## Rate provider
`settings.RATE_PROVIDER` names the provider class. Phase 3 uses `ManualOnlyProvider` (always "unavailable", so foreign payments need a manual rate). Phase 4 swaps in Frankfurter/ECB.

## Display currency
Stored per session and shown in the header. No exchange-rate source for display conversion exists before Phase 4, so totals stay in EUR and the UI says so. No rates are invented.
