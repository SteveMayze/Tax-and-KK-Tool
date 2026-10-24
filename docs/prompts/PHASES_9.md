# PHASES_9.md: Tax and Healthcare Tool, Phases 31 and 32 (payments page for reconciliation; broker naming, categories and Fidelity analysis)

Save this file as `docs/prompts/PHASES_9.md`.
**Do not edit or overwrite `PHASES.md` to `PHASES_8.md`.** If you find an error in them, record it in your end-of-phase report. Phases 1 to 30 are implemented (Phase 20 deliberately not) and the app is in production.

## Why these phases

The owner is reconciling the app's payments against the US tax documents and the broker statements (E*TRADE and Fidelity) and has found three obstacles:

1. **Navigation.** Reconciling needs "all payments of one year or one month, filtered by organisation and category". Today that means home, then a year page, then a month page. Phase 30 gave the reports organisation and category filters, but the reports have no editable payment rows and no month selector.
2. **Names and categories of broker income.** To tell the two brokers apart, and to separate interest-like income from dividends, the owner edited stored payments by hand (see Phase 32). Imports must produce the same names and categories from now on, otherwise a re-import will not be recognised as a duplicate (the duplicate key in `imports.py` uses the lower-cased organisation name) and the owner's manual work is lost on the next upload.
3. **Fidelity.** An upload of the Fidelity reports ends with notices and warnings that the owner wants understood before trusting the totals.

Two independent phases. **Phase 31 first** (it helps with checking Phase 32), each ending with a report and a stop.

## Standing rules

1. Read first: `CLAUDE.md` (all of it applies: Decimal only, state the basis of every figure, no inline `style=`, CSS tokens only, `.btn` classes, translated strings, synthetic test data only, no new dependency, no JS framework), `docs/reporting.md`, `docs/imports.md`, `docs/glossary.md`, `docs/rules/README.md` (items 12, 15 and 16 in particular), ADR 0012, 0013, 0018, 0019, 0030 and 0031, and the code named in each phase.
2. One phase only, in the order named. At the end give the end-of-phase report (what was done, key decisions, files changed, checks with real results, deviations, open issues, how to verify by hand, proposed next scope) and **stop and wait for "go"**.
3. **Ask first.** Put the questions of the phase in your first reply together with what you found when you verified the current state. If unanswered, use the stated default, say so at the top of your work, and continue.
4. **Verify the current state.** This file was written from a read of the code, not from running it. Where it says "verify", read the code, say what you found and adapt if it differs.
5. **Do not overwrite or discard existing work.** Do not touch the owner's database, the git-ignored `local/` folders (except reading `local/samples/` as Phase 32 allows) or any stored payment. Never invent financial data, rates, dates or classifications; where a classification is the owner's or the tax adviser's decision, ask.
6. **Privacy.** Names of real securities, funds, organisations and categories come only from the database or the owner's files at runtime. Nothing taken from the owner's data appears in tracked files, test names, fixtures, docs, ADRs or commit messages: use invented names ("EXAMPLE MONEY MARKET FUND", "EXAMPLE STOCK CO"). Detailed findings from the owner's sample files go into your reply in the conversation only. Review staged files before every commit.
7. **Unchanged behaviour stays unchanged.** Every page, report and CSV that a phase does not name is identical afterwards, and existing tests stay green and unchanged. Where a test must change, list it and say why.
8. **Acceptance criteria** are checkable statements, each needing a test or a demonstrated command. Report each as met, not met, or not verifiable here, with evidence. Every corner-case id gets a test named after it.
9. **Deployment is untouched** (nothing under `infra/`, the Containerfile or the Makefile). No `make deploy`. No schema change unless a phase says so and I have agreed.
10. Update the documentation `CLAUDE.md` asks for, and add an ADR with the next free number (verify the sequence: 0031 exists, 0020 was never used). Never delete an old ADR; a superseded decision is marked in the new ADR and in a one-line note at the top of the old one.
11. Language (Phase 12): all new text through `{% trans %}` / `gettext`, English and German, `makemessages` and `msgfmt`, commit both. German terms come from `docs/glossary.md`. CSV stays English.

---

## Phase 31: Payments page filtered by year, month, organisation and category (spike on a branch)

### Goal

A single page that lists payments with the editable rows of the month page, limited by **year** (default: the current year), **month** (default: all months) and the Phase 30 **organisation** and **category** check-box groups. It replaces the home, year, month sequence for reconciling. It is built as a **spike**: a new page added next to the existing ones, on its own branch, so the owner can try it before deciding whether it becomes the landing page. Nothing existing is removed or changed in behaviour.

The owner also asked whether to convert the whole application to "all payments filtered by year". **Not in this phase**: that is hard to reverse in a production app. The spike gives the evidence; the decision comes afterwards (see the end of this phase).

### Questions for the owner (defaults in brackets)

- **Q31.1 Branch.** [Default: `git switch -c spike/payments-page` from `main`; commits on that branch only; no merge, no push unless I say so, no deployment.]
- **Q31.2 Address and navigation.** [Default: `payments/` (verify it does not clash with `payments/<int:pk>/`), named `payment_list`, a link in the page header next to Reports, and a link from the home page. The home page itself is not changed otherwise.]
- **Q31.3 Year choice.** [Default: the year selector lists every reporting year plus "All years"; the page opens on the current calendar year (Europe/Berlin) when the parameter is absent. If the current year has no reporting year, the page shows an empty list with the message, not an error.]
- **Q31.4 Columns.** [Default: date, organisation, category, original amount and currency, gross EUR, net EUR, **withholding tax (original currency)**, frequency, comment, and the edit and view controls of `_payment_rows.html`. Withholding is added because the tax documents are compared with it. Say if `_payment_rows.html` cannot take the extra column without changing the month page; then use a copy of the row partial for this page and say so.]
- **Q31.5 Totals.** [Default: below the filters and above the table, a basis block (Principle 4) and a totals table: payment count; gross, net and withholding in **each original currency** (so a USD statement can be compared with a USD tax form without conversion), and gross and net EUR at each payment's stored rate with the count of unconverted payments left out. Use the existing aggregation services; no totals in templates.]
- **Q31.6 Sort order.** [Default: payment date ascending, then organisation, then id. No clickable column sorting in this phase.]
- **Q31.7 Where edit and delete return to.** [Default: back to this page with the same query string, wherever the existing edit/delete flow allows a safe `next` target (verify how the month page returns; accept only a relative path of this app, never an arbitrary URL). If that needs a change to the shared payment views, make the smallest change, test the old behaviour is unchanged, and report it.]
- **Q31.8 Pagination.** [Default: none. A year holds a few hundred rows at most. Report the largest page you measure with a synthetic dataset.]

### Corner cases (every id needs a test)

- **P1 Default year.** No parameters: current calendar year, all months, no filter.
- **P2 Year and month.** Month 1 to 12 of a year lists exactly the payments whose reporting month is that month; "all months" lists the year. "All years" ignores the month and the page says so in the basis block (a month without a year is meaningless).
- **P3 Bad parameters.** Non-numeric, unknown, negative, very long or repeated year, month, organisation and category parameters: an error message in the same style and place as the existing "Unknown year" message of the reports, never a 500, never a silently different list; the message echoes at most 10 characters of the input.
- **P4 Filter semantics are Phase 30's.** The page uses `ReportFilter` (`core/services/report_filter.py`) and the same partials (`_report_filter.html`, `_filter_group.html`) unchanged or extended without changing the reports; OR within a group, AND between groups, an empty group no restriction, by id. The filter is applied once, in the queryset builder of the service; the template filters nothing.
- **P5 Query string survives.** The year form, the month selector, `Show`, `Clear filters`, the links to a payment, the edit return (Q31.7) and the header language switch keep year, month and the ticked boxes (verify what the language switch does with a query string; Phase 30 checked it for the reports).
- **P6 Counts on the options.** Each organisation and category option shows its payment count **for the selected year and month**, computed in one query per list (no per-option queries).
- **P7 No match.** A filter that matches nothing gives an empty table with the message "No payments match this filter", the filter in the basis block, and totals of 0.
- **P8 Totals equal the rows.** The totals are computed over exactly the listed payments. Property test: with the month page's own totals as the oracle, the page for one year and month with no filter equals the month page's actual totals; and the totals of a filter plus its complement equal the unfiltered totals.
- **P9 Unconverted and negative payments.** Pending-conversion payments are listed, marked, and excluded from the EUR totals with the count stated; a negative payment (category flagged `may_be_negative`) and a correction/reversal are listed and totalled as the month page does.
- **P10 Mixed currencies.** Original-currency totals are never added across currencies.
- **P11 Method and login.** GET only, login required, no state change; the edit and delete controls keep their own methods and confirmations (CLAUDE.md UI rules; icon-only controls carry a translated `aria-label`).
- **P12 Print.** The filter form is hidden in print; the basis block and totals print.
- **P13 Existing pages unchanged.** Home, year, month, report and reconciliation pages render as before (the new header link is the only difference; say so).

### Tasks

1. **Verify** and report in one paragraph: how `month_detail` builds its rows and totals, what `_payment_rows.html` needs, how the reports parse and display the year error and the filter (`views_reports._year`, `report_filter.parse`), how the payment edit and delete views choose where to return, whether `payments/` is free, and what the header and home page contain.
2. **Branch** per Q31.1.
3. **Service.** A function in `core/services/` (new module `payment_list.py` or an existing one, verify what fits) that takes year (or all), month (or all) and a `ReportFilter` and returns the ordered queryset, the totals (Q31.5) and the option lists with counts (P6). No raw SQL, no name matching.
4. **View and template.** `payment_list` in a views module (verify which), one GET form (year, month, the two check-box groups, `Show`, `Clear filters`), the `<details>` behaviour of Phase 30, basis block above the table, notes below. CSS tokens only, no inline `style=`, visible text on `Show` and `Clear filters`, existing icons only.
5. **Tests** (`core/test_payment_list.py`): every corner-case id by name, with figures worked out by hand in a comment, plus login, GET-only, template (fieldset and legend, a label for every box, no inline `style=`), i18n (English and German) and query-string tests. Synthetic data only.
6. **Docs and ADR.** `docs/reporting.md` or a new short section in the document you judge right (say which): the page, its parameters and its basis; `CLAUDE.md` UI section, one line; ADR `0032-payments-page-spike.md` with status "proposed (spike, not merged)", recording why a new page and not a conversion of the app, and what would decide adoption.
7. **Checks.** Full test suite, `python manage.py check`, `makemigrations --check` (must report no changes), `tools/check_contrast.py` if a token changed, `makemessages` plus `msgfmt`. Check by hand in the browser (or say you could not): the default page, one month, one organisation, two categories, both groups, a bad month in the URL, editing a payment and returning.

### Acceptance criteria

- `payments/` opens on the current year, all months, no filter, and every corner case P1 to P13 has a passing test.
- The totals equal the sum of the listed rows and equal the month page's totals for the same month (P8).
- The ticked boxes, year and month survive `Show`, the selectors, the links and the language switch (or the limitation is reported).
- The form works with JavaScript disabled.
- All earlier tests pass unchanged; no schema change; no file under `infra/`, the Containerfile or the Makefile touched; no new dependency; no real name in any tracked file.
- Work is on `spike/payments-page` only; `main` is untouched.

### Stop and report

End-of-phase report as in the standing rules, plus a short **adoption note** for the owner's decision: what making this page the landing page (or retiring the year and month pages) would change, which tests and docs it would touch, and your recommendation. Do not do any of it.

---

## Phase 32: Broker income naming and categories, and the Fidelity analysis

Work on `main` (or a branch from `main`; ask if unsure), **not** on the Phase 31 branch.

### What the owner did by hand (the state to reproduce)

All four changes are in the stored data already:

| Broker | What the importer produced | What the owner has now |
|---|---|---|
| E*TRADE, money-market fund income | organisation = the printed fund name; category Dividends | organisation = `E*Trade ` + the fund name; category **Interest** |
| E*TRADE, company-stock dividends | organisation = the printed company name; category Dividends | organisation = `E*Trade ` + the company name; category Dividends (unchanged) |
| Fidelity, money-market fund income | organisation = the printed fund name, which begins with the abbreviation `FID `; category Dividends | organisation = the same name with the leading `FID ` **replaced by** `Fidelity `; category **Interest** (to be confirmed, see Q32.2) |
| Fidelity, company-stock dividends | organisation = the printed company name; category Dividends | organisation = `Fidelity ` + the company name; category Dividends (unchanged) |

**Seen on the owner's development import (24 October 2026, import #17 at `localhost:8000/imports/17/`: 16 Fidelity PDFs, 29 rows, 0 invalid, 0 duplicates, all with a rate).** Facts to build on, to be verified by you:

- Fidelity has **two core money-market funds**. The first (January to February 2025) has a printed name that **already begins with "Fidelity"**, no `FID ` abbreviation, and **carries US withholding** (two small amounts). The second (from the end of February 2025 to September 2026) has a printed name beginning `FID ` and **no withholding at all**. Both have a row on the same date at the end of February 2025: the fund change falls in one statement, and that statement is one of the two where "income summary not found" appears. So the naming rule must **not** blindly put `Fidelity ` in front: `Fidelity Fidelity ...` would be wrong.
- There is one company-stock dividend series (quarterly, with withholding); the owner has prefixed it with `Fidelity `.
- Of the 29 rows, 22 are core-fund rows and 7 are company-stock rows. From late 2025 the fund income drops from roughly 700 to roughly 20 USD a month, in the months after the September sale and the journal lines. Treat that as a lead for Part A, not as a finding.
- The notices on that import are exactly the five "Not imported" lines (one purchase, one sale and one journal on two consecutive days in September 2025, one journal in November 2025, one in June 2026), "income summary not found" for two statements, and "Tax postings for events not in this upload: 4".
- **Findings from a first read of the statements by the person drafting this prompt (confirm each, do not take them as given; amounts are deliberately left out of this tracked file):**
  - *Income summary.* The "Income Summary" box exists in all 16 statements. The two statements where the reader says it is missing are the two (February and March 2025) in which the heading shares a printed line with "Credit Balance", so the "Dividends" line of the box is interleaved with other text. It is a **reader gap, not a missing box**, and the box agrees with the income lines in both. The check is therefore silently weaker than ADR 0019 promises for those two statements.
  - *The four unmatched tax postings* are the four lines in the January 2025 statement dated in November and December 2024 and marked as prior-year activity. They revise the withholding of two 2024 fund dividends: the original posting is reversed and a much smaller amount is booked again. The difference was credited to the core fund in January 2025 as two purchases of the fund. Those two 2024 events are not in the upload, so "not staged" is correct for the rows, but the January 2025 cash refund relates to 2024 tax.
  - *The same pattern in 2025:* the first fund's dividend is first charged a flat 15 % withholding, then reversed and re-booked at a small residual in the next statement; the app's net amounts show the residual. The statements do not print why.
  - *The fund switch is printed:* a line in the February 2025 statement says the core position was switched from the first fund to the second on a day in that month, and the core-fund table shows the transfer. That is why two names appear; the first fund pays for the days before the switch and the second for the rest of the month. After the switch there is no withholding on the second fund's income.
  - *Fidelity's own wording:* every income line is "Dividend Received", and the statement's Income Summary calls all of it "Taxable Dividends". Nothing in the Fidelity statements calls fund income interest. The Interest category is the owner's recording choice, not the broker's classification.
  - *Tax documents in the sample folders:* an E*TRADE Form 1042-S for tax year 2025 (`local/samples/ETrade-Tax`), with a single income-code line (code 06) and a single withholding figure; and for Fidelity (`local/samples/Fidelity-Tax`) a Form 1042-S for tax year 2025 (copies B, C and D of **two forms**), a "year-end investment report", a "custom transaction summary" from the Fidelity web site and two trade confirmations. Read all of them (structure and the figures needed for the comparison; nothing from them goes into a tracked file).
  - *Lead on the Fidelity form, from a first arithmetic check by the person drafting this prompt (confirm it, do not take it as given):* the two 1042-S forms are one with income code 01, a 0 % rate and chapter 3 exemption code 04, no withholding, and one with income code 06, a 15 % rate and withholding. Their gross incomes add up, to within whole-dollar rounding, to the 2025 income of the **first fund plus the company stock only**; the income code 01 form equals the first fund's income minus a small residual, and that residual plus the company-stock dividends equals the code 06 form, whose withholding equals, within rounding, the withholding the app holds for those events. The **second fund's income (the larger part of the year) does not appear on the 1042-S at all**. The Fidelity web summary and the year-end report both total all 2025 income, including the second fund. If the arithmetic holds, the form splits the first fund's payments into an interest-coded part and a dividend-coded part, which the statements print as one dividend per month, and does not report the second fund.
- The development database holds the **old** names and the Dividends category: the owner's manual edits were made elsewhere. You may read import #17 and the development database **read only**; never write to either, never run a commit, a refresh of rates or a delete on them.

Rationale given by the owner: the same security can appear at both brokers, so the broker must be part of the organisation; and money-market fund income is interest-like. This reverses the recording choice in `docs/rules/README.md` items 12 and 15 and ADR 0018 and 0019 ("fund income is category Dividends"). It is a **recording choice only**: whether German tax and SBK treat the income as interest, dividends or fund income stays open and unverified (README items 9, 11, 12, 15). Implement no tax rule and decide no classification.

Why it matters technically: `imports.py` flags a duplicate by (payment date, organisation name lower-cased, currency, gross). An importer that still emits the old names would **not** recognise the owner's renamed payments as already imported, and a re-upload would double the income.

### Part A: analyse (read only, report before changing anything)

Read the code and the owner's samples (`local/samples/Fidelity`, `local/samples/ETrade`, `local/samples/ETrade-Tax`, read only; the owner agrees to this) and report in the conversation. Nothing from the samples goes into a tracked file.

1. **What the Fidelity upload said**, the owner's staging screen showed:
   - a warning "Tax postings for events not in this upload: 4 (not staged)";
   - the notice "The income summary was not found; that check was skipped" for two statements, one of them for February 2025;
   - "Not imported" notices: shares bought (a delivery or purchase) on one date in September, shares sold on the next day, other activity (a journal) on that day, one journal in November, one journal in June 2026.

   For each, explain from the reader (`fidelity_stock_plan.py`, ADR 0019) and the statements what it is, whether it affects any income or withholding figure the app holds, and whether the app's behaviour is right. In particular:
   - **The four unmatched tax postings:** which statement and which event period they belong to (the previous year's December dividends booked in January is the expected case). Say whether the withholding of those events is missing from the app, which tax year the owner's tax document counts them in (event date or posting date; if that is not knowable from the files, say so and ask), and what the owner would need to upload to settle them.
   - **The income summary not found:** read the two statements. Is the summary absent because the statement has no income (a legitimate skip), or because of a layout variant that the reader misses (then the check is silently weaker than ADR 0019 promises)? Say which, with evidence.
   - **Bought, sold and journal lines:** what each line is (delivery of shares, sale, transfer), whether any cash amount or tax in them could explain a difference between the app and the tax documents. README item 16 records the owner's decision that sales and deliveries stay out of the tool because they were taxed while employed; confirm the notices are consistent with that, and say plainly if any of them looks like something else (for example a dividend reinvestment or a fee).
2. **"Interest paid as Dividend" at Fidelity.** Find every income line of every sample statement and list, per statement, the description, whether the security is the core money-market fund (`is_fund` in the reader) or stock, and the count and USD total by group. Say whether any income line is described other than "Dividend Received" (the reader refuses those) and handle both core funds (see the facts above). Explain why the first fund had withholding and the second none, **from what the statements print** (a withholding line, a note, a classification), without a tax opinion; if the statements do not say, say so. Check the arithmetic the owner will rely on: for each row, gross minus withholding equals net. Look for the lead about the fall in fund income from late 2025 (balance moved by the sale and the journals?) and report what the statements show, nothing more.
3. **The tax documents.** Inspect `local/samples/ETrade-Tax` and `local/samples/Fidelity-Tax`. Say which document types are there, which boxes or income codes they report per income type (look the codes up in the IRS Form 1042-S instructions and quote the source), and whether the app's categories can be mapped to them. Do the reconciliation of Q32.10. **Do not decide the classification.** Present the mapping options and what each would need to be verified.
4. **A reconciliation view of the app's own data**, read only: a management command or a function in `tools/` (verify which convention exists; see `tools/pdf_inventory.py`) that, for a year and a broker (organisation name prefix), prints per organisation and category: count, gross, withholding and net in USD from the stored payments. It writes nothing, prints no file contents, and is not run against the owner's database by you; give the command for the owner to run. If Phase 31's page already shows the same figures, say so and skip this item.

Put the findings, the questions below with your proposed default, and a list of what Part B will change in **one message**, then continue with Part B using the defaults unless the owner objects.

### Questions for the owner (defaults in brackets)

- **Q32.1 Naming rule.** [Default: E*TRADE rows: organisation = `E*Trade ` + the tidied printed name. Fidelity rows: if the tidied printed name begins with the token `FID ` it is replaced by `Fidelity `; if it already begins with `Fidelity ` it is left as it is; otherwise `Fidelity ` is put in front. Single spaces only. Ask the owner what the stored name of the first core fund (which already begins with "Fidelity") is; if the owner left it unchanged, the rule above reproduces it. Verify the owner's stored Fidelity fund name does not contain a double space (the owner's message shows `Fidelity  Treasury ...` with two): the duplicate key compares lower-cased names without collapsing spaces, so a double space would defeat duplicate detection. If `organisations.py` normalises spaces, say so; if not, report the stored form for the owner to correct and make the importer emit single spaces.]
- **Q32.2 Category rule.** [Default: income of the **core money-market fund** (E*TRADE `kind == 'Dividend'`; Fidelity `is_fund`) is category **Interest**; company-stock dividends (E*TRADE "Qualified Dividend", Fidelity non-fund) stay **Dividends**. Frequency and comments are unchanged. The category `Interest` exists in the seed (`0002_seed_income_categories.py`); no new category, no migration.]
- **Q32.3 Does the rule apply to the other readers?** [Default: no. Revolut, HSBC, RVB, MECU and Ord Minnett already record Interest or have their own rules (README items 11 to 19); only the two broker readers change.]
- **Q32.4 Old decisions.** [Default: ADR 0033 `0033-broker-fund-income-as-interest-and-broker-prefix.md` (verify the number; 0032 is used by Phase 31 on its spike branch, so 0033 avoids a clash when that branch is merged) supersedes the "fund income is Dividends" decision of ADR 0018 and 0019 and README items 12 and 15; a one-line "superseded in part by ADR 00xx" note goes at the top of ADR 0018 and 0019; the README items are edited in place with the date and the owner's decision, status still unverified.]
- **Q32.5 The owner's expected-results file.** [Default: `local/samples/expected/fidelity.csv` (and the E*TRADE equivalent, if present) belongs to the owner, is git-ignored and holds the old names. Do not change it. Write the updated expectation next to it with the suffix `.proposed`, say so, and let the owner replace the original. Tests that read it (verify `test_sample_regression.py`) must say clearly what to do when the file differs only by names and categories.]
- **Q32.6 Fidelity sales and deliveries.** [Default: still not imported (README item 16). If Part A shows that a notice hides income or a tax amount, stop and ask; do not widen the reader.]
- **Q32.7 Unmatched tax postings.** [Default: unchanged behaviour (a counted warning, staged as nothing). If Part A shows that they belong to the target tax year, propose the smallest change and ask before making it.]
- **Q32.8 Existing payments.** [Default: the code does not touch stored payments. The owner has already edited them. Offer, but do not build, a read-only check listing stored payments that came from a broker import batch whose organisation lacks the broker prefix or whose fund income is not Interest.]

- **Q32.9 Prior-year withholding refunds.** [Default: not recorded (no row, no change). Report, from the statements, which prior-year events were revised in the upload period and the cash effect in the period, so the owner can decide with the tax adviser which tax year a refund belongs to. Do not guess; do not create negative payments.]
- **Q32.10 Documents to reconcile against.** [Default: Part A compares both 1042-S sets (E*TRADE and Fidelity) with the app's stored data of the dev import, per form: income code, gross, rate, withholding, against the statement lines that make it up (by payment, with the arithmetic shown in the conversation). Report a per-form table "form figure / sum of statement lines / difference / what explains it", and mark every difference you cannot explain from the documents as open. Do not edit any stored payment.]
- **Q32.11 Should the first fund's payments be split?** [Default: no. The importer keeps one payment per printed dividend, as today. If the arithmetic in Part A shows that the form reports each month's payment in two parts, describe the split and what splitting would need (a source for the split, which the statements do not print), and ask. Do not implement a split.]
- **Q32.12 The September stock sale.** [Default: out of scope (README item 16). Part A reports, from the web summary and the trade confirmations, what the "bought", "sold" and journal notices are (date, quantity, proceeds, gain or loss) so the owner and the tax adviser can decide whether the loss belongs in the German return; the existing capital-loss support (Phase 11) is not used or changed.]

### Corner cases (every id needs a test)

- **B1 E*TRADE fund row.** Organisation `E*Trade EXAMPLE MONEY MARKET FUND`, category Interest; amounts, frequency, comment and withholding as before.
- **B2 E*TRADE stock row.** Organisation `E*Trade EXAMPLE STOCK CO`, category Dividends.
- **B3 Fidelity fund row with the `FID ` abbreviation.** The abbreviation is replaced, not kept (`Fidelity EXAMPLE ...`, never `Fidelity FID EXAMPLE ...`); category Interest.
- **B4 Fidelity fund row without the abbreviation,** and a name that merely contains `FID` inside a word: prefix only, nothing replaced.
- **B4a Name already starting with the broker.** A Fidelity fund whose printed name already begins with `Fidelity ` stays unchanged (no `Fidelity Fidelity`), category Interest, withholding as printed. The same check for an E*TRADE name that already begins with `E*Trade ` or `E*TRADE `, compared case-insensitively, output with the owner's spelling `E*Trade `.
- **B5 Fidelity stock row.** `Fidelity EXAMPLE STOCK CO`, Dividends.
- **B6 Same security at both brokers** produces two different organisations.
- **B7 Duplicate detection with the new names.** A payment stored under the new name and a re-upload of the same statement: the row is flagged duplicate; a row from the other broker with the same date and amount is not.
- **B8 Fund changed during the period.** Two different core funds in the same upload, one with withholding and one without, and both with a row on the same date: both Interest, each with its own name, two separate rows, no merging, no duplicate flag between them.
- **B9 Settlement across the upload still works.** Withholding matching in `settle` uses the normalised security name, not the final organisation string (verify; the prefix must not break matching of tax postings to events), and a warning text is unchanged.
- **B10 Tidying.** `tidy_security_name` is unchanged for every other reader; the prefix is applied in the two broker readers only.
- **B11 Reports.** A payment-level and a by-category report over a synthetic E*TRADE and Fidelity dataset show the fund income under Interest and the stock dividends under Dividends; the tax information summary and the SBK estimate use the new category through the existing configuration without a code change (verify, and report any figure that moves).
- **B12 Notices unchanged.** The "Not imported", "income summary not found" and "Tax postings for events not in this upload" texts and counts are unchanged.
- **B14 Interleaved income summary.** A synthetic statement whose "Income Summary" heading and "Dividends" line are interleaved with other text is read correctly and the check against the income lines runs (agree: passes; disagree: refuses as today); a statement without any summary still gives the existing notice.
- **B13 Fixtures.** Existing tests that assert the old names or the Dividends category (`test_etrade_client.py`, `test_fidelity_stock_plan.py`, `test_sample_regression.py`, `test_pdf_imports.py`, others you find) are changed minimally, listed in the report, and each change is only a name or category.

### Tasks

1. Part A as above, reported in one message.
1a. **Income-summary reader gap** (if Part A confirms the finding above): make the smallest change in `fidelity_stock_plan.py` so that the summary figure is found when the heading shares a line with other text, using the existing line-reading helpers; refuse nothing new; add a synthetic-layout test that reproduces the interleaved lines (corner case **B14**). With the change, the "income summary not found" notice must disappear for those two statements and the check must pass; for a statement that really has no summary it must still say so. Report the effect on the notice count.
2. Implement the naming and category rule in `etrade_client.py` and `fidelity_stock_plan.py` through one small shared helper (for example in `core/services/organisations.py`, next to `tidy_security_name`), not by two copies of the logic. Constants for the prefixes in one place.
3. Tests for B1 to B13, synthetic text PDFs or the existing synthetic helpers only.
4. Documentation per Q32.4: `docs/imports.md`, `docs/rules/README.md` items 12 and 15, `CLAUDE.md` Imports line (E*TRADE and Fidelity), the two old ADRs' notes, and the new ADR.
5. Checks: full test suite, `python manage.py check`, `makemigrations --check` (no changes), `makemessages` plus `msgfmt` if any string changed. Run the readers on the owner's samples **in memory** (no database write; use the existing tools) and report: counts of rows by organisation prefix and category, no names or amounts in tracked files, and that the notice texts are the same as before.

### Acceptance criteria

- Part A answers every sub-point with evidence, or says what is not knowable from the files and asks.
- Fund income from both brokers is staged as Interest with the broker prefix; stock dividends stay Dividends with the broker prefix; B1 to B13 pass.
- Re-staging a statement whose payments the owner already renamed and recategorised is flagged duplicate (B7), shown by a test, and by the in-memory run on the samples if the data allows it (say how).
- No stored payment, no `local/` file and no database is modified; the `.proposed` file is the only file written outside tracked paths.
- No schema change, no new dependency, nothing under `infra/` touched, no real security or fund name in any tracked file.

### Stop and report

End-of-phase report as in the standing rules, plus: the list of tests changed under B13 with the reason, the effect (if any) on the tax information summary and the SBK estimate, the Part A findings that still need the owner or the tax adviser, and one proposed next step. Then wait for "go".
