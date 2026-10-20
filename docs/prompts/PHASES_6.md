# PHASES_6.md: Tax and Healthcare Tool, Phase 28 (stored import PDFs outlive a deleted year)

Save this file as `docs/prompts/PHASES_6.md`.
**Do not edit or overwrite `PHASES.md` to `PHASES_5.md`.** If you find an error in them, record it in your end-of-phase report. Phases 1 to 27 are implemented (Phase 20 deliberately not) and the app is in production.

## Problem as reported by the owner

When a year is deleted, the PDFs (and zips) that were uploaded to populate that year stay behind, and the imports page offers no way to delete them. The stored originals contain personal and financial data (names, account numbers, addresses). They must not linger after the owner has decided to remove the data they belong to, and the owner must be able to remove them deliberately.

## Standing rules

1. Read first: `CLAUDE.md`, all `docs/prompts/PHASES*.md`, `docs/imports.md`, `docs/architecture.md`, `docs/deployment.md`, `docs/podman-explained.md`, ADR 0003, 0014, 0015 and any ADR about year deletion, backups or stored originals, and the code: the year-delete view and service, `ImportBatch`, `ImportRow`, the stored-original storage (field, upload path, MEDIA or data directory), `pdf_imports.py`, `imports.py`, the imports list, history and original-download views, the backup and restore flow, and their tests. Everything in `CLAUDE.md` still applies (Decimal only, keep originals unless the owner explicitly removes them, state the basis of every figure, never guess a legal or SBK rule, no real network in tests, synthetic test data only).
2. **One phase, one report.** Ask the questions below in your first reply together with what you found, then continue with the stated defaults if unanswered (say so at the top). Stop at the end with the report (what was done, commits, tests with real results, deviations, open questions, anything not verified) and wait for "go".
3. **Verify, do not assume.** This file was written from the owner's description, not from the code. Where it says "verify", read the code and say what you found. If the code differs, say so and adapt.
4. **Privacy (highest priority).** Use only synthetic data in tests, reports, commits and logs. Never print amounts, names, account numbers or file contents. File names are shown masked as elsewhere (digit runs of six or more).
5. **Deleting is a deliberate, confirmed, POST-only action**, never a GET, never silent, never automatic without the owner's confirmation on screen. `CLAUDE.md` rules on keeping originals mean: the app never removes an original on its own initiative. Here the owner is explicitly asking for removal, so removal is allowed only through the confirmed actions designed below. State in the report how this fits the wording of `CLAUDE.md` and update `CLAUDE.md` so it says so.
6. **Acceptance criteria** are checkable statements. Each needs a test or a demonstrated command, reported as met, not met, or not verifiable here, with evidence. At least one test exercises the real artifact: a real file written to a temporary storage directory and shown to be gone from disk, not only a missing database row.
7. No new dependency. No change under `infra/`, the Containerfile or the Makefile except a documented test target. Nothing in the app is a tax calculation or an SBK assessment.
8. After the owner's decisions, update `CLAUDE.md` (Imports and data-retention text), `docs/imports.md`, `docs/architecture.md` and add ADR 0028 (`docs/decisions/0028-...md`). Never delete an old ADR; mark any superseded one.

## Phase 28: Lifecycle of stored import files

Goal: understand exactly what is kept when a year (or a payment, or an import batch) is deleted, then make the lifecycle of stored originals explicit, safe and owner-controlled.

### Questions for the owner (ask in the first reply, with defaults)
1. **What should deleting a year do with its imports?** Default: the year-delete confirmation page lists the import batches that contributed to payments of that year, says for each whether it is *only* used by that year or *also* used by other years, and offers a checkbox "also delete these stored PDFs and their import history", **off by default**, and applying only to batches that are not used by any other year.
2. **Batches spanning years** (for example statements covering two months across a year end, or one zip with several years): default is to keep them and say so on the confirmation page; they can be removed later from the imports page once no remaining payment refers to them. Confirm.
3. **Imports page: delete a batch.** Default: add a per-batch "Delete stored file" and "Delete batch completely" action on the imports history page, as POST buttons with a confirmation step. "Delete stored file" removes the original (PDF or zip) from disk and keeps the history line and the row data, marked "original removed". "Delete batch completely" removes the batch, its staged rows, its history and the file. Which of the two do you want, or both? (Default: both.)
4. **Committed batches whose payments still exist.** Default: deleting the file or batch never deletes payments. The confirmation says how many payments still came from this batch. Confirm.
5. **Re-upload after deletion.** Deleting a batch also removes the same-file and fingerprint memory for it, so the same statement can be imported again. Default: yes, and the confirmation says so. Confirm.
6. **Already orphaned files.** Default: a read-only report first (`manage.py` command or `tools/` script, dry run by default) listing stored files that no batch refers to and batches whose file is missing, counts and masked names only; deletion only with an explicit `--apply` after the owner has seen the list. Also a button on the imports page? (Default: no, command only.)
7. **Backups.** Existing backups still contain the removed files. Default: document this clearly and do not touch backups. Do you want a documented procedure to expire old backups, as a separate decision?

### Tasks
1. **Verify and report in one paragraph each:** (a) what the year-delete action removes today (payments, rates, import rows, batches, files) and what it deliberately leaves; (b) how a batch is linked to the payments it created (direct foreign key, row data only, or no link) and whether that link survives deletion of the payments; (c) where the stored original lives (path, naming, owner and permissions inside the rootless container's data volume) and whether the database holds the path or a file field; (d) what the imports page and history show and which actions exist; (e) what the same-file and fingerprint detection relies on, so deleting a batch has the effect in question 5 and nothing worse; (f) how backups and the restore drill treat stored originals.
2. **Reproduce** the owner's problem with a test: create a year with a committed import batch (synthetic PDF), delete the year, and assert what remains in the database and on disk. The test must fail or document the current behaviour before the fix.
3. **Design** per the owner's answers: the linkage needed to know which batches belong to which year (derive it from the payments the batch created; if no link exists, report the options and choose the least invasive, with a reversible migration and no guessing for old batches: batches that cannot be attributed are listed as "unattributed" and are only deletable manually from the imports page).
4. **Service layer.** One function that deletes a batch's stored file, one that deletes a batch completely, both transactional with the file removal done only after the database change commits (and a failed file removal reported, not swallowed). Missing file on disk is not an error, it is reported as "already gone". The file path must be resolved inside the storage directory and refused if it escapes it (no path traversal).
5. **Year delete.** Extend the confirmation page and action per answer 1 and 2. Everything the owner sees is counts and masked names, never contents.
6. **Imports page.** Add the actions per answers 3 to 5: POST-only forms, CSRF protected, confirmation step stating exactly what will be removed and what will remain (payments, history), a success or failure message, and the history line updated ("original removed on <date>").
7. **Orphan report** per answer 6, read-only by default.
8. **Audit.** Record each deletion in the existing history or log mechanism (what kind, when, how many files and batches; no names or amounts).
9. **Docs.** `docs/imports.md` (stored files, retention, deleting, backups), `docs/podman-explained.md` only if a command is added, `CLAUDE.md`, `docs/architecture.md`, ADR 0028.

### Acceptance criteria
- A test reproduces the reported behaviour before the fix (year deleted, file remains) and passes after it with the option chosen.
- Deleting a year with the option on removes the files of batches used only by that year, from the database **and from disk** (test inspects the temporary storage directory); with the option off nothing is removed.
- A batch that also supports payments of another year is not removed by the year delete and is named on the confirmation page.
- "Delete stored file" removes the file, keeps history and row data, and the download link then explains the original was removed; "Delete batch completely" removes batch, rows, history and file; neither deletes any payment.
- Neither action can be triggered by a GET request; both require CSRF; both show a confirmation naming what is kept and what is removed.
- After deleting a batch, the same synthetic statement can be uploaded again (answer 5); before deleting it, it is still detected as a duplicate.
- A stored path that points outside the storage directory is refused (test).
- A missing file on disk does not crash the delete and is reported.
- A failure of the file removal after the database change is reported to the owner and logged; the database is not left pointing at a file that is gone without the history saying so.
- The orphan report, run without `--apply`, deletes nothing and prints counts and masked names only (test asserts no digit run of six or more and no amount); with `--apply` it removes exactly the listed orphans.
- Migration (if any) applies to and reverses from a copy of a realistic database; old unattributed batches are listed and untouched.
- Backup and restore tests still pass; `docs/imports.md` states that existing backups keep their copies.
- All earlier tests pass unchanged.

### Stop and report
In the report, say in plain language what is now deleted when a year is deleted, what the owner can delete from the imports page, what is still kept (and where), and how backups are affected.
