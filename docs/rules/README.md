# Legal rules register (Phase 7)

Purpose: record every SBK contribution rule and German income-tax rule the app might apply, with its authoritative source and how far it has been verified, **before** any rule is coded. Nothing here is legal or tax advice. The app produces general summaries, not an SBK assessment or a tax calculation.

Research date: **2026-10-18**. Rules change yearly (rates, limits) and sometimes mid-year (per a comparison site, SBK's additional contribution changed on 2025-08-01: SECONDARY). Every rule-bearing figure must carry a rule version and be re-checked each January.

## Status legend
| Status | Meaning |
|---|---|
| **VERIFIED** | Read in the primary source (statute text, GKV-Spitzenverband rules, or the insurer's own published page) on the research date |
| **SECONDARY** | Seen only in a guide, press release or calculator; not read in a primary source |
| **CONFLICT** | Sources disagree; needs your decision or a confirmation from SBK/your adviser |
| **UNVERIFIED** | Not found or not checked; **must not be implemented** until confirmed |
| **YOUR INPUT** | Depends on your personal circumstances; the app cannot assume it |

## Documents
- [sbk-contribution-rules.md](sbk-contribution-rules.md): how SBK assesses contributions for a voluntary member (SGB V, SGB XI, GKV-Spitzenverband rules).
- [income-tax-rules.md](income-tax-rules.md): income-tax rules relevant to the annual return (EStG). Kept separate from the SBK rules because the two systems define income differently.

## The most important differences between SBK and tax
| Topic | SBK contributions | Income tax |
|---|---|---|
| Which income counts | All income usable for living, "regardless of tax treatment" (BVSz §3(1)) | Only income of a taxable Einkunftsart, after exemptions and treaties |
| Capital income deductions | Flat **51 EUR** per year unless higher costs proven (BVSz §3(1b)) | **Sparer-Pauschbetrag 1,000 EUR** (2,000 joint), no actual costs (§20(9) EStG) |
| Private sale gains (§23) | Counted (Katalog), spread as one-off income | 1,000 EUR Freigrenze: below it nothing is taxed, at or above it all is (§23(3) EStG) |
| Spreading over time | By months earned / 1/12 of one-offs (BVSz §5) | By calendar year of receipt |
| Currency | Contributions paid in EUR; conversion of foreign income not found (UNVERIFIED) | Conversion practice not verified (SECONDARY only) |
| Limits | Min 1,318.33 and max 5,812.50 EUR per month in 2026 | Progressive tariff, allowances; not modelled |

## Decisions and confirmations needed from you (blocking implementation)
See the end of each document, summarised here:
1. **Your SBK status** (which contribution rate applies, Pflegeversicherung child status, spouse income). YOUR INPUT.
2. **Monthly figure rule.** The earlier "annual total / 12" decision does not match SBK's own rules (BVSz §5): rental and capital income are divided by the number of months in which it was earned; one-off income is 1/12 per month for 12 months. CONFLICT with the Phase 2 decision.
3. **Category mapping.** Each income category must be mapped by you to an SBK treatment and a tax Einkunftsart/Anlage. The app will not guess.
4. **Expenses.** SBK deducts Werbungskosten for rental/capital income; tax deducts expenses. The app has no expense data today.
5. **Foreign currency conversion** for SBK and for the tax return: not verified. Ask SBK and/or your tax adviser which rate they accept.
6. **Tax scope.** Treaty rules (UK, Australia, USA), foreign-tax credit and progression reservation are not verified and are not implemented.

## How rules will be implemented (after confirmation)
Each verified rule becomes a separate policy class with a name, version and validity period, its own tests, and the source reference in its docstring. Every result stores the policy versions and assumptions used. Unverified rules are listed in reports as "not applied".
