# ADR 0041: Use one organisation for all rows of the same printed company

Status: accepted (fix branch `fix/au-dividend-statements`, 2026-11-05). Extends ADR 0040; review-page convenience only, no financial rule.

## Decision
- `ImportRow.org_hint` (CharField, one reversible migration 0015) keeps the company name printed in a statement without an ASX code. It is a grouping label only: never a CSV column, never matched in code, no name-to-code table. It survives the single-row edit.
- The preview (only in preview state) lists one small form per distinct hint that still has rows with an empty organisation: printed name, row count, a text input (prefilled only with the single existing organisation that starts with the name), button "Use for all N rows".
- The POST (`import_apply_organisation`, login, POST only, preview-state guard) validates like `validate_row` (not empty, at most 200 characters, not an inactive organisation; an error changes nothing), then in one transaction sets the organisation of this batch's rows with that hint whose organisation is still empty, drops their `_structural`, leaves `original` untouched and re-checks the batch once. A row the owner already edited is not overwritten. A group disappears when none of its rows is empty; the new organisation then shows up in the country control (ADR 0040) and duplicate detection runs as usual.

## Consequences
Rows staged before this change have no hint and are edited one by one, as before.
