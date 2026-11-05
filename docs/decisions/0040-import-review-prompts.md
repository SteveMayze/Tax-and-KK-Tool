# ADR 0040: Review-page prompts: missing ASX code, and the country of a new organisation

Status: accepted (fix branch `fix/au-dividend-statements`, 2026-11-05). Owner's decisions: prompt only for the code, owner-confirmed country proposals, control for new organisations only. German wording is proposed, awaiting the owner's review.

## Decision
- **Missing ASX code:** only when date, gross, net and withholding read and reconcile, the statement stages one row with an empty organisation (invalid, so it cannot be committed) and a `_structural` explanation. The explanation adds the company name taken from the anchored phrase "your holding in <name>" and, when exactly one existing organisation starts with it, that organisation, shown and never applied. No name-to-code table (no names in code); it can be added later as admin data if the situation keeps recurring. No "use for all rows" action (it would need a separate re-validating POST; skipped).
- **Country:** a per-reader constant (`Reader.country`, stored per row as `ImportRow.reader_country`, outside the CSV format) then `CURRENCY_COUNTRY` for non-EUR currencies, else blank; EUR is never inferred. The preview shows one control per new organisation; the choice is stored in `ImportBatch.organisation_countries` and used at commit (`lookups.resolve_organisation(name, country)`); an untouched control commits the proposal that was shown. Codes are validated against a fixed ISO 3166-1 alpha-2 list (`core/countries.py`). Existing organisations keep their country; those with a blank country are filled only through an opt-in tick (default off). The Organisations page proposes countries where every payment has the same non-EUR currency, applied only after a confirming POST using the server's own proposal.
- **Reports:** unchanged code. The existing `effective_country` already prefers the stored country, so the "taken from the payment currency" flag disappears for that organisation; a test shows no amount changes.

## Consequences
One reversible migration (0014: `ImportBatch.organisation_countries`, `ImportRow.reader_country`). Currency remains a hint, not proof of the country.
