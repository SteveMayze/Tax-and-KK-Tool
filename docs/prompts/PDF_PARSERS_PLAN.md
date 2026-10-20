# PDF parsers for bank interest and brokerage dividends: findings and development plan

Save as `docs/prompts/PDF_PARSERS_PLAN.md`. It is the background for `docs/prompts/PHASES_3.md` (Phases 15 to 20), which is the prompt Claude Code works from. Written 2026-10-20 from a read-only review of the four sample folders in `local/samples/`.

**Privacy of this document.** It describes layouts, labels, counts and corner cases only. It contains no amounts, names, account numbers, addresses or employer names, because tracked files must hold no personal data (`CLAUDE.md`, Security and privacy). Where this plan says "the company stock", the actual security is in the samples, not here. Hand-checked expected figures for the real samples belong in the git-ignored `local/samples/expected/`, never in a tracked file.

## 1. Scope

| Folder | Currency | Wanted | Phase |
|---|---|---|---|
| `HSBC` | GBP | Interest paid. Fees if the statements show any | 16 |
| `RVB` | EUR | Interest paid, tax withheld on it. Fees if shown | 17 |
| `ETrade` | USD | Dividends and money-market-fund income, withholding | 18 |
| `Fidelity` | USD | Same, plus detection of stock sales | 19 |
| `ETrade-Tax`, `Fidelity-Tax` | USD | Not parsed. Year-end documents used only as cross-checks | 20 (optional) |

Already done and not touched: `Securities/` (Australian dividend advices, ADR 0014) and `Revolut/` (Flexible Cash Funds). Not in scope here: `MECU`, `Ords`, `Hodges` (named in ADR 0014 as later work) and the `AU-*` tax return PDFs.

Out of scope for every phase: OCR, scanned PDFs, sending documents to any external service, any tax or SBK calculation. The app records what the statement says and shows where it said it.

## 2. What the samples contain

All files in the four folders have a real text layer, so pypdf is enough.

**HSBC (3 files, 3 to 8 pages).** A UK "Flexible Saver" savings account in GBP. Each statement covers about six to ten months (not a calendar month; the periods are irregular). The account table holds a monthly credit labelled "GROSS INTEREST" with a second line "TO <day><MON><year>", plus occasional internet transfers in and out (not income). The remaining pages are terms, deposit-protection sheets and accessibility text. No fee lines occur in the samples.

**RVB (23 files, 2 pages each).** A German current account (Kontokorrent, EUR). One statement per month, but interest is only credited in the four quarterly closing statements (7 of the 23 files are closings). The closing has three parts: a booking line "Abschluss lt. Anlage 1", separate booking lines for Kapitalertragsteuer and Solidaritätszuschlag when tax applies, and an "Anlage 1" with one or more "HABENZINSEN" lines (rate, "bis" date, amount), a sum, and a small tax block that states the interest base the tax was charged on. The other 16 files contain transfers, standing orders and small prize credits, and no interest.

**E*TRADE (14 files, 8 or 10 pages).** "Client Statement" of a self-directed stock-plan account at Morgan Stanley. USD. Each file covers one or two calendar months. Income appears in "Cash Flow Activity by Date": monthly money-market-fund dividends ("Dividend", description "DIV PAYMENT"), quarterly company-stock dividends ("Qualified Dividend") each followed by a "Tax Withholding" line with the same date and description, in parentheses. A second table lists the automatic sweep of the net cash into the fund. The summary pages repeat the totals by class (qualified, other).

**Fidelity (16 files, 8 or 10 pages).** "Stock Plan Services Report" for a stock-plan account, USD. One or two calendar months per file. Income is in "Dividends, Interest & Other Income" (company-stock dividends and money-market-fund dividends, the latter credited into the core fund). Tax is in a separate "Taxes Withheld" table. The September 2025 report also holds an RSU delivery, a sale of part of it to cover German tax, a "Realized Gains and Losses from Sales" block and a journaled payout of the sale proceeds ("Other Activity Out").

**Year-end documents (not parsed).** E*TRADE: a 1042-S packet (several copies of each form). Fidelity: 1042-S forms (several copies), a 2025 year-end investment report, two single-trade confirmations (the RSU distribution and the sale to cover tax) and a large transaction summary printout (5.5 MB, above the app's current 5 MB limit).

## 3. Findings about the sample folders themselves

These are not parser problems but they would make any result look wrong, so they are listed here. The inventory tool (Phase 15) reports them without printing amounts.

1. **E*TRADE: resolved 2026-10-20.** The first review found misnamed and missing files (one file named for October 2025 held January 2025; one 2025 name held a copy of a 2026 statement; July 2025, August to September 2025 and October 2025 were absent). The owner refreshed the folder from source. Re-check: 14 files, January 2025 to September 2026, no gaps, file names match periods, same line types as before. The inventory tool must keep checking this.
2. **RVB re-issued statements.** Two statement numbers exist twice with different timestamps in the file name and identical text.
3. **RVB file names contain the account number**, and the importer shows the uploaded file name in the review and history. Digit runs of six or more must be masked in the displayed name, as is already done for source lines.
4. **Fidelity is complete** (January 2025 to September 2026, no gaps).

## 4. Corner cases

Numbered so tests, ADRs and reports can refer to them.

### General (all institutions)
- **G1. Row order is lost by default.** `page.extract_text()` returned HSBC table rows with dates and amounts separated and some rows repeated. pypdf's layout mode (`extraction_mode="layout"`) kept each row on one line for HSBC, E*TRADE and Fidelity. The extractor must offer layout mode and the readers must use it where needed. Verify on each file type; do not assume.
- **G2. One statement, many payments.** The importer stages one row per statement today. These statements hold from zero up to about ten income events.
- **G3. A statement with no income is not an error.** 16 of 23 RVB files, and some brokerage months, contain nothing to import. They must be reported as "recognised, nothing to import", not as refused, so that uploading a whole folder shows only real problems.
- **G4. Statement period is not the calendar month** (HSBC irregular, brokerage one or two months, RVB quarterly closings dated by balance date, not by file name).
- **G5. Dates without a year** (brokerage activity "4/23", "04/23"; RVB "30.06."). The year comes from the statement period; a period that crosses a year end must be handled.
- **G6. Different thousands and decimal conventions**: UK/US "1,234.56"; German "1.234,56" with a trailing H (credit) or S (debit); US negatives in parentheses; em dash for zero.
- **G7. Duplicates of the same statement** with different bytes (re-issued, regenerated). The file hash does not catch them. Use a fingerprint from the statement's own identity (type, number or period, closing balance), and keep the existing row duplicate rule as the second line of defence.
- **G8. Garbled text in boilerplate.** Letter-spaced words ("Ope ning Balance", "B itte"), a bank name rendered as noise, replacement characters in rule lines. Never anchor on headings, logos or boilerplate; anchor on structured rows and arithmetic.
- **G9. Every figure must close arithmetically** (running balance, section totals, summary totals). A statement that does not reconcile is refused with the reason; nothing is guessed (ADR 0014 principle).
- **G10. Year attribution.** Payment date, income period and the year the issuer reports it for can differ. The app stores the payment date as printed and records the rest in the comment. It decides nothing about tax years.
- **G11. Personal data in the source lines.** Names, addresses, account and IBAN numbers sit next to the figures. Provenance keeps only the line used, with long digit runs masked.
- **G12. Unknown line types.** A line type not seen in the samples (a fee, a different income type, a reclassification) refuses the statement with the line type named. It is never skipped silently and never guessed.

### HSBC
- **H1.** Interest is two text lines: label, then "TO <date>" plus the amount. Dates are "29 Jan 26" (two-digit year); the TO date has no spaces ("28JAN2026").
- **H2.** Transfers in and out are interleaved with interest. They are not income but they change the balance, so the running balance check must include them.
- **H3.** Opening balance, "brought forward" and "carried forward" lines give the continuity check. Each statement's opening equals the previous closing. The sheet number increases by one. Both detect a missing statement.
- **H4.** "Gross interest" with no tax line. Withholding 0 is accepted only because the running balance rises by exactly the credited amount; a statement where it does not is refused.
- **H5.** The monthly credit is dated shortly after the TO date. The payment date and the income period end therefore differ by a day or more.
- **H6.** Later pages of a long statement may repeat page headers inside the table. Page breaks inside the account table must not drop or duplicate rows.
- **H7.** Fees: none in the samples. Phase 16 refuses any debit line that is not a transfer until a real example exists.

### RVB
- **R1.** Interest exists only on quarterly closing statements. Detect the closing by its "Abschluss lt. Anlage 1" booking and the Anlage 1 block, not by the statement number or file name (a closing at the end of a quarter can be named for the first day of the next month).
- **R2.** Several HABENZINSEN lines in one closing (rate changes, balance tiers, a split at a date). Gross is their sum and must equal the booked closing amount plus any debited fees.
- **R3.** Tax is booked as separate debit lines (Kapitalertragsteuer, Solidaritätszuschlag; Kirchensteuer if the owner is liable), each with a small second line that states the interest base. The base can be a part of the interest (an exemption order covers the rest) or the whole interest, or tax can be absent. The app records the tax actually booked and never infers an exemption order.
- **R4.** Booking date and value date differ at year end. Which one is the payment date is an owner question (default below).
- **R5.** The bank's name and the layout of the statement header changed during 2026 (name rendered as noise, a different telephone format). Use a fixed organisation name per statement type, not the printed name.
- **R6.** Prize credits from a savings lottery ("Gewinn", "Los") appear as ordinary credits. They are not interest and are never staged. The reader recognises them so they do not look like unknown credits.
- **R7.** Transfers, standing orders to a savings account, and "Umbuchung" lines are not income.
- **R8.** Fees: none in the samples (only a notice that a fee information sheet is available). Phase 17 refuses an unrecognised debit line inside the closing block until a real example exists.
- **R9.** Running balance is "alter Kontostand ... H" to "neuer Kontostand ... H", with H and S suffixes. It must close.

### E*TRADE
- **E1.** Money-market-fund dividends are monthly, dated on the first business day, and can fall in the first days of January while the statement notes "Transaction Reportable for the Prior Year". The amount is received in the new year; the US reporting year is the previous one. The statement's own year-to-date totals exclude it. Record the payment date as printed and note the remark in the comment. The German treatment is an owner question.
- **E2.** Company-stock dividend and its withholding are two lines with the same date and description. Combine them into one payment: gross, withholding, net.
- **E3.** The net cash is swept into the fund; the sweep table is an independent check on the net amounts.
- **E4.** Parentheses mean negative; an em dash means zero.
- **E5.** One file may cover two months, and a quarter in which nothing was paid may produce no income lines at all.
- **E6.** The per-share dividend changed during the sample period. Never assume a constant amount or rate between quarters; withholding rate is read from the statement (and compared, not assumed).
- **E7.** Section totals (cash-flow total, income summary by class, tax withholdings) must equal the sum of the lines used.
- **E8.** The statement's messages may contain sensitive text (links, passwords for fund documents). Never read it, never log it, never store it.
- **E9.** The 1042-S gross and withheld figures differ from the statement sums by cents. Cross-checks need a stated tolerance.

### Fidelity
- **F1.** Income lines have wrapped security names (the name continues on the next line, sometimes with a share-class code). Rejoin before matching.
- **F2.** Tax is in a separate table. "Non-Resident Tax" is negative. "Adj Non-Resident Tax" is positive and is a reversal of an earlier withholding. A reversal and a new withholding can be booked together, in a later statement than the income.
- **F3.** Tax lines can carry dates from the previous month or previous year (marked with a flag letter). A January report contains December and November entries of the year before.
- **F4.** "Total Federal Taxes Withheld" changes sign depending on whether the adjustments exceed the withholdings. Do not use its sign as an anchor. Compute from the lines and compare the absolute value.
- **F5.** The withholding that finally applies to one income event is the sum of every posting for that event across statements. A statement uploaded alone can therefore show a withholding that a later statement revises. The importer must settle postings across the whole upload and warn when a posting refers to an event outside the upload.
- **F6.** Core-fund activity ("You Bought", "Reinvestment", "You Sold") is movement of cash, not income. Only the income table and tax table are read; the core-fund table is a cross-check.
- **F7.** The September 2025 report holds an RSU delivery, a sale of part of it ("sell to cover"), a realised loss and a journaled payout. These are recognised, listed as "not imported", and carry no amounts into payments. They are employment-related and capital-gain matters and need owner rules first.
- **F8.** Reports with two months in one file, and months with only core-fund activity.
- **F9.** Rounding: a percentage tax that falls on a half cent is rounded half up in the sample (for example 0.125 shown as 0.13). Compare with a one-cent tolerance only when the statement itself rounds.
- **F10.** Cash withdrawals and journals out are not income.

## 5. Design

The existing structure stays: pypdf text only, extraction separate from the models, one staging path shared with CSV, refusal with a reason instead of a guess (ADR 0014). The changes are what the new statements force:

1. **Reader registry.** Replace the two-way `if` in `pdf_imports._read` with an ordered list of readers, each with `recognises(pages)` and `parse(pages)`. First match wins; the match must be exclusive (a test proves no sample file is claimed by two readers).
2. **Result type.** A reader returns a `StatementResult`: a list of `IncomeRow` (same fields as today's `row_data`, plus per-field provenance), a list of `Notice` (informational, such as "sale recognised, not imported") and a statement fingerprint. An empty list of rows with no error is the "nothing to import" outcome (G3). `UnsupportedStatement` stays for refusals. Existing `Dividend` and `FundReturn` are wrapped, not rewritten, so the 54 + 11 existing statements keep working byte for byte.
3. **Layout extraction.** `pdf_text.extract_pages(raw, layout=False)`; layout mode is used by readers that declare it. Add a blank-line and whitespace normaliser shared by readers.
4. **Cross-statement settlement** for withholding (Fidelity, F5): after parsing every file of an upload, group tax postings by (security, event date), sum them, attach to the income rows, and report postings that have no income row in the upload.
5. **Continuity and fingerprint checks** (HSBC H3, G7): run over the whole upload, produce warnings, never refuse.
6. **Safe display.** Mask digit runs of six or more in the displayed file name and keep provenance as today.
7. **Inventory tool** `tools/pdf_inventory.py <folder>`: for each PDF prints type, period, statement number, number of income rows, flags (duplicate content, period gap, name does not match period). It prints no amounts and no names, so its output can be pasted into a report.
8. **Fixed organisation names** per statement type, configurable in one dictionary (R5, G8).
9. **No new dependency.** pypdf is enough. If layout mode proves insufficient for a layout, stop and ask before adding a library.

### Field mapping

| Institution | One row per | Payment date | Income period | Gross | Withholding | Expenses | Net | Category | Frequency |
|---|---|---|---|---|---|---|---|---|---|
| HSBC | "Gross interest" credit | Credit date printed | End = "TO" date | The credit | 0, proven by the running balance | 0 (fees refused until seen) | = gross | Interest | monthly |
| RVB | Quarterly closing | Booking date (owner decision) | Anlage 1 period | Sum of HABENZINSEN | Booked Kapitalertragsteuer + Solidaritätszuschlag (+ Kirchensteuer if booked) | Debits inside Anlage 1 (none seen) | gross - withholding - expenses, proven by the balance | Interest | quarterly |
| E*TRADE | Income event (fund dividend, or stock dividend with its withholding) | Activity date | none | Dividend line | The paired Tax Withholding line | 0 | gross - withholding, checked against the sweep table | Dividends (owner decision: also for the fund) | monthly for the fund, quarterly for stock |
| Fidelity | Income event | Settlement date printed | none | Dividend line | Net of every posting for the event across statements | 0 | gross - withholding | Dividends (owner decision: also for the fund) | monthly for the fund, quarterly for stock |

**Organisation (owner decision 2026-10-20).** For the two banks it is the bank (fixed names `HSBC UK (Flexible Saver)`, `RVB (Girokonto)`), because the bank is the payer. For E*TRADE and Fidelity it is the **payer**: the company whose stock pays the dividend, or the money-market fund, as printed on the income line and tidied the way ADR 0014 tidies issuer names. The custodian goes in the comment ("via E*TRADE" / "via Fidelity"). The same company stock paid through both brokers must give the identical organisation string, so reports by organisation add up. Consequence for the duplicate rule (same date, organisation, currency and gross): two brokers paying the same company on the same day with the same gross would be flagged as a possible duplicate; the owner then uses "Keep anyway". The comment makes the custodian visible in the review.

Everything stays editable per row in the review, as today.

## 6. Questions for the owner (consolidated; each repeats in its phase)

| # | Question | Default |
|---|---|---|
| 1 | Organisation name | **Answered 2026-10-20: the payer** for E*TRADE and Fidelity (company stock or fund); the bank itself for HSBC and RVB. Custodian in the comment |
| 2 | RVB payment date | **Answered: booking date** (the yearly amount matters, EUR needs no conversion). Value date in the comment |
| 3 | RVB tax withheld: record in the existing withholding field? | Yes, labelled in the comment as German capital-gains tax and solidarity surcharge, since the field is generic. The tax summary's "not credited" note was written for foreign tax; whether it needs wording for domestic tax is an open question, no calculation changes |
| 4 | RVB prize credits | Not staged, listed as a notice |
| 5 | Money-market-fund income (E*TRADE, Fidelity) | **Answered: Dividends**, as the statements call it. The open tax question is recorded, as for the Revolut fund |
| 6 | January payments marked "reportable for the prior year" | Payment date as printed, remark in the comment, no year logic |
| 7 | Stock sales and RSU deliveries found in Fidelity | Recognised, listed, not staged. Whether and how to record sales is a later decision |
| 8 | Fees | Not implemented until a real statement with a fee line is supplied (blacked out) for HSBC and RVB |
| 9 | The missing E*TRADE statements for 2025 | **Resolved**: the folder was refreshed and is complete |
| 10 | Fidelity withholding that a later statement revises | Net of all postings found in the upload; provisional rows are marked and warned |

## 7. Phase overview

| Phase | Content | Depends on |
|---|---|---|
| 15 | Foundation: registry, result type, layout extraction, "nothing to import", fingerprints, display masking, inventory tool | none |
| 16 | HSBC interest (GBP) | 15 |
| 17 | RVB interest and tax (EUR) | 15 |
| 18 | E*TRADE dividends and withholding (USD) | 15 |
| 19 | Fidelity dividends, settlement across statements, sale detection (USD) | 15, 18 |
| 20 | Optional: reconcile statements to the year-end documents | 18, 19 |

16 and 17 are independent. 18 comes before 19 because it introduces income/tax pairing that 19 extends.

## 8. Test strategy

- Synthetic PDFs generated in the suite (`core/test_pdf_support.py`) for every layout, with invented figures worked out in the test file. They imitate structure: the same labels, line breaks, sign conventions and column order, with invented names ("EXAMPLE BANK", "EXAMPLE CORP (EXMP)").
- At least one test per reader goes through the real chain: bytes, `pdf_text`, reader, `pdf_imports` staging, review, commit.
- One test per corner case above, named by its id (for example `test_h4_gross_interest_requires_balance_proof`).
- Negative tests: unknown line type, broken running balance, a total that does not close, two readers matching, encrypted file, scan.
- An optional local test over `local/samples/` runs only when the folder exists. It checks that every file is either staged, "nothing to import" or refused with a reason, and compares with the git-ignored `local/samples/expected/` file. It prints no amounts or names.
- Existing 54 + 11 statement tests stay unchanged and green.

## 9. Risks

| Risk | Mitigation |
|---|---|
| Layout mode output differs between pypdf versions | Pin the version (already pinned); a test over synthetic PDFs fails on a change |
| A layout changes (the RVB header already did) | Anchor on rows and arithmetic, never on headings; refuse with a reason |
| Withholding settled in a statement that is not uploaded | Warn per row; mark the row provisional |
| Missing source months look like missing income | Inventory tool and continuity warnings |
| Reader claims a file meant for another | Exclusivity test over all samples |
| Real amounts leaking into tracked files | Reports describe structure; expected figures only under `local/`; review staged files before commit |

## 10. How to start

Start Claude Code in the repository root with:

```
Read CLAUDE.md, docs/prompts/PHASES.md, docs/prompts/PHASES_2.md, docs/prompts/PDF_PARSERS_PLAN.md and docs/prompts/PHASES_3.md, and the code and ADR 0014 for the existing PDF import. Do Phase 15 only, following the standing rules in PHASES_3.md. Ask the questions listed for Phase 15 in your first reply, together with what you found in the current code, then wait for my answers. Stop at the end of the phase with the report and wait for "go". The sample PDFs in local/samples are private: describe their structure in reports but never print amounts, names, account numbers or addresses.
```
