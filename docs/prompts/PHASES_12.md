# PHASES_12.md: Tax and Healthcare Tool, Phases 35 to 39 (move to /u01, then PostgreSQL), revised after the parts-db pilot

Save this file as `docs/prompts/PHASES_12.md`. It **replaces `PHASES_10.md` for Phases 35 to 39**. None of those phases was started, and this file adds what the parts-db pilot taught us. **Do not edit or overwrite `PHASES.md` to `PHASES_11.md`.** If you find an error in them, or something here that contradicts them, record it in your end-of-phase report. Phases 1 to 34 and 40 to 42 are implemented (Phase 20 deliberately not), plus the fix branches up to ADR 0044. The app is in production behind the gateway. This file contains no secrets, no disk UUID, no addresses and no user names other than the service user `homeapps`. Keep it that way.

How to use: open a session in the `Tax-and-KK-Tool` repo and say "Read `docs/prompts/PHASES_12.md` and `CLAUDE.md`. Do only Phase 35" (then 36, 37, 38, 39). One phase per session, then stop and report. `CLAUDE.md` applies in full. The phase IDs are the same as the IDs in the plan sheet (`cornil-gateway` `docs/prompts/cornil-u01-postgres-execution-plan.xlsx`, the master copy).

## Why these phases

The home server `cornil` (Debian 13, rootless Podman + Quadlet, run by the user `homeapps`) keeps this app's SQLite database, the stored original statements (PDF/CSV uploads, including zips of originals) and its backups under `/home/homeapps/tax-healthcare-tool/` on the eMMC. The 1 TB USB disk is mounted at `/u01`. The agreed strategy is:

1. Move this app's files to `/u01` (Phase 37).
2. Run the app on the **shared PostgreSQL container** that the `cornil-gateway` repository already runs, using database `taxtool` and role `taxtool` (Phase 39).

**PostgreSQL is not installed by this repository.** The platform repository (`cornil-gateway`, ADR 0005) installed PostgreSQL 17.11 on 2026-11-03 (container `postgres` on the Podman network `db`, data in `/u01/data/postgres`). It also created the empty database `taxtool`, the role `taxtool` and the Podman secret `taxtool-db-password`. It runs the nightly `pg_dump` (which already includes `taxtool`), the offsite restic copy to the owner's NAS, and the disk-health checks. This repository is only the **client**: settings, driver, client tools in the image, unit lines, its own backup archive, and moving its own data. If the owner wants a separate PostgreSQL container for this app instead, that contradicts ADR 0005 and contract v1. **Stop and ask.** Do not build one.

parts-db was the pilot and is finished. It was moved to `/u01` on 2026-11-08 and cut over to PostgreSQL on 2026-11-08. Fingerprints were identical, the restore drill gave `DRILL_OK`, the reboot test passed, and the 7-day soak ran from 2026-11-13 to 2026-11-20. Read its ADR 0003 (Parts-DB repo, `docs/adr/0003-storage-on-u01-and-postgresql.md`) before Phase 36. Reuse its design wherever it fits so that the two repositories stay alike.

**This is the owner's financial and health-insurance data, and keeping it intact is the top priority of this plan.** A migration must be provably lossless and reversible. Nothing from the data may appear in a report, log, test, ADR or commit message: counts, hashes and file names of our own artefacts only.

## Lessons from the parts-db pilot (apply them; verify each against this repo)

- **`dumpdata` loses precision.** It cut timestamps to milliseconds while SQLite keeps microseconds. Row counts were equal, but the fingerprint hashes differed, and only the fingerprint showed it. parts-db added `dump_exact` (a dumpdata with a full-precision encoder). This app has 9 `DateTimeField`s and `DecimalField`s up to 20 digits with 10 decimal places (`RATE`) and 6 (`EUR_AMOUNT`), so the export must keep both timestamps and decimals exact.
- **The role has no `CREATEDB`** (platform decision 11). Scratch or rehearsal databases, the restore drill and a restore swap are created and dropped on the platform side, never by this app's role. Use `make pg-restore-drill DB=taxtool` in `cornil-gateway` for drills.
- **The network name is `db`** (the platform's `NetworkName`), not `systemd-db` (parts-db fix PR #3).
- **Where the switch variables live.** In parts-db a group-vars file overrode `all.yml`, so `use_postgres` had to be set in the git-ignored inventory. Check this repo's variable precedence (`infra/group_vars/all.yml`, `infra/inventory.ini.example`) and document where the owner sets `use_u01` and `use_postgres`.
- **Storage marker.** parts-db keeps a marker file `config/storage_location` (`u01` or `legacy`), and `make deploy` refuses before changing anything when the marker disagrees with the variable. Do the same here.
- **Consistent backups while running.** On PostgreSQL, take `pg_dump -Fc` from an exported snapshot inside a REPEATABLE READ transaction, and count rows through the ORM in that same transaction.
- **Ordering.** Sort what users see in Python with one engine-independent key (parts-db `parts/ordering.py`), not by relying on the database collation.
- **The platform's dump does not hold the files.** The nightly `pg_dump` has no uploads, so this app's own archive (database plus uploads) remains the primary backup.
- **Offsite coverage.** The owner's `local/vars.yml` in `cornil-gateway` overrides `restic_backup_paths` and today lists only `/u01/data/backups` and `/u01/data/parts-db/backups`, because restic fails on a missing folder. After Phase 37 the owner must add `/u01/data/tax-healthcare-tool/backups` and run `make restic-deploy` there. Until then this app's archives are **not** offsite.

## Execution modes (every phase carries one)

- **[LOCAL]** needs the server (SSH as `homeapps`), the live data or the owner's sudo. Run it in a normal Claude Code session on the Mac.
- **[CLOUD OK]** needs only a checkout. This repo's `CLAUDE.md` and `docs/prompts/` are tracked, so a cloud session sees them. Work on a branch, open a pull request, do not merge. A cloud session cannot reach the server or see git-ignored files (`local/`, `infra/inventory.ini`), and it has no real data: use placeholders and synthetic data only. If it needs the server, stop and say what is needed.
- **[OWNER]** commands the owner runs by hand (sudo, reboot, anything in `cornil-gateway`'s `local/`). Give the exact command, what it changes, what normal output looks like, and what to do if it fails.

## Standing rules

1. **Read first:** `CLAUDE.md` (all of it applies: Decimal only, keep originals, state the basis of every figure, separation of concerns, privacy, plain language, Podman explained plainly). Also read `docs/deployment.md`, `docs/podman-explained.md`, `docs/data-model.md`, ADR 0005, 0007, 0008, 0009 and 0029, `core/services/backup.py`, `core/services/import_files.py`, `core/services/report_sources.py`, `core/services/report_package.py`, the management commands `backup_db`, `restore_backup`, `data_fingerprint` and `stored_files_report`, `config/settings.py`, `config/settings_prod.py`, all of `infra/`, the `Containerfile`, `Makefile`, `core/test_deploy_artifacts.py`, and the code each phase names.
2. **One phase only, in order.** End with the end-of-phase report (below) and **stop for "go"**.
3. **Ask first.** Put the phase's questions in your first reply, together with what you found when you checked the current state. If a question is unanswered, use the stated default, say so at the top of your work and continue. Exception: questions marked **(blocking)** have no default. Wait for the answer.
4. **Stop and report on ambiguity.** If this file, `CLAUDE.md`, an ADR, the code or the server disagree, or if anything needed is missing (a value, a decision, access, a tool), stop. Say exactly what is missing or contradictory, give the options with a recommendation, and wait. Never resolve an ambiguity about the data, the financial rules or another repository on your own.
5. **Check the current state.** This file was written from a read of the three repositories (`main` as of 2026-11-13 for `cornil-gateway`, 2026-11-08 for this repo and Parts-DB), not from running anything. Wherever it says "verify", read the code or the server, say what you found, and adapt.
6. **Do not overwrite or discard existing work.** Do not touch the owner's database, any stored payment or any stored original, except in Phases 37 and 39 where the steps say how and the owner has said "go". The git-ignored `local/` folders are not touched. Never invent financial data, rates, dates or classifications.
7. **Privacy.** Real names of organisations, securities, accounts, categories and files come only from the database at runtime. Nothing from the owner's data goes into tracked files, test names, fixtures, docs, ADRs, commit messages or the report. Output shown to the owner is limited to counts, hashes, sizes and names of our own files. Scrub server output (addresses, user names other than `homeapps`, anything that looks like a key). Never print unit files or `Environment=` lines unfiltered. Never print, read or echo a Podman secret's value. Review staged files before every commit; `.gitignore` is not a security boundary.
8. **Unchanged behaviour stays unchanged.** Every page, report, CSV and PDF that this plan does not name is identical afterwards, and existing tests stay green. Where a test must change, list it and say why.
9. **No sudo for routine deploys** (a test enforces this; the only existing exceptions are `bootstrap-rootless` and `migrate-copy`). **No data is ever deleted** by a playbook or a command you run: no `state: absent` on data, no `rsync --delete`, no `rm`, no `prune` of data, no `DROP` of a database you did not create in this plan. Restores move data aside. Removing old copies is the owner's decision. You give the command; you never run it.
10. **No new dependency** except `psycopg` (Phase 38) and the PostgreSQL client tools in the image. No JS. `CLAUDE.md` says "SQLite ... no extra databases". That line is superseded by the owner's decision (plan sheet decision 2; confirm it in Phase 35). Record the change in **ADR 0035** (reserved for this; verify that the sequence still skips it). Amend `CLAUDE.md` and `docs/architecture.md` in Phase 38, not before. Never delete an old ADR.
11. **Acceptance criteria are checkable.** Report each one as met, not met, or not verifiable here, with evidence. Every corner-case id gets a test named after it.
12. **Language (Phase 12):** any new user-visible text goes through gettext, in English and German.
13. **Never the stale rootful copy.** The live Tax tool is the **rootless** container `tax-healthcare-tool-web` of `homeapps`, and its data is the only migration source. A stale **rootful** container with the same name may still run as a system service on plain port 8889, with its own data under `/var/lib/tax-healthcare-tool` (database unchanged since 2026-10-19). Never read from it, stop it, migrate it or remove it. Use `podman` as `homeapps`, never `sudo podman`. Its removal is a separate owner step (`cornil-gateway` `docs/closing-plain-ports.md`).
14. **Data-safety gate before every phase that changes the server (37, 39):** a fresh verified backup on the server (`make backup-now`), a verified copy on the Mac (`make fetch-backup`), and the live `data_fingerprint` recorded in the report. Do not continue if any of the three fails.

## Shared contract v1 (identical in all three repos; if you disagree, say so in your first reply, do not diverge silently)

**Server.** `cornil.fritz.box`, Debian 13, rootless Podman + Quadlet as `homeapps` (linger on). The disk is mounted at `/u01` (fstab with `nofail`). The unmounted mount point is immutable, so nothing can be written there by accident.

**Who owns what.**

| Thing | Owner |
|---|---|
| `gateway` network, Caddy | `cornil-gateway` |
| `db` network (`db.network`, `NetworkName=db`), the `postgres` container, creating databases, roles and scratch databases, nightly dumps, restic, disk health | `cornil-gateway`, platform area |
| App containers, their settings, migrating their own data, their own backup archives | the app repo |

No repo writes into another repo's files, units, folders or secrets. The shared objects are exactly: the `gateway` network, the `db` network, the `postgres` container and the Podman secret *names*.

**Layout.**

```
/u01/data/postgres/                                     PostgreSQL data (platform)
/u01/data/backups/postgres/<db>/                        nightly dumps (platform)
/u01/data/parts-db/{data,media,backups}                 parts-db (done)
/u01/data/tax-healthcare-tool/{data,uploads,backups}    this app (data/ holds SQLite until the cutover, then legacy-sqlite/)
/u01/apps/tax-healthcare-tool/build/                    image build contexts (were ~/tax-healthcare-tool/build)
```

The folder is `/u01/apps` (plural), as created by the platform and used by parts-db. Stays on the eMMC, never on the removable disk: `~/tax-healthcare-tool/config/env` (Django secret key and the optional settings), the Podman image storage and the Podman secrets. Image builds use `/u01` for temporary files.

**Database.** Container `postgres` on the Podman network `db`. It is not published on the host: only containers that join `db` can reach it, as host `postgres`, port 5432. Official `postgres` image, pinned by the platform (17.11). `scram-sha-256`. Cluster locale `en_US.utf8`. This app uses database `taxtool` and role `taxtool` (not a superuser, owns only its database, `NOCREATEDB`).

**Password.** Podman secret `taxtool-db-password`, created on the server by the platform. The unit reads it with `Secret=taxtool-db-password,type=env,target=DJANGO_DB_PASSWORD`. Never in git, never in an env file, never printed.

**App settings contract.** If `DJANGO_DB_HOST` is unset, the app uses SQLite exactly as today (development and tests unchanged). Otherwise it uses PostgreSQL from `DJANGO_DB_HOST`, `DJANGO_DB_PORT` (default 5432), `DJANGO_DB_NAME`, `DJANGO_DB_USER` and `DJANGO_DB_PASSWORD`. Driver: `psycopg` 3, pinned.

**Units.** Each app unit gets `Network=db.network` (in addition to `gateway.network`) and starts after `postgres.service`. In the unit that means `Wants=postgres.service` and `After=postgres.service`, not `Requires=`, so a restart of PostgreSQL does not restart the app (Django reconnects on its own). The `/u01` guard goes in the `[Service]` section of the app unit **and** of the backup service: `ExecStartPre=/usr/bin/mountpoint -q /u01`, `Restart=on-failure`, `RestartSec=10`, `StartLimitIntervalSec=0`. `RequiresMountsFor=/u01` alone is not a guard in a user unit (proven in U0, gateway ADR 0006). The container name `tax-healthcare-tool-web` and the in-container port 8000 do not change, so the gateway's `tax_upstream` stays as it is.

**Not in the contract: text ordering.** PostgreSQL sorts text by locale rules, SQLite by bytes. Anything displayed or exported in an order must have an explicit, tested ordering.

---

## Phase 35: Confirm the gates, inspect and design  [LOCAL, read-only]

Change nothing on the host, and nothing in the repo except the findings and the draft ADR 0035 (proposed: storage on `/u01` and PostgreSQL), on branch `docs/phase-35-design`.

### Gates to confirm first (report each one with evidence; stop if any fails)

- G1: parts-db is finished. Parts-DB `main` holds PD1 to PD4 (PRs #1 to #5). `cornil-gateway` `main` holds U4 (PR #8, ADR 0007 accepted). Read-only on the server: `systemctl --user --failed` is empty; `pg-dump.service` and `restic-backup.service` succeeded at their last runs, or the restic run was skipped because the NAS was off (`Result: exec-condition`), which is fine; the parts-db container is healthy and `/parts-db/` answers through the gateway.
- G2: the soak is over. It ran from 2026-11-13 to 2026-11-20 (decision 9). Ask the owner whether anything went wrong with parts-db during the soak.
- G3: the platform side for this app exists. Checked by name only, never by value: database `taxtool` exists and is empty (`make pg-status` in `cornil-gateway`, or a read-only `\dt` count as the platform does it), role `taxtool` exists, secret `taxtool-db-password` exists (`podman secret ls`), and `/u01/data/backups/postgres/taxtool/` holds nightly dumps (0 tables, which is expected).
- G4: `/u01` is mounted, has enough free space for at least three times the current `data + uploads + backups`, and `make disk-status` (in `cornil-gateway`) shows SMART PASSED with no new USB resets or I/O errors.
- G5: `git status` is clean on `main` in this repo. List any unmerged branches.

### Questions for the owner (defaults in brackets)
1. **(blocking)** `PHASES_11.md` put Phases 35 to 39 **on hold until the tax adviser accepts the report**. Is that hold lifted (adviser accepted, or your decision to go ahead anyway)? Record the answer and the date in ADR 0035.
2. Plan sheet decision 2: is the `CLAUDE.md` rule "SQLite, no extra databases" superseded [yes, via ADR 0035 and a `CLAUDE.md` amendment in Phase 38]?
3. Shared PostgreSQL container `postgres` with database `taxtool` [yes, as in ADR 0005; a separate container needs a new platform decision and is not built here].
4. How should the rehearsal database `taxtool_rehearsal` be created and dropped, given that the role has no `CREATEDB`? [The owner runs two platform-side commands that you give, as the superuser via `podman exec` into `postgres`, owned by `taxtool`, created just before the rehearsal and dropped right after it, named exactly `taxtool_rehearsal`. Alternative: a small `cornil-gateway` change first (`make pg-scratch-db`), in a gateway session.] Ask what was done for `partsdb_rehearsal` in PD4 and copy it if it was safe.
5. How long to keep the SQLite copy after the cutover [decision 10: until the next tax return and SBK assessment that use the migrated data are filed; the owner removes it]. Also the old home-folder copies after Phase 37 [the owner removes them after Phase 39 is verified; removing them disables `make rollback-storage`].
6. Maintenance windows for Phases 37 and 39 [any evening; the owner does not use the app during the window].
7. Does anything else read the SQLite file or the uploads folder directly: a script, a spreadsheet, a sync tool, a Mac-side job [no]? If yes, it breaks at the move or the cutover.
8. The stale rootful copy on port 8889 [left untouched by this plan; removal is a separate owner step after Phase 39].

### Inspect
- **Repo:** everything in standing rule 1. Answer each risk below with file and line.
  - The seven `JSONField`s (`warnings`, `organisation_countries`, `data`, `original`, `errors`, `notes`, `provenance`; `PHASES_10.md` said six; verify the count). SQLite keeps JSON as text, while PostgreSQL `jsonb` normalises key order and whitespace and changes how numbers are written. Does any code, hash, fingerprint or report depend on the stored text or key order?
  - `DecimalField` exactness (`AMOUNT` 16/4, `RATE` 20/10, `EUR_AMOUNT` 20/6, the 14/2 fields). Can a value stored in SQLite (numeric affinity) differ from what Django returns? The comparison in Phase 39 must be exact. Propose a read-only check that every stored decimal round-trips through the export unchanged.
  - All `DateTimeField`s (microseconds) and `DateField`s.
  - Every `order_by`, `Meta.ordering` and `distinct` that reaches a page, report, CSV, PDF, ZIP index or source-document index.
  - Case-insensitive lookups and the duplicate key that lower-cases the organisation name (`imports.py`). `icontains` and `iexact` become locale-aware on PostgreSQL.
  - `TransactionTestCase` in `test_breakdown.py` and `test_loss.py`, any `select_for_update`, raw SQL or `connection.vendor`.
  - The 18 migrations: any `RunSQL`, or `RunPython` with SQLite assumptions or non-portable defaults?
  - The `Containerfile` (`python:3.14.5-slim-trixie`). Can `postgresql-client-17` be installed from Debian 13's own repository? Is there a `psycopg[binary]` wheel for CPython 3.14 on linux/amd64? If not, say which fallback you propose (`psycopg` plus `libpq5`) and why.
  - Every test that asserts a path or a string in a unit (`core/test_deploy_artifacts.py`: mounts, `DJANGO_DB_PATH=/data/db.sqlite3`, backup timer).
  - The stored originals: `ImportBatch.stored_path` is relative to `UPLOAD_DIR` and reached only through `import_files.locate`. Confirm that no absolute path to the uploads is stored anywhere in the database (search every text and JSON field's use in code). If one is, stop and report: the move would break it.
- **Server (read-only, as `homeapps`, scrubbed):**
  - `podman inspect tax-healthcare-tool-web --format '{{json .Mounts}}'` (Source and Destination only).
  - Sizes and file counts of `data`, `uploads` (and `uploads/imports`), `backups` and `build`.
  - Free space on the eMMC and on `/u01`.
  - The existing backups and their ages.
  - The live `data_fingerprint` (counts and hashes only).
  - `stored_files_report` in its default dry-run mode (counts only: referenced, missing, unreferenced).
  - Whether the `/u01/data/tax-healthcare-tool` and `/u01/apps/tax-healthcare-tool` folders already exist, and who owns them.

### Deliver
- A findings table for the gates and the risks.
- **Migration method** with trade-offs: ORM export and import with an exact encoder, like parts-db's `dump_exact` and `loaddata`, versus `pgloader` versus a custom ORM copy. Recommend one. Consider `contenttypes`, `auth.permission`, `sessions`, `admin.LogEntry`, the user and password hash, sequences, JSON and decimals.
- **Report checksums proposal:** a read-only management command `report_checksums` that prints `report-name year sha256` for every CSV report and every reporting year, so that "the reports are identical before and after" can be proven without showing a single value. Also propose a **stored-originals check**: for every batch, the state from `locate` and whether the file's SHA-256 equals `ImportBatch.sha256` (or the per-member hashes for a zip, as `report_sources` does), printed as counts only.
- **Backups on PostgreSQL:** recommend keeping one verified archive holding the database and uploads together, as parts-db does, with the platform's dump as a second layer.
- The list of existing tests that will change, each with a reason.
- Draft ADR 0035.

Acceptance: no change on the server; G1 to G5 reported with evidence; question 1 answered; the other questions asked or defaulted; no data value printed.

---

## Phase 36: Storage relocation code, not deployed  [CLOUD OK]

Branch `feat/u01-storage`. Start after Phase 35 is approved. Follow Parts-DB PD1 (merged PR #1, ADR 0003 decision 7) wherever it fits.

1. `infra/group_vars/all.yml`: separate `config_root` (`/home/homeapps/tax-healthcare-tool/config`, holding the 0600 secret file and the marker; never moves) from `storage_root: /u01/data/tax-healthcare-tool` (`data`, `uploads`, `backups`) and `build_root: /u01/apps/tax-healthcare-tool/build`. Keep `legacy_root` (`~/tax-healthcare-tool`) for rollback. `data_root` is derived from `use_u01`.
   - **Default `use_u01: false`, so that merging and deploying changes nothing.** parts-db defaulted to true and needed a "do not deploy" warning. Say if you recommend otherwise.
   - Update `podman_run_flags`, the Quadlet template, the backup service, `manage.sh.j2` and all playbooks consistently, including `fetch-backup`, `restore`, `restore-drill`, `rollback`, `status` and `verify-migration`. Container-side paths (`/data`, `/uploads`, `/backups`) do not change.
2. Add the `/u01` guard to the Quadlet unit and the backup service, exactly as in the contract's Units paragraph, when `use_u01` is true.
3. Marker file `config/storage_location` (`u01` or `legacy`). `deploy.yaml` refuses, before any change, when the marker disagrees with `use_u01`, when `/u01` is not a real mount point, or when the storage folders are missing or not owned by `homeapps`. Folders are only created, never removed or emptied. `podman build` uses `build_root` and a temporary folder on `/u01`.
4. `infra/relocate-storage.yaml` and `make relocate-storage`:
   - stop the unit and the backup timer;
   - take a verified backup (`backup_db --label pre-relocate`);
   - copy `data`, `uploads` (all of it, including `imports/` and the zips of originals) and `backups` into target folders that must be empty, with `cp -a` or `rsync -a` and no delete option;
   - compare the file lists and the SHA-256 of every file (names and hashes only, in a file the owner can keep), and show a summary: files, bytes, identical or different;
   - switch the unit to the new paths (and write the marker) only after the owner types `SWITCH`;
   - on any failure, restart on the old folders.
   
   Old folders stay untouched. `make rollback-storage` (the owner types `ROLLBACK`) points the unit back. Document both in plain language in `docs/deployment.md`.
5. Update tests deliberately, listing each changed test and why. Add tests: the guard is present in both units when `use_u01` is true and absent when false; the relocation playbook has no deleting option and no `become`/`sudo`; the preconditions run before the first change; no path contains a parts-db name; `use_u01: false` renders the same unit as today.
6. ADR 0035: final text for the storage part. Update `README.md` and `docs/deployment.md`.

Acceptance: `.venv/bin/python manage.py test` passes; `make syntax` passes; with `use_u01: true` the rendered unit mounts only `/u01/data/tax-healthcare-tool/*` plus the config location on the eMMC; with `false` it is unchanged; nothing deployed.

---

## Phase 37: Move the files to /u01 on the server  [LOCAL + OWNER]

Start after the Phase 36 pull request is merged and the owner says "go" for the window.

1. **Data-safety gate** (standing rule 14): `make status`, `make backup-now`, `make fetch-backup` (a verified copy on the Mac), the live `data_fingerprint`, and the stored-originals check (or `stored_files_report` as a dry run) as counts only. Keep all of them in the report.
2. **[OWNER]** If the folders do not exist yet: give the exact commands to create `/u01/data/tax-healthcare-tool/{data,uploads,backups}` and `/u01/apps/tax-healthcare-tool/build`, owned by `homeapps`. Check first whether `homeapps` can create them without sudo (it owns `/u01/data` and `/u01/apps`).
3. Set `use_u01: true` where Phase 36 documented it. Run `make deploy` (the precondition checks must pass), then `make relocate-storage`. Show the comparison and wait for the owner to type `SWITCH`.
4. **Verify:**
   - the mounts show only `/u01/data/tax-healthcare-tool/*` (plus the config location);
   - `https://cornil.fritz.box/tax-healthcare/` loads, and the owner logs in, opens a year, opens one import preview and one stored original, and downloads one report package;
   - `data_fingerprint` after equals before;
   - the stored-originals check gives the same counts as before, with 0 newly missing;
   - a new backup (`make backup-now`) lands in `/u01/data/tax-healthcare-tool/backups`;
   - the next scheduled backup runs from the timer (show it the next morning, or give the owner the command to check).
5. **[OWNER] Reboot** (give the command). Check that `/u01` mounted by itself, the container is healthy, the gateway answers, and `dmesg` shows no I/O errors.
6. **[OWNER] Offsite:** in `cornil-gateway`, add `/u01/data/tax-healthcare-tool/backups` to `restic_backup_paths` in `local/vars.yml`, run `make restic-deploy` (rehearse with `--check` first), and with the NAS on, start one run and show that the new snapshot contains the folder. You may only give these commands; this repo never edits the gateway's files.
7. The old folders stay. Report their size and give, but do not run, the removal command for the owner to use after Phase 39.

Acceptance: items 4 to 6 shown with real output; fingerprints equal before and after; stored-originals counts equal; `make rollback-storage` rehearsed with `--check`; nothing deleted.

---

## Phase 38: PostgreSQL support in the app, not deployed  [CLOUD OK]

Branch `feat/u01-postgres`. Start after Phase 36 is merged (both phases edit `infra/`). Read Parts-DB PRs #2 to #4 (PostgreSQL support, `db_network_name`, `dump_exact`) and reuse their approach where sensible.

1. **Settings.** Implement the app settings contract in `config/settings.py` and `settings_prod.py`. SQLite stays unchanged when `DJANGO_DB_HOST` is unset. Otherwise the five variables are all **required** in production (the existing `_required` style). Set `CONN_MAX_AGE=60`, `CONN_HEALTH_CHECKS=True` and `connect_timeout=5`, and never let the password reach a log. Add `psycopg[binary]` pinned, or the Phase 35 fallback. `DJANGO_DB_PATH` keeps working for SQLite.
2. **Image.** Add `postgresql-client-17` from Debian's own repository, plus a build step that fails if `pg_dump` or `pg_restore` is missing or older than 17. Every other property of the image stays unchanged: non-root, read-only root, no new capabilities, same Python patch release.
3. **Backups.** Update `core/services/backup.py` and the commands. For PostgreSQL, write `pg_dump -Fc` (from an exported snapshot, REPEATABLE READ, with the row counts taken in the same transaction) plus the uploads into **one verified archive**: SHA-256 per file and row counts through the ORM, with the app version and `engine` in the manifest. Re-verify the archive after writing (checksums and `pg_restore --list`), with the same retention and labels. `restore_backup` restores only into a new, empty database prepared on the platform side, and swaps only after explicit confirmation, renaming the old database aside. It never drops the live database. **Existing SQLite archives must stay readable**: `data_fingerprint --archive` and `fetch-backup` verification work for both formats, and the SQLite behaviour stays tested.
4. **Exact export.** Write a `dump_exact`-style command, or reuse parts-db's design, that keeps microseconds and decimals exactly. Excluded models are recreated by `migrate` (`contenttypes`, `auth.permission`, `sessions`); say whether `admin.LogEntry` and the user are carried (default: yes, the user with its password hash). Use natural keys where needed. Add a test that a synthetic data set with edge values survives the round trip byte for byte in the fingerprint: maximum digits, 10-decimal rates, negative amounts in `may_be_negative` categories, microsecond timestamps, umlauts and nested JSON.
5. **Engine-neutral `data_fingerprint`**: row counts and content hashes through the ORM, in primary-key order. Decimals are compared as exact normalised strings (never floats), timestamps in UTC with microseconds, and JSON as canonical JSON (sorted keys, fixed separators), so that SQLite and PostgreSQL fingerprints of the same data are equal. It never prints a value. A golden test pins the hashes.
6. **`report_checksums`** (read-only management command, from Phase 35's proposal), plus the **stored-originals check** as a read-only command (counts only). Reports must produce byte-identical CSV on SQLite and PostgreSQL for the same data.
7. **Ordering.** Wherever Phase 35 found a dependence on SQLite's ordering, make the ordering explicit, in Python with one key as in parts-db where sensible. Add a test with umlauts, mixed case and numbers that passes on both engines. Add a **golden test**: build a synthetic data set through the ORM (invented names only), generate every report CSV, and compare the checksums between the SQLite run and the PostgreSQL run.
8. **Tests.** The whole suite passes on SQLite (the default) **and** on PostgreSQL, including `test_breakdown.py` and `test_loss.py` (check transactions and any row locks). Add `make test-pg`: a throw-away PostgreSQL 17 container via `podman run --rm` on the Mac, with the five variables set and the container removed afterwards. If the cloud session cannot run a PostgreSQL server, mark the PostgreSQL run **not verifiable here**, give the owner `make test-pg`, and do not claim it passed. Add tests for the settings contract and the rendered unit: network `db.network`, the secret line, no password text, no published database port.
9. **Deployment files.**
   - Quadlet template, when `use_postgres` is true: `Network=db.network`, `Wants=postgres.service`, `After=postgres.service`, `Secret=taxtool-db-password,type=env,target=DJANGO_DB_PASSWORD`, the four non-secret variables, and no `DJANGO_DB_PATH`.
   - One-off `podman run` flags get the matching `--network db`, `--secret ...,type=env,target=DJANGO_DB_PASSWORD` and `-e` flags.
   - Variables `db_host: postgres`, `db_name: taxtool`, `db_user: taxtool`, `db_network_name: db`, `use_postgres: false` by default, so that merging deploys nothing different. Document where the owner sets it (see the lesson about variable precedence).
   - `deploy.yaml` precondition, when `use_postgres` is true: check by name that `db.network` and the secret exist; never read a value.
   - Update `verify-migration.yaml`, `restore-drill.yaml` and `status.yaml` for PostgreSQL, and keep their SQLite path. For drills and swaps, point to the platform tools (`make pg-restore-drill DB=taxtool`).
10. **Documents.** Final ADR 0035. Amend `CLAUDE.md` (the "Keep it simple: ... SQLite ... no extra databases" line, the Environment and deployment paragraph, the decisions note; also correct the stale note that `spike/payments-page` is "not merged": it was merged as PR #1). Update `docs/architecture.md`, `docs/deployment.md`, `docs/data-model.md` (engine notes), `README.md` and `.env.example`.

Acceptance: the SQLite suite passes, unchanged apart from the listed tests; the PostgreSQL suite passes via `make test-pg` (or is marked not verifiable here); the exact-export round trip and the golden report test pass on both engines; `use_postgres: false` renders the same unit as after Phase 36; nothing deployed.

---

## Phase 39: Cutover to PostgreSQL, then close out  [LOCAL + OWNER]

**Start only when all of these hold:** Phase 37 is verified (including the offsite step), Phase 38 is merged and the owner has run `make test-pg` locally with a pass, the deployed image is the merged `main`, `restic-backup.timer` has succeeded at least once since Phase 37 with the Tax backups folder included, and the owner says "go" for a maintenance window. Name each condition with its evidence in your first reply.

1. **Baseline before touching anything** (standing rule 14, plus more): `make backup-now`, `make fetch-backup`, then on the live SQLite data `data_fingerprint`, `report_checksums` and the stored-originals check. **[OWNER]** Trigger one restic run with the NAS on, so that the pre-cutover archive is offsite. Keep the counts and hashes in the report.
2. **Rehearse on a copy:**
   - **[OWNER]** create `taxtool_rehearsal` as answered in Phase 35, question 4;
   - restore the latest SQLite backup into a scratch SQLite file outside the live folder;
   - run the chosen migration method into `taxtool_rehearsal` (`migrate`, exact export, `loaddata`, sequence reset);
   - run `data_fingerprint` on both sides: they must be equal;
   - run `report_checksums` against the rehearsal: identical to the baseline;
   - check that every sequence is above its table's maximum id;
   - **[OWNER]** drop `taxtool_rehearsal` (the only database this plan may drop), with the owner's go.
   
   If anything differs, stop: no cutover.
3. **Cutover.** Announce the downtime. Stop the app and the backup timer. Take the final SQLite archive (`backup_db --label pre-cutover`) and verify it. Check that `taxtool` is still empty, then migrate into it with the same method as the rehearsal and reset the sequences. `data_fingerprint` must equal the final SQLite fingerprint. Set `use_postgres: true`, run `make deploy` and wait until the app is healthy. `report_checksums` on PostgreSQL must be identical to the baseline, and the stored-originals check must give identical counts. If any check fails: roll back (step 5) before doing anything else, and report.
4. **Verify:**
   - `https://cornil.fritz.box/tax-healthcare/` works through the gateway;
   - the owner logs in and opens each reporting year, one import preview, one report in the browser, one report PDF and one report package; a stored original opens;
   - one harmless write works and can be undone by the owner (for example an edit to a note on a test year, or the owner's choice);
   - `make backup-now` writes a PostgreSQL archive and it verifies;
   - `make pg-restore-drill DB=taxtool` in `cornil-gateway` gives `DRILL_OK` with the table count greater than 0;
   - the next nightly platform dump of `taxtool` under `/u01/data/backups/postgres/taxtool/` is no longer empty (show it the next day).
5. **Rollback** (rehearse with `--check`, do not run): set `use_postgres: false` and redeploy. The SQLite file stays untouched in `data/` until the owner decides. Data written after the cutover would exist only in PostgreSQL; say so plainly. Once verification passes, move the SQLite file (a move, not a deletion) to `/u01/data/tax-healthcare-tool/legacy-sqlite/`, and document the move back.
6. **[OWNER] Reboot:** PostgreSQL comes up first, then the app is healthy and the gateway answers; `dmesg` is clean.
7. **Close-out:**
   - update `CLAUDE.md`'s decisions note, `docs/deployment.md` and `README.md`, and set ADR 0035 to accepted;
   - list for the owner what to set in the plan sheet (yellow cells only: 35 to 39 Status, Date done, Notes; the "Prompt files" tab row for this repo now names `PHASES_12.md`);
   - list what the owner may remove and when, giving the commands but not running them: the old home-folder copies (after this phase), the legacy SQLite (decision 10), and, separately, the stale rootful copy and port 8889 (`cornil-gateway` `docs/closing-plain-ports.md`);
   - add this app to the quarterly rehearsal in `cornil-gateway` `docs/recovery.md` 7.8: `taxtool` now has tables, so explain what to check. Give the gateway text to the owner; do not edit that repo.

Acceptance: fingerprints, report checksums and stored-originals counts equal before and after, shown with real output; rehearsal passed before the cutover; rollback rehearsed; restore drill `DRILL_OK`; offsite copy of the pre-cutover archive shown; no SQLite file and no stored original deleted; no value from the data and no secret in any output.

---

## End-of-phase report (every phase)
- What was implemented, and key decisions.
- Files changed and commits.
- Checks run, with real results.
- Deviations from this file, and contradictions found in this file, `CLAUDE.md`, the ADRs or the other repos.
- Open issues and assumptions, including defaults used for unanswered questions.
- Commands for the owner to run or verify by hand.
- What was not verified, and why.
- Each acceptance criterion: met, not met, or not verifiable here, with evidence.
- What the owner should set in the plan sheet.
- Proposed next scope.

Then wait for "go".
