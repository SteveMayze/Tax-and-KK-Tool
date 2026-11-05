# "Use for all rows": enter a missing organisation once for every statement of the same company

Branch: `fix/au-dividend-statements` (continue on it, after ADR 0040). Follow CLAUDE.md: scope and assumptions first,
small commits, real test results, end-of-phase report, STOP for the owner's "go" before merging. No financial rule is
involved; this is review-page convenience only.

## Why
Four Mirvac advices (no ASX code printed) now stage as four blocked rows with an empty organisation. Each needs the same
edit ("Mirvac Group (MGR)"), four times. The owner wants to enter it once.

## What the code does today (verified by reading; re-check)
* `dividend_statements.Dividend.row_data` sets `organisation=''`, `data['_structural']=[...]` and `data['_org_hint']` (the
  printed company name) when `code_missing`.
* `pdf_imports._add_organisation_proposal` pops `_org_hint` BEFORE the rows are stored, turning it into text inside
  `_structural` (and an existing-organisation proposal when exactly one organisation starts with the name). So after
  staging, nothing durable says which rows belong to the same company.
* `imports.update_row` replaces `row.data` with the CSV columns only, so a single-row edit drops `_structural`;
  `revalidate_batch` then re-checks, and `lookups`/`validate_row` handle new organisations as usual.
* The preview page already has a batch-level form for countries (`import_countries`, `org_countries.review`) that is the
  pattern to follow for placement, POST handling and the preview-state guard.

## Task
1. Keep the grouping key. Store the printed company name per row so it survives the pop and the single-row edit (a small
   CharField on `ImportRow`, e.g. `org_hint`, one reversible migration; or another durable place if you can justify it).
   It is a label for grouping only: never shown as data, never used for matching in code, no name-to-code table.
2. On the preview page (only while the batch is in preview), when rows exist whose organisation is empty AND have an
   `org_hint`, show one small form per distinct hint: the printed name, the number of rows, a text input for the
   organisation (prefilled ONLY with the single existing-organisation proposal, else empty) and a button
   "Use for all N rows".
3. New POST view (login required, `require_POST`, `_state_guard`, same style as `import_countries`). In one transaction:
   * validate the value like `validate_row` does for an organisation (non-empty, <= 200 characters after whitespace
     squeeze, not an inactive organisation; no row is changed on a validation error, show the message);
   * set `data['organisation']` for the rows of THIS batch with that hint whose organisation is STILL empty (never
     overwrite a row the owner already edited or excluded-by-choice), remove their `_structural`, keep `original` untouched;
   * call `revalidate_batch` once for the batch.
   Report how many rows were changed in a success message.
4. The single-row edit page keeps working unchanged. A group disappears from the page once none of its rows is empty.
5. The country control for NEW organisations must pick up the organisation the owner just applied (it appears after the
   refresh with its proposed country), and duplicate detection must still run (the four statements are different dates,
   so none is a duplicate of another).

## Tests (synthetic text only; no real names or amounts in tracked files)
* Three staged rows with the same hint and one with another hint: applying a value changes exactly the three rows,
  leaves the fourth blocked, and the batch becomes committable once the fourth is handled.
* A row the owner edited by hand before is not overwritten.
* An empty value, an over-long value and an inactive organisation are refused and change nothing.
* The POST is refused when the batch is no longer in preview; GET is not allowed; anonymous access is redirected.
* The prefilled proposal appears only when exactly one existing organisation matches.
* Migration forward and backward. `python manage.py test`: report the full-suite result (3 SBK "unverified year" tests
  already fail on a clean checkout; report them, do not fix them). Re-run the 76 Securities samples and report counts
  only (expect 72 staged, unchanged).

## Docs and translations
Update ADR 0040 or add a short ADR, docs/imports.md and CLAUDE.md. Append the new German strings to the `.po` by hand
(makemessages rewrites thousands of unrelated lines), compile the `.mo`, and list the new terms for the owner's review.
Say in the report that the page was exercised through Django's test client only, and list what the owner should click
through in a browser: upload the four MGR statements, apply one organisation to all, set the country, commit.
