# Phase 35 findings: storage on /u01 and PostgreSQL (inspection and design)

Phase 35 of `docs/prompts/PHASES_12.md`, done on 2026-11-27. It was read-only. Nothing on the server changed, and the only repository changes are this file and the draft ADR 0035 (`docs/decisions/0035-storage-on-u01-and-postgresql.md`), on branch `docs/phase-35-design`. Every figure below is a count, a size, a hash or the name of one of our own files. No data value appears.

"Platform repository" means the separate gateway repository that runs the gateway, the `db` network and the shared PostgreSQL container (ADR 0005 there, contract v1).

## 1. Gates

| Gate | Result | Evidence |
|---|---|---|
| G1 parts-db finished | **met** | Parts-DB `origin/main` holds PRs #1 to #5 (PD1 storage, PD3 PostgreSQL, fix `db` network name, `dump_exact`, PD4 close-out). Platform `origin/main` holds PR #8 (U4 close-out, ADR 0007 accepted). On the server (as `homeapps`): `systemctl --user --failed` lists 0 units. `pg-dump.service` Result=success (last run 2026-11-27). `restic-backup.service` Result=exec-condition (NAS off, skipped, which is acceptable). `parts-db-web` is healthy. Through the gateway, `/parts-db/` answers 302 (login redirect) and `/parts-db/health/` answers 200. The first probe timed out once (code 000), and the repeat answered normally. |
| G2 soak over | **met** | The soak ran from 2026-11-13 to 2026-11-20. The owner reports that nothing went wrong (answer of 2026-11-27). |
| G3 platform side exists | **met** | Database `taxtool` exists, its owner is `taxtool`, collation `en_US.utf8`, and it has 0 tables. Role `taxtool` has rolsuper=false and rolcreatedb=false. Secret `taxtool-db-password` is listed (checked by name only). `/u01/data/backups/postgres/taxtool/` holds 14 nightly dumps (newest 2026-11-27, 1082 bytes each, an empty database). PostgreSQL is 17.11. |
| G4 /u01 and disk health | **met** | `/u01` is a mount point: 916 GB in total, 907 GB free. Three times the current data + uploads + backups is about 6 GB. The platform's `disk-status` (checked 2026-11-27 05:00Z) shows SMART PASSED, 0 reallocated, 0 pending, 0 uncorrectable, 0 CRC errors, and 0 USB resets, I/O errors and ext4 errors since boot. The eMMC has 15 GB of 27 GB free. |
| G5 clean tree | **met, with one note** | `main` was clean apart from the untracked `docs/prompts/PHASES_12.md` (this plan), which is committed on this branch. `git branch --no-merged main` and `git branch -r --no-merged main` both list **no branches**: every local and remote branch, `spike/payments-page` included, is merged into `main`. |

Other server observations:
- The live container is the rootless `tax-healthcare-tool-web` on image revision `2e02a5376891`, which equals `main`. The stale rootful copy was not looked at (standing rule 13).
- There was no daily backup on 2026-11-25. The journal and `/proc/uptime` show that the server was suspended from about 2026-11-24 to 2026-11-26 14:31. The timer caught up after resume (`Persistent=true`) with `backup-20261126-134045`. This is not a gate failure. A server that suspends does misses backup slots and soak time, though, and this matters for the Phase 37 and 39 windows. **Question for the owner:** was the suspend deliberate?
- `~/tax-healthcare-tool/DEPLOYED` says `deployed_utc=2026-11-08`, but the commit it records is the newest one. The file gives the date of the first deploy of that commit's image, or it is out of date. This does not matter here.

## 2. Current state on the server (as `homeapps`, read-only)

| Item | Value |
|---|---|
| Mounts of `tax-healthcare-tool-web` | `~/tax-healthcare-tool/{data,uploads,backups}` → `/data`, `/uploads`, `/backups` |
| `data` | 1.8 MB, 2 files: `db.sqlite3` and `db.sqlite3.before-restore-20261019-095314` (the latter left by the Phase 9A migration) |
| `uploads` (all under `uploads/imports`) | 101 MB, 30 files |
| `backups` | 1.8 GB, 21 archives, oldest `backup-20261031-021823`, newest `backup-20261127-022206` (daily ones, plus 7 `pre-deploy` ones from 2026-11-04 to 2026-11-08) |
| `build` | 50 MB, 5410 files |
| `/u01/data/tax-healthcare-tool`, `/u01/apps/tax-healthcare-tool` | both **absent**. Parents `/u01/data` and `/u01/apps` are `homeapps:homeapps` with mode 750 |
| SQLite | version 3.46.1, journal mode `delete` |
| `data_fingerprint` | `FINGERPRINT rows=1396 content=bd54a32d5e3b547f9cc6ddee7c3406729e4066c55904cb212a90e4f3f50903e2 uploads=30:9c88b66a3e2ec270ddaf062f9b3e405e6fc6b7fbeff93aeda932ed8e848a9e11` |
| Table counts | auth_permission 84, auth_user 2, annualinput 2, assessmentsettings 1, conversionevent 275, exchangeraterecord 227, importbatch 32, importdeletion 11, importrow 318, incomecategory 8, organisation 35, payment 270, reportingmonth 30, reportingyear 3, sourcedocument 32, statementrule 2, django_admin_log 7, django_content_type 21, django_migrations 36, django_session 16 |
| `stored_files_report` (dry run) | 0 unreferenced, 0 missing, 0 outside |

## 3. Risks in the repository

| Risk | Finding | Consequence |
|---|---|---|
| JSONFields | There are **7** (`PHASES_10.md` said 6): `ImportBatch.warnings`, `.organisation_countries` (`core/models.py:164-165`) and `ImportRow.data`, `.original`, `.errors`, `.notes`, `.provenance` (`core/models.py:213-239`). All 32 + 5×318 live values are stored as text. No hash, fingerprint, report or CSV uses the stored JSON text, except the current `backup.fingerprint` (`core/services/backup.py:75`, `repr(row)` of raw SQLite rows), which is SQLite-specific anyway. **One display depends on key order:** `row.provenance.items` in `core/templates/core/import_preview.html:74` and `core/templates/core/import_row_form.html:9` lists "where each value was read" in insertion order, and `jsonb` stores keys by length, then bytes. `org_countries.py:97` iterates `fill_existing` keys, but the result does not depend on the order. Lists (`warnings`, `errors`, `notes`) keep their order in `jsonb`. No JSON holds a float: cell values are text and `page` is an integer. | Phase 38: give the provenance display an explicit field order, plus a test. The fingerprint becomes ORM-based (see 5). |
| Decimals | The fields are `AMOUNT` 16/4, `RATE` 20/10, `EUR_AMOUNT` 20/6 and the four 14/2 fields (`AnnualInput.costs_eur`, 3 × `TaxAssessmentFigures`). Measured on the live file: **SQLite stores them as REAL or INTEGER, not as text** (numeric affinity, for example `payment.gross_amount` 226 real, 44 integer). REAL keeps 15 significant digits. **0 stored values have 15 or more significant digits** (all 19 decimal columns, checked by count). Django reads them back with a 15-digit context and quantizes, so what the app shows today is exact and is what an ORM export writes. PostgreSQL `numeric` is exact. Moving to it also removes SQLite's silent 15-digit limit for future values. | The export must go through the ORM with an exact `Decimal` encoder. Proposed read-only check `decimal_check` (Phase 38): for every DecimalField, count values whose ORM value ≠ `Decimal(str(value))` after a JSON round trip through the exact encoder, values with ≥ 15 significant digits, and values that do not fit `max_digits`/`decimal_places`. It prints counts only and must give 0 / 0 / 0 before the cutover. |
| DateTimeFields | There are **9** in `core`, plus `auth_user.last_login`, `date_joined` and `django_admin_log.action_time`. `USE_TZ=True`, `TIME_ZONE='UTC'`. **Every non-null live value has a fractional second** (for example 270/270 `payment.created_at`), so plain `dumpdata` (milliseconds) **would lose data**, exactly as in the parts-db pilot. The 13 DateFields are plain dates. | Use `dump_exact` (full microseconds), as parts-db does. |
| Ordering | Pages, reports, CSV and PDF that rely on database text order: `Organisation`/`IncomeCategory` `Meta.ordering=['name']` (`models.py:76,124`: dropdowns, the organisations and categories pages, admin); `report_filter.py:125` (`order_by('name')`, the filter check-box list); `tax_income_report.py:218` (`order_by('payment_date','organisation__name','id')`, which orders the payments of the **tax summary** on screen, in CSV, PDF and the ZIP); `tax_income_report.py:241` (unused categories list); `payment_list.py:62` (payments page); `org_countries.py:114`; `StatementRule` `ordering=['label','id']`; `tools/broker_summary.py:26`. Already engine-independent: `reports.py` (Python sorts, `.lower()` keys), `report_sources.py:161` (source index), `sbk_letter.py:99-100`, `tax_income_report.py:70-156`, `report_filter.py:133` (currency codes are ASCII upper case, so byte order equals locale order). Numeric and date orderings are safe. No `.distinct()` anywhere. | Phase 38: one Python key (as in parts-db `parts/ordering.py`) for every displayed or exported text order listed here, a test with umlauts, mixed case and numbers, and the golden report test. |
| Case-insensitive lookups | `name__iexact` (`forms.py:56`, `lookups.py:16,56`, `org_countries.py:98`), `name__istartswith` (`pdf_imports.py:174`, `org_hints.py:31`) and the unique constraints `Lower('name')` (`models.py:77,126`). SQLite folds only ASCII, and PostgreSQL folds Unicode. The CSV duplicate key (`imports.py:217,307`) uses Python `.lower()`, so it does not depend on the engine. Live data: 35 organisation and 8 category names, **0 non-ASCII, 0 pairs that collide** under Unicode lower-casing. | No unique constraint can fail at load time. The behaviour change (Ü/ü now match) gets a test in Phase 38. |
| Raw SQL, vendor | No `raw()`, `cursor()`, `extra()`, `RawSQL`, `select_for_update` or `connection.vendor` in app code. Only `core/services/backup.py` (and its tests) uses `sqlite3` directly. | Only the backup and fingerprint services need a PostgreSQL code path. |
| `TransactionTestCase` | `test_breakdown.py:233` and `test_loss.py:196` migrate 0005↔0006 and 0006↔0007 through the ORM only. Portable. | Unchanged. They must pass under `make test-pg`. |
| Migrations | 18 migrations. No `RunSQL`. Three `RunPython` (0002 seed categories, 0006 zero EUR amounts, 0007 flag categories), all ORM-only with `Decimal` values. No non-portable defaults. | Run as they are on the empty `taxtool` database. |
| Image | `python:3.14.5-slim-trixie`. `postgresql-client-17` is in Debian 13 main (17.12-0+deb13u1, amd64), which is not older than the server's 17.11. `psycopg-binary==3.3.8` has a `cp314` manylinux x86_64 wheel (downloaded to check), so `psycopg[binary]==3.3.8` works as in parts-db and the image needs no `libpq5`. | No fallback needed. |
| Stored originals | `ImportBatch.stored_path` is relative (`models.py:161`), written only by `imports.store_upload` (`imports.py:327-329`) and read via `import_files.locate`. Live: 30 non-empty, **all 30 begin with `imports/`, 0 absolute**. No text or JSON column contains `/uploads`, `/data/`, `/home/` or a drive path (0 rows). Two cleanup paths join `UPLOAD_DIR` with the relative path directly (`imports.py:369`, `pdf_imports.py:159`, only when storing fails). They do not depend on where the folder is. | The move does not break any stored reference. |
| Other | `report_csv.py:47` writes `Generated (UTC)` into every CSV. Baseline suite on 2026-11-27: the first full run had 1 failure, where two CSV renders of the same report differed only in that `Generated (UTC)` second (`…:40` vs `…:39`, most likely `test_report_package.py:109`). The rerun passed (1061 tests, OK, 2 skipped). This is a pre-existing flaky test. | `report_checksums` must fix `generated_at` (see 5). The flaky test gets a fixed clock in Phase 38 (listed as a changed test). |

### Ansible variable precedence (verified)
`infra/group_vars/all.yml` sits next to both the inventory and the playbooks. A variable defined there **beats** `[taxtool:vars]` in `infra/inventory.ini`, and a host variable on the `tax-service` line beats both. This was checked with ansible-core 2.20.10 in a scratch inventory: `all.yml` value → shown for the host without a host variable, host-line value → shown for the host with one. The existing optional settings work only because `all.yml` never defines them (`| default('')`).
**Proposal:** `use_u01` and `use_postgres` default to `false` in `all.yml`. The owner switches them as host variables on the `tax-service` line of the git-ignored `infra/inventory.ini` (the same place as parts-db, ADR 0003 decision 16). `inventory.ini.example` documents it.

## 4. Migration method

| Method | For | Against |
|---|---|---|
| **ORM export and import with an exact encoder** (`dump_exact` → `migrate` on empty `taxtool` → `loaddata` → `sqlsequencereset`) | Proven on parts-db with the same platform. It passes through Django's field conversion, so decimals arrive exactly as the app reads them today, and JSON is parsed and re-stored as `jsonb`. One code path. Small data (1396 rows). | Needs `dump_exact` (microseconds, exact decimals). `loaddata` skips `save()`, which is what we want: `auto_now` timestamps stay as they are. |
| `pgloader` | Fast for large databases. | A new tool, its own type-cast rules (SQLite REAL → numeric must be configured, or rates become floats), `jsonb` cast rules, and a second schema not made by Django's migrations. |
| Custom ORM copy (two database aliases, model by model) | Full control. | More code to write and test, with no gain over `dump_exact` for 1396 rows. |

**Recommendation: ORM export with `dump_exact`, as in parts-db.** Details:
- Excluded and recreated by `migrate`: `contenttypes`, `auth.permission`. Dropped: `sessions` (the owner logs in again). Kept: `auth.user` (with its password hash, so the login stays the same), `admin.LogEntry` (7 rows; its content-type and user references use natural keys), `core.*`.
- Natural keys (`--natural-foreign --natural-primary`) for content types and permissions. Every `core` primary key is kept as it is: report source references (`Dnn`) and stored file names (`imports/<pk>-<sha12>`) contain batch ids.
- After `loaddata`: `sqlsequencereset core auth admin`, run through the ORM.
- Proof: the new engine-neutral fingerprint (see 5) and `report_checksums` must be equal on SQLite and PostgreSQL. `decimal_check` must give 0 / 0 / 0. Row counts of every table are compared, sessions excluded.
- Rehearse first in `taxtool_rehearsal` (question 4), then do the real run into `taxtool`.

## 5. Checks that prove "identical"

**Engine-neutral fingerprint** (replaces the SQLite-only `repr(row)` hash in `backup.fingerprint`, as in parts-db decision 11). Every model is hashed in primary-key order in one normalised text form: decimals normalised (`Decimal.normalize()`, so trailing zeros are dropped), datetimes as UTC ISO with microseconds, dates as ISO, JSON as `json.dumps(sort_keys=True, separators=(',',':'))`, and foreign keys to content types and permissions by natural key. Sessions are left out. Uploads are hashed as today. A golden test pins the hashes on both engines. The current SQLite fingerprint stays available, so the Phase 37 comparison (same engine, files moved) uses the same command as today.

**`report_checksums`** (read-only management command): for every CSV report (each `REPORTS` entry, plus the tax summary and the other assessment CSVs, listed exactly in Phase 38) and every `ReportingYear`, render the CSV with `generated_at` fixed to a constant and the default (unfiltered) parameters, and print `report-key year sha256`. It writes no figure, and the outputs before and after the cutover must be identical line for line.

**Stored-originals check** (read-only command, for example `stored_files_check`): for every `ImportBatch`, take the state from `import_files.locate` and compare the file's SHA-256 with `ImportBatch.sha256`. For zip batches, also compare the per-member hashes as `report_sources._zip_members` does. It prints counts only: `ok`, `none`, `missing`, `outside`, `hash_mismatch`, `member_mismatch`. It runs before and after Phase 37 and Phase 39, and every count except `ok`/`none` must be 0.

## 6. Backups on PostgreSQL
Keep **one verified archive per backup that holds the database and the uploads together**, as parts-db does (its ADR 0003 decision 10). The archive holds `pg_dump -Fc` taken from an exported snapshot in a REPEATABLE READ transaction, row counts taken through the ORM in that same transaction, `uploads/…`, and `MANIFEST.json` (SHA-256 per file, `engine`, `app_version`, row counts). It is verified after writing with the checksums and `pg_restore --list`, and the file name and retention stay the same. The SQLite path stays as it is for development and for the period before the cutover. The platform's nightly `pg_dump` of `taxtool` is the second, independent layer. It holds no uploads, so it never replaces the archive. Restore drills and swaps run on the platform side (`make pg-restore-drill DB=taxtool` there), because the `taxtool` role has no `CREATEDB`.

**Offsite:** until the owner adds `/u01/data/tax-healthcare-tool/backups` to `restic_backup_paths` in the platform's local vars and runs `make restic-deploy` there (after Phase 37), this app's archives are **not** copied offsite. Today they are on the eMMC and also not offsite.

## 7. Existing tests that will change

| Test | Phase | Why |
|---|---|---|
| `test_deploy_artifacts.ContainerfileTests…` (pinned requirements, image contents) | 38 | New `psycopg[binary]` pin and `postgresql-client-17`, plus a build step that checks `pg_dump` ≥ 17. |
| `test_deploy_artifacts…test_data_volumes` | 36 | `data_root` becomes derived (`/u01/data/tax-healthcare-tool` or the legacy home folder). |
| `…test_hardening` (line 116) and `…test_hardening_is_kept` (line 317) | 36 | They assert `Restart=always`. Contract v1 wants `Restart=on-failure`, `RestartSec=10`, `StartLimitIntervalSec=0` and the `mountpoint` guard in the /u01 layout, while the legacy layout keeps today's lines. |
| `…test_unit_joins_the_gateway_network_and_keeps_its_name_and_port` | 38 | `Network=` gains `db.network` when `use_postgres` is true. |
| `…test_uses_the_current_tag_and_production_settings` (line 145) | 38 | There is no `DJANGO_DB_PATH` line when `use_postgres` is true (unchanged when false). |
| `…test_one_off_container_runs_share_the_service_hardening` | 38 | `podman_run_flags` gain `--network`, `--secret` and the `-e` database variables. |
| `…test_backup_timer_runs_daily_and_prunes` | 36 | The backup service gets the /u01 guard lines. |
| `…test_restore_drill_is_non_destructive` (line 240) | 38 | It assumes the SQLite path. On PostgreSQL the drill goes to the platform. |
| `test_settings_prod` (lines 56, 69 and the env dicts) | 38 | `DJANGO_DB_PATH` is required only when `DJANGO_DB_HOST` is unset. The five database variables are required when it is set. |
| `test_backup` fingerprint tests (line 384 and the `data_fingerprint` command tests) | 38 | The fingerprint becomes engine-neutral, so its hash values change once (both sides are computed with the new code). |
| `test_breakdown.MigrationTests`, `test_loss.MigrationTests` | none | Portable. They stay, and must pass under `make test-pg`. |

## 8. Questions and answers (2026-11-27)

| # | Question | Answer |
|---|---|---|
| 1 (blocking) | Is the `PHASES_11.md` hold lifted? | **Yes: the tax adviser accepted the report** (owner, 2026-11-27). |
| 2 | Is "SQLite, no extra databases" superseded? | **Yes** (owner), via ADR 0035. `CLAUDE.md` and `docs/architecture.md` are amended in Phase 38. |
| 3 | Shared `postgres` container, database `taxtool`? | Default: yes (ADR 0005 of the platform). Not contradicted. |
| 4 | How `taxtool_rehearsal` is created and dropped | Default: the owner runs two platform-side commands, as the superuser via `podman exec` into `postgres`, owned by `taxtool`, created just before the rehearsal and dropped right after it. Parts-DB records that it used `partsdb_rehearsal` "created through the platform" but **does not record the exact commands**. **Asked again:** how was `partsdb_rehearsal` created and dropped? |
| 5 | Retention of the SQLite copy and of the home-folder copies | Default: the SQLite copy is kept until the next tax return and SBK assessment that use the migrated data are filed. The home-folder copies are kept until Phase 39 is verified. The owner removes both. |
| 6 | Maintenance windows | Default: any evening, with the app not in use. |
| 7 | Other readers of the SQLite file or uploads? | **No** (owner). |
| 8 | Stale rootful copy on port 8889 | Default: untouched. Removal is a separate owner step after Phase 39. |

## 9. Discrepancies between documents
- `PHASES_12.md` says that 6 JSONFields were counted in `PHASES_10.md`. There are 7 (see 3).
- Parts-DB ADR 0003 (on `main`) still says "the reboot test after the cutover is still open", while `PHASES_12.md` says that it passed. This is not a blocker, but the Parts-DB ADR is out of date.
- `CLAUDE.md` and contract v1 differ on restart policy: the current unit has `Restart=always`, `RestartSec=5`, and the contract has `Restart=on-failure`, `RestartSec=10` plus the guard. Phase 36 follows the contract in the /u01 layout only.
