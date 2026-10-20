# Architecture (through Phase 8)

Single Django project (`config`) with one app (`core`), SQLite, server-rendered templates, no JavaScript.

## Layers
- `core/models.py`: data and invariants (see data-model.md).
- `core/services/`: calculation and workflow logic, independent of views (`money`, `rates`, `conversion`, `normalisation`, `aggregation`, `lookups`, `reconciliation`, `imports`, `reports`, `report_csv`, `policy_reports`) and `core/services/policies/` (`sbk`, `tax`: versioned rule policies, see docs/rules/). Templates only display values.
- PDF import (Phase 15, ADR 0015): `pdf_text` (bytes to page text, plain or layout mode) -> `statement_readers` (ordered registry; exactly one reader claims a file; a reader returns a `StatementResult` of zero, one or many rows plus notices and a fingerprint) -> `pdf_imports` (staging into `ImportBatch`/`ImportRow`, the only step that touches the database). `amounts` holds the US/UK/German amount parsers, `organisations` the shared security-name tidier and the fixed bank names, `pdf_inventory` the read-only folder report behind `tools/pdf_inventory.py`.
- PDF readers (Phases 14 to 23), one module each behind the registry in `statement_readers.READERS`: `dividend_statements` and `interest_statements` (Phase 14), `hsbc_savings`, `rvb_account`, `etrade_client`, `fidelity_stock_plan`, `hodges_rental`, `mecu_account`, `ordminnett_cmt` (+ `ordminnett_valuation`). A reader may add a batch step `settle(items)`, run by the staging after every file is read and before files are classified, for values that depend on several statements: Fidelity (withholding postings across statements), MECU (annual payment summary check), Ord Minnett (overlap dedupe, quarter pairing, creation of the interest rows). `tools/pdf_inventory.py` and `tools/collision_report.py` (read-only, counts only) use the same readers.
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

## Payment save flow
Validate form -> resolve organisation/category (existing, case-insensitive, or new) -> assign month from payment date -> obtain rate (EUR: 1; else manual rate if given; else provider) -> on failure show the error, keep all input, reveal manual-rate fields, save nothing (new organisations/months are rolled back) -> on success save original + rate + EUR amounts and show the confirmation page.

Editing: if only amounts/text change, EUR amounts are recomputed with the stored rate (the rate is untouched). If currency or payment date changes, a new rate is required through the same flow. A manual rate on an edit where the basis is unchanged is refused; use Recalculate.

## Rate provider
`settings.RATE_PROVIDER` names the provider class. Default `FrankfurterProvider` (ECB via Frankfurter v2; see exchange-rates.md); `ManualOnlyProvider` works offline. Conversion reuses stored rates, writes provenance records and an audit trail (`core/services/conversion.py`). Reconciliation queries live in `core/services/reconciliation.py`.

## Currency display
There is no display-currency selector (removed in Phase 9, ADR 0006). Amounts are shown in their own currency; reports and totals are EUR at each payment's stored rate.

## Language and locale (Phase 12, ADR 0012)
One setting (`AssessmentSettings.language`) is activated per request by `core.middleware.LanguageMiddleware`. Texts use Django's gettext (`core/locale/de`); numbers and dates use `core/formats` and `core.services.i18n` (display only, never in calculations). CSV rendering is forced to English and to the fixed CSV format.

## Deployment (Phase 8; rootless since Phase 9A, see ADR 0007 and docs/podman-explained.md)
Two settings modules: `config.settings` (development, safe defaults) and `config.settings_prod` (container; everything from the environment, refuses to start on missing or weak values). The container runs gunicorn as an unprivileged user with a read-only root file system; data lives on three mounted directories (`/data`, `/uploads`, `/backups`). Plain HTTP on its own port (no proxy). Backup and restore logic is in `core/services/backup.py` with the management commands `backup_db` and `restore_backup`. Infrastructure code is in `infra/` (Ansible playbooks and templates) and the `Makefile`. Details: `docs/deployment.md`.
