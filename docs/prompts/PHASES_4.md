# PHASES_4.md: Tax and Healthcare Tool, Phases 21 to 24 (PDF statements: Hodges, MECU, Ord Minnett)

Save this file as `docs/prompts/PHASES_4.md`. Background, findings and the corner-case catalogue are in `docs/prompts/PDF_PARSERS_PLAN_2.md`; ids G1 to G12 are in `docs/prompts/PDF_PARSERS_PLAN.md`; ids A1 to A8 (Hodges), M1 to M10 (MECU) and O1 to O10 (Ord Minnett) are in the new plan.
**Do not edit or overwrite `PHASES.md`, `PHASES_2.md` or `PHASES_3.md`.** Phase 20 of PHASES_3 was deliberately not implemented by the owner; do not implement it here. If you find an error in an earlier file, record it in your end-of-phase report.

## Standing rules for every phase below

1. Read first: `CLAUDE.md`, all `docs/prompts/PHASES*.md`, both `PDF_PARSERS_PLAN*.md`, `docs/imports.md`, `docs/decisions/0003`, `0014`, `0015` and the latest ADR written for a reader, `docs/rules/README.md`, and the code: `core/services/pdf_text.py`, `statement_readers.py`, `statement_types.py`, `amounts.py`, `organisations.py`, `pdf_imports.py`, `imports.py`, and the tests `core/test_pdf_support.py`, `core/test_pdf_imports.py`. Everything in `CLAUDE.md` still applies (Decimal only, keep originals, state the basis of every figure, never guess a legal or SBK rule, no real network in tests, synthetic test data only).
2. Work on **one phase at a time**. At the end: stop, give the end-of-phase report (what was done, commits, tests added with real results, deviations, open questions, anything not verified) and wait for "go".
3. **Ask first.** Ask each phase's "Questions for the owner" in your first reply, together with what you found when you verified the current state. If unanswered, use the stated default, say so at the top of your work, and continue.
4. **Verify the current state.** These phases were written from a read-only review of the samples and the existing code, not from running the code. Where a phase says "verify", read the code and say what you found; if it differs from what this file assumes, say so and adapt.
5. **Privacy of the samples (highest priority).** `local/samples/` holds the owner's real statements. You may read them to learn structure. Reports, commit messages, docs, ADRs, test names, fixtures and logs must contain **no amounts, names, addresses, account numbers, tenant, property or security names taken from the samples**. Describe structure, label text, counts and line positions only. Hand-checked expected figures go only into git-ignored `local/samples/expected/` (the owner checks them). Synthetic fixtures use invented names ("EXAMPLE AGENT", "EXAMPLE CREDIT UNION", "EXAMPLE BROKER") and invented figures worked out in the test file. The rental payer name is read from the database/settings at run time, never from code. Before every commit, review the staged files for anything copied from a sample.
6. **Refuse rather than guess.** A statement that does not reconcile (running balance, In/Out/Received, section totals), contains a line type not described here, or cannot be read with certainty is refused with a specific reason and stages nothing (G9, G12). Nothing is skipped silently. The only "not an error" outcomes are **staged**, **nothing to import**, and **recognised and not imported** (a notice).
7. **Acceptance criteria** are checkable statements, each needing a test or a demonstrated command. Report each as met, not met, or not verifiable here, with evidence. Every corner-case id listed in a phase gets a test named after it.
8. At least one test per reader runs the real chain: PDF bytes, `pdf_text`, reader, `pdf_imports` staging, review, commit. Synthetic PDFs are generated in the test suite; nothing from `local/samples` is committed.
9. All readers from Phases 14 to 19 must produce exactly the same rows as before; their tests stay green and unchanged.
10. After the owner's decisions, update `CLAUDE.md` (Imports section), `docs/imports.md`, `docs/rules/README.md` (open questions) in the same phase, and add an ADR `docs/decisions/00NN-...md` where NN is the phase number. Never delete an old ADR.
11. **Dependencies.** pypdf stays the library that extracts text. **Answered by the owner (2026-10-20): one new dependency is approved for opening damaged PDFs (Phase 22), provided it causes no conflict with existing work.** No other dependency is approved. Check licence, pinned version, wheel availability for the Python version and CPU architecture used by the Containerfile and the home server, image size, and that the full test suite and `make` targets still pass; if any of that fails, fall back to the in-memory repair in Phase 22 task 2 and say so. Never send a document to an external service.
12. Nothing in the app is a tax calculation or an SBK assessment. The importer records what a statement says and where it said it. It never classifies income as taxable, exempt or credited, and never decides how Australian withholding tax is treated.
13. Deployment is untouched. No change under `infra/`, the Containerfile or the Makefile except a documented test target if needed.
14. **Existing data.** The owner's database already holds rows entered by hand or from CSV for MECU, Ord Minnett and the rental. Never modify or delete them. Rely on the existing duplicate rule (date + organisation + currency + gross) to flag collisions in the review.

---

## Phase 21: Hodges rental statements (AUD)

Goal: read the managing agent's monthly statements and stage rent received for each statement period, with the costs that reduce it.

Corner cases covered: G4, G5, G6, G9, G11, G12, A1 to A8.

### Questions for the owner
- **Answered by the owner (2026-10-20):** one row per statement; fees (management fee, sundry fee, repairs) go into **expenses**. Owner withdrawals are never staged.
- Organisation: the payer name already used for this rental in the database (default; read it from settings at run time, one setting, no name in code), or the managing agent.
- Category: use the existing rental/other-income category already in the database. Which one? (If unsure, list the categories and use the one the existing rental rows use.)

### Tasks
1. **Verify** how existing rental rows look in the database (read-only, report category, frequency and organisation without amounts) and how payments with expenses are shown in review.
2. **Inspect** the 11 sample files with `extract_pages` in default and layout mode and report, without figures, which mode keeps wrapped rent lines together (A2), where the `*` flag appears (A3), and which statements are two-month or short (A6).
3. **Reader `hodges_rental`.** Recognise by structure: a "Tax Invoice" statement with a Money In block, a Money Out block and a "You Received" line; do not anchor on the agency name, address or logo text (G8).
4. **Invariant (A1).** Money In total - Money Out total = You Received, using the listed lines. Failure refuses the statement. The printed "Total" line may exclude a sundry fee (A5); do not rely on it.
5. **Rows.** Gross = rent received lines in the period; expenses = fees and charges listed as costs of the rental (A4); withholding 0; net = gross - expenses. Payment date = the date on the rent line or the statement date (default: the statement date; state which). Income period = the printed period (A6). Currency AUD, frequency monthly, comment "Rental statement (PDF import)". `*` lines are flagged in the comment as GST-inclusive; no GST split.
6. **Owner withdrawals** are recognised, excluded from the row, and mentioned in a notice (count and date only).
7. **Unknown lines (A7, G12):** arrears, part payments, advance rent or any other line type refuse the statement naming the label text.
8. **Fingerprint:** statement number plus period end plus You-Received figure.
9. Tests, docs, `CLAUDE.md`, ADR 0021, rules item (next free number): "Rental income: treatment of Australian rental income of a German resident, and of GST-inclusive fees, is not decided (unverified)".

### Acceptance criteria
- A synthetic statement with two rent lines (one wrapped over two lines), a management fee, a `*` repair cost and an owner withdrawal produces one row with hand-worked gross, expenses and net; the withdrawal is not staged and is noticed.
- A synthetic statement whose lines do not satisfy In - Out = Received is refused with a reason naming the block, not the figures.
- A synthetic statement with a "Total" line that excludes a sundry fee stages the correct expenses (A5).
- A synthetic two-month statement and a short final period get the printed income period (A6).
- A synthetic statement with an arrears line is refused naming the label (A7).
- No payer or agent name is present in any tracked file (test scans the reader module and fixtures for the invented names only; a repository scan confirms no sample text).
- `local/samples/Hodges` through the optional local test: every file staged, none refused; rows equal the owner-checked expected file.
- Earlier-phase tests still pass.

### Stop and report

---

## Phase 22: MECU statements (AUD interest and withholding)

Goal: open the MECU PDFs reliably and stage one payment per interest credit, with the overseas withholding tax shown in its memo line.

Corner cases covered: G1, G4, G5, G6, G7, G9, G11, G12, M1 to M10.

### Questions for the owner
- **Q22.1 Opening the files: answered by the owner (2026-10-20).** pypdf cannot open any of the 24 MECU files (the cross-reference table is one entry longer than its header declares). A new dependency is approved if it causes no conflict with existing work. Suggested choice, to be verified by you: `pikepdf` (MPL-2.0; wheels bundle qpdf, which rebuilds damaged cross-reference tables), used only to normalise the bytes in memory before pypdf extracts text. Evaluate it first against the conditions in rule 11; if it does not work or conflicts, choose another candidate or fall back to the pure-Python repair, and report the choice and the reasons. Do not use a library with a copyleft licence stricter than the existing stack without telling the owner (for example PyMuPDF is AGPL: not acceptable without asking).
- **Q22.2 Term deposits: answered.** Stage term-deposit interest from the term-deposit section only, with category **Interest**; a later credit into a savings account that matches a term-deposit payment is a transfer, not income (M5).
- **Q22.3 Bonus interest.** Separate row per line (default), or merge Interest Credit and Bonus Interest of the same date.
- Payment date: the **Effective** date (default) or the Posted date; put the other in the comment.
- Fees: none expected. Any fee line refuses the statement naming its label unless you give a sample (default).

### Tasks
1. **Verify** exactly what fails (xref table, `strict` flag, pypdf version) with the synthetic test described below, not with real files in tracked code; report the cause in one paragraph.
2. **Tolerant opening.** Per Q22.1: first prove, with the approved dependency in a scratch environment, that it opens the damaged cross-reference table (use a synthetic PDF; the real files only for the optional local test). Then add it to the project's dependency files with a pinned version, and in `pdf_text.py` apply it in memory only when pypdf fails to open the file, then hand the normalised bytes to pypdf. Verify that the Containerfile build, the Makefile test target and the existing tests are unaffected and report image size change. If it fails any condition of rule 11, implement the pure-Python repair of the subsection count instead. Tests: a synthetic PDF with a deliberately short subsection header opens; a truly corrupt PDF (garbage xref) is still refused; the normalised bytes are never stored and the original is kept; undamaged files do not go through the dependency at all.
3. **Inspect** the 24 files (default and layout mode): count multi-account statements (M1), statements with term-deposit sections, with memo lines (M4), with the annual Payment Summary (M6), with barcode-only pages (M7), and list name/period mismatches (M8). No figures.
4. **Reader `mecu_account`.** Recognise by structure: an account-statement layout with Effective / Posted / Description / Debit / Credit / Balance columns and a closing balance per account. Do not anchor on the name, address or branch text.
5. **Dates (M2).** Derive the year from the statement period; handle the December-January wrap. A date outside the statement period refuses the statement.
6. **Per-account arithmetic (M9).** For every account section: previous balance + credits - debits = balance. Failure refuses.
7. **Interest rows.** One row per "Interest Credit" (and per "Bonus Interest" per Q22.3) in interest-bearing accounts. Gross = the "Gross Interest" memo figure when present, otherwise the credit; withholding = the "Overseas Withholding Tax" memo figure (M4); net = the credit; assert gross - withholding = net else refuse. Currency AUD, category Interest, frequency monthly (or the interval printed), organisation `MECU` from the fixed dictionary, comment names the kind (interest, bonus interest, term-deposit interest) and the account type only (no account number).
8. **Term deposits (M5).** Per Q22.2. Test the double-appearance case.
9. **Annual summary (M6).** If the June statement has the Payment Summary for Withholding Tax, compare its totals with the staged rows of the financial year; mismatch is a warning, never a refusal.
10. **Barcode pages (M7).** A page with no text layer does not refuse the file when other pages carry text.
11. **Unknown lines (G12):** any booking text that is not interest, transfer, fee-free payment or deposit refuses naming the text.
12. **Fingerprint (G7):** statement number plus period end plus the sum of closing balances. Periods are taken from content (M8); file names are never trusted.
13. Tests, docs, `CLAUDE.md`, ADR 0022, rules item: "MECU interest: tax treatment of Australian-source interest and Australian withholding tax for a German resident is not decided (unverified)".

### Acceptance criteria
- A synthetic PDF with the cross-reference defect opens (per Q22.1); a synthetic truly corrupt PDF is refused; stored original bytes equal the uploaded bytes; the dependency is pinned and the container build and all tests pass with it.
- A synthetic multi-account statement stages interest only from interest-bearing sections, with gross, withholding and net from the memo lines, and the check gross - withholding = net holds.
- A synthetic statement with a memo-line mismatch is refused (M4).
- Dates without a year resolve correctly across a year boundary (M2); an out-of-period date is refused.
- A synthetic term deposit maturing in one statement and a monthly term deposit paying into savings stage the interest once (M5).
- A synthetic statement with a barcode-only page stages normally (M7).
- A swapped file name does not change the period read (M8).
- A synthetic June statement whose annual summary disagrees by one unit produces a warning and still stages (M6).
- `local/samples/MECU` through the optional local test: 24 files opened, none refused, expected rows equal the owner-checked file; the report lists, without figures, the rows that collide with rows already in the database.
- Earlier-phase tests still pass.

### Stop and report

---

## Phase 23: Ord Minnett Cash Management Trust (AUD)

Goal: read the CMT statements (monthly and financial-year), stage interest with its withholding, and report stock-sale evidence without importing it.

Corner cases covered: G4, G5, G6, G7, G9, G11, G12, O1 to O10.

### Questions for the owner
- **Q23.1 Withholding pairing: answered.** The withholding debit appears as a separate whole-dollar line, usually on another date than the interest. Pair it with the interest of the same quarter and put the debit date in the comment.
- **Q23.2 Property-sale credit.** Not income; shown as a notice (date only). Confirm (default yes).
- **Q23.3 Stock sales: answered, out of scope.** Sales are recognised only as a proceeds transfer and reported as a notice (date only); never imported. Do not build any sales import.
- Payment date: credit date (default).

### Tasks
1. **Verify** how sales and securities rows are handled by the existing Phase 14 and 18/19 code so the CMT does not duplicate dividends (O5); report what you found.
2. **Inspect** the 24 files plus the valuation snapshot: monthly vs financial-year layout (O9), which files carry interest, which carry withholding, which carry the taxation summary (O4). No figures.
3. **Reader `ordminnett_cmt`.** Recognise by structure: a CMT statement with a Date / Description / Amount / Balance table and a running balance. Do not anchor on the broker name or address. The holdings snapshot gets a separate small recogniser `ordminnett_valuation` returning nothing to import (O8).
4. **Direction by balance (O1).** For every line, derive credit/debit from the change in the running balance; assert opening + credits - debits = closing. A line whose direction cannot be proven refuses the statement.
5. **Classification.** By booking text: interest credit, overseas withholding tax debit, dividend credit (not staged, O5), tax refund, BPAY, transfer, scheme consideration, property sale, stock-sale proceeds. Anything else refuses naming the text (G12).
6. **Rows.** Interest credit becomes a row: gross = credit; withholding = the paired withholding debit (O2, Q23.1), net = gross - withholding; AUD, Interest, quarterly, organisation `Ord Minnett` from the fixed dictionary; income period = the quarter from the statement text.
7. **Cross-statement dedupe (O3).** After all readers run, drop exact duplicates across overlapping statements (same date, kind, amount), first seen wins, list the repeats in the batch warnings. FY-only quarters stage from the FY file. If a withholding has no interest partner in the batch, warn (O10); do not stage it alone.
8. **Taxation summary (O4).** Cross-check totals per year; mismatch is a warning.
9. **Notices.** Property sale (date only), stock-sale proceeds (date only), scheme consideration (date only). No names, no amounts.
10. **Fingerprint (G7):** period plus statement number plus closing balance.
11. Tests, docs, `CLAUDE.md`, ADR 0023, rules item: "Ord Minnett interest and overseas withholding tax: treatment is not decided (unverified); sales are not imported".

### Acceptance criteria
- A synthetic statement with an interest credit and a later whole-dollar withholding debit stages one row with hand-worked gross, withholding and net, pairing by quarter (O2).
- A synthetic financial-year statement that repeats two months of a monthly statement stages each row once and lists the repeats (O3).
- A synthetic statement where a line's direction cannot be proven from the balance is refused (O1).
- A synthetic CMT dividend credit is not staged (O5); a sale-proceeds transfer and a property credit produce notices with no names or amounts (O6, O7).
- A synthetic statement with an unknown booking text is refused naming it (G12).
- A synthetic holdings snapshot returns nothing to import (O8).
- An orphan withholding produces a warning and no row (O10).
- `local/samples/Ords` through the optional local test: all files staged, nothing-to-import or noticed, none refused; expected rows equal the owner-checked file; collisions with existing database rows reported without figures.
- Earlier-phase tests still pass.

### Stop and report

---

## Phase 24: Close-out for the Australian statements

Goal: check the three readers together and against what is already in the database, then finish the documentation.

### Questions for the owner
- Collisions with rows already entered by hand or from CSV: report only (default). Any deletion is a separate decision by you.

### Tasks
1. Run `tools/pdf_inventory.py` over the three folders; report counts of staged / nothing to import / noticed / refused, name-vs-period mismatches, period gaps, and overlaps. No figures.
2. Local-only report (not committed, no amounts in output): for each of the three organisations, how many staged rows would collide with existing database rows under the duplicate rule, and how many staged rows have no counterpart in the existing rows (for example term-deposit interest missing from the hand-made CSV).
3. Confirm that the Phase 14 to 19 samples still give identical rows.
4. Update `docs/imports.md` (Australian statements: fingerprints, notices, tolerant opening, dedupe), `docs/architecture.md`, `CLAUDE.md`, `docs/rules/README.md` (all open items from Phases 21 to 23 numbered and consolidated), and an ADR 0024 that records the decisions made in Phases 21 to 23.
5. Remove nothing from earlier docs.

### Acceptance criteria
- The inventory over each folder shows no refused file and the expected counts (the owner checks).
- The collision report exists locally and contains no amounts or names.
- All earlier tests pass; docs list every open rules item.

### Stop and report
