# Claude Code prompt: reconcile the SBK letter of 2026-11-06 with the SBK estimate and the 2025 assessment settings

Read CLAUDE.md, docs/rules/README.md, docs/rules/sbk-contribution-rules.md, ADR 0004 and
core/services/policies/sbk.py first. Follow CLAUDE.md for rules: nothing is coded as a legal rule
unless it is verified and recorded in docs/rules/ with a source; owner data is never guessed.
Work in small steps, run the tests after each step, and ask the owner before changing anything in
local/db.sqlite3 (make a backup with the existing backup command first).

## 0. Git branch (do this before anything else)

All work for this prompt happens on its own branch so the change can be reviewed and reverted as a unit.

1. Run `git status` and `git log --oneline -5`. If there are uncommitted changes, stop and ask the owner.
2. Switch to the main branch and make sure it is current (`git switch main`, `git pull --ff-only` if a remote
   is configured). Then create the branch: `git switch -c fix/sbk-letter-2025-reconciliation`.
   (Earlier fixes used the same pattern, for example `fix/au-dividend-statements`.)
3. Commit after each completed, tested task (A to H) with a message that names the task, for example
   "SBK 2025 parameters: verified figures, policy 1.1". Keep commits small. End each commit message with the
   attribution lines given by the session.
4. Do not commit `local/db.sqlite3`, uploads, exports or anything else the .gitignore excludes, and review
   `git diff --staged` before every commit (CLAUDE.md: no personal data in tracked files; the letter fixture
   must not contain the insurance number or the IBAN).
5. Do not push, open a pull request or merge into main unless the owner asks. At the end, report the branch
   name, the commit list (`git log --oneline main..HEAD`) and the test results, then stop for approval.
6. Any change to the owner's local database (task E settings, task F annual costs) is not part of the branch:
   describe it in the report and make it only after the owner agrees, after a backup.

## 1. What the letter says (facts, copied from the PDF "Beitragsmitteilung", 2026-11-06)

SBK has set the owner's health (KV) and care (PV) contributions **provisionally ("unter Vorbehalt")**
from 2025-11-01, because rental/self-employed income can only be finally assessed from the
2025 income tax assessment (Einkommensteuerbescheid). Deadline to hand it in: 2028-12-31, otherwise
SBK charges the maximum contribution retroactively for 2025.

| Period | Capital income | "Sonstige Einnahmen" | Rental | Base (KV) | KV 14.00 % | Zusatzbeitrag 3.80 % | PV 4.20 % | Monthly total |
|---|---|---|---|---|---|---|---|---|
| 2025-11-01 to 2025-12-31 | 975.52 | 1,045.62 | 1,950.68 | 3,971.82 | 556.05 | 150.93 | 166.82 | 873.80 |
| from 2026-01-01 | 970.24 | 561.52 | 765.22 | 2,296.98 | 321.58 | 87.29 | 96.47 | 505.34 |

(KV 2025 = 706.98, KV 2026 = 408.87. Arithmetic checked: the components add up.)
Back payment: **6,295.66 EUR, due 2026-12-15**. It equals exactly 2 x 873.80 + 9 x 505.34
(Nov 2025 to Dec 2025, Jan 2026 to Sep 2026). Objection period: one month after receipt, in writing
with a handwritten signature, in person at an SBK office, or with a qualified electronic signature
(plain e-mail is not allowed).

What this settles:
- KV rate **14.00 %** (reduced rate, no sick-pay entitlement) is what SBK applies to all three income types.
- Additional contribution **3.80 %** applies from 2025-11 and in 2026, on the whole base.
- Care insurance **4.20 %** = 3.6 % base + 0.6 % childless surcharge (SBK-11 conflict resolved in practice).
- Additional contribution is not charged on the care side.
- Both figures are annual amount / 12 per income type, with no cost deduction visible.

## 2. What I found in the repository (read-only review, 2026-11-06)

Settings in local/db.sqlite3 (AssessmentSettings): kv_rate = general (14.6 %), kv_rate_confirmed = false,
pflege = childless, joint_assessment = true. No AnnualInput rows exist for any year. Categories:
Pension, Rental, Rental (joint), Interest, Dividends, Capital gains, Salary mapped; "Other" unmapped.

Problems:
1. **PARAMETERS[2025] in sbk.py is a copy of 2026** (commit 1d9c757, "for example"): ceiling 5,812.50
   and Bezugsgroesse 3,955 are 2026 figures. 2025 figures (to verify from the Sozialversicherungs-
   Rechengroessenverordnung 2025, do not trust this note): ceiling 5,512.50 per month, Bezugsgroesse
   3,745, so minimum base 1,248.33. Its version string says "not verified", but the estimate report
   builds for 2025 without refusing. The tests expect the opposite:
   `test_unverified_years_are_refused` (years 2024, 2025, 2027) and
   `test_report_for_unverified_year_is_unavailable` (2025) should currently fail. Run the tests and confirm.
2. **Rate setting is out of date.** The letter confirms the reduced rate 14.0 %; the app is on the
   general rate 14.6 % labelled "NOT confirmed", so it over-estimates by 0.6 points.
3. **Membership months.** assess_year assumes membership for all 12 months. SBK's self-payer
   assessment starts 2025-11-01 (earlier 2025 months were presumably paid through another route:
   ask the owner). The 2025 report should show only the months the owner pays himself, and the back
   payment check should be reproducible.
4. **Rental costs are not used.** DB 2025 rental gross: Rental (AUD) 13,775.35 EUR with recorded expenses
   4,406.05 EUR, plus Rental (joint) 9,632.79 EUR = 23,408.14 EUR. The letter's rental figure is
   1,950.68 x 12 = 23,408.16 EUR, i.e. **gross rent with no costs deducted**. BVSz section 3(1b) allows
   Werbungskosten (SBK-02). The app only deducts what is entered as AnnualInput (none), so it also
   shows no deduction.
5. **Capital and "Sonstige" do not reconcile with the 2025 data.** App: dividends 7,769.63 + interest
   12,112.32 = 19,881.95 EUR gross (19,830.95 after the 51 EUR flat). Letter: capital 11,706.24
   (975.52 x 12) and Sonstige 12,547.44 (1,045.62 x 12), total 24,253.68. Two dividend rows (AUD 185.38
   and 237.28, 2025-03-27) are still "pending" conversion and are excluded. What SBK counts as
   "Sonstige Einnahmen" is unknown. The 2026 rental figure (765.22 x 12 = 9,182.64) matches the 2026
   Rental (joint) total in the DB (9,182.62), so the 2026 letter apparently contains only the joint
   account's rent; the 2026 capital/Sonstige figures (11,642.88 and 6,738.24) vs DB dividends 6,722.65 and
   interest 6,598.35 do not match cleanly.
6. **Joint rental income** is recorded in full. Whether 9,632.79 is the owner's share or the whole
   rent of the joint account is not decided (docs/rules/README.md item 22, SBK-14). If SBK used the
   whole amount the base is overstated.

## 3. Tasks

Do these in order. Stop and ask the owner where marked OWNER.

A. **Baseline.** Run the full test suite; record which tests fail (expect the two 2025 tests). Do not
   change data. Report the failures before fixing.

B. **Reconciliation report (new, read-only).** Add a small service + management command (and, if cheap,
   a report page) `sbk_letter_reconciliation` that, for a given year, prints per SBK treatment the annual
   gross, recorded expenses, AnnualInput costs, the app's monthly base, and next to it the figures typed in
   from a letter (store the letter figures in a documented fixture/YAML under docs/sbk-letters/2026-11-06.md,
   no insurance number). Include the pending-conversion rows and a per-organisation breakdown for the
   capital and rental treatments so the owner can see which rows could add up to 11,706.24 and
   12,547.44 (2025) and 11,642.88 / 6,738.24 / 9,182.64 (2026). Try obvious hypotheses (net of
   withholding, interest only, dividends only, Sonstige = foreign-source dividends, with/without the joint
   account, calendar vs reporting year) and list which ones match to the cent. Do not pick one silently.
   OWNER: ask which report/package was sent to SBK and what the "Sonstige" lines were in it.

C. **2025 parameters.** Verify the 2025 figures from primary sources (Rechengroessenverordnung 2025,
   SBK page, section 223 SGB V) and record them in docs/rules/sbk-contribution-rules.md with a status.
   Replace the copied PARAMETERS[2025] with verified values and bump the policy version to 1.1.
   Letter-confirmed values: KV reduced 14.0, Zusatz 3.8 (from 2025-11; the 2025-08-01 change is SECONDARY,
   and the rate for Jan to Oct 2025 is not needed unless the owner paid himself then), PV 3.6 + 0.6.
   Mark each field's source (letter 2026-11-06 / Verordnung) in the SbkParameters sources.
   Fix the tests: the 2025 refusal tests change to the next unverified year (2024, 2027); add hand-calculated
   tests that reproduce the letter: base 3,971.82 gives 556.05 + 150.93 + 166.82 = 873.80 and base 2,296.98
   gives 321.58 + 87.29 + 96.47 = 505.34 (check the one-cent rounding behaviour against the letter's
   per-type rounding; document any difference as ADR 0004 did).

D. **Membership months.** Add the first month of self-payment per year (a field on AnnualInput-like per-year
   model or on ReportingYear; migration + form + test). OWNER: confirm 2025-11 and whether any months
   in 2026 were paid by someone else. The estimate for 2025 then covers Nov to Dec only and the year
   total shows "2 months". Add a "back payment check" that sums letter periods and compares with 6,295.66
   (2 x 873.80 + 9 x 505.34 reproduces it).

E. **Assessment settings.** Propose, do not silently apply: kv_rate = reduced, kv_rate_confirmed = true
   (the letter is the confirmation), pflege = childless unless the owner has children (the letter offers
   a lower care rate with proof of children; OWNER: any child under 25 or older children?). Update
   docs/rules/README.md "Decisions made" and item 3/7 (SBK-11 and 2025 now answered), and the wording of
   the "affordability" label so a confirmed reduced rate no longer says "upper bound".

F. **Rental costs and joint account.** Show on the SBK report, for rental, gross, recorded expenses and the
   AnnualInput costs used, with a visible note when expenses exist but no AnnualInput costs were entered
   (as now, but loud). OWNER decides: (1) enter the 2025 rental costs as AnnualInput (recorded expenses
   total 4,406.05 EUR; check that they are only costs of the rental, not tax or fees that are not deductible),
   (2) is the joint rent the owner's share. Then show the effect on the monthly base and contribution
   (a cost reduction of 4,406.05 per year is about 367 per month of base, roughly 81 EUR per month in
   contributions at 22 %, if the letter's treatment is otherwise unchanged; compute properly, do not
   reuse this estimate).

G. **Final-assessment path.** SBK will recompute from the 2025 Einkommensteuerbescheid. Add inputs (or a
   documented place) for the figures the Bescheid will show per income type (capital income, rental income
   after costs, other income) so the app can compare Bescheid, letter and estimate. Keep the policy
   statement: planning estimate, not an SBK assessment.

H. **Docs.** New ADR (next number) for: letter as confirmation of rates, membership months, 2025
   parameters. Update docs/rules/*, README "still open" list, and glossary (Beitragsmitteilung, Vorbehalt,
   Sonstige Einnahmen, Einkommensteuerbescheid) in English and German.

## 4. Questions for the owner / for SBK (list them at the end of your report; do not code answers)
- What exactly are "Sonstige Einnahmen" (1,045.62 and 561.52)? Which of my submitted lines do they contain?
- Why do the 2026 monthly figures differ from the 2025 figures, and which documents were used for 2026?
- Are rental costs (Werbungskosten) accepted now, by submitting the 2025 cost statement, or only once the
  tax assessment exists? Can the provisional amount be corrected before 2026-12-15?
- Is the joint account's rent counted in full or at my share?
- Does the objection deadline (one month) need a protective objection, and who signs it?
- Which months of 2025 were paid by whom (the back payment covers 2025-11 to 2026-09 only)?

Report at the end: files changed, tests run (before and after), decisions needing the owner, and
anything that stays unverified. Use the commit attribution given by the session.
