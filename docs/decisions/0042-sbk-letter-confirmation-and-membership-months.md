# ADR 0042: SBK letter as confirmation of rates, 2025 parameters, membership months

Status: accepted (branch `fix/sbk-letter-2025-reconciliation`, 2026-11-06). Extends ADR 0004. Prompt: `docs/prompts/SBK_LETTER_REVIEW.md`.

## Context
SBK's Beitragsmitteilung of 2026-11-06 (figures in `docs/sbk-letters/2026-11-06.md`) set the owner's contributions provisionally from 2025-11-01. `PARAMETERS[2025]` was a copy of 2026 and the SBK estimate for 2025 assumed 12 months of membership at an unconfirmed upper-bound rate.

## Decision
- **The letter is evidence of what SBK applies**, accepted by the owner as a valid source (2026-11-06): reduced health rate 14.00 %, additional contribution 3.80 % (2025-11 and 2026), care 4.20 % (3.6 % + 0.6 % childless surcharge; the owner has no children). It is recorded as YOUR INPUT / SBK document, not as statute. Assessment settings of the owner were set accordingly (reduced, confirmed, childless).
- **2025 parameters** are verified from primary sources (Bezugsgröße 3,745 EUR a month, SVBezGrV 2025 section 1; ceiling 5,512.50 EUR a month, BMAS page, same figure as section 2(2)); minimum base 1,248.33. Policy version 1.1. Years without verified parameters are still refused (2024, 2027).
- **Membership months:** `ReportingYear.self_pay_first_month` (blank = 12 months). Months before it are shown with no contribution ("not self-paid"); the year total and the monthly average use the member months. Never inferred from payments. 2025: first month 11 (owner, 2026-11-06).
- **Rounding:** the letter's two assessments are reproduced to the cent by rounding each component once on the total base (hand-calculated tests); no difference to SBK's per-type figures was found.
- **Costs:** recorded payment expenses are still information only (ADR 0010). The SBK report lists, per income type, gross, recorded expenses and annual costs used, and warns loudly when expenses exist but no annual costs were entered. Nothing is deducted automatically.
- **Final assessment:** `TaxAssessmentFigures` per year (capital, rental after costs, other) typed in from the Einkommensteuerbescheid; compared with the app in `manage.py sbk_letter_reconciliation`. No calculation uses them.
- **Reconciliation** (`sbk_letter_reconciliation --year`, read only) lists which groupings reproduce a letter figure and picks none. Result for the dev data: rental 2025 (Australian rental gross + joint rent gross, 100 %, no costs) and rental 2026 (joint rent gross) match to the cent; no grouping reproduces the capital and "Sonstige" figures.

## Consequences
The back payment 6,295.66 = 2 x 873.80 + 9 x 505.34 is reproduced (`sbk_letter.back_payment`). The owner's 50 % share of the joint rent is NOT modelled: SBK appears to count the whole recorded rent. Which treatment is right is for SBK to answer (docs/rules/README.md item 22).
