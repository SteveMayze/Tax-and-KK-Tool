# PHASES_10.md: Tax and Healthcare Tool, Phases 35 to 39 (storage on /u01, then PostgreSQL)

Save this file as `docs/prompts/PHASES_10.md`. **Do not edit or overwrite `PHASES.md` to `PHASES_9.md`.** If you find an error in them, record it in your end-of-phase report. Phases 1 to 34 are implemented (Phase 20 deliberately not) and the app is in production behind the gateway. This file contains no secrets, no disk UUID and no addresses; keep it that way.

How to use: open a session in the `Tax-and-KK-Tool` repo and say "Read `docs/prompts/PHASES_10.md` and `CLAUDE.md`. Do only Phase 35" (then 36, 37, 38, 39). One phase per session, then stop and report. `CLAUDE.md` applies in full.

## Why these phases

The home server `cornil` (Debian 13, rootless Podman + Quadlet as the user `homeapps`) keeps this app's SQLite database, uploads and backups on the eMMC (about 27 GB root partition). A 1 TB USB disk is now mounted at `/u01`. The agreed strategy: (1) move this app's files to `/u01`; (2) run the app on a **shared PostgreSQL container** (database `taxtool`, role `taxtool`), after the pilot app (parts-db) has run on it successfully. The shared PostgreSQL, its network, the nightly dumps, the offsite backup and disk health belong to the `cornil-gateway` repo (`docs/prompts/U01-POSTGRES-PLATFORM.md`); the pilot is in the Parts-DB repo (`docs/prompts/PARTSDB-U01-POSTGRES.md`). This repo contains **no** Caddy configuration and **no** PostgreSQL server configuration, only the client side.

This is the owner's financial and health-insurance data. A migration must be provably lossless and reversible, and nothing from the data may appear in a report, log, test, ADR or commit message: counts and hashes only.

## Execution modes (every phase carries one)

- **[LOCAL]** needs the server (SSH as `homeapps`), the live data or the owner's sudo. Run in a normal Claude Code session on the Mac.
- **[CLOUD OK]** needs only a checkout (this repo's `CLAUDE.md` and `docs/prompts/` are tracked, so a cloud session sees them). Work on a branch, open a pull request, do not merge. It cannot reach the server or see git-ignored files (`local/`, `infra/inventory.ini`), and it has no real data: use placeholders and synthetic data only. If it needs the server, stop and say what is needed.
- **[OWNER]** commands the owner runs by hand (sudo, reboot). Give the exact command and what it changes.

## Standing rules

1. Read first: `CLAUDE.md` (all of it applies: Decimal only, state the basis of every figure, separation of concerns, privacy, plain language), `docs/deployment.md`, `docs/podman-explained.md`, ADR 0005, 0007, 0008, 0009 and 0029, `core/services/backup.py`, `config/settings.py`, `config/settings_prod.py`, `core/test_deploy_artifacts.py`, and the code each phase names.
2. One phase only, in order. End with the end-of-phase report (what was done, key decisions, files changed, checks with real results, deviations, open issues, how to verify by hand, proposed next scope) and **stop for "go"**.
3. **Ask first.** Put the phase's questions in the first reply together with what you found when you verified the current state. If unanswered, use the stated default, say so at the top of your work and continue.
4. **Verify the current state.** This file was written from a read of the repo, not from running it. Where it says "verify", read the code, say what you found and adapt.
5. **Do not overwrite or discard existing work.** Do not touch the owner's database or any stored payment, except in Phases 37 and 39 where the steps say how and the owner has said "go". The git-ignored `local/` folders are not touched. Never invent financial data, rates, dates or classifications.
6. **Privacy.** Real names of organisations, securities, accounts or categories come only from the database at runtime. Nothing from the owner's data in tracked files, test names, fixtures, docs, ADRs, commit messages or the report. Output shown to the owner is limited to counts, hashes and names of files. Review staged files before every commit; `.gitignore` is not a security boundary.
7. **Unchanged behaviour stays unchanged.** Every page, report and CSV this plan does not name is identical afterwards, and existing tests stay green. Where a test must change, list it and say why.
8. **No sudo for routine deploys** (a test enforces it; the only existing exceptions are `bootstrap-rootless` and `migrate-copy`). **No data is ever deleted** by a playbook: no `state: absent`, `rsync --delete`, `rm` or `prune` of data. Restores move data aside.
9. **No new dependency** except `psycopg` (Phase 38). No JS. `CLAUDE.md` currently says "SQLite ... no extra databases": that line is superseded by the owner's decision above; record it in **ADR 0035** (next free number; verify the sequence) and amend `CLAUDE.md` and `docs/architecture.md` in Phase 38, not before. Never delete an old ADR.
10. Acceptance criteria are checkable; report each as met, not met, or not verifiable here, with evidence. Every corner-case id gets a test named after it.
11. Language (Phase 12): any new user-visible text through gettext, English and German.

## Shared contract v1 (identical in all three repos; if you disagree, say so in your first reply, do not diverge silently)

**Server.** `cornil.fritz.box`, Debian 13, rootless Podman + Quadlet as `homeapps` (linger on). The disk is mounted at `/u01` (fstab with `nofail`); the unmounted mount point is immutable so nothing can be written there by accident.

**Who owns what.**

| Thing | Owner |
|---|---|
| `gateway` network, Caddy | `cornil-gateway` |
| `db` network (`db.network`), the `postgres` container, creating databases and roles, nightly dumps, restic, disk health | `cornil-gateway`, platform area |
| App containers, their settings, migrating their own data, their own backup archives | the app repo |

No repo writes into another repo's files, units, folders or secrets. The shared objects are exactly: the `gateway` network, the `db` network, the `postgres` container and the Podman secret *names* below.

**Layout.**

```
/u01/data/postgres/                       PostgreSQL data (platform)
/u01/data/backups/postgres/<db>/          nightly dumps (platform)
/u01/data/parts-db/{data,media,backups}   parts-db
/u01/data/tax-healthcare-tool/{data,uploads,backups}   this app (data/ holds SQLite until the cutover, then legacy-sqlite/)
/u01/apps/tax-healthcare-tool/build/      image build contexts (were ~/tax-healthcare-tool/build)
```

Stays on the eMMC, never on the removable disk: each app's `config/env` (Django secret key), the Podman image storage, and the Podman secrets. Image builds use `/u01` for temporary files.

**Database.** Container `postgres` on the Podman network `db`. Not published on the host: reachable only from containers that join `db`, as host `postgres`, port 5432. Official `postgres` image, exact tag and major version fixed by the platform repo (default major 17). `scram-sha-256`. This app: database `taxtool`, role `taxtool` (not a superuser, owns only its database).

**Password.** Podman secret `taxtool-db-password`, created on the server by the platform repo. The unit reads it with `Secret=taxtool-db-password,type=env,target=DJANGO_DB_PASSWORD`. Never in git, never in an env file, never printed.

**App settings contract.** If `DJANGO_DB_HOST` is unset the app uses SQLite exactly as today (development and tests unchanged). Otherwise PostgreSQL from `DJANGO_DB_HOST`, `DJANGO_DB_PORT` (default 5432), `DJANGO_DB_NAME`, `DJANGO_DB_USER`, `DJANGO_DB_PASSWORD`. Driver `psycopg` 3, pinned.

**Units.** Each app unit gets Network=db.network (in addition to gateway.network) and starts after postgres.service. The /u01 guard, proven on the server, goes in the unit’s [Service] section: ExecStartPre=/usr/bin/mountpoint -q /u01, Restart=on-failure, RestartSec=10, StartLimitIntervalSec=0. RequiresMountsFor=/u01 alone does not work in a user unit, because it only orders the start and never blocks it.

**Not in the contract: text ordering.** PostgreSQL sorts text by locale rules, SQLite by bytes. Anything displayed or exported in an order must have an explicit, tested ordering.

---

## Phase 35: Inspect and design  [LOCAL, read-only]

Change nothing on the host or in the repo, except writing the findings and ADR drafts (ADR 0035 proposed: storage on `/u01` and PostgreSQL).

### Questions for the owner (defaults in brackets)
1. Soak time: how long must parts-db have run on PostgreSQL, with a successful restore drill, before this app is migrated [7 days]?
2. How long to keep the SQLite copy after the cutover [at least until the next tax return and SBK assessment that use the migrated data are filed; the owner decides removal, you never remove it].
3. Maintenance window [any evening].
4. Is anything else (a script, a spreadsheet, a connector) reading the SQLite file directly [no]? If yes it breaks at the cutover.

### Inspect
- **Repo:** `config/settings.py` and `settings_prod.py` (`DATABASES`, `_absolute_path('DJANGO_DB_PATH')`), `core/services/backup.py` and the `backup_db`, `restore_backup` and `data_fingerprint` commands (they use the `sqlite3` module and file paths), `infra/` (deploy, rollback, restore, restore-drill, fetch-backup, status, verify-migration, migrate-from-rootful, Quadlet and backup templates), the `Containerfile` (`python:3.14.5-slim-trixie`: confirm the PostgreSQL client tools exist for that release at a major version at least the server's), `requirements.txt` (is there a `psycopg` wheel for this Python version? if not, say which fallback), `core/test_deploy_artifacts.py` and every test that asserts a path or a string in a unit.
- **SQLite-specific risks, each answered with file and line:** the six `JSONField`s (`warnings`, `data`, `original`, `errors`, `notes`, `provenance`: SQLite keeps JSON as text, PostgreSQL `jsonb` normalises key order and whitespace; does any code or hash depend on the stored text?), `DecimalField` values (SQLite stores them with numeric affinity: can a stored value differ from what Django returns? the comparison in Phase 37/39 must be exact), all `order_by`, `ordering`, `distinct` and `Meta.ordering` that reach a page, report or CSV, the duplicate key that lower-cases the organisation name (`imports.py`), `TransactionTestCase` and `select_for_update` in `test_breakdown.py` and `test_loss.py` (SQLite ignores row locks, PostgreSQL does not), raw SQL, and the migrations (15: do any use `RunSQL`, `RunPython` with SQLite assumptions or non-portable defaults?).
- **Server (read-only, as `homeapps`, scrubbed):** `podman inspect tax-healthcare-tool-web --format '{{json .Mounts}}'` (Source and Destination only), sizes of `data`, `uploads`, `backups`, free space on the eMMC and on `/u01`, the existing backups and their ages, and the app's `data_fingerprint` of the live data (counts and hashes only).

### Deliver
A findings table; the migration method with its trade-offs (`dumpdata`/`loaddata` versus `pgloader` versus a custom ORM copy; recommend one; consider `contenttypes`, permissions, sequences, the JSON fields and decimal exactness); a proposal for **report checksums**: a read-only management command that prints the SHA-256 of every report CSV for every reporting year, so that "the reports are identical before and after" can be proven without showing a single value; how backups work on PostgreSQL (one verified archive still holds database and uploads together; propose `pg_dump -Fc` by a client in the app image versus relying on the platform's nightly dump alone; recommend one); the list of existing tests that will have to change, each with a reason; draft ADR 0035.

Acceptance: no change anywhere; each question asked or defaulted; no data value printed.

---

## Phase 36: Storage relocation code, not deployed  [CLOUD OK]

Branch `feat/u01-storage`. Start after Phase 35 and after the platform's U0 has confirmed the contract. (If Parts-DB's PD1 is merged, follow its design where it fits, so the two repos stay alike.)

1. `infra/group_vars/all.yml`: separate the **config** root (`/home/homeapps/tax-healthcare-tool/config`, the 0600 secret file, stays on the eMMC) from `storage_root: /u01/data/tax-healthcare-tool` (`data`, `uploads`, `backups`) and `build_root: /u01/apps/tax-healthcare-tool/build`. Update `podman_run_flags`, the Quadlet template, the backup service, `manage.sh.j2` and all playbooks consistently. Container-side paths (`/data`, `/uploads`, `/backups`) do not change.
2. The `/u01` guard in the Quadlet unit and the backup service exactly as decided by the platform's ADR 0006 (use `RequiresMountsFor=/u01` as a placeholder if that ADR is not yet merged, and say so in the pull request).
3. `deploy.yaml` preconditions: assert `/u01` is a real mount point and the storage folders exist and belong to the service user, failing politely **before** any change. Folders are only created, never removed or emptied.
4. `infra/relocate-storage.yaml` and `make relocate-storage`: stop the unit, take a verified backup (`backup_db --label pre-relocate`), copy `data`, `uploads`, `backups` to the new root without any delete option, compare file lists and SHA-256 of every file (names and hashes only), show the comparison, and switch the unit to the new paths only after a second explicit confirmation variable. Old folders stay untouched. `make rollback-storage` points the unit back. Document in `docs/deployment.md` in plain language.
5. Update tests deliberately (the assertions about mounts `['/data','/uploads','/backups']` and their sources, `DJANGO_DB_PATH=/data/db.sqlite3`, the backup-timer tests): list each changed test and why. Add tests: guard present in both units, the relocation playbook has no deleting option and no `become`/`sudo`, preconditions run before the first change, no path contains a parts-db name.
6. ADR 0035 final text for the storage part; README and `docs/deployment.md`.

Acceptance: `.venv/bin/python manage.py test` passes; `make syntax` passes; the rendered unit mounts only `/u01/data/tax-healthcare-tool/*` and the config location; nothing deployed.

---

## Phase 37: Relocate to /u01 on the server  [LOCAL + OWNER]

Start after the Phase 36 pull request is merged and the owner says "go". Relocate parts-db first if it has not been done; do one app at a time.

1. `make status`, then `make backup-now` and `make fetch-backup` (a verified copy on the Mac). Run `data_fingerprint` on the live data and keep the counts and hashes in the report.
2. `make deploy`, then `make relocate-storage`; show the comparison; ask for confirmation before the switch.
3. Verify: mounts show only `/u01/data/tax-healthcare-tool/*`; `https://cornil.fritz.box/tax-healthcare/` loads, the owner logs in, opens a year, an import preview works, a stored original opens; `data_fingerprint` after equals before; a new backup lands in `/u01/data/tax-healthcare-tool/backups`.
4. **Owner reboots** (give the command): `/u01` mounted by itself, container healthy, gateway answering, no I/O errors in `dmesg`.
5. Old folders stay; report their size and give (do not run) the removal command for the owner's decision.

Acceptance: items 3 and 4 shown with real output; fingerprints equal before and after; `make rollback-storage` rehearsed with `--check`; nothing deleted.

---

## Phase 38: PostgreSQL support, not deployed  [CLOUD OK]

Branch `feat/u01-postgres`. Start after Phase 36 is merged (both edit `infra/`), and after the Parts-DB pilot has settled its design (read its merged PostgreSQL pull request and reuse its approach where sensible).

1. **Settings.** Implement the app settings contract in `config/settings.py` and `settings_prod.py`: SQLite unchanged when `DJANGO_DB_HOST` is unset; otherwise the five variables, all **required** in production (the existing `_required` style), `connect_timeout` set, no password in logs. Add `psycopg` (pinned; verify the wheel for the image's Python; fall back to `psycopg` with `libpq5` in the image if needed, and say why). `DJANGO_DB_PATH` keeps working for SQLite.
2. **Image.** PostgreSQL client tools in the `Containerfile` at a major version not older than the server's; every other property of the image unchanged (non-root, read-only root, no new capabilities).
3. **Backups.** `core/services/backup.py` and the commands: for PostgreSQL, `pg_dump -Fc` plus the uploads in **one verified archive** (SHA-256 per file, row counts through the ORM, app version, engine in the manifest), re-verified after writing (`pg_restore --list`), same retention and labels. `restore_backup` restores into a **new, empty** database and swaps only after explicit confirmation, renaming the old database aside; it never drops the live one. SQLite behaviour unchanged and still tested.
4. **Engine-neutral `data_fingerprint`**: row counts and content hashes computed through the ORM with a stable primary-key order. Decimals are compared as exact strings (never floats), JSON as canonical JSON (sorted keys, fixed separators), so SQLite and PostgreSQL fingerprints of the same data are equal. It never prints a value.
5. **`report_checksums`** (read-only management command, from Phase 35's proposal): for every reporting year and every report that has a CSV, print `report-name year sha256`. Reports must produce byte-identical CSV on SQLite and PostgreSQL for the same data.
6. **Ordering.** Wherever Phase 35 found a dependence on SQLite's ordering, make the ordering explicit and add a test with umlauts, mixed case and numbers that passes on both engines. Add a **golden test**: build a synthetic data set through the ORM (invented names only), generate every report CSV, and compare the checksums between the SQLite run and the PostgreSQL run (the PostgreSQL run is `make test-pg`).
7. **Tests.** The whole suite passes on SQLite (default) **and** on PostgreSQL, including `test_breakdown.py` and `test_loss.py` (check that `select_for_update` and transactions behave). Add `make test-pg` (a throw-away PostgreSQL container via `podman run --rm` on the Mac, the five variables set, container removed afterwards). If the cloud session cannot run a PostgreSQL server, mark the PostgreSQL run **not verifiable here**, give the owner `make test-pg`, and do not claim it passed. Add tests for the settings contract and the rendered unit (network, secret, no password text, no published database port).
8. **Deployment files.** Quadlet template: `Network=db.network`, `Requires=` and `After=postgres.service`, `Secret=taxtool-db-password,type=env,target=DJANGO_DB_PASSWORD`, the four non-secret variables; group_vars `db_host`, `db_name`, `db_user`, `use_postgres: false` by default so merging deploys nothing different; `deploy.yaml` precondition (when `use_postgres` is true, check by name that `db.network` and the secret exist; never read a value). Update `verify-migration.yaml` and `restore-drill.yaml` for PostgreSQL, and keep their SQLite path.
9. **Documents.** ADR 0035 final; amend `CLAUDE.md` ("Keep it simple: ... SQLite ... no extra databases", the Environment and deployment paragraph, the Decisions note) and `docs/architecture.md`, `docs/deployment.md`, `docs/data-model.md` (engine notes), `README.md`, `.env.example`.

Acceptance: SQLite suite passes unchanged apart from the listed tests; PostgreSQL suite passes via `make test-pg` (or is marked not verifiable here); the golden test passes on both engines; `use_postgres: false` renders the same unit as before apart from the guard; nothing deployed.

---

## Phase 39: Cutover to PostgreSQL, then close out  [LOCAL + OWNER]

Start only when: the platform's U2 is done (`taxtool` exists), parts-db has run on PostgreSQL for the agreed soak time with a passing restore drill, Phases 37 and 38 are merged and deployed code is current, the platform's nightly dump timer is running (U4 is ideal), and the owner says "go" for a maintenance window.

1. **Baseline (before touching anything):** `make backup-now`, `make fetch-backup`, `data_fingerprint` and `report_checksums` on the live SQLite data. Keep the counts and hashes in the report.
2. **Rehearse on a copy.** Restore the latest backup into a scratch database `taxtool_rehearsal` (created through the platform repo's tooling), run the chosen migration method, then `data_fingerprint` on both sides: equal. Run `report_checksums` against the rehearsal: identical to the baseline. Drop the rehearsal database (one you created yourself, with the owner's go).
3. **Cutover.** Announce the downtime; stop the app; take the final SQLite archive; migrate into `taxtool`; reset sequences; `data_fingerprint` equal; set `use_postgres: true`; `make deploy`; wait healthy; `report_checksums` on PostgreSQL identical to the baseline.
4. **Verify:** `https://cornil.fritz.box/tax-healthcare/` through the gateway; the owner logs in, opens each reporting year, one import preview, one report in the browser; a stored original opens; `make backup-now` writes a PostgreSQL archive; `make restore-drill` shows it restores into a throw-away database; the platform's dump of `taxtool` exists under `/u01/data/backups/postgres/taxtool/`.
5. **Rollback (rehearse with `--check`, do not run):** `use_postgres: false`, redeploy; the SQLite file is untouched until the owner removes it. After verification move it (a move, not a deletion) to `/u01/data/tax-healthcare-tool/legacy-sqlite/`.
6. **Owner reboots:** PostgreSQL first, then the app healthy, the gateway answering.
7. **Close-out:** update `CLAUDE.md`'s decisions note, `docs/deployment.md`, `README.md`, ADR 0035 status accepted. State when the owner may remove the legacy SQLite copy (give the command, do not run it). Tell the owner the quarterly restore rehearsal for this app (platform repo `docs/recovery.md`) and what to check.

Acceptance: fingerprints and report checksums equal before and after, shown with real output; rollback rehearsed; restore drill passes; no SQLite file deleted; no value from the data and no secret in any output.

---

## End-of-phase report (every phase)
What was implemented, key decisions, files changed, checks run with real results, deviations, open issues and assumptions, commands to run or verify, what was not verified and why, each acceptance criterion met / not met / not verifiable here, proposed next scope. Then wait for "go".
