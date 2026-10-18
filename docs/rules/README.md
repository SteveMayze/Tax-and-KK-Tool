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

## Decisions made (2026-10-18) and what was implemented
| Question | Your decision | Effect |
|---|---|---|
| Monthly figure | Implement SBK's rules per income type | `sbk-contribution-estimate` policy; the simple annual / 12 figure stays, labelled as an average of actuals |
| Health-insurance rate | You are not employed and must ask SBK; meanwhile use the **general rate (18.4 %) as an "affordability rate"** (upper bound) | Setting "Rate confirmed with SBK" is off by default; every output says "NOT confirmed with SBK, upper-bound affordability figure" |
| Care insurance | **4.2 %** (23 or over, no children) | Default setting; base 3.6 % selectable; reduced rates for several children are not implemented until verified |
| Tax scope | Information summary + the verified checks | `tax-information` policy: Sparer-Pauschbetrag, private-sale Freigrenze, flat-tax rate as reference. **No tax amount**, no treaty logic |

## Still open (your input or verification)
1. **Category mapping.** Each category needs your SBK treatment and tax income type (Categories page). Unmapped categories are excluded and listed on every output.
2. **Months earned.** BVSz section 5(2) divides annual rental/self-employed/capital income by the months it was earned. Which months receive the result is not spelled out; the policy applies it to the months you enter (default January to December). Please confirm this reading with SBK if your income does not run all year.
3. **Care-insurance base rate (SBK-11 CONFLICT)** and which statute/ordinance sets 3.6 %. The policy uses SBK's published rate.
4. **Spouse income** (SBK-14), **child deductions**, **ranking of income types** (SBK-16) are not modelled.
5. **Foreign-currency conversion** for SBK and for tax (SBK-12, TAX-08): ask SBK / your adviser.
6. **Costs**: enter annual Werbungskosten / Betriebsausgaben per year for rental, self-employed and capital income (Annual inputs page). Tax-side expenses are not modelled (TAX-10).
7. **Years**: the SBK estimate exists for **2026 only**. 2025 is waiting for SBK's answers to the open questions above before its parameters are verified and added.
8. **Newer SBK rules**: check for a BVSz amendment after 2024-03-20 and for SBK rate changes during the year.
9. **Deferred by the owner:** PDF extraction (Phase 5 part 2) and the CLAUDE.md update for the new import design; SBK's answers will be supplied by the owner when available.

## Implemented policies
| Policy | Version | Rules | Tests |
|---|---|---|---|
| `sbk-contribution-estimate` | 1.0 (2026 parameters) | SBK-01 to SBK-10, SBK-17 (SBK-11 using SBK's published rate) | `core/test_policies_sbk.py` (hand-calculated) |
| `tax-information` | 1.0 | TAX-01, TAX-02, TAX-03 (reference), TAX-04 | `core/test_policies_tax.py` |

Not implemented (unverified or out of scope): TAX-05 to TAX-10, SBK-13 detail, SBK-14, SBK-15 workflow, SBK-16.

## How rules are implemented
Each verified rule lives in a policy module with a name, version and validity period, its own tests and source references (`core/services/policies/`). Every report built from a policy states the policy version, parameters, assumptions and what was not applied, both on screen and in the CSV. Unverified rules are never coded; they are listed as "not applied". Parameters exist only for verified years.
