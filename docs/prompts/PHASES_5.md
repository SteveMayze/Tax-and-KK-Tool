# PHASES_5.md: Tax and Healthcare Tool, Phases 25 to 27 (RVB joint account: rent received directly from the tenant, EUR)

Save this file as `docs/prompts/PHASES_5.md`. This file is self-contained: the review findings and corner-case ids (J1 to J22) are in section "Findings" below; ids G1 to G12 are in `docs/prompts/PDF_PARSERS_PLAN.md`.
**Do not edit or overwrite `PHASES.md`, `PHASES_2.md`, `PHASES_3.md` or `PHASES_4.md`.** If you find an error in them, record it in your end-of-phase report. Phases 1 to 24 are implemented (Phase 20 deliberately not).

## Findings (from a read-only review of `local/samples/RVB-joint`, 21 statements, December 2024 to September 2026)

Structure only: no amounts, names, addresses or account numbers appear here, and none may appear in anything you write.

1. **Same bank and layout as the Phase 17 reader, but a different account and a different job.** The files are current-account statements ("Kontoauszug", Bu-Tag / Wert / Vorgang, `alter Kontostand` / `neuer Kontostand`, German amounts with H/S suffix, `PN:` posting code per booking, `Blatt n von m` pages with `Übertrag` lines). The account number differs from the Phase 17 account (the first digits differ). The existing reader `rvb_account` recognises by structure only (an `alter` and a `neuer` balance row), so it **already claims these files** and would silently return "nothing to import" (J1).
2. **It is the household joint account, not a rental-only account.** Most bookings are not rental: standing orders between the owners, fund purchases and sales, insurance, telephone, energy, tax-office refunds, club and tax-adviser fees, card payments, cash deposits, bank charges and overdraft interest. Only a small subset concerns the rented property (J2).
3. **Rent arrives straight from the tenant**, as `Gutschrift`, `Echtzeit-Gutschrift` or `Dauerauftrag` credits (posting code 931). The payer is usually the tenant, but sometimes a relative pays and the tenant is named only in the purpose text; spelling varies by case, umlauts (ü / ue / u) and spacing (J3, J4, J5).
4. **Irregular rent credits:** two rent credits in one statement (next month paid early), months without any rent credit, a "rest" payment after a rent increase, and a rent that changed twice (J6, J7).
5. **Tenancy changed in September 2026.** The new tenant's first credit combines a **deposit (Kaution) and the first month's rent in one credit**, with the two figures written in the purpose text; the second credit carries only "Miete" (J8).
6. **Other tenant credits:** annual service-charge back-payments (purpose names "Nebenkosten…"), and a small credit from the property manager for the service-charge settlement of a year, which is a cost matter and is out of scope (J9).
7. **(Out of scope by owner decision, 2026-10-20; kept here for the later extension.) Rental costs are debits to the property manager (monthly house-fee "Wohngeld" direct debits, amount changing over the years), to the city of the property (annual property charges, "GRDABG" in the cash reference), and to a landlords' association (annual fee).** The property manager's printed name **changes during the period** (a different legal name and abbreviation in later statements). The city of the owners' own home also debits similar-looking property charges: those are not rental costs. Costs are NOT handled in Phases 25 to 27 (J10, J11).
8. **Look-alike words:** car-rental debits ("Mietwagen") contain "Miet" (J12).
9. Statements chain without gaps (each `alter` date and balance equals the previous `neuer`); the first one starts 30.12.2024; file names carry a date that is **not** the statement period (e.g. a date a day or a month after the period end). Use the content (J14).
10. Boilerplate on the last page mentions "Rechnungsabschluss" in every statement; do not use it as a signal. Bank charges ("Entgelte", "Abschluss") and overdraft interest ("Sollzins") appear and are not income or rental cost (J18).
11. Letter-spacing and stray characters occur in headers ("S teven", "B itte"), not in booking lines (G8 still applies).
12. The owner's other project filtered by name patterns (tenant names, property manager, city, a landlords' association). This phase turns that filter into **configurable matching rules stored in the app**, never in code (J15).

### Corner cases
- **J1 Routing conflict.** Two readers recognise the same structure. Exactly one reader may claim a file (Phase 15 rule): the joint-account reader claims files of the configured joint account number; `rvb_account` must step aside for that account and keep behaving exactly as before for all others.
- **J2 Household account.** Unmatched lines are normal and ignored. The usual "unknown line type refuses the statement" rule (rule 6 of earlier files) applies only to **grammar and arithmetic**: every booking must parse (date, text, PN, amount, direction), page-carry lines must agree, and `alter + credits - debits = neuer`. A line that does not parse refuses the statement; a line that parses but matches no rule is simply not rental.
- **J3 Payer is not always the tenant.** Match the tenant by payer name **or** purpose text.
- **J4 Name normalisation.** Matching runs on normalised text: case-folded, German umlauts and ß folded (ä→ae, ö→oe, ü→ue, ß→ss) and also with diacritics stripped, hyphens and runs of spaces collapsed, digit runs masked only for display.
- **J5 Booking types.** Rent credits may be `Gutschrift`, `Echtzeit-Gutschrift` or a credit `Dauerauftrag`; all are credits (direction H). A debit never makes rental income.
- **J6 Several rent credits in a month and none in another.** One row per credit; never invent a missing month; never merge two credits.
- **J7 Rent changes / part payments.** Amounts are never assumed. A "rest" or part payment is its own row.
- **J8 Deposit combined with rent.** If the purpose text states two figures labelled as deposit (Kaution) and rent (Miete) and their sum equals the credit, stage the rent part only and add a notice for the deposit part (not income, not staged). If the labels are not both present or the sum does not match, **do not stage** that credit and show it as an unresolved credit the owner must handle (refuse-rather-than-guess applied to one booking: the statement is staged without it and the notice says so; the statement is not refused).
- **J9 Service-charge settlements.** Back-payment from the tenant: stage as rental income of kind "service-charge settlement" (own row, comment names the kind). A credit from the property manager for a year's settlement is a cost matter: out of scope, ignored (not income, not staged, no notice).
- **J10 Rental costs: OUT OF SCOPE (owner decision).** Property-manager house-fee debits, municipal property charges and association fees are not read, matched, staged, summarised or noticed in these phases; they are left for a later extension (income and expenses for the tax return). The reader ignores all debits except for the arithmetic check.
- **J11 Look-alikes.** Tenant-rent rules apply to credits only; a rule is a pattern on the counterparty line and/or the purpose, nothing broader. The conflict check and tests prove one booking cannot match two rules of different kinds.
- **J12 Generic words.** A credit whose purpose contains the word "Miete" (word boundary) that matches no tenant rule is not staged but listed as "possible rent not matched" (so a new tenant paying under another name is noticed). Debits such as car rental are not credits and are never listed.
- **J13 Owner-to-owner and owner-to-account transfers**, fund purchases, tax refunds, cash deposits, merchant refunds, small gifts: ignored.
- **J14 Dates.** Bu-Tag and Wert have no year: derive from the statement's `alter`/`neuer` dates (statements may span a year end, and the first statement starts at the end of the previous year). The period comes from the content, not the file name. Payment date = booking date (Bu-Tag), consistent with the other RVB reader.
- **J15 Rules are data, not code.** No tenant, manager, city or association names in code, tests, docs, ADRs or commit messages. Synthetic tests use invented names ("EXAMPLE TENANT", "EXAMPLE PROPERTY MANAGER", "EXAMPLE CITY", "EXAMPLE LANDLORDS CLUB").
- **J16 Multi-page layout.** `Übertrag auf Blatt` / `Übertrag von Blatt` lines are not bookings; they must agree with the running balance.
- **J17 Letter-spacing (G8)** in headers must not prevent recognition or number reading.
- **J18 Charges and overdraft interest** are ignored (not income, not rental cost).
- **J19 Joint ownership.** The credit is recorded in full (owner decision below); the category marks it as joint; the app does not split it and does not decide how the share is treated for tax or SBK.
- **J20 Cash basis.** The payment date is the date the money arrived. A rent paid for the following month at month end is recorded on its arrival date. The app does not decide which tax year such a payment belongs to.
- **J21 Identical credits on one day** are legitimate; the existing duplicate rule will flag them in review; nothing is deduplicated inside a statement.
- **J22 Re-issues and overlaps.** Same statement number and period uploaded twice stages once (fingerprint, Phase 15).

## Standing rules for every phase below

1. Read first: `CLAUDE.md`, all `docs/prompts/PHASES*.md`, `docs/prompts/PDF_PARSERS_PLAN*.md`, `docs/imports.md`, ADR 0014, 0015, 0017, 0021, and the code: `core/services/rvb_account.py`, `hodges_rental.py`, `statement_readers.py`, `statement_types.py`, `amounts.py`, `organisations.py`, `pdf_text.py`, `pdf_imports.py`, `pdf_inventory.py`, `tools/collision_report.py`, `core/models.py` (Organisation, IncomeCategory, Payment), settings handling, and the tests for rvb and hodges. Everything in `CLAUDE.md` still applies (Decimal only, keep originals, state the basis of every figure, never guess a legal or SBK rule, no real network in tests, synthetic test data only).
2. Work on **one phase at a time**. At the end: stop, give the end-of-phase report (what was done, commits, tests with real results, deviations, open questions, anything not verified) and wait for "go".
3. **Ask first.** Ask each phase's "Questions for the owner" in your first reply with what you found when you verified the current state. If unanswered, use the stated default, say so at the top of your work, and continue.
4. **Verify the current state.** This file was written from a read-only review of the samples and the repository log, not from running the code. Where it says "verify", read the code and say what you found; if it differs, say so and adapt.
5. **Privacy (highest priority).** `local/samples/` holds the owner's real statements. Reports, commit messages, docs, ADRs, test names, fixtures and logs must contain **no amounts, names, addresses, account numbers, IBANs, tenant names, property or street names taken from the samples or from the owner's messages**. Describe structure, label text and counts only. Expected figures for the real samples go only into git-ignored `local/samples/expected/`. Matching rules and the joint account number live in the database / environment settings, never in tracked files. Before every commit, review the staged files for anything copied from a sample.
6. **Refuse rather than guess.** A statement whose lines do not parse, whose page carries or running balance do not reconcile, or that cannot be read with certainty is refused with a specific reason (no document text) and stages nothing. Per-booking uncertainty (J8, J12) never refuses the statement; the booking is left out and a notice says so. Nothing is skipped silently. Outcomes: staged, nothing to import, recognised and not imported (notice).
7. **Acceptance criteria** are checkable statements, each needing a test or a demonstrated command. Report each as met, not met, or not verifiable here, with evidence. Every corner-case id listed in a phase gets a test named after it.
8. At least one test runs the real chain: PDF bytes, `pdf_text`, reader, `pdf_imports` staging, review, commit. Synthetic PDFs are generated in the test suite (`make_pdf`); nothing from `local/samples` is committed.
9. All earlier readers produce exactly the same rows as before; their tests stay green and unchanged. In particular the Phase 17 sample behaviour for the other RVB account is unchanged.
10. After the owner's decisions, update `CLAUDE.md` (Imports), `docs/imports.md`, `docs/rules/README.md` (open questions), and add an ADR `docs/decisions/00NN-...md` with NN = the phase number. Never delete an old ADR.
11. No new dependency. Never send a document to an external service.
12. Nothing here is a tax calculation or an SBK assessment. The importer records what a statement says and where. It never decides how joint rental income is shared, taxed, or counted for SBK. Category mappings (SBK and tax) belong to the owner; do not set them.
13. Deployment is untouched (no change under `infra/`, the Containerfile or the Makefile except a documented test target).

---

## Phase 25: Routing and matching rules for the joint account

Goal: the app can recognise the joint account's statements as their own kind, and the owner can define, in the app, what counts as rent, without any name in code.

Corner cases covered: J1, J4, J11, J15, J16, J17.

### Questions for the owner
- **Q25.1 Account identity.** The joint account's account number is given once, in an environment setting (`DJANGO_JOINT_RENTAL_ACCOUNT`, digits only, never logged or shown unmasked), the same way `RENTAL_ORGANISATION` works. Default yes. The reader recognises a file as joint-account when its printed account number equals the setting.
- **Q25.2 Where rules are edited.** Default: a small model `StatementRule` edited in the existing Django admin / settings area (verify what exists), with a migration and no seed names. Fields: label, kind (`tenant_rent`, `service_charge_settlement`; cost kinds may be added by the later extension, none now), direction (credit only for now), pattern (case-insensitive regular expression on normalised text), match_on (`counterparty`, `purpose`, `either`), organisation (for income kinds: the string to use as Organisation, usually the tenant), valid_from, valid_to (both optional), active. Confirm.
- **Q25.3 Category.** The joint rent goes into a **new category** with the name from a setting (default `Rental (joint)`), created by the owner like any category. The importer never creates or maps it. If the category does not exist the upload explains what to create and stages nothing for the joint reader.

### Tasks
1. **Verify** how `rvb_account.recognises` decides, how the registry enforces "exactly one reader", how settings are read for `RENTAL_ORGANISATION`, how categories and organisations are created, and what admin or settings pages already exist. Report in one paragraph.
2. **Account number reading.** Read the printed account number from the first page (layout mode), compare digit-for-digit with the setting; never store or log it; masked display only (last two digits at most).
3. **Registry exclusivity (J1).** Add the new reader id (`rvb_joint`) and make `rvb_account.recognises` return False for a file whose account number equals the joint setting (and only then). No other behaviour of `rvb_account` changes. The new reader does not claim when the setting is empty.
4. **Model and normalisation (J4, J15).** `StatementRule` with a migration; a pure function `normalise(text)` (case-fold, umlaut and ß folding both ways, diacritics stripped, hyphen and space collapsing); a rule compiler that rejects invalid regular expressions with a clear message and rejects patterns that match the empty string. A test proves "Jürgen Köhler", "JUERGEN KOEHLER" and "Juergen Koehler" normalise to the same string.
5. **Look-alike safety (J11).** A rule preview in the settings area (or a management command `tools/rule_preview.py`): runs the rules over an uploaded or local folder of statements and prints, **without amounts and names**, per rule the number of matching lines and the statements they were in, plus the number of lines matching more than one rule (a conflict; the reader refuses to stage a booking matched by two rules of different kinds).
6. **Skeleton reader `rvb_joint`** with recognition, account check, statement grammar (J16 page carries, J17 letter-spacing) and the arithmetic check, returning "nothing to import" for now. Statement fingerprint: statement number plus year plus closing balance (J22).
7. Tests, docs, `CLAUDE.md`, ADR 0025, rules item "Joint rental income: how the shared rent is treated for the tax return and for SBK is not decided (unverified)".

### Acceptance criteria
- A synthetic joint-account PDF is claimed by `rvb_joint` only; the same layout with another account number is claimed by `rvb_account` only; with the joint setting empty nothing changes for any file (J1).
- Both RVB readers' existing tests pass unchanged.
- Normalisation test (J4) passes for the three spellings; an empty-matching pattern and an invalid pattern are rejected.
- A synthetic statement with a corrupted page carry or a broken running balance is refused with a reason naming the page or row position, not the figures.
- A synthetic statement with letter-spaced headers is recognised (J17).
- No digit run of six or more in rendered pages or logs for the account number (test).
- The conflict check refuses a booking matched by two rules of different kinds.

### Stop and report

---

## Phase 26: Rental rows from the joint account

Goal: stage one payment per rent credit (and per service-charge back-payment), report deposits and unmatched possible rent as notices. Costs are out of scope.

Corner cases covered: J2, J3, J5 to J9, J12 to J14, J16 to J21.

### Questions for the owner
- **Q26.1 Whole or half (answered by the owner's inclination, confirm):** record the **whole** credit; the category (Q25.3) marks it joint, the comment says "joint account, whole amount". The share is a later decision.
- **Q26.2 Costs: answered, out of scope.** A later extension will cover income and expenses for tax purposes. Do not build cost rules, a cost summary or `tools/rental_costs.py`.
- **Q26.3 Income period.** Default: leave `income_period_*` empty and put the purpose snippet's month name in the comment only if the purpose states one unambiguously; never derive a period from the payment date.
- **Q26.4 Service-charge back-payments** as separate rental rows of kind "service-charge settlement" (default yes).
- **Q26.5 Organisation.** The rule's `organisation` string (the tenant), created with country DE if it does not exist (default). A relative paying on behalf of the tenant is attributed to the tenant.

### Tasks
1. **Verify** category flags and how reports treat a category with a blank SBK/tax mapping (flagged and left out per the model docstring); report the exact behaviour for `Rental (joint)` so the owner knows what the summary pages will show.
2. **Booking grammar.** Parse every booking: Bu-Tag, Wert, type text, `PN:` code, amount, H/S, counterparty line, purpose lines (joined, wrapped lines rejoined by position), reference blocks (`EREF`, `MREF`, `IBAN`, `BIC`) stripped for matching and masked for display.
3. **Arithmetic.** Before looking at any rule: `alter + credits - debits = neuer`; page carry lines agree; the sum of parsed bookings equals the movement. Failure refuses the statement (J2, J16).
4. **Rent rows (J3, J5, J6, J7).** A credit matched by a `tenant_rent` rule (within valid_from/valid_to, if set) becomes a row: payment date = Bu-Tag (J14), currency EUR, category from the setting, frequency monthly, organisation per Q26.5, gross = net = the credit, expenses 0, withholding 0, comment "Rent received directly from tenant, joint account, whole amount (PDF import)". Provenance cites page and the sanitised counterparty/purpose line. No amount-based rule (rent may change).
5. **Deposit combined with rent (J8).** Detect labelled figures in the purpose text (German number forms such as `1530` or `1.530,00`, labels Kaution and Miete in either order); stage the rent figure only when the labelled figures sum to the credit; deposit goes to a notice ("deposit part of a credit, not income, not staged"; date only in logs, amount allowed in the on-screen notice); otherwise leave the credit out and add the notice "credit could not be split".
6. **Service-charge settlements (J9).** `service_charge_settlement` credits become rows with the kind in the comment. 
7. **Possible rent not matched (J12).** Credits with the whole word "Miete" in the purpose and no tenant rule: not staged, one notice per credit ("possible rent not matched by any rule").
8. **Debits (J10, J18).** All debits (costs, charges, overdraft interest) are ignored apart from the arithmetic check.
9. **Ignored lines (J13).** Everything else is ignored silently except in the count shown in the upload summary ("N bookings ignored").
10. **Dates (J14)** and period continuity: use the Phase 17 continuity check for the chain of statements of this account (opening balance and date equals previous closing).
11. **Fingerprint (J22)** and duplicates (J21): no deduplication inside a statement.
12. Tests, docs, `CLAUDE.md`, ADR 0026 (record that rental costs are deliberately deferred), rules item "Rental costs of the joint account: deferred by the owner until income and expenses are next summarised for the tax return (unverified)".

### Acceptance criteria
- A synthetic statement with two rent credits (one paid early for next month), a "rest" payment, a relative's payment naming the tenant only in the purpose, a service-charge back-payment and a credit with a look-alike word stages the right number of rows with hand-worked figures; the look-alike produces a notice only.
- A synthetic credit with a labelled deposit and rent whose sum equals the credit stages the rent only; one whose sum does not equal the credit is left out with a notice, and the statement is still staged (J8).
- A synthetic tenant change: two rules with valid_from/valid_to attribute credits to the correct tenant organisation; a credit on a date outside both ranges and without a rule is a possible-rent notice.
- A synthetic statement full of debits (house fee, city charge, club fee, car rental) stages nothing and produces no notice (J10).
- A synthetic statement with car-rental debits and a funds purchase stages nothing and produces no notice (J12, J13).
- A synthetic statement with a booking line that cannot be parsed is refused with a reason naming the page and position (J2).
- Uploading the same synthetic statement twice stages it once.
- All dates without a year resolve correctly across a year end and for the first statement of a series (J14).
- The Phase 17, 21 and 22 to 24 tests still pass unchanged.
- `local/samples/RVB-joint` through an optional local test: all 21 statements staged or nothing-to-import with none refused, the chain has no gaps, and rows equal the owner-checked `local/samples/expected/` file (the owner checks it and enters the rules first).

### Stop and report

---

## Phase 27: Close-out for the joint account

Goal: check against what is already in the database and finish documentation.

### Questions for the owner
- The earlier project's CSV rows for the joint rental (2025) may already be in the database: report collisions only (default); any deletion is the owner's decision.

### Tasks
1. Run the inventory over `local/samples/RVB-joint`: counts of staged / nothing to import / noticed / refused, name-vs-period mismatches, chain gaps. No figures.
2. Extend `tools/collision_report.py` (local only, no amounts or names in its output) to cover the joint rental: staged rows colliding with existing rows under the duplicate rule, near-collisions (same date and organisation, gross differing), and staged rows without a counterpart.
3. Confirm Phase 14 to 24 sample behaviour is unchanged.
4. Update `docs/imports.md` (joint-account statements, rules, deposit split), `docs/architecture.md`, `CLAUDE.md`, `docs/rules/README.md` (consolidate the open items of Phases 25 and 26), and ADR 0027 recording the decisions.
5. Remove nothing from earlier docs.

### Acceptance criteria
- Inventory over the folder shows no refused file, a gapless chain, and the expected counts (the owner checks).
- The collision report exists locally and contains no amounts or names.
- All earlier tests pass; docs list every open rules item.

### Stop and report
