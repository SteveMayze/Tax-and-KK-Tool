# ADR 0032: Payments page filtered by year, month, organisation and category (spike)

Status: proposed (spike, not merged). Phase 31, branch `spike/payments-page`. Read-only page plus one small, safe change to where edit and delete return to; no model, migration, import or calculation changed.

## Context
Reconciling payments against tax documents and broker statements needs "all payments of a year or month, filtered by organisation and category". Today that is home, year page, month page; the reports (Phase 30) have the filter but no editable rows and no month selector. The owner also asked whether the whole application should become "all payments filtered by year".

## Decision
- **A new page, not a conversion.** `payments/` (`payment_list`) is added next to the existing pages; nothing is removed or changed in behaviour. Converting the app (landing page, retiring the year and month pages and their tests and docs) is hard to reverse in a production app; the spike gives the evidence first.
- **Parameters:** `year` (absent = current calendar year in Europe/Berlin; `all` or empty = every year), `month` (1 to 12, `all` or empty; ignored with all years, and the basis block says so), repeated `organisation=<id>` and `category=<id>` as in ADR 0031. Bad values are an error message and a redirect to the bare page in the style of the reports (at most 10 characters echoed). The current year is accepted even without a reporting year (an empty list with a message), any other unknown year is an error.
- **One filter, one place:** `ReportFilter.apply` in `payment_list.queryset`; the same partials as the reports. `report_filter.options` gained an optional `month` so the counts beside the boxes follow year and month (one query per list).
- **Totals** over exactly the listed payments (`core/services/payment_list.py`, `aggregation.actual_totals`): per original currency (count, gross, net, withholding; never added across currencies) and EUR gross/net at stored rates with the number of unconverted payments left out. Withholding is shown in the original currency because tax documents are compared with it.
- **Rows** are a copy of the month page's row markup (the existing `_payment_rows.html` is the small table of the import preview and cannot take these columns), with the normalised-monthly column replaced by withholding. Sorted by payment date, organisation, id. No pagination (measured with 400 synthetic rows in one month: 7 queries, independent of the row count).
- **Return after edit/delete:** the edit and delete links carry `?next=<this page's full path>`. `payment_edit` and `payment_delete` honour `next` only when its path is exactly `payment_list`'s (relative, no host, no other path); anything else is ignored and the old behaviour applies (detail page after edit, month page after delete). Without `next` nothing changes.
- No schema change, no new dependency, no new icon (the header link reuses the report icon), nothing under `infra/`.

## What would decide adoption
The owner reconciles a full tax year with the page and finds it replaces the year and month pages in practice. See the adoption note in the Phase 31 report for what making it the landing page would touch.

## Consequences
One new URL, one service module, one template, two helper changes (`options(month=)`, `next`). Counts beside the check boxes use the period only, not the other group's ticks (as in ADR 0031).
