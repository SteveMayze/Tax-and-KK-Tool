# PHASES_8.md: Tax and Healthcare Tool, Phase 30 (filter reports by organisation and category)

Save this file as `docs/prompts/PHASES_8.md`.
**Do not edit or overwrite `PHASES.md` to `PHASES_7.md`.** If you find an error in them, record it in your end-of-phase report. Phases 1 to 29 are implemented (Phase 20 deliberately not) and the app is in production.

## Goal

Reports can today be limited by year only. To verify the figures against statements, the owner needs to limit them by **organisation** and by **income category** as well. Because one organisation can have payments in several categories (and a category can hold payments of several organisations), both filters are **groups of check boxes** (any number ticked), not single-value drop-downs.

This is a read-only reporting change: no model, migration, import or payment logic changes, and nothing is stored.

## Behaviour requested by the owner

1. On the reports index page and on every report page, next to the existing year selector, two check-box groups: **Organisations** and **Categories**. Several can be ticked in each.
2. Within a group the ticked items are combined with **OR**; the two groups are combined with **AND**. Nothing ticked in a group means no restriction by that group (not "show nothing").
   - Example: ticking organisation A shows all of A's payments, whatever their category; ticking A and category X shows only A's payments in X; ticking categories X and Y shows every organisation's payments in X or Y; ticking A, B and category X shows A's and B's payments in X.
3. The filter combines with the year selector (any year or all years).
4. The filter is applied to the on-screen report **and** to the CSV download, and the report states it in its basis block (Financial principle 4).

## Standing rules

1. Read first: `CLAUDE.md`, `docs/reporting.md`, `docs/imports.md` only as needed, `docs/glossary.md`, ADR 0006, 0010, 0011, 0012, 0013 and 0030, `docs/prompts/PHASES_2.md` (Phases 12 and 13), and the code: `core/services/reports.py` (`_payments`, `_basis`, `_make`, `_group_report`, the registry `REPORTS` / `ReportSpec`), `core/services/policy_reports.py`, `core/services/report_csv.py`, `core/services/reconciliation.py` (`build_report`), `core/services/policies/` (`tax_summary_rows`, `tax_checks`, `assess_year`), `core/views_reports.py`, `core/templates/core/report.html`, `report_index.html`, `templates/base.html` (header language switch), `core/static/core/base.css`, `core/icons.py`, `core/test_reports.py`, `core/test_visual.py`, `core/test_i18n.py`, `core/test_icons.py`. Everything in `CLAUDE.md` still applies (Decimal only, state the basis of every figure, no inline `style=`, CSS tokens only, `.btn` classes, translated strings, synthetic test data only).
2. One phase only. At the end stop, give the end-of-phase report (what was done, key decisions, files changed, checks with real results, deviations, open issues, how to verify by hand) and wait for "go".
3. **Ask first.** Put the questions below in your first reply together with what you found when you verified the current state. If unanswered, use the stated default, say so at the top of your work, and continue.
4. **Verify the current state.** This file was written from a read of the code, not from running it. Where it says "verify", read the code, say what you found and adapt if it differs.
5. **Unfiltered output must not change.** With no filter ticked, every report page, every CSV (byte for byte, apart from the `Generated (UTC)` row) and every existing test is exactly as before. Before changing any code, capture the current output of every report (page text and CSV, all years and one year) from a synthetic dataset into a temporary test helper, and prove equality afterwards. Existing tests stay green and unchanged; say if one has to change and why.
6. **Filter by id, never by name.** Organisation and category names are unique case-insensitively, but the form, the query string and the queries use primary keys. Unknown, non-numeric or duplicate ids: unknown or non-numeric is an error message in the same style and place as the existing "Unknown year" message (no 500, no silent ignore); duplicates collapse. The ids are sorted so equal selections give equal URLs.
7. **The numbers come from one place.** The filter is applied once, where the payment set is chosen (`_payments`), so every figure, count, exclusion line and share in a report is computed over the same filtered set. No report re-implements the filter, and no total is computed over unfiltered data and then "adjusted".
8. **State it.** A filtered report's basis block gets one extra row, `Filter`, naming the ticked organisations and categories (by name, as stored) and saying that the groups combine as "any of the ticked organisations AND any of the ticked categories". The row appears only when a filter is active, so unfiltered reports are unchanged. It is also the second row group at the top of the CSV (in the same `label,value` block as the other basis items), and it is in print. If a filter is active on a report that cannot honour it (see Q30.1), the page and the CSV say so explicitly instead of showing unfiltered figures silently.
9. **Privacy.** Names of real organisations and categories come only from the database at runtime. Nothing taken from the owner's data appears in tracked files, test names, fixtures, docs, ADRs or commit messages. Tests use invented names ("EXAMPLE ORG A", "EXAMPLE CATEGORY X"). Review staged files before every commit.
10. **Acceptance criteria** are checkable statements, each needing a test or a demonstrated command. Report each as met, not met, or not verifiable here, with evidence. Every corner-case id listed in the phase gets a test named after it.
11. **No new dependency, no JS framework, no icon font, no CDN.** The check boxes are a plain HTML GET form and work without JavaScript. Small progressive enhancement (select all / none) is allowed in the same inline style as `report_index.html`, but nothing may depend on it.
12. **Visual rules (Phase 13) and icons (Phase 29, ADR 0030) apply.** Each group is a `<fieldset>` with a `<legend>`; every box has a real `<label for=...>`; colours only as CSS tokens in `base.css` (extend `tools/check_contrast.py` for any new token and report the result); no inline `style=`; click targets at least 32 x 32 px; keyboard order natural; focus outline visible; no dark mode. Use existing icons only; do not add one. Keep visible text on the buttons ("Show", "Clear filters"): they are ambiguous without it.
13. **Language (Phase 12).** All new text goes through `{% trans %}` / `gettext`, English and German; update the `.po` with makemessages, compile the `.mo` with msgfmt, commit both. German report terms come from `docs/glossary.md` (check how it names Organisation and Category; do not invent a second wording). CSV stays English whatever the interface language is.
14. **Deployment is untouched** (nothing under `infra/`, the Containerfile or the Makefile). No change to the database schema.
15. Update `CLAUDE.md` (Reports: one or two lines), `docs/reporting.md` (a "Filters" section, the `Filter` basis row, which reports honour it, the URL parameters), `docs/architecture.md` if it describes the reports code, and add an ADR with the next free number (expected `0031-report-filters.md`; verify the sequence). Never delete an old ADR.

---

## Phase 30: Organisation and category filters on reports

### Questions for the owner (defaults in brackets)

- **Q30.1 Which reports honour the filter.** [Default: annual summary, monthly breakdown, payment-level detail, by organisation, by category, original-currency summary, normalised monthly, missing data and reconciliation, and the tax information summary (information only). **Not** the SBK contribution estimate and the tax checks: those are whole-person assessments computed by the policy services from all the owner's income (and, for the tax checks, from annual inputs such as the saver's allowance), so an estimate over part of the income would be a wrong figure that looks right. On those two pages the filter form is replaced by a one-line note, and a filter in the URL is ignored with a visible message.] Verify what `tax_summary_rows` and `build_report` need to accept a filtered payment set; if honouring the filter on the tax information summary or on the reconciliation report would require touching policy rules or the reconciliation logic beyond passing the payment set in, tell me and leave that report unfiltered with the note.
- **Q30.2 Which options are listed.** [Default: every organisation and every category that has at least one payment in any year, active or not (inactive ones are marked "inactive"; a payment may still point at one), each with its payment count for the period currently selected, so a zero is visible before you tick it. Organisations and categories with no payment at all are not listed.]
- **Q30.3 Where the form lives.** [Default: on each report page (one form: year, organisations, categories, `Show`, `Clear filters`) and on the reports index page, where it is applied to the View and CSV links the same way the year is today (JavaScript enhancement; without JavaScript the links open unfiltered and the report page's own form is used). Check boxes sit inside `<details>` that is closed when no box is ticked and open when one is, so long lists do not push the report down.]
- **Q30.4 CSV file name.** [Default: unchanged when no filter is active; `report-<key>-<year or all>-filtered.csv` when one is. The details are in the `Filter` row, not in the file name, because names can be long.]
- **Q30.5 Other pages.** [Default: only the Reports pages and the CSV. The month, year, reconciliation and payment list pages are not changed.]
- **Q30.6 A cross-table.** [Default: not built. Say if you want an "organisation x category" report; for checking organisations that straddle categories it would show every pairing at once. List it as a candidate in the end-of-phase report only.]

### Corner cases (every id needs a test)

- **F1 Organisation across categories.** One organisation with payments in two categories: ticking only the organisation shows both; ticking the organisation and one category shows only that one.
- **F2 Category across organisations.** The mirror case: ticking only a category shows every organisation's payments in it.
- **F3 AND between groups, OR within.** Two organisations and two categories ticked: exactly the payments whose organisation is one of the two and whose category is one of the two.
- **F4 Empty group is no restriction.** Nothing ticked in one group and something in the other restricts by the other only. Nothing ticked in either equals the unfiltered report (F0 below).
- **F0 Unfiltered equals today.** See standing rule 5, for every report, with and without a year.
- **F5 Ticking everything.** Ticking every listed organisation and every listed category gives the same figures as ticking nothing (the basis block still states the filter; the figures are equal).
- **F6 Inactive organisation or category** is listed, marked, and filterable.
- **F7 Bad ids.** Non-numeric, unknown, negative, very long, repeated and mixed-case parameter names: error message or collapse as in rule 6, never a 500, never a silently different result; the error does not echo more than 10 characters of the input (as for the year).
- **F8 Look-alike names.** Two organisations whose names differ only in case, spacing or umlaut spelling (they may exist as separate rows if the spelling differs beyond what the unique constraint catches): filtering one never includes the other.
- **F9 Corrections and reversals** belong to the organisation and category they were entered under and follow the filter; the gains, losses and "corrections / reversals" columns are filtered with them.
- **F10 Exclusions and rate basis.** "Unconverted", "without a net amount", "correction/reversal entries" and the exchange-rate counts in the basis block count only the filtered payments.
- **F11 Empty months stay.** Monthly breakdown and normalised monthly still show all 12 months when the filter leaves some empty.
- **F12 Shares.** In the by-organisation and by-category reports the "share of gross" is relative to the filtered total (so it adds up to 100 % within the filter); a note says so when a filter is active.
- **F13 No match.** A filter that matches nothing gives an empty report with the message "No payments match this filter" (not "No data for this period"), the filter stated in the basis block, and a CSV with the header, basis and no data rows.
- **F14 Year and filter together,** and "all years" with a filter; the annual summary lists only the years that have matching payments.
- **F15 Reports that do not honour the filter** (Q30.1): the note is shown, the figures are the unfiltered ones, the CSV says `Filter,not applied to this report` when a filter was passed, and a test proves the figures do not change when a filter parameter is added.
- **F16 Query string survives.** Changing the year, pressing `Show`, following the CSV link, the back link to the reports index and the header language switch keep the ticked boxes (verify what the language switch does with a query string today; if it drops it, report it, and fix it only if the fix is small and contained in the switch).
- **F17 Print.** The form is hidden in print; the `Filter` row in the basis block prints.
- **F18 Long lists.** With 30 organisations and 12 categories the form stays usable (the `<details>` rule, a scroll limit by CSS class on the group, not inline).
- **F19 Method and login.** GET only, login required, no state change, `Cache-Control: no-store` on the CSV as today.

### Tasks

1. **Verify** and report in one paragraph: how `year` flows from `views_reports._year` / `_build` into `spec.build(year)`, which builders use `_payments`, which use something else (`policy_reports`, `reconciliation.build_report`, `tax_summary_rows`), what `report_csv.render` writes at the top, and how the header language switch treats a query string.
2. **Filter object.** A small frozen value object (for example `ReportFilter(organisation_ids, category_ids)` with `is_active`, `describe()` returning the text for the basis row, and a `querystring()` helper) in `core/services/`, with a parser from `request.GET` that returns the object or an error text (rule 6). Builders take it as an optional keyword argument defaulting to "no filter"; `_payments(year, flt=None)` applies it with `organisation_id__in` / `category_id__in`. No raw SQL, no name matching.
3. **Registry.** `ReportSpec` gets a `supports_filter` flag (default true in the registry above, false for `sbk` and `tax_checks` unless Q30.1 is answered otherwise). The view passes the filter only to builders that support it, and sets the "not applied" note otherwise (F15).
4. **Basis row and notes.** The `Filter` row (rule 8), the share note (F12), the "no match" message (F13), the "not applied" note (F15). All strings translated.
5. **CSV.** `report_csv.render` shows the `Filter` row in the basis block through the same path as the other rows; file name per Q30.4; formula-injection protection applies to the names (they are text cells and may begin with `=` and so on). **Report format version** stays 2 because an unfiltered file is unchanged and a filtered file only adds a labelled row; state this in `docs/reporting.md`. If you judge a bump necessary, ask before doing it.
6. **View and templates.** Parse and validate in `views_reports` (error handling as for the year, redirecting to the index); build the option lists with their counts (Q30.2) in one query per list (no per-option queries); render one GET form on the report page and the index page. The CSV link, back link and year form keep the filter (F16) through the helper from task 2, not by string concatenation in templates. Hide the form in print. Add the `base.css` rules (tokens only) and, if used, the small enhancement script (select all / none for one group; not required for anything to work).
7. **Tests** (`core/test_reports.py` or a new `core/test_report_filters.py`; reuse the synthetic dataset and extend it only with additive rows if that does not change existing hand-worked figures, otherwise build a separate small dataset): every corner-case id above by name, with figures worked out by hand in a comment; the property test that the filtered totals of a partition add up to the unfiltered total (for example the gross EUR of "organisation A" + "all other organisations" = unfiltered, and the same by category); the view tests (login, GET only, error messages, redirect, option lists and counts, boxes ticked after a submit, links keep the query string); the template tests (fieldset and legend, label for every box, no inline `style=`); the i18n test for English and German; the CSV structure test.
8. **Docs and ADR** (rule 15). The ADR records: AND/OR semantics, filtering by id, one place where the filter is applied, which reports honour it and why the SBK estimate and tax checks do not (or the owner's other answer), no format-version bump and why, no schema change.
9. **Checks.** Run the full test suite, `python manage.py check`, `makemigrations --check` (must report no changes), `tools/check_contrast.py`, `makemessages` plus `msgfmt`, and report the actual results. Check by hand in the browser (or say you could not): tick one organisation, two categories, both groups, nothing, a bad id in the URL; compare the by-organisation total of a ticked organisation with the total in the payment-level detail filtered the same way.

### Acceptance criteria

- With nothing ticked, all report pages and all CSV files are identical to before (F0), and all earlier tests pass unchanged.
- Hand-worked figures match for F1 to F4 on the by-organisation, by-category, payment-level and annual reports, with and without a year.
- For every supported report, the gross EUR of a filtered selection plus the gross EUR of its complement equals the unfiltered gross EUR (partition test).
- A report with an active filter shows the `Filter` row in the page and in the CSV, with the ticked names and the AND/OR statement; an unfiltered report has no such row.
- The SBK estimate and the tax checks (or whatever Q30.1 decides) do not change when a filter parameter is added, and say so on the page and in the CSV.
- A bad id never produces a 500 and never a silently different report.
- The ticked boxes survive `Show`, the year selector, the CSV link, the back link and the language switch (or the language-switch limitation is reported).
- The form works with JavaScript disabled.
- `makemigrations --check` reports no changes; no file under `infra/`, the Containerfile or the Makefile is touched; no new dependency.
- No real organisation, category or other personal name appears in any tracked file.

### Stop and report
