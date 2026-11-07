# ADR 0043: "Gross to net" table on the Tax information summary, CSV format version 3

Status: accepted (branch `fix/tax-summary-net-expenses`, 2026-11-07). Amends the "Not done" paragraph of ADR 0036; ADR 0036 is otherwise unchanged. Proposal: `docs/proposals/tax-summary-net-expenses.md`; prompt: `docs/prompts/TAX_SUMMARY_NET_EXPENSES_REVIEW.md`.

## Context
The tax information summary showed gross and withholding tax but neither expenses nor net (ADR 0036 left them out; "rental costs are deferred"). The owner will ask SBK whether only gross or also net income counts, and wants every group stated as gross, withholding tax, expenses and net side by side. Tables 1 to 4 already sit at 7 pt (tables 1 and 2) and 6 pt (table 4) on landscape A4; adding four columns to them breaks headers and dates (measured on a copy of the production data, see the proposal).

## Decision
- **A new table** `gross_to_net`, "Gross to net by category and currency", placed after table 1: payments, gross, withholding tax, expenses, net, unallocated (original currency), then gross, withholding tax, expenses and net in EUR; one row per category and currency, EUR-only total line. 12 columns, so the PDF sets it at 7 pt. Tables 1 to 5 are unchanged.
- **Presentation only.** Every figure is a sum of values stored on the payments (`net_amount`, `withholding_tax`, `expenses`, their EUR counterparts at the payment's stored rate); nothing is calculated, re-derived or interpreted. `gross = net + withholding tax + expenses` is stated in the basis block; unallocated is `Payment.unallocated`, shown and flagged when it is not zero, never corrected.
- **Blank, not zero**, when a group has no payment with a net amount (net, unallocated, net EUR); such payments are counted in a note under the table. Unconverted payments add nothing to the EUR columns (as in the other tables).
- **No claim about expenses.** They are shown as recorded, in the original currency and in EUR at the stored rate; the basis row says they are not a deduction and that no one has accepted them as one. No tax-office or SBK vocabulary is used.
- **Wording:** the basis row "Gross/net" and the PDF notice now say gross, withholding tax, expenses and net. German terms follow `docs/glossary.md` (Ausgaben, Nicht zugeordnet); the new German strings are proposed and need the owner's review.
- **CSV:** the table is added to the tax summary's CSV; `CSV_FORMAT_VERSION` is bumped from 2 to 3 (one global constant, so every report's CSV now says 3; their layouts are unchanged).
- **Page layout:** each report table scrolls inside its own region (`.table-scroll`, keyboard focusable, first column sticky) instead of widening the page; the page previously scrolled sideways at 1280 and 1440 px.
- **PDF:** a table title is preceded by a conditional page break so that it no longer ends a page on its own.

## Not done
The expenses columns are not hidden when empty (the proposal's option d): a fixed layout keeps the CSV stable and shows an explicit 0.00. Tables 2 and 4 get no net or expenses columns (14 columns at 6 pt cannot take more without wrapping dates). The SBK estimate, tax checks, category mappings, `policies/` and the letter reconciliation are not touched.

## Consequences
Every CSV file carries format version 3. The tax summary's CSV has one more table. Reports other than the tax summary are byte-identical in HTML, CSV and PDF text to `main`, apart from the version row and the scroll wrapper in the HTML of multi-table reports (only the tax summary has one).
