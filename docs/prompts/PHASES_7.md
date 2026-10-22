# PHASES_7.md: Tax and Healthcare Tool, Phase 29 (icons instead of text links and buttons)

Save this file as `docs/prompts/PHASES_7.md`.
**Do not edit or overwrite `PHASES.md` to `PHASES_6.md`.** If you find an error in them, record it in your end-of-phase report. Phases 1 to 28 are implemented (Phase 20 deliberately not) and the app is in production.

## Goal

Make the interface look more modern by replacing the plain-text links and buttons for common actions with small icons, without changing what any control does. This is a presentation change only: no model, service, URL, view or report logic changes.

## Standing rules

1. Read first: `CLAUDE.md`, the Visual rules of Phase 13 (ADR 0013), the language rules of Phase 12 (ADR 0012), `docs/prompts/PHASES_2.md` (Phases 12 and 13) and, for the history of what the controls do, `docs/prompts/PHASES_3.md` to `PHASES_6.md` as needed; `core/static/core/base.css`, `core/static/core/autosize.js`, `templates/base.html`, `templates/registration/login.html`, every file in `core/templates/core/`, `tools/check_contrast.py`, and the tests that assert on link or button text. Everything in `CLAUDE.md` still applies.
2. One phase only. At the end, stop, give the end-of-phase report (what was done, key decisions, files changed, checks with real results, open issues, how to verify by hand) and wait for "go".
3. **Ask first.** Put the questions below in your first reply with what you found. If unanswered, use the stated default, say so at the top of your work, and continue.
4. **Behaviour is unchanged.** Anything that changes or deletes data stays a POST form button; a delete control still only opens its confirmation page when it was a link; confirmations, CSRF tokens, URLs (including the `/tax-healthcare` prefix; use `{% url %}`, never hard-coded paths) and permissions stay as they are.
5. **No new dependency, no JS framework, no icon font, no CDN.** Icons are inline SVG. Take them from an open-source set with a permissive licence (suggestion: Lucide, ISC, or Feather, MIT; verify the licence text yourself), copy only the icons used, and record the source, licence and copyright notice in `docs/architecture.md` (or a `docs/third-party-notices.md`) and in the file that holds the icons. Do not draw look-alikes of a brand's logo.
6. **Visual rules of Phase 13 still apply:** colours only as CSS tokens in `base.css` (icons use `currentColor`, so they follow the button's token colours); no inline `style=`; no dark mode; `.btn` classes stay the way actions are styled; contrast still passes `tools/check_contrast.py` (extend it to cover any new token and report the result).
7. **Accessibility and language (Phase 12).** Every icon-only control has an accessible name and a tooltip, both translated with `{% trans %}` (English and German; update `.po` with makemessages, compile `.mo` with msgfmt, commit both). The SVG itself is `aria-hidden="true"` and `focusable="false"`. Keep the existing translated strings for the names where possible, so German wording does not change. Focus outline stays visible; click and tap target at least 32 x 32 px; keyboard order unchanged.
8. **Print and export.** The print stylesheet already hides `.btn` and `button`; check that nothing icon-related appears in print. CSV exports are untouched.
9. **Tests.** Existing tests must keep passing. Where a test asserts on visible link or button text, change it to assert on the accessible name (the `aria-label` or the visible text that remains), and say which tests you changed and why. Add: a test that every control that has an icon and no visible text has a non-empty accessible name, in both languages; a test that no template contains an inline `style=` (if one exists already, keep it); a test that each icon name used in a template exists in the icon set.
10. Privacy rules of earlier phases apply to anything you write: no personal data in tracked files, tests, screenshots or commit messages.
11. Deployment is untouched (nothing under `infra/`, the Containerfile or the Makefile). Static files are still only the app's own files via WhiteNoise.
12. Update `CLAUDE.md` (UI, Visual rules: one line on icons and the accessible-name rule), `docs/architecture.md`, and add an ADR (next free number, it should read `0030-...` unless the sequence has moved) recording the decisions below. Never delete an old ADR.

## Phase 29: Icons for common actions

### Questions for the owner (defaults in brackets)

- **Q29.1 Delete icon.** You suggested "-" or "X". A minus usually means "collapse" or "remove one from a quantity", and an X usually means "close" or "cancel", which clashes with Cancel. Options: X, trash can, minus. [Default: trash can for destructive delete controls, X kept for nothing else; say if you want a plain X as asked. It is a one-word change in one file.]
- **Q29.2 View on the imports list.** A "download" arrow would suggest the file is downloaded, but this control opens the import's review page. [Default: an eye icon for "View import"; the download arrow is used only for real downloads (the CSV template, the stored original file).] Glasses are not offered by the usual icon sets; the eye is the common modern equivalent.
- **Q29.3 CSV.** `<>` ("code") says "raw text" but not "download". [Default: the `<>` icon with the visible text "CSV" kept next to it, because a bare `<>` is cryptic; the tooltip says "Download CSV".] Alternative: a table/spreadsheet icon.
- **Q29.4 Icon only or icon plus text.** [Default: icon only (with tooltip and accessible name) for the universally understood actions: add, edit, delete, view, log out, back; icon plus visible text for anything ambiguous or rare (CSV, reports, assessment settings, reconciliation, "Try automatic conversion for all of these", "Enter a rate manually instead"). Main navigation keeps its text and gets an icon before it.]
- **Q29.5 Scope of the extra suggestions** (section "Further candidates"). [Default: implement the "Do now" group, list the "Maybe" group in the report and wait for the owner's choice.]
- **Q29.6 Style.** [Default: outline icons, 1.75 px stroke, 18 px inside a 32 px button, rounded, one size everywhere, one icon set only.]

### Mapping requested by the owner

| Today (text) | Icon | Notes |
|---|---|---|
| Add year, Add month, Add payment, Add organisation, Add category (the `Add {{ cfg.singular }}` link) | plus | Icon-only on tables and list headers; keep the visible text on the first-time empty state if there is one |
| Delete (payment, year, month, organisation/category, import rows), "Delete this year…", "Delete this month…" | trash can (Q29.1) | Still opens the confirmation page; the confirmation page's "Yes, delete" button keeps its text and the danger colour |
| Edit | pencil | |
| View / View import / Open (imports) | eye (Q29.2) | |
| Log out | power | Stays a POST form button in the header; keeps the user name beside it |
| Reports (the report links and the report index entries) | file with lines (report) | Visible text kept where it names a report |
| CSV (Download CSV) | `<>` (Q29.3) | Visible text "CSV" stays |

Resolve each of these against the actual templates and say, per template, which controls you changed. Do not change a control that does not appear in a template.

### Further candidates (my suggestions)

**Do now (low risk, obvious meaning):**
- Back (back to imports, back to review, link back to year or years) : arrow left, icon plus text.
- Save, Save payment, Save notes, Save rate, Save and re-check : keep the text (these are the primary actions of a form); optionally a check mark before the text. Do not make them icon-only.
- Cancel : text only, secondary style. Do not use an X (it would look like delete).
- Navigation: Years (calendar), Organisations (building), Categories (tag), Reports (report), Assessment settings (sliders), Imports (inbox or upload), Reconciliation (scale or check-in-circle): icon before the text.
- Original file / stored original : paperclip or file; "Download a template with synthetic example rows" : download arrow, text kept.
- Request exchange rates again / recalculate : circular arrows, text kept.
- Include / Exclude / Skip duplicate / Keep anyway on import rows : eye and eye-off for Include and Exclude, text kept (state-changing, so they stay POST buttons).
- Language switch EN / DE : unchanged (text is clearer than flags).

**Maybe (ask the owner):**
- Filter : funnel.
- Upload and preview : upload arrow, text kept.
- Delete stored file : file with an X; Delete batch completely : trash can with the danger colour (both stay behind their confirmation).
- Discard (import) : trash can.
- Map categories : tag with an arrow.
- "SBK contribution estimate" and "SBK estimate" links : calculator.
- The existing "i" info buttons (glossary popovers): keep as they are.
- Status marks in tables (needs attention, duplicate, imported, excluded): small icons with text, never colour alone.
- Sortable column headings and expandable sections: chevron.

### Tasks

1. **Inventory.** List every link and button in `templates/` and `core/templates/core/` (including `_payment_rows.html` and the login page) with its text, element type (link or POST button), template and the action it performs. Put the table in the report (text and counts only, no data values). Verify that the Phase 13 rule "state-changing = POST button" holds everywhere before you change anything, and report exceptions without fixing them in this phase.
2. **Icon mechanism.** Choose the smallest mechanism that fits Django templates and the Phase 9 static setup, and say why. Suggestion: an inline SVG sprite included once in `base.html` (or a template tag `{% icon "plus" %}` that renders one `<svg>`), because external `<use href>` files can misbehave under the `/tax-healthcare` prefix and cross-origin rules. Do not hard-code the prefix. Keep all icons in one file, named by what they depict (`plus`, `pencil`, `trash`, `eye`, `power`, `report`, `code`), not by where they are used.
3. **Styles.** In `base.css`: an `.icon` class (size, stroke, `currentColor`), an `.btn-icon` modifier (square target, no extra border for secondary and link style, hover and focus states from existing tokens), the danger variant using the existing danger tokens. No new colours unless a token is added and passes `tools/check_contrast.py`.
4. **Convert the controls** per the mapping and the "Do now" group. Every icon-only control gets `aria-label` and `title` with the same translated string. Where a visible label remains, the SVG is decorative. In tables, group the row actions (edit, delete, view) in one cell with consistent order: view, edit, delete.
5. **Language.** Add the new strings to the `.po` files (English and German), compile, commit both; German terms for actions come from the existing translations or `docs/glossary.md`, nothing invented.
6. **Responsive and keyboard check.** On a laptop width and a narrow window (about 360 px): no overflow, targets at least 32 px, tab order unchanged, focus visible on every icon. Describe how you checked (for example a headless browser screenshot into the git-ignored `local/` area; do not commit screenshots that show data).
7. **Tests, docs, `CLAUDE.md`, ADR** as in the standing rules.

### Acceptance criteria

- No control changes its URL, method, confirmation step or permission; the existing view and service tests pass unchanged except for the text assertions listed in the report.
- Every converted icon-only control has a non-empty, translated accessible name and tooltip in English and German (test).
- Every state-changing control is still a POST form button with a CSRF token; no icon wraps a GET link that changes data (test or a documented grep).
- `make` check, test and contrast targets pass; real results reported.
- No inline `style=`, no new dependency, no external request for icons; the licence notice is present.
- Print preview shows no icons or buttons; CSV exports are byte-for-byte unchanged.
- The report lists the inventory table, the final mapping (control, icon, icon-only or with text), the "Maybe" items not done, and any control you left as text with the reason.

### Stop and report
