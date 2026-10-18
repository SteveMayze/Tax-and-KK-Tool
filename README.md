# Tax and Healthcare Tool

Django app to record, convert and report personal income for German statutory health insurance (SBK) income assessments and the annual tax return. It produces general financial summaries only; it is **not** an official SBK assessment or tax calculation.

Status: Phase 2 (data model and calculation services). Login, a landing page and `/health/` exist; there is no UI for financial data yet. See `CLAUDE.md` for standing instructions and `docs/` for design notes (`data-model.md`, `financial-calculations.md`, `decisions/`).

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

See `.env.example`. Django does not load `.env` itself; export the variables in your shell.

## Migrate, create a user, run
```
python manage.py migrate
python manage.py createsuperuser
DJANGO_DEBUG=1 python manage.py runserver
```
Open http://127.0.0.1:8000/ (redirects to login). `GET /health/` is unauthenticated and returns `{"status": "ok"}`.

## Test
```
python manage.py check
python manage.py test
```

## Private data
`local/` holds the database, secrets, samples, uploads and exports. Its contents are git-ignored; only placeholder READMEs are tracked. Never commit personal or financial data; review `git status` before each commit.
