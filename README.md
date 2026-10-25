# Tax and Healthcare Tool

Django app to record, convert and report personal income for German statutory health insurance (SBK) income assessments and the annual tax return. It produces general financial summaries only; it is **not** an official SBK assessment or tax calculation.

Status: Phase 9A (rootless Podman; Phase 9 added sub-path readiness; phases 9 to 14 are in `docs/prompts/PHASES_2.md`). See `CLAUDE.md` for standing instructions and `docs/` (`architecture.md`, `data-model.md`, `financial-calculations.md`, `exchange-rates.md`, `imports.md`, `reporting.md`, `deployment.md`, `rules/`, `decisions/`).

## Requirements
- Python 3.14 (developed on 3.14.5; Django 5.2 supports 3.10–3.14)
- Django 5.2 LTS (pinned in `requirements.txt`)

## Install
```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration (environment variables)
| Variable | Default | Purpose |
|---|---|---|
| `DJANGO_SECRET_KEY` | insecure dev key | Set a real value anywhere outside local development |
| `DJANGO_DEBUG` | `0` | `1` enables debug mode |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated |
| `DJANGO_DB_PATH` | `local/db.sqlite3` | SQLite file; use an absolute path in production |
| `DJANGO_RATE_PROVIDER` | Frankfurter/ECB | Set to `core.services.rates.ManualOnlyProvider` to work offline (manual rates only) |
| `FRANKFURTER_BASE_URL` / `FRANKFURTER_TIMEOUT` | `https://api.frankfurter.dev` / `10` | Rate service URL (https) and timeout in seconds |
| `DJANGO_UPLOAD_DIR` | `local/uploads` | Where uploaded import files are stored (git-ignored; use an absolute path in production) |
| `DJANGO_URL_PREFIX` | empty | Serve the app under a sub-path, e.g. `/tax-healthcare` (see `docs/deployment.md`) |
| `DJANGO_BEHIND_TLS_PROXY` | `0` | `1` trusts `X-Forwarded-Proto` from a TLS-terminating proxy |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | empty | Comma-separated origins with scheme, for a proxy |
| `RATE_MAX_LOOKBACK_DAYS` | `7` | Oldest acceptable rate date before a payment date |

See `.env.example`. Django does not load `.env` itself; export the variables in your shell.

## Migrate, create a user, run
```
python manage.py migrate
python manage.py createsuperuser
DJANGO_DEBUG=1 python manage.py runserver
```
Open http://127.0.0.1:8000/ (redirects to login). `GET /health/` is unauthenticated and returns `{"status": "ok"}`.

## Exchange rates
Foreign-currency payments are converted with the ECB reference rate for the payment date (via Frankfurter); see `docs/exchange-rates.md`. On macOS with python.org Python, run `/Applications/Python 3.14/Install Certificates.command` once (or set `SSL_CERT_FILE=/etc/ssl/cert.pem`), otherwise lookups fail and you must enter rates manually.

## CSV import
Upload a CSV on the Imports page, review and fix rows, then confirm. The format is described in `docs/imports.md` and a synthetic template can be downloaded from the page.

## Reports
The Reports page offers annual, monthly, payment-level, by-organisation, by-category, original-currency, normalised-monthly and reconciliation reports, each with a stated basis, a CSV download and a landscape PDF (the tax information summary's PDF has a notice and a signature block). See `docs/reporting.md`. Downloads are generated on demand and not stored on the server; keep saved files out of the repository.

## SBK estimate and tax information
Map your categories (Categories page), set your circumstances (Assessment settings), enter annual costs/months earned where relevant, then open the SBK estimate (2026) and tax reports under Reports. These are planning aids, not an SBK assessment or a tax calculation; rule sources and open points are in `docs/rules/`.

## Deployment
The app deploys as its own Podman container on the server (plain HTTP on its own port, no reverse proxy), with daily verified backups. Steps, backup/restore and rollback: `docs/deployment.md`. In short: `make ansible-setup`, commit, `make deploy`, `make createsuperuser`; then open `http://<server>:8889/`. Production uses `config.settings_prod`, which takes everything from environment variables.

## Test
```
python manage.py check
python manage.py test
```

## Private data
`local/` holds the database, secrets, samples, uploads and exports. Its contents are git-ignored; only placeholder READMEs are tracked. Never commit personal or financial data; review `git status` before each commit.
