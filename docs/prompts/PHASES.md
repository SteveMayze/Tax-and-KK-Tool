# Phase prompts for Claude Code

## Reference only. 
Claude Code should not act on this file unless the user pastes a phase prompt from it.


Paste one at a time into Claude Code. Each assumes CLAUDE.md is in the repo root. Claude Code stops for review after each phase. Reply "approved, start Phase N" to proceed.

## Phase 1 — Git and Django scaffolding
Do Phase 1 only. Follow CLAUDE.md.
1. Inspect the directory; `git init` if needed.
2. Create `.gitignore` and the `local/` structure with placeholder READMEs. Verify private paths and DBs are ignored.
3. Create a virtualenv and pinned dependencies (confirm the Python/Django versions first).
4. Create the Django project and one app, with env-configured SQLite path (default `local/db.sqlite3`).
5. Add Django login, a minimal landing page (login required) and an unauthenticated `/health/` endpoint.
6. Add tests for setup, login redirect and health endpoint.
7. Write README (install, run, test, migrate, create superuser).
8. Run `manage.py check` and the tests. Review staged files for secrets/PII. Make the initial commit.
Do not create financial models, conversion, import, reporting or deployment code. Then present results and stop.

## Phase 2 — Data model and calculations
Do Phase 2 only. Implement the models, migrations, currency/money validation, the exchange-rate provider interface (with a fake provider for tests), EUR conversion, frequency normalisation, and annual/monthly aggregation services (actual vs normalised, gross vs net). Test rounding, missing values, invalid data and provider failures. Write docs/data-model.md and docs/financial-calculations.md. Stop for review.

## Phase 3 — UI and manual entry
Do Phase 3 only. Implement years → months → payments views with CRUD, confirmed deletes, organisation and category management, display-currency selection, validation and error messages, and the payment form flow including manual-rate fallback (use the fake/manual provider; the live provider is Phase 4). Test the full manual workflow. Stop for review.

## Phase 4 — Frankfurter/ECB integration and reconciliation
Do Phase 4 only. First verify the Frankfurter API's current behaviour and document it. Integrate it behind the provider interface and persist the rate with provenance. Add manual correction with an audit trail, explicit recalculation, and a view of missing rates/incomplete records. Test date handling, weekends/holidays, failures, repeat requests and recalculation (mock all HTTP). Stop for review.

## Phase 5 — Imports
Do Phase 5 only. CSV profiles, mapping, preview, validation, duplicate detection, explicit confirmation, history and error reporting. Then text-based PDF extraction with human review. OCR only if I ask. Use synthetic samples only. Write docs/imports.md. Stop for review.

## Phase 6 — Reporting and export
Do Phase 6 only. Implement the reports listed in CLAUDE.md with CSV export, each stating its basis, currency, period and exclusions. Test against independently computed expectations. Write docs/reporting.md. Stop for review.

## Phase 7 — SBK and German tax rules (do not start until I confirm the rules are verified)
Do Phase 7 only. Before coding, document each rule and its authoritative source, separating SBK contribution rules from income tax rules, including treatment of foreign income, capital gains, rental income, dividends, interest, expenses, thresholds and exchange-rate requirements. Ask me about anything unverified. Implement each verified rule as a separate, versioned, testable policy, record the rule version and assumptions with every result, and produce explanatory reports. Stop for review.

## Phase 8 — Podman and Ansible
Do Phase 8 only. First inspect the existing host and Ansible conventions (I will give access or paste them). Then define the separate container, config, database and document storage. Create the container build, Ansible role, WSGI server and proxy setup, health checks, backup/restore, upgrade and rollback. Do not modify shared infrastructure without my approval. Stop for review.
