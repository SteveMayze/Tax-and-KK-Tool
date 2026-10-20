# PHASES_3.md: Tax and Healthcare Tool, Phases 15 to 20 (PDF statements: HSBC, RVB, E*TRADE, Fidelity)

Save this file as `docs/prompts/PHASES_3.md`. Background, findings and the corner-case catalogue are in `docs/prompts/PDF_PARSERS_PLAN.md`; the corner-case ids used below (G1, H4, R3, E2, F5 and so on) refer to that file.
**Do not edit or overwrite `docs/prompts/PHASES.md` or `PHASES_2.md`.** If you find an error in them, record it in your end-of-phase report.

## Standing rules for every phase below

1. Read first: `CLAUDE.md`, `docs/prompts/PHASES.md`, `docs/prompts/PHASES_2.md`, `docs/prompts/PDF_PARSERS_PLAN.md`, `docs/imports.md`, `docs/decisions/0003` and `0014`, `docs/rules/README.md`, and the existing code: `core/services/pdf_text.py`, `dividend_statements.py`, `interest_statements.py`, `pdf_imports.py`, `imports.py`, and the tests `core/test_pdf_support.py`, `core/test_pdf_imports.py`. Everything in `CLAUDE.md` still applies (Decimal only, keep originals, state the basis of every figure, never guess a legal or SBK rule, no real network in tests, synthetic test data only).
2. Work on **one phase at a time**. At the end: stop, give the end-of-phase report (what was done, commits, tests added with real results, deviations, open questions, anything not verified) and wait for "go".
3. **Ask first.** Ask each phase's "Questions for the owner" in your first reply, together with what you found when you verified the current state. If unanswered, use the stated default, say so at the top of your work, and continue.
4. **Verify the current state.** These phases were written from a read-only review of the sample PDFs and the existing parser code, not from running the code. Where a phase says "verify", read the code and say what you found. If the code differs from what this file assumes, say so and adapt.
5. **Privacy of the samples (highest priority).** `local/samples/` holds the owner's real statements. You may read them to learn structure. Your reports, commit messages, docs, ADRs, test names, test fixtures and log output must contain **no amounts, names, addresses, account numbers, IBANs, sort codes, employer or security names taken from the samples**. Describe structure, label text, counts and line positions only. Hand-checked expected figures for the real samples go only into git-ignored `local/samples/expected/` (create it; the owner checks them). Synthetic fixtures use invented names ("EXAMPLE BANK", "EXAMPLE CORP (EXMP)") and invented figures worked out in the test file. Before every commit, review the staged files for anything copied from a sample.
6. **Refuse rather than guess.** A statement that does not reconcile (running balance, section totals, summary totals), contains a line type not described here, or cannot be read with certainty is refused with a specific reason and stages nothing (G9, G12). Nothing is ever skipped silently. The only "not an error" outcomes are: **staged**, **nothing to import** (recognised, no income), and **recognised and not imported** (a notice, for example a stock sale).
7. **Acceptance criteria** are checkable statements. Each needs a test or a demonstrated command. Report each as met, not met, or not verifiable here, with evidence. Every corner case id listed in a phase gets a test named after it.
8. At least one test per reader exercises the real chain: PDF bytes, `pdf_text`, reader, `pdf_imports` staging, review, commit. Synthetic PDFs are generated in the test suite; nothing from `local/samples` is committed.
9. The 54 dividend and 11 Revolut statements handled by Phase 14 must produce exactly the same rows as before (existing tests stay green and unchanged).
10. After the owner's decisions in a phase, update `CLAUDE.md` (Imports section), `docs/imports.md`, and `docs/rules/README.md` (open questions) in the same phase, and add an ADR `docs/decisions/00NN-...md` where NN is the phase number. Never delete an old ADR.
11. No new dependency. pypdf stays the only PDF library. If a layout cannot be read with pypdf (default or layout mode), stop and ask before adding anything. Never send a document to an external service.
12. Nothing in the app is a tax calculation or an SBK assessment. The importer records what a statement says and where it said it. It never classifies income as taxable, exempt or credited.
13. Deployment is untouched in these phases. No change under `infra/`, the Containerfile or the Makefile except a documented test target if needed.

---

## Phase 15: Foundation (reader registry, multi-row results, layout extraction, inventory)

Goal: change the PDF import so that one statement can yield zero, one or many payments, a reader can be added without editing the others, and the owner can see what a folder of statements contains before importing it. No new institution is read in this phase.

### Questions for the owner
- **Answered by the owner (2026-10-20):** organisation = the payer. For the two banks that is the bank, with fixed names `HSBC UK (Flexible Saver)` and `RVB (Girokonto)` kept in one dictionary in the code. For E*TRADE and Fidelity it is the company whose stock pays the dividend, or the money-market fund, as printed on the income line and tidied the way ADR 0014 tidies issuer names; the custodian ("via E*TRADE", "via Fidelity") goes in the comment. Do not put the actual company or fund names from the samples into code, tests or docs; they are read from the statement at run time. Implement one shared function that tidies a printed security name into the organisation string so both brokers give the identical string for the same stock.
- **Also answered:** RVB payment date = booking date; money-market-fund income = category Dividends.
- Should "nothing to import" files be listed in the upload result? Default: yes, as one summary line with a count ("12 statements recognised, no income"), not one warning per file.

### Tasks
1. **Verify** how `pdf_imports.stage_pdf_batch`, `_read`, `ImportRow.source_name/provenance` and `Dividend`/`FundReturn.row_data` work today, and how many places assume one row per statement. Report what you found.
2. **Reader registry.** Replace the `if interest_statements.recognises(...)` chain with an ordered list of readers, each exposing `recognises(pages) -> bool`, `parse(pages) -> StatementResult` and a flag `needs_layout`. Exactly one reader may claim a file; if two do, refuse the file with a message naming the two reader ids (no document text). Existing Phase 14 readers are registered unchanged.
3. **Result type.** `StatementResult` holds `rows` (list of row dictionaries in the existing import columns plus per-field provenance), `notices` (informational strings, never containing amounts or names from the document unless they are the figures shown in the review), and `fingerprint` (a short hash of statement-identity fields chosen by each reader). Empty `rows` and no exception means **nothing to import**. Wrap `Dividend` and `FundReturn` in an adapter; do not rewrite them.
4. **Staging.** Stage every row of every result, with `line_number` unique per batch and `source_name` and `provenance` per row. Add the "nothing to import" and "recognised, not imported" outcomes to the upload result and to `ImportBatch.warnings` as summary lines. Keep: sorted processing, same-file detection, atomic creation, stored original (single PDF or zip), the committed-batch warning.
5. **Layout extraction.** Add `extract_pages(raw, layout=False)` to `pdf_text.py`. In layout mode use `extraction_mode="layout"`. Keep the size, page, encryption and "no text layer" refusals. Add a small shared helper that normalises runs of spaces and the dash/parenthesis/H/S/comma conventions of G6 (`parse_amount_us`, `parse_amount_uk`, `parse_amount_de_with_hs`), each with a test.
6. **Statement fingerprints (G7).** In a batch, two files with the same reader id and fingerprint are one statement: stage the first, list the second as "same statement as <file>" in the warnings. Fingerprint fields are decided by each reader and documented in `docs/imports.md`.
7. **Display masking.** Mask digit runs of six or more in the displayed `source_name` and `ImportBatch.file_name`, the same way `_clean_evidence` does for source lines. The stored original keeps its generated name. Add a test.
8. **Inventory tool.** `tools/pdf_inventory.py <folder> [--recursive]`: for each PDF print file name (masked as above), reader id or "unrecognised", statement period if the reader found one, number of income rows, number of notices, outcome (staged / nothing to import / refused with reason), and flags: same content as another file, period gap to the previous statement of the same reader, file name period differs from the period read. It prints **no amounts and no names**. It does not touch the database. It is documented in `docs/imports.md`.
9. **Docs.** Update `docs/imports.md` (section "PDF statements": multi-row results, nothing-to-import, notices, fingerprints, inventory tool), `docs/architecture.md`, `CLAUDE.md` Imports section, and write ADR 0015.

### Acceptance criteria
- With only the Phase 14 readers registered, a test over the existing synthetic dividend and fund fixtures produces rows identical to before (compare full row dictionaries and provenance).
- A synthetic reader registered in the test returns 0, 1 and 3 rows; the batch stages 0 (with a "nothing to import" line), 1 and 3 rows with unique line numbers.
- Two readers claiming the same synthetic file produce a refusal naming both reader ids.
- Two synthetic files with identical fingerprints stage one statement and warn about the other.
- A file name with an account-number-like digit run is shown masked in the review and history pages (test on the rendered page).
- `tools/pdf_inventory.py` run on a folder of synthetic PDFs prints the expected table; a test asserts its output contains no digit run of six or more and no amount.
- An optional local test runs the inventory over `local/samples/` when present and, for the four folders, reports, without printing amounts, the re-issued RVB statements (same content, different bytes) and confirms that the E*TRADE and Fidelity folders have no period gaps and no file whose name differs from its period.
- All existing tests pass.

### Stop and report

---

## Phase 16: HSBC Flexible Saver interest (GBP)

Goal: read HSBC savings statements and stage one interest payment per "GROSS INTEREST" credit.

Corner cases covered: G1, G4, G5, G6, G8, G9, G11, H1 to H7.

### Questions for the owner
- Payment date: the credit date printed in the date column (default), or the "TO" date.
- Is there a statement with a fee or charge line (blacked out) you can add? Default: none; any debit line that is not an internet transfer is then refused with its line type named (H7).
- Income period: only the end date is printed (the TO date). Default: set `income_period_end` only, leave the start empty. Verify that the payment model and the importer accept an end without a start; if not, leave both empty and put the TO date in the comment.

### Tasks
1. **Inspect** the three sample statements with the inventory tool and with `extract_pages(layout=True)` and `layout=False`. Report, without amounts, which mode keeps each table row on one line (expected: layout mode, G1) and where the irregular parts are (letter-spaced summary headings G8, multi-page, repeated headers H6).
2. **Reader `hsbc_savings`** (`needs_layout=True`). Recognise by structure, not by headings: a table with columns date / payment type and details / paid out / paid in / balance, a "BALANCE BROUGHT FORWARD" row and a "BALANCE CARRIED FORWARD" row, currency sign pound, and at least one of the interest or transfer row types. Do not anchor on the letter-spaced summary labels.
3. **Rows.** One row per credit whose description is "GROSS INTEREST" followed by the line "TO <ddMONyyyy>". Payment date from the date column (two-digit year, H1), income period end from the TO date. Currency GBP, category Interest, frequency monthly, organisation from the fixed dictionary, comment "Gross interest (PDF import)". Gross = the credit. Expenses 0. Withholding 0 **only if** the running balance proves the credit was paid in full (H4). Net = gross.
4. **Arithmetic.** For every row of the table: previous balance + paid in - paid out = balance. Sum of paid in and paid out must equal the summary's totals if the summary is readable (it may be letter-spaced; use it only as an optional second check). Opening balance equals the brought-forward row; closing equals the carried-forward row. Any failure refuses the statement (G9).
5. **Unknown rows (G12, H7).** Rows other than interest credits, internet transfers (any direction) and the brought/carried-forward rows refuse the statement, naming the row type text (the type text only, not amounts).
6. **Continuity (H3).** In a batch, compare each statement's opening balance and sheet number with the previous statement's closing balance and sheet number and warn about gaps or overlaps. Warnings only.
7. **Fingerprint.** Sheet number plus closing balance plus period end.
8. **Provenance.** Each row cites the page and the two source lines (credit line and TO line), digit runs of six or more masked.
9. Tests, docs, `CLAUDE.md`, ADR 0016, rules item (next free number) "HSBC interest: tax treatment of UK-source interest of a German resident is not decided (unverified)".

### Acceptance criteria
- A synthetic statement with 3 interest credits and one transfer in produces exactly 3 rows with the hand-worked gross figures, GBP, monthly, Interest, withholding 0, expenses 0, net = gross; the transfer is not staged.
- A synthetic statement whose running balance is wrong by one penny is refused with a reason that names the row position, not the figures.
- A synthetic statement with an unknown row type ("a charge") is refused naming the type text.
- A synthetic multi-page statement where the table continues on page 2 with a repeated header row stages every credit once (H6).
- The summary headings letter-spaced in a synthetic fixture do not prevent recognition (G8).
- Two consecutive synthetic statements with a missing sheet number produce a gap warning; uploading the same statement twice stages it once.
- `local/samples/HSBC` run through the optional local test: every file staged, none refused, expected rows equal the owner-checked `local/samples/expected/` file (the owner checks it).
- The dividend and fund fixtures still produce identical rows.

### Stop and report

---

## Phase 17: RVB quarterly interest and tax withheld (EUR)

Goal: read RVB current-account statements; stage one payment per quarterly interest closing with the tax actually booked; report all other statements as "nothing to import".

Corner cases covered: G3, G4, G6, G7, G8, G9, G11, G12, R1 to R9.

### Questions for the owner
- Payment date: **answered, booking date** (R4); put the value date in the comment.
- Tax (plan question 3): record Kapitalertragsteuer, Solidaritätszuschlag and, if booked, Kirchensteuer together in the withholding field (default yes) with a comment naming them. Confirm.
- Prize credits (plan question 4): not staged, shown as a notice (default).
- Fees: any statement with a fee line (blacked out)? Default none; an unrecognised debit line inside the closing block refuses the statement (R8).

### Tasks
1. **Inspect** the 23 sample files with the inventory tool and in default and layout mode. Report which statements are closings, which have tax lines, and which are re-issues (same text, different bytes), without figures.
2. **Reader `rvb_account`.** Recognise by structure: "Kontoauszug" with an "alter Kontostand" row and a "neuer Kontostand" row, and German number format with H/S suffix. Do not anchor on the bank name, address or any header text (R5, G8).
3. **Statement without interest.** If no "Abschluss lt. Anlage 1" booking exists, return no rows and no error (nothing to import), but still verify the running balance (alter + credits - debits = neuer; R9, G9) so a damaged statement is not reported as empty.
4. **Closing statement.** Read the booking "Abschluss lt. Anlage 1" and the Anlage 1 block: period (von/bis), each HABENZINSEN line (rate, "bis" date, amount, H), the sum line. Check: sum of the interest lines minus any debited fee lines in the block equals the booked closing amount and the sum line (R2).
5. **Tax.** Read booked "Kapitalertragsteuer", "Solidaritätszuschlag" and (if present) "Kirchensteuer" debit lines and the small second line that states the interest base ("aus <amount> Habenzins"). Withholding = sum of the booked tax lines. The base on the second line is written to the comment ("tax charged on <base> of the interest") because a base smaller than the interest means part of the interest was not taxed, and the app does not say why (R3). The tax lines in the Anlage 1 tax block must agree with the booked lines; otherwise refuse.
6. **Row.** Payment date per the owner's answer, income period = Anlage 1 period, currency EUR, category Interest, frequency quarterly, gross = sum of interest lines, expenses = debited fees (0 if none), withholding as above, net = gross - expenses - withholding. The running balance must prove it: the booked amounts must account for the whole movement of the statement (R9). Organisation from the fixed dictionary.
7. **Prize credits (R6) and transfers (R7).** Recognise credits and transfers by their booking text and posting code only to classify them as not income; a prize credit adds a notice ("savings-lottery prize credit, not imported") with no amount. A booking that is neither interest, tax, transfer nor prize refuses the statement naming the text (G12).
8. **Fingerprint (G7).** Statement number plus year plus closing balance. Re-issued statements with identical text stage once and warn.
9. **Garbled text (G8).** Tests with letter-spaced words and replacement characters in headers and rules; recognition and rows unaffected.
10. Tests, docs, `CLAUDE.md`, ADR 0017, rules item "German capital-gains tax and solidarity surcharge on bank interest in the withholding field: how the tax summary should label and use it is open (the 'not credited' text was written for foreign tax)". No calculation changes.

### Acceptance criteria
- A synthetic closing with three interest lines, one booked tax pair and a stated base smaller than the interest produces one row: gross = sum, withholding = tax pair, net = gross - withholding, income period = the Anlage 1 period, quarterly, Interest; the comment contains the base.
- A synthetic closing with no tax lines stages gross = net with withholding 0 and the balance check closes.
- A synthetic ordinary monthly statement (transfers, standing order, prize credit) returns nothing to import plus one prize notice; a broken balance in it is refused (R9).
- A closing whose interest lines do not add to the booked amount is refused (R2). A closing with an unknown debit line is refused naming the text (R8, G12).
- A closing with a Kirchensteuer line includes it in withholding and names it in the comment.
- Two synthetic files with identical text and different bytes stage one statement and warn (G7).
- Letter-spaced and replacement-character fixtures read identically to clean ones (G8).
- Uploading a synthetic year of 12 statements (4 closings, 8 others) yields 4 rows, 8 "nothing to import" in one summary line, and no warnings.
- `local/samples/RVB` through the optional local test: 7 closings staged, the other files nothing to import, 2 duplicates warned, none refused; rows equal the owner-checked expected file.
- Phases 15 and 16 tests still pass.

### Stop and report

---

## Phase 18: E*TRADE dividends and withholding (USD)

Goal: read E*TRADE client statements and stage one payment per income event, with its withholding when the statement shows one.

Corner cases covered: G1, G2, G4, G5, G6, G9, G11, G12, E1 to E9.

### Questions for the owner
- **Answered:** money-market-fund income is category Dividends. Record the open classification question in `docs/rules/README.md`, as for the Revolut fund.
- January items marked "reportable for the prior year" (plan question 6): payment date as printed with a comment (default).
- Sales of stock appear in other months? Default: any sales or purchases section is recognised and listed as "not imported" (notice), nothing else.

### Tasks
1. **Inspect** the 13 sample files with the inventory tool and in both extraction modes. Report without amounts: period formats, sections found, which activity types occur, which files are duplicates or misnamed.
2. **Reader `etrade_client`** (`needs_layout` as the inspection decides). Recognise by structure: a "client statement" with "For the Period <start>-<end>", the Cash Flow Activity table with columns activity date / activity type / description / credits (debits), and the Income and Distribution Summary.
3. **Period and dates (G4, G5).** Parse the period (one or two months, possibly across a year end), then dates "m/d" with that period's year.
4. **Rows.** From the Cash Flow Activity table: each "Dividend" and "Qualified Dividend" line is an income event. A "Tax Withholding" line with the same date and the same description is attached to that event (E2). A withholding line without an event, an event type not listed here (for example interest, return of capital, adjustment), or two withholding lines for one event refuses the statement naming the type text (G12). Amounts per G6 (parentheses negative, dash zero).
5. **Row fields.** Gross = the dividend line, withholding = the paired line as a positive number (0 only when the statement has no withholding line for a dividend of a type that has none; **never assume**: for stock dividends a missing withholding line refuses the statement unless the owner states otherwise), expenses 0, net = gross - withholding. Currency USD, category Dividends, organisation = the payer as printed on the income line, tidied by the shared function (Phase 15), comment "via E*TRADE" plus "fund dividend" or "qualified dividend", frequency monthly for the fund and quarterly for stock dividends. The "Transaction Reportable for the Prior Year" remark goes into the comment when printed on the line (E1).
6. **Reconciliation (E3, E7, G9).** Sum of credits and debits equals "Net credits/(debits)". The income summary's period totals by class equal the sums of the lines by class. The tax withholdings total equals the sum of the withholding lines. The sweep table's automatic investments (net cash into the fund) equal the net credits; report a mismatch as a refusal. If a statement has no sweep table, skip that check and say so in the notice.
7. **Not imported.** Any securities purchased or sold, realised gain or loss section with entries, and journal entries are listed as a notice with their type and date only (E-notice).
8. **Messages and disclosures (E8).** Never read, store or log the messages section or the standard disclosures.
9. **Fingerprint (G7).** Period plus closing total value. Identical text with different bytes stages once.
10. **Rate handling.** Rates are proposed by the existing mechanism for USD; nothing new.
11. Tests, docs, `CLAUDE.md`, ADR 0018, rules item for the fund classification.

### Acceptance criteria
- A synthetic quarterly statement with one stock dividend and its withholding, and one fund dividend, stages 2 rows: stock row gross/withholding/net as worked out in the test file, fund row withholding 0 with the sweep check closing.
- A synthetic two-month statement across a year end assigns the right years to "12/31" and "1/2" lines.
- A synthetic statement whose cash-flow total differs by one cent from the sum of its lines is refused (E7). A withholding line with no event is refused (E2).
- A synthetic January fund dividend carrying the "reportable for the prior year" remark is staged with the remark in the comment (E1).
- Parentheses and dash amounts parse correctly (E4).
- Two statements with identical text stage once (G7).
- A synthetic E*TRADE statement and a synthetic Fidelity report that pay the same invented company produce the identical organisation string (test of the shared tidy function; custodian differs only in the comment).
- Dividend rates that change between two synthetic quarters are read as printed (E6).
- The messages section of a synthetic statement containing a fake password string is never copied into any row, provenance, log record or notice (E8; test captures logs).
- `local/samples/ETrade` through the optional local test: all 14 files staged, none refused, the inventory reports no gaps and no name/period mismatches, rows equal the owner-checked expected file. The 2025 1042-S cross-check is Phase 20.
- Phases 15 to 17 tests still pass.

### Stop and report

---

## Phase 19: Fidelity dividends, withholding settlement and sale detection (USD)

Goal: read Fidelity stock-plan reports; stage one payment per income event with withholding settled across all uploaded statements; recognise stock deliveries and sales without importing them.

Corner cases covered: G1, G2, G4, G5, G6, G9, G11, G12, F1 to F10.

### Questions for the owner
- **Answered:** fund income is category Dividends. January remark: as in Phase 18 (default).
- **Withholding settlement (plan question 10).** The default is to sum every posting for an income event (original withholding, reversal, new withholding) across the statements in the upload. If a posting refers to an event outside the upload, show a warning on the batch and mark the row. Confirm, or choose to stage the original withholding and ignore later reversals (not recommended: the amount would be wrong).
- Stock deliveries (RSUs) and sales: confirm they are recognised and not imported (default). Whether and how to record them (employment income, capital gain or loss) is a separate decision with rules to verify and is not part of this phase.

### Tasks
1. **Inspect** the 16 sample files and the 3 related year-end documents without importing the latter. Report without amounts: sections found, activity descriptions used, which reports have tax lines dated outside their month, which reports have two months, where the September 2025 sale and delivery sections are.
2. **Reader `fidelity_stock_plan`** (layout as decided). Recognise by structure: "Stock plan services report" with a period line "<Month d, yyyy> - <Month d, yyyy>", the "Dividends, Interest & Other Income" table, and the "Account Summary".
3. **Income table.** Rejoin wrapped security names (F1). Each "Dividend Received" line is an income event: date (MM/DD with the period's year, G5), security (name only, the code is a cross-check), amount. Any other description (interest, capital-gain distribution, return of capital, other) refuses the statement naming the description text (G12).
4. **Tax table.** Lines with "Non-Resident Tax" (negative) and "Adj Non-Resident Tax" (positive) with their date and security. Do not use the sign or value of "Total Federal Taxes Withheld" as an anchor (F4); recompute the total from the lines and compare absolute values. Flag letters in front of a line mark prior-period items and are kept as provenance.
5. **Settlement across statements (F5).** After all files of an upload are parsed, group postings by (security, event date). Net withholding for an event = sum of its postings (original negative, adjustment positive, re-booked negative), as a positive number. Postings for events that are not in the upload (for example December postings in a January report) become warnings on the batch ("tax postings for events not in this upload: n"). A group whose net is negative (refund larger than withholding) is a warning and the row withholding is 0 with a comment. Rows that depend on a posting booked in a statement outside the upload are marked in the comment ("withholding may be revised by a later statement").
6. **Row fields.** Gross = the dividend line, withholding = settled net, expenses 0, net = gross - withholding. USD, category Dividends, organisation = the payer as printed (wrapped names rejoined, F1), tidied by the shared function, comment "via Fidelity", frequency monthly for the core fund and quarterly for stock.
7. **Reconciliation (G9, F6).** Sum of income lines equals "Total Dividends, Interest & Other Income" and the income summary's period amount. Core-fund activity is read only as a check: reinvested income plus other movements must reconcile with the fund's beginning and ending quantity if both are printed; skip with a note if not. Cash movements ("You Bought" into the core fund, "Reinvestment", withdrawals, journals) are never income (F10).
8. **Sales and deliveries (F7).** If the report has a "Securities Bought & Sold" section, a realised gains/losses block, an RSU vesting or distribution block, or "Other Activity" entries, list each as a notice (type and date only) and import nothing from them.
9. **Rounding (F9).** When a statement's withholding is a round-half-up of a percentage of the gross, accept a one-cent difference only for the comparison of rate to amount; never adjust the stated figures.
10. **Fingerprint (G7).** Period plus ending account value.
11. Tests, docs, `CLAUDE.md`, ADR 0019, rules item "stock sales and share deliveries from the stock plan: recording and tax treatment are not decided".

### Acceptance criteria
- A synthetic report with one stock dividend with withholding and one fund dividend with none stages 2 rows with the worked-out figures.
- Synthetic Statement A (January) with a fund dividend and withholding, and Statement B (February) with a reversal and a re-booked smaller withholding for the same event, uploaded together: one row for the event with withholding = original - reversal + re-booked (hand-worked); uploaded alone, A's row is marked "may be revised by a later statement".
- A January statement that contains reversal and re-booking lines dated in the previous year stages no row for them and adds the "events not in this upload" warning (F3).
- A synthetic report where the "Total Federal Taxes Withheld" is positive (net refund) still reconciles (F4).
- A synthetic report with a delivery and a sale stages only the dividends and shows two notices (F7).
- A wrapped security name is matched to its pair of lines (F1).
- A report with an unknown income description is refused naming it (G12).
- `local/samples/Fidelity` through the optional local test: all 16 files staged or nothing to import, none refused, no month missing (the inventory), expected rows equal the owner-checked file, warnings for out-of-upload postings listed by count only.
- Phases 15 to 18 tests still pass.

### Stop and report

---

## Phase 20 (optional): Reconcile statements with the year-end documents

Do this phase only if the owner says "go" for it after Phase 19. Gate: Phases 18 and 19 are done (the E*TRADE and Fidelity folders are complete for 2025).

Goal: a read-only check, not an importer, that compares yearly totals from imported statement rows with the year-end documents and says where they differ.

### Questions for the owner
- Which year-end documents should be compared: the US year-end reports and the US withholding forms (1042-S) for 2025? Default: yes.
- Tolerance: forms may differ from statement sums by cents (E9). Default: 1.00 USD per form line, shown as "within tolerance" or "differs".

### Tasks
1. Read, with the same refusal rules, the totals that matter from the US withholding forms (income code, gross income, tax rate, tax withheld; ignore recipient details and duplicate copies) and from the Fidelity year-end report (taxable dividends, taxes withheld).
2. A report page or CSV "Statement vs year-end form" per institution and year: statement total by class, form total, difference, status. It uses stored payments of the year and category/organisation, nothing else. No calculation of tax.
3. The forms contain tax identification numbers and dates of birth; none of this is read, stored or shown.
4. Tests with synthetic forms. Docs, ADR 0020.

### Acceptance criteria
- A synthetic form and matching rows report "within tolerance"; a changed row reports "differs" with the difference.
- The tax identification and date of birth text of a synthetic form never appears in any output, row or log.

### Stop and report
