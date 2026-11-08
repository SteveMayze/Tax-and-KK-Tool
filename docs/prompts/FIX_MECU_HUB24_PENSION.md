# Fix: HUB24 pension credits on the MECU statements are not captured

Branch: `fix/mecu-hub24-pension` (from `main`; `main` is checked out and clean apart from this file). Follow CLAUDE.md: scope first,
list assumptions, decisions are settled in section 3 (do not re-ask), small commits, real test results, end-of-phase report, STOP for the
owner's "go" before merging.

FIRST ACTIONS (before any code):
1. `git checkout -b fix/mecu-hub24-pension` (this prompt file is untracked on `main` and comes along).
2. Commit this prompt file alone as the first commit, e.g. `Docs: prompt for the MECU HUB24 pension fix`. Do not mix it with code.

## 1. Findings (verified by reading the code and the owner's samples in `local/samples/MECU`; re-check, do not assume)
The owner's pension is paid by direct credit into the "S1 Everyday Access" account and appears as
`Direct Credit Hub24 Custodial - <reference number>` (the reference may vary; do NOT hard-code or log it, and match on the
words, not the number). The first one is a back payment in the June 2026 statement (`2606-498.pdf`, posted 10 Jun 2026); regular credits follow on the
10th of July, August and September 2026.

Why nothing is staged: in `core/services/mecu_account.py` the loop over booking rows classifies a row by its first words.
`NOT_INCOME` contains `'Direct Credit'`, so every Direct Credit (salary-like credits, the cleaning-job credits, and this
pension) is balance-proved and then silently skipped with `continue`. There is no refusal and no notice, so the importer
reports the statement as fine. The row is read correctly (direction credit, running balance proved); it is only never
turned into a `StatementRow`. Also: `docs/imports.md`, ADR 0022 and CLAUDE.md all say MECU yields interest only.

Do not confuse with the OUTGOING rows in `2407` to `2510`: `BPAY Payment To Hub24 <biller code>` is a monthly debit TO HUB24
(a contribution). It is not income, must stay in `NOT_INCOME` (`BPAY Payment`), and a regression test must prove it is not
staged. Re-run a text search over all 27 files to confirm the only incoming HUB24 lines are the four credits of June to September 2026.

The sample folder now runs 2407 to 2609 (October 2026 is not yet available). The owner's app database may already hold some of
these PDFs as imported batches (2606 certainly), but holds no hand-entered pension rows (owner confirmed).

## 2. What the statement does and does not tell us
The bank line shows ONLY the net amount credited. It shows no gross, no tax withheld, no payment period and no frequency.
The June credit is a back payment (several periods paid at once, a one-off); the later ones are regular. Nothing may be
invented (CLAUDE.md financial principles): gross = net + withholding + expenses (ADR 0010).

## 3. Owner decisions (answered 2026-11-08; the decision gate is closed, do not ask again)
1. **Shape: option A.** Stage each HUB24 credit as the NET amount: gross = net = the credit, withholding 0, expenses 0. The owner
   confirms the net value is what is wanted: the costs and tax belong to the superannuation fund and are not attributable to any
   single payment, so they are NOT estimated or split per payment. Comment (translated) states "net credit as shown on the bank
   statement; fund costs and tax are not attributed to this payment (PDF import)". The existing review edit step stays available.
2. **Frequency:** the first credit (June 2026, a back payment) is `one-off`. The regular credits after it (10 Jul, 10 Aug, 10 Sep
   2026 in the samples) are `monthly`. The reader cannot know which credit is the back payment: implement it as "the EARLIEST
   HUB24 credit ever seen is one-off" ONLY if it can be done without hidden state; otherwise stage all as `monthly` and have
   the review page make the June row easy to change to `one-off`, and tell the owner which you did and why. Do not store a date
   or amount in code for this.
3. **Organisation `HUB24`, category `Pension`, payment date = Effective date, currency AUD.** Country AU is proposed by the
   preview as for any AUD organisation. Check whether a HUB24 organisation already exists and reuse it.
4. **Rules register:** yes, add an open item to `docs/rules/README.md` (status unverified, nothing implemented): how an
   Australian superannuation pension, paid net of the fund's costs and tax, is treated for SBK and for the German tax return.
5. **Samples:** the owner has now added statements up to September 2026 (`2607-499.pdf` to `2609-501.pdf`; October is not yet
   available). The folder holds 27 files and four incoming HUB24 credits (June one-off, July to September monthly), all in the
   S1 Everyday Access account. Use all 27 files for the regression expectations (expect four Pension rows in total).
6. All other points of the earlier draft are approved as written. Hand-entered pension rows: the owner confirms NONE exist in the
   database, so no collisions are expected. Still run `tools/collision_report.py` (read-only, counts only) as a check and report
   the result; existing rows are never modified.

## 4. Tasks (after section 3 is answered)
1. **Rule data, not code, for the payer.** Recognise an incoming booking as pension by its words, case-insensitive,
   normalised spaces: description starts with `Direct Credit` AND contains `Hub24`. Put the match words in one clearly named
   constant in `mecu_account.py` (e.g. `PENSION_PAYERS`), not scattered. No reference number or account number in code, tests
   or logs. Keep every other `Direct Credit` skipped exactly as today.
2. **Direction:** the existing running-balance proof stays. A HUB24 line that is a DEBIT (it cannot be, but a reversal could be)
   refuses the statement naming its first words, like an interest debit does today. Add the credit to the proved balance
   as usual.
3. **Row:** one `StatementRow` per HUB24 credit with the shape chosen in section 3. Evidence (page and source line) for
   `payment_date` and `net_amount`/`gross_amount`, as the interest rows do. Comment text via `gettext` (add German
   translation, rebuild `.mo`, per CLAUDE.md). Set `period` and `fingerprint` unchanged. Keep `Bonus Interest`,
   `Interest Credit` and the term-deposit logic and the M4/M5/M6 checks intact; `settle()` annual-summary cross-check must
   still compare INTEREST ONLY, so exclude pension rows from its sums (category `Pension`) and add a test for that.
4. **Statements wrapped over two lines.** A real HUB24 line can wrap (the description is long). Make sure `_entries` joins it
   (it does for up to 4 lines); add a synthetic test with a wrapped description.
5. **Tests with SYNTHETIC text only** (no real name, reference, account number or amount in tracked files; the existing
   tests use `EXAMPLE EMPLOYER` and invented figures, worked out by hand in comments):
   - a Direct Credit from an invented `Hub24 Custodial - 0000000000` stages one Pension row with the agreed shape;
   - an invented `BPAY Payment To Hub24 00000` debit stages nothing and the balance still closes;
   - a non-HUB24 `Direct Credit EXAMPLE EMPLOYER` still stages nothing;
   - a HUB24-like line with a running balance that does not add up still refuses;
   - interest and pension in the same statement: both staged, interest summary cross-check unaffected;
   - the review/commit path creates a `Payment` with category `Pension` (extend the existing MECU commit test).
   Extend `core/test_sample_regression.py` so that the local samples assert exactly four `Pension` rows (2606 to 2609, one each), printing no
   amounts, and the other 23 files assert none.
6. **Going forward.** No schema change is needed. Document in `docs/imports.md` (MECU section and the Australian table) that
   MECU now yields Interest rows AND Pension rows from a HUB24 direct credit, that the amount is the net credit only, and how
   to correct gross/withholding in the review step. Update the MECU line in CLAUDE.md "Imports" and the docstring of
   `mecu_account.py` ("interest only" statements). Add a short ADR (next free number after 0043) recording the decisions of
   section 3, and an open item in `docs/rules/README.md` (decision 4).
7. **Already-loaded PDFs (re-import, nothing automatic).** The app never changes existing payments. Do this and report:
   a. Run the inventory/regression over `local/samples/MECU` and report the staged counts per reader (expect 27 interest rows
      as before, plus four HUB24 pension rows). Nothing is written to the database.
   b. Check whether re-uploading an already imported statement such as `2606-498.pdf` is blocked by "same reader and fingerprint is one statement" or by a stored
      batch. The fingerprint is statement number, period end and closing balances, which this change does NOT alter, so find
      out from `pdf_imports.py` / `imports.py` whether a previously COMMITTED batch blocks a new upload of the same file or
      whether the row-level duplicate detection (same date, organisation, category, amount) handles it. State the answer
      from the code; if the old batch blocks it, propose the smallest fix (for example let the owner re-import and rely on
      row-level duplicates) and ask before implementing.
   c. Tell the owner the exact steps: upload the already-loaded MECU statements again (the June to September 2026 ones hold a
      HUB24 credit), review the four new Pension rows, correct gross/withholding if known, commit. Existing interest rows
      are flagged duplicates by the review and skipped; the owner's hand-entered rows are never modified.
   d. Extend `tools/collision_report.py` (read-only, counts only) to report how staged Pension rows relate to the payments
      already in the database (exact match, near match, none), as was done for rental and joint rent. Never print names or amounts.
8. Run `python manage.py test` and `python manage.py makemessages`/`compilemessages` as CLAUDE.md requires; report the real
   results and the staged/refused counts over the 24 MECU samples.
9. Commit in small steps on `fix/mecu-hub24-pension` (code + tests, docs/ADR, translations separately). Review staged files
   for personal data before each commit (no account numbers, reference numbers, names or real amounts in anything tracked).
   Final report per CLAUDE.md, then STOP for the owner's "go" before any merge into `main`.

## 5. Out of scope
Other Direct Credits (employment-like or the cleaning job): separate decision, they stay skipped. HUB24 BPAY debits.
Tax or SBK treatment of the pension (open rules item only). Changing the PDF opening repair or the other readers.
