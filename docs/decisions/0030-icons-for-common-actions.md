# ADR 0030: Icons for common actions

Status: accepted (Phase 29, 2026-10-22). Presentation only: no model, service, URL, view or report logic changed.

## Decision
- **Mechanism:** a template tag `{% icon "name" %}` (`core/templatetags/icons.py`) renders one inline `<svg class="icon" aria-hidden="true" focusable="false">` from the dictionary in `core/icons.py`. Inline SVG needs no extra request, no CDN, no icon font and no `<use href>` file, so the `/tax-healthcare` prefix and WhiteNoise are not involved. One file holds every icon, named by what it depicts.
- **Set:** Lucide (ISC; some icons derive from Feather, MIT). Notices in `core/icons.py` and `docs/third-party-notices.md`. Outline, 1.75 px stroke, 18 px icon in a 32 px square (`.btn-icon`), `currentColor`, so icons follow the existing button tokens; no new colour token.
- **Owner's answers:** trash can for delete (no X, which would clash with Cancel); eye for view/review/open; `<>` icon with the visible text "CSV" and the tooltip "Download CSV"; icon only for add, edit, delete, view, log out; icon plus text for everything ambiguous or rare; "Do now" candidates implemented, "Maybe" list left for the owner.
- **Accessibility:** an icon-only control has `aria-label` and an identical `title`, both translated with existing msgids (German wording unchanged). Where text remains, the SVG is decorative. Cancel stays text. Save buttons keep their text with a check mark.
- **Behaviour:** every control keeps its element type, URL, method and CSRF token. A delete link still only opens its confirmation page; state-changing controls remain POST form buttons.
- Row actions are grouped in one cell in the order view, edit, delete.

## Tests
`core/test_icons.py`: every icon used exists (and every icon is used), no inline `style=`, no colour or external reference in an icon, every icon-only control has a non-empty name equal to its tooltip in English and German, every icon button sits in a POST form, the licence notice is present.

## Consequences
New icons need an entry in `core/icons.py` and, if copied from Lucide, a notice only if its source licence differs. Text assertions in two older tests were moved to the accessible name.
