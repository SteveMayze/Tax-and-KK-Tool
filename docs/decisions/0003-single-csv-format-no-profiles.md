# ADR 0003: One documented CSV format, previewed rates applied at commit

Status: accepted (Phase 5). Supersedes the "configurable per-institution profiles" wording in CLAUDE.md.

## Context
The original brief called for per-institution CSV profiles with column mapping. The owner prepares the CSV by hand, so the input format can follow the app's own payment table.

## Decision
- One fixed, documented format (docs/imports.md); no profile or mapping models. A template download shows it.
- Rows are staged and reviewed before anything is created. Validation reuses the `Payment` model rules.
- The conversion shown in the review is stored on the staged row and applied unchanged at commit (`StoredQuoteProvider`), so there is no second lookup and no surprise.
- Commit is a single transaction guarded by a status check, which makes double submission harmless.
- Duplicate rule: date + organisation + currency + gross amount, flagged and skipped unless kept.
- Original uploads are kept under `UPLOAD_DIR` and linked from history; discarding a pending batch removes them.
- PDF extraction and its dependency are deferred.

## Consequences
Simple code and a simple mental model; importing an institution's own export needs a spreadsheet step first. Profiles can be added later behind the same staging model if needed.
