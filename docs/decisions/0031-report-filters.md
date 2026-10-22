# ADR 0031: Organisation and category filters on reports

Status: accepted (Phase 30, 2026-10-22). Read-only reporting change: no model, migration, import or payment logic changed; nothing is stored.

## Decision
- **Semantics:** two groups of check boxes, any number ticked. OR within a group, AND between the groups, an empty group is no restriction. Ticking everything equals ticking nothing.
- **By id, never by name:** `organisation=<pk>` and `category=<pk>` (repeated), sorted, duplicates collapse. Names are unique case-insensitively but look-alikes may exist, so names are only used to describe the filter. Bad ids (non-numeric, negative, unknown, wrongly cased parameter names) are an error message and redirect in the style of the unknown-year message, never a 500 and never a silently different report; at most 10 characters of the input are echoed.
- **One place:** `ReportFilter.apply` is called where a payment set is chosen (`reports._payments`, `reconciliation.build_report`, `tax.tax_summary_rows`), so every figure, count, exclusion line and share of a report comes from the same filtered set. Nothing is computed unfiltered and adjusted.
- **Which reports:** all except the SBK contribution estimate and the tax checks (`ReportSpec.supports_filter = False`). Those are whole-person assessments computed from all income and annual inputs; an estimate over part of the income would look right and be wrong. They show a note, ignore a filter in the URL with a message, and say `Filter: Not applied to this report` in the basis block and the CSV. The reconciliation report and the tax information summary only needed the payment set passed in; no rule or reconciliation logic changed.
- **Stated in the basis:** a `Filter` row after `Period` (ticked names as stored plus the AND/OR rule), only when a filter is active, also in the CSV and in print.
- **CSV:** file name gets `-filtered` when a filter is active; **format version stays 2**, because an unfiltered file is byte-for-byte unchanged (proved against a capture of all reports before the change) and a filtered file only adds one labelled row. Column headings are now also protected against formula injection (a no-op for fixed headings; needed for the category columns of the new report).
- **Options:** every organisation and category with at least one payment in any year, active or not (inactive marked), each with its payment count for the selected period; one query per list.
- **Form:** one plain GET form with `<details>` (open when a filter is active) and a scrolling group; works without JavaScript. The reports index applies year and boxes to the View/CSV links by a small script; without it the links open unfiltered. Language switch already posts the full path, so the query string survives.
- **New report** `cross` (organisation by category), requested by the owner: signed gross EUR per pairing (blank = no payment), row and column totals; it honours the filter.
- No schema change, no new dependency, no new icon, nothing under `infra/`.

## Consequences
Counts beside the check boxes use the period only, not the other group's ticks, and are not refreshed when the year select changes on the index page (they are on the report page, which reloads). The German wording of the new report title comes from `docs/glossary.md`.
