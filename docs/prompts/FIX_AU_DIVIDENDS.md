# Fix: Australian dividend advices that are refused, and what to do with the franking figures

Branch: `fix/au-dividend-statements` (from `main`). Follow CLAUDE.md: scope first, list assumptions, STOP at the decision
gate in section 3, small commits, real test results, end-of-phase report.

## 1. Findings (already verified on the owner's samples in `local/samples/Securities`; re-check, do not assume)
76 PDFs were run through `statement_readers.read_statement`. 62 stage one row. Refused:

| Files | Reason shown | Cause |
|---|---|---|
| ANN x4 (2025-03-06, 2025-09-18, 2026-03-13, 2026-09-17) | "The amount paid (net payment) could not be found." | The layout prints `Net Payment (AUD$) $122.01` and, below, `Amount Deposited` / `AUD $122.01`. `NET_PATTERNS` in `core/services/dividend_statements.py` allow at most 3 non-word characters between "Net Payment" and the currency, so ` (` fits but `(AUD$) ` does not; the label-first rule needs a line that STARTS with `$`/`AUD`+digits, and `AUD $122.01` has a space-dollar. Not a regression: this layout never matched since Phase 14. |
| MGR x4 (2025-02-27, 2025-08-28, 2026-02-26, 2026-08-31) | "The payment date could not be found with certainty." | The date is printed as `DATE PAID: 27 February 2025`. `_payment_date` knows "payment date", "date payable", "payable date", "date credited", "date:" but not "date paid". The page also holds `TOTAL PAYMENT` / `LESS RESIDENT WITHHOLDING TAX` / `NET PAYMENT`. |
| AGL 2025_09_25 and 2025_09_25a | same | A "DRP Residual Cash Balance" payout (A$2.21). The label-first branch finds TWO "Payment Date" labels (`Payment Date` and `Payment Date:`) so `labels.count('payment') == 1` fails. The statement itself says the amount was already included in taxable income when the shares were allotted. |
| CSR 2024_07_09 | scheme consideration | Refused on purpose (sale, not a dividend). Leave it. |
| NAB x3 | bonus share plan | Refused on purpose (shares allotted, no cash). Leave it unless the owner decides otherwise. |

A scratch check (nothing committed) showed that one added net pattern,
`(?i)\bnet\s+payment\s*\(\s*A?U?D?\s*\$?\s*\)\s*(?:AUD|A\$|AU\$|\$)\s?(\d[\d,]*\.\d{2})`, makes all four ANN files stage
(gross = net = 122.01 / 149.77 / 131.88 / 202.58, withholding 0.00), and that `(?i)\bdate\s+paid\s*:?\s*` + `DATE`
reads the MGR date. Re-derive both properly with tests.

## 2. Franked / unfranked / franking credit: what is read today
The module docstring records a decision (2026-10-19): franking details are NOT read. Gross = the largest amount of the
holding table (the total dividend = franked + unfranked), net = the amount paid, withholding = gross - net. On the
samples that gives withholding 0.00 for every file, which matches the printed "Australian tax deducted / withholding tax"
of $0.00. Checked by hand: ANN franked $0.00 + unfranked $122.01 = total $122.01, franking credit $0.00; AMP franked
$4.08 + unfranked $16.30 = $20.38 (the gross read), franking credit $1.75 (not read); WOW 100% franked: total $149.76,
franking credit $64.18 (not read).

## 3. DECISION GATE: ask the owner before coding anything about the franking credit
The owner suggests treating the franking credit as the withholding tax. Do not implement that without an answer, because:
* The franking credit is not deducted from the cash paid: the amount deposited already equals franked + unfranked. With
  `gross = net + withholding + expenses` (ADR 0010), AMP cannot be gross 20.38, withholding 1.75 and net 20.38. It would
  need a grossed-up gross of 22.13 that is printed nowhere (20.38 + 1.75), changing every income figure in the reports.
* Whether a German resident can use an Australian franking credit at all is a tax-rule question. CLAUDE.md: never
  implement an unverified rule; rules live in `docs/rules/` with a verification status.
Offer these options and wait:
 A. Keep ignoring franking (status quo; only fix the refusals).
 B. Read franked amount, unfranked amount, franking percentage and franking credit as INFORMATION only: shown in the
    review (provenance) and written to the comment, with NO effect on gross, net or withholding; reconcile
    franked + unfranked == total or refuse; credit == 0 when 0% franked.
 C. Gross-up with the credit as withholding: only after the owner supplies a verified rule (adviser / Steuerberater)
    recorded in `docs/rules/`, then an ADR superseding the 2026-10-19 decision.
Recommendation: B now, C only with a verified rule.

## 4. Tasks (after section 3 is answered)
1. Fix the ANN net-amount reading and add `date paid` to the inline date patterns. Keep the "several different amounts /
   dates are ambiguous" refusals and the gross/net/withholding arithmetic checks intact.
2. AGL DRP residual payout: first ask the owner whether it is income (the statement says it was already taxed when the
   shares were allotted). If yes, allow repeated identical "Payment Date" labels (same label twice is one date); if no,
   recognise it and report it as "recognised, not imported" with a notice rather than "not recognised".
3. Implement the option chosen in section 3 (A needs nothing).
4. Tests with SYNTHETIC text for each layout (no real names, numbers or amounts in tracked files): the ANN bracketed
   layout, MGR `DATE PAID`, AGL duplicate labels, a 0% / 20% / 100% franked layout for option B. Extend
   `core/test_sample_regression.py` so the local samples assert that every Securities file is either staged or refused for
   one of the three intended reasons (scheme consideration, bonus share plan, owner-decided), printing no amounts.
5. Run `python manage.py test`. Re-run all 76 samples and report the staged/refused counts (expect 62 -> 70, or 72
   with the AGL files). Update docs/imports.md and the docstring/CLAUDE.md line about franking if the decision changes;
   add an ADR if section 3 is B or C. Update German translations if messages change.
6. Report and STOP for the owner's "go" before merging.
