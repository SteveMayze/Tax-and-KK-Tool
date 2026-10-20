# ADR 0029: Lifecycle of stored import files

Status: accepted (Phase 28, 2026-10-20). The owner reported that the PDFs and zips uploaded for a year stayed on the server after the year was deleted and could not be removed. (PHASES_6.md calls this "ADR 0028"; that number was already used by the optional-settings ADR, so this is 0029.)

## Decision
- Stored originals are removed only by confirmed POST actions of the owner: the year-delete confirmation (checkbox, off by default; only batches used by that year alone), "Delete stored file" and "Delete batch completely" on the imports page, and `manage.py stored_files_report --apply`. Nothing deletes a payment.
- Which batches belong to a year is derived from `Payment.import_batch` when the confirmation page is shown, because that link is cleared when payments are deleted. Batches left from earlier year deletions are shown as "unattributed" and are removable only manually. No guessing, no backfill.
- One service module (`import_files.py`): database change in one transaction, files removed after the commit, path resolved inside `UPLOAD_DIR` and refused otherwise, a missing file is "already gone", a failed removal is reported and logged and leaves the batch pointing at nothing (the leftover is found by the orphan report).
- "Delete stored file" sets the new `ImportBatch.original_removed_at` and keeps history and rows, so the "already imported" memory stays; "Delete batch completely" removes it with the batch, so the same statement can be uploaded again. That memory is only the file hash on the batch; row duplicate detection compares against existing payments and is unchanged.
- Audit: `ImportDeletion` (kind, time, counts) shown on the imports page, plus a log line with counts. No names, amounts or paths.
- Migration 0013 adds one nullable field and one table; it reverses cleanly.

## Consequences
CLAUDE.md's "keep originals" is read as: the app never removes one on its own; the owner may. Backups made earlier keep their copies (documented, untouched; expiring them is a separate decision). The default year delete is unchanged, so the privacy risk remains until the box is ticked; the confirmation page lists the batches so that this is visible.
