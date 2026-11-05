# Review-page prompts: a missing ASX code, and the country of a new organisation

Branch: `fix/au-dividend-statements` (continue on it). Follow CLAUDE.md: scope and assumptions first, STOP at the
decision gate in section 4, small commits, real test results, end-of-phase report. Do not change any parsing result for
statements that read today (the 68 staged samples must stay identical).

## 1. Why the four MGR (Mirvac) statements are refused today
`dividend_statements._code` raises `UnsupportedStatement('The security (ASX code) could not be found.')`, so
`pdf_imports.stage_pdf_batch` stages nothing and there is no row for the owner to correct. The statement does print the
name ("your holding in Mirvac Group") but no ASX code, and `_issuer` only accepts a name printed next to an ABN.
The review page can already edit a row (`import_row_edit`, `ImportRowForm`, `services.imports.update_row`): every CSV
column including `organisation` is editable, the value is re-validated with `validate_row`, and the original value stays
in `ImportRow.original`. A row with a `_structural` error is blocked until it is edited (`data['_structural']`, dropped
on edit), and an empty organisation fails validation with "organisation: required.".

## 2. Task A: prompt for the ASX code instead of refusing
Applies ONLY when everything else in the statement reads and reconciles (date, gross, net, withholding) and the only
missing anchor is the ASX code. Any other failure still refuses as today.
* The reader returns a row with `organisation` empty, so it is invalid and cannot be committed until corrected, plus a
  visible notice/explanation on the row: "The ASX code was not found in this statement. Enter the organisation as
  '<company name> (<ASX code>)'." Add a proposal when it can be made without guessing: (a) the company name as printed
  (Mirvac statements print it in the sentence about the holding; take it only from a labelled/anchored place), and
  (b) the existing Organisation whose name starts with that printed name, if exactly one exists (show it, do not apply it).
* Never put a name-to-code table in code (CLAUDE.md: no names in code). If a remembered mapping is wanted it must be DATA
  (a small model edited in the admin, like `StatementRule`): see the decision gate.
* Four statements from the same company means four edits. Add, on the preview page, a "use for all rows from this
  company" action ONLY if it can be done as one explicit POST that re-validates every affected row; otherwise skip it.
* Fingerprint, duplicate detection and the one-row-per-statement rule are unchanged. Provenance for the other fields stays.

## 3. Task B: determine and confirm the country of a NEW organisation at import
Facts found: `Organisation.country` is blank unless the owner types it on the Organisations page; the only automatic
value is `DE` for organisations named by a `StatementRule` (`lookups.resolve_organisation`). The import preview only says
`New organisation "X" will be created.` and has no country control. A currency-to-country map exists
(`core/currencies.py: CURRENCY_COUNTRY`: AUD to AU, GBP to GB, USD to US; EUR deliberately absent) but is used ONLY by
`policies/tax.effective_country` as a report-time fallback that flags the result as "inferred"; it is never stored, which
is why the Organisations list shows no country.
Design (smallest change):
* Proposed country per row: the reader's own knowledge first (a per-reader constant, for example the RVB readers DE,
  HSBC UK GB, MECU and Ord Minnett AU, E*TRADE and Fidelity US, the Australian dividend reader AU), else
  `CURRENCY_COUNTRY` for a non-EUR currency, else blank. Keep this out of the CSV format (ADR 0003: one format; no new
  column): hold it beside the row, not in `COLUMNS`.
* Only for organisations that do not exist yet (case-insensitive, as `lookups.find`). On the preview page show one small
  control per new organisation (not per row): name, proposed country prefilled, editable, validated as ISO 3166-1
  alpha-2 (a fixed list, uppercase, via `Organisation.save` normalisation). Blank is allowed and means "unknown".
  Store the choice on the batch (for example a JSON field `organisation_countries`, one migration) and re-use it for all
  rows of that organisation; changing it is a POST that re-validates nothing else.
* Commit creates the organisation with the confirmed country (`lookups.resolve_organisation(name, country=...)`).
  An existing organisation keeps its country; never overwrite. If an existing organisation has a blank country, show a
  note and an opt-in tick "set country to AU", default off.
* Existing blank-country organisations: add a read-only list/button on the Organisations page that PROPOSES a country
  where every payment of the organisation has the same non-EUR currency, applied only after the owner confirms in a POST,
  one organisation at a time or all ticked. Say plainly that currency is a hint, not proof of the country.
* Reports: once a country is stored it replaces the "inferred" flag in the tax information summary for that
  organisation; keep the fallback for organisations still blank. Add a test that the summary output changes only in the
  flag text, not in any amount.

## 4. DECISION GATE: ask the owner before coding
1. Task A: for a missing ASX code, is a prompted, empty-organisation row (corrected by hand each time) enough, or should
   corrected codes be remembered as admin-edited data (a name to code table, applied as a proposal that still needs
   confirmation)? Recommendation: start with the prompt and the existing-organisation proposal; add the table only if
   it keeps recurring.
2. Task B: is it acceptable that a stored country is chosen by the owner from a proposal (reader / currency), never
   silently? Recommendation: yes, with the proposal always visible and editable.
3. Should the country control appear only for new organisations (recommended) or also for existing blank ones?

## 5. Tests and checks
* Synthetic text only (no real names, numbers or amounts in tracked files): a distribution advice without an ASX code
  stages one blocked row with the explanation; editing the organisation to a valid string makes it committable; a
  statement with a missing date/amount still refuses; the existing-organisation proposal appears only when exactly one
  matches.
* Country: proposal order (reader, currency, blank); EUR never inferred from currency; the control only for new
  organisations; invalid code rejected; commit stores the confirmed value; existing organisation not overwritten; the
  opt-in fill; the Organisations-page proposal changes nothing until confirmed; one migration, reversible.
* `python manage.py test`. Known and unrelated: 3 SBK "unverified year" tests already fail on a clean checkout; report
  them, do not fix them here. Re-run the 76 Securities samples and report counts only (expect the 68 staged to stay
  identical and the 4 MGR files to become staged-but-blocked).
* Translations: append German strings to the `.po` by hand (makemessages rewrites thousands of unrelated lines), compile
  the `.mo`, and list the new terms for the owner's review. Update docs/imports.md and data-model.md, CLAUDE.md, and add
  an ADR.
* Report, then STOP for the owner's "go" before merging.
