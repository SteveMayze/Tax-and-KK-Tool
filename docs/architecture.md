# Architecture (through Phase 8)

Single Django project (`config`) with one app (`core`), SQLite, server-rendered templates, no JavaScript.

## Layers
- `core/models.py`: data and invariants (see data-model.md).
- `core/services/`: calculation and workflow logic, independent of views (`money`, `rates`, `conversion`, `normalisation`, `aggregation`, `lookups`, `reconciliation`, `imports`, `reports`, `report_csv`, `policy_reports`) and `core/services/policies/` (`sbk`, `tax`: versioned rule policies, see docs/rules/). Templates only display values.
- `core/forms.py`: validation of user input. `core/views*.py`: thin request handlers. `core/templates/core/`: pages.

## Pages (all require login except `/health/`)
| URL | Purpose |
|---|---|
| `/` | Years: totals, annual total / 12 estimate, add year, link to delete |
| `/years/<y>/` | 12 months (existing or "Add month"), year totals, notes, delete year (confirm) |
| `/years/<y>/months/<m>/` | Payments table, actual and normalised totals, add/edit/delete |
| `/payments/<id>/` | Confirmation/detail: original amount, rate, rate date and source, EUR amount |
| `/payments/<id>/recalculate/` | Explicit recalculation from the rate source (replaces the stored rate; history kept) |
| `/payments/<id>/correct-rate/` | Manual rate entry/correction; reason mandatory |
| `/reconciliation/` | Unconverted, manual-rate, date-differs, no-net and inconsistent payments; explicit bulk "convert pending" action |
| `/imports/` and `/imports/<id>/...` | CSV import: upload, review/edit rows, confirm, history, original-file download (see imports.md) |
| `/reports/`, `/reports/<key>/`, `/reports/<key>.csv` | Reports and CSV export (see reporting.md) |
| `/assessment/settings/`, `/assessment/<y>/inputs/` | Assessment settings (rates, care rate, joint assessment) and per-year costs/months earned |
| `/organisations/`, `/categories/` | List, add, edit (incl. deactivate), delete (only if unused) |
| `/display-currency/` | POST: store display currency in the session |

## Payment save flow
Validate form -> resolve organisation/category (existing, case-insensitive, or new) -> assign month from payment date -> obtain rate (EUR: 1; else manual rate if given; else provider) -> on failure show the error, keep all input, reveal manual-rate fields, save nothing (new organisations/months are rolled back) -> on success save original + rate + EUR amounts and show the confirmation page.

Editing: if only amounts/text change, EUR amounts are recomputed with the stored rate (the rate is untouched). If currency or payment date changes, a new rate is required through the same flow. A manual rate on an edit where the basis is unchanged is refused; use Recalculate.

## Rate provider
`settings.RATE_PROVIDER` names the provider class. Default `FrankfurterProvider` (ECB via Frankfurter v2; see exchange-rates.md); `ManualOnlyProvider` works offline. Conversion reuses stored rates, writes provenance records and an audit trail (`core/services/conversion.py`). Reconciliation queries live in `core/services/reconciliation.py`.

## Display currency
Stored per session and shown in the header. Totals still display in EUR: display-currency conversion was not part of Phase 4 and no rates are invented. The UI says so when a non-EUR display currency is chosen.

## Deployment (Phase 8)
Two settings modules: `config.settings` (development, safe defaults) and `config.settings_prod` (container; everything from the environment, refuses to start on missing or weak values). The container runs gunicorn as an unprivileged user with a read-only root file system; data lives on three mounted directories (`/data`, `/uploads`, `/backups`). Plain HTTP on its own port (no proxy). Backup and restore logic is in `core/services/backup.py` with the management commands `backup_db` and `restore_backup`. Infrastructure code is in `infra/` (Ansible playbooks and templates) and the `Makefile`. Details: `docs/deployment.md`.
