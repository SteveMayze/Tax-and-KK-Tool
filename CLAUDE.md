# Tax and Healthcare Tool — Standing Instructions for Claude Code

Django web app to record, convert and report personal income from multiple institutions and countries (DE, UK, AU, US). It supports preparing information for German statutory health insurance (SBK) income assessments and the German annual tax return. Single user, developed locally on a MacBook Pro, later deployed in Podman on a Linux server (Ansible) that already runs another Django app.

The app produces general financial summaries. It is NOT an official SBK assessment or tax calculation.

## How to work
- Work one phase at a time (see doc/prompts/PHASES.md (reference only)). Do only the phase I name. At the end of a phase, report and STOP for my approval.
- At the start of a phase: read README and docs/, inspect `git status` and `git log`, confirm scope, list assumptions and blocking questions, propose steps.
- Ask me when a financial rule or requirement is ambiguous. Never invent financial data, exchange rates, dates or classifications.
- Do not overwrite or discard existing work. Keep changes focused. Make small commits that match completed, tested changes.
- Write tests alongside code, run them, and report actual results (not expected ones).
- Keep it simple: Django templates and plain HTML forms, SQLite, no JS framework, no queues, no extra databases, no unneeded dependencies.
- End-of-phase report: what was implemented, key decisions, files changed, checks run with real results, open issues/assumptions, commands to run/verify, proposed next-phase scope.

## Financial principles
1. Preserve the original transaction. Store amount and currency as reported, plus the rate used and resulting EUR amount. Never overwrite originals when recalculating.
2. Keep source data, currency conversion, monthly normalisation and assessment/tax reporting as separate concerns (separate models/services). Calculation logic lives in testable Python services, never in templates.
3. Use `Decimal` and DecimalFields only. Keep full precision internally; round only for display/export.
4. Reports state their basis: period, display currency, gross vs net, actual vs normalised, exchange-rate basis, excluded/missing items.
5. Do not assume a category is taxable, exempt or SBK-relevant. Categories are configurable. Legal rules come later (Phase 7) as versioned, documented, verified rules.

## Currency conversion (decisions made)
- Convention: `EUR amount = original amount × rate` where rate = EUR per 1 unit of original currency. EUR payments always use rate 1.
- Default rate date = payment date (historical). Never silently substitute today's rate, another date or a guess. If a fallback is ever used, label it explicitly.
- Provider: ECB reference rates via Frankfurter, behind a small provider interface so it can be swapped. Verify the API's current behaviour (endpoints, supported currencies, weekend/holiday handling) before coding, and document it.
- Persist per payment: original currency/amount, rate, rate date, provider/source, converted gross/net EUR, status/notes. Rate changes must be auditable. Reports use the stored rate unless I explicitly trigger a recalculation.
- On provider failure: show a clear error, offer manual rate entry, and never lose the user's form input.
- Initial currencies: EUR, GBP, AUD, USD; adding more must not need a schema redesign.

## Frequency and normalisation
Frequencies: monthly, quarterly, half-yearly, yearly, one-off/irregular. Monthly equivalent = amount ÷ 1/3/6/12. State whether gross or net is normalised. One-off items (e.g. capital gains) are never treated as recurring. Support two modes, always labelled: (a) actual payments received in a calendar year, (b) normalised recurring monthly income. An annual total ÷ 12 is an average of actuals, not a recurring figure. Preserve income-period dates separately from payment date when supplied.

## Data model (starting point; improve if justified and document why)
ReportingYear (unique year, notes) → ReportingMonth (unique year+month) → Payment. Also Organisation (name, country, active; avoid duplicate spellings), IncomeCategory (configurable, deactivate rather than delete if referenced; seed: salary, pension, rental, interest, dividends, capital gains, other), ExchangeRateRecord, SourceDocument, ImportBatch.
Payment: month, organisation, category, payment date, optional income period start/end, original currency, gross, nullable net, frequency, comment, source doc/import batch, timestamps. Validate dates, amounts, currency codes. Support explicit corrections/reversals. Payment date determines the reporting month by default; keep them consistent on edit.
Deleting a year deletes its months and payments; deleting a month deletes its payments. Both require UI confirmation. Document deletion behaviour in docs/data-model.md.

## UI (Django templates, responsive on a laptop, keyboard-accessible)
- Display-currency dropdown at the top of every page (EUR, GBP, AUD, USD), persisted in session/preference. It affects presentation only.
- Opening page: list years, add year, delete year (confirm), per-year gross/net totals and a clearly labelled estimated monthly figure.
- Year page: all 12 months (including empty), gross/net, payment count, add/delete month, link back.
- Month page: payments table (date, organisation, category, original amount+currency, gross/net EUR, frequency, normalised monthly where meaningful, comment) with add/edit/delete (confirm). Organisation and category are combo-style: pick existing or add new.
- Payment form flow: validate → get rate → show error or manual-rate option → compute and save → confirmation showing original amount, rate, EUR amount. Editing never silently replaces a stored rate; recalculation is an explicit action.
- No dashboards or charts in the first version.

## Imports (Phase 5 only)
CSV: configurable per-institution profiles, column mapping, preview, invalid-row and duplicate detection, correct/exclude rows, show proposed conversions, explicit confirmation before commit, import history. PDF: text-based extraction first, OCR later only if needed; extract candidates, show source, require human review. Keep extraction logic separate from the core model. Never send documents to an external AI/OCR service unless I explicitly enable it and understand the data sharing.

## Security and privacy
- No personal or identifying data in tracked files. Use git-ignored `local/secrets/`, `local/samples/`, `local/uploads/`, `local/exports/`, with tracked placeholder/README files only. Synthetic sample CSV/PDF for tests only.
- `.gitignore` excludes: virtualenvs, SQLite files, .env files, secrets, uploads, exports/reports, private fixtures, temp files, OCR output. It is not a security boundary: review staged files before every commit.
- Django auth required for all financial views (single user via `createsuperuser`; no hard-coded identity). CSRF, form validation and password hashing via Django defaults. No public static URLs for uploads/reports. Never log payment details, secrets or document contents. SECRET_KEY and DB settings come from environment variables.

## Environment and deployment
- Pin Python and Django versions (verify compatibility first; prefer a current Django LTS) and use a lock file. Runs locally with no Podman or DB server.
- SQLite with a dedicated, env-configurable DB path (default under `local/`, production e.g. `/var/lib/tax-healthcare-tool/db.sqlite3`). Never repo-relative in production. Never touch the existing server app's database.
- Deployment (Phase 8): own image, container name, env, data dir, DB, port/route, health check, WSGI server (not runserver), separate dev/prod settings, backup and tested restore, rollback plan. Inspect the existing Ansible conventions first, propose the smallest change, and ask before modifying shared infrastructure.

## Reports (Phase 6)
Annual summary, monthly breakdown, payment-level, by organisation, by category, original-currency summary, EUR gross/net summary, normalised monthly recurring summary, missing-data/reconciliation. CSV first, PDF later. Reproducible from saved data.

## Documentation to maintain
README.md, docs/architecture.md, data-model.md, financial-calculations.md, imports.md, reporting.md, deployment.md, docs/decisions/ (ADRs).
