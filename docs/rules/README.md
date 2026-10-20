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
9. **Withholding tax and expenses (Phase 10, OPEN QUESTION).** How recorded withholding tax and expenses should affect the SBK and the tax figures is NOT decided: the app shows them next to gross and net and changes no calculation. Open: whether SBK takes gross or net foreign income, whether source-state withholding tax is creditable (treaty rules UK, AU, US; section 32d(5) EStG), and whether recorded expenses may replace the manual annual costs. Ask SBK and your tax adviser. Status: unverified, not implemented.
10. **Loss-offset rules (Phase 11, UNVERIFIED).** Owner answer 2026-10-19: no SBK or tax-office statement on how losses count for health-insurance contributions is available; it stays unverified. Questions to ask SBK and your adviser are listed in income-tax-rules.md (TAX-11). The app implements no offset.
11. **Revolut Flexible Cash Funds return (Phase 14, OPEN QUESTION).** The monthly "Total Earned Return" of Revolut's interest-bearing account is the payout of a money-market fund (units of an Irish fund, `IE...`), with a daily service fee. It is recorded as category Interest, gross = return, expenses = fee. Whether German tax and SBK treat it as interest (Zinsen) or as an investment-fund distribution (Investmenterträge), and whether the fee reduces anything, is NOT decided: ask your tax adviser and SBK. Status: unverified, no rule implemented.
12. **Bank, broker and money-market-fund income (Phase 15 decisions, OPEN QUESTION).** Owner decisions 2026-10-20: the organisation of an imported payment is the payer (the bank, or the company or money-market fund as printed on the statement); RVB payment date = booking date; money-market-fund income is recorded as category Dividends. These are recording choices only. Whether German tax and SBK treat such income as interest, dividends or fund income, and how withholding tax on it counts, is NOT decided (see items 9 and 11). Status: unverified, no rule implemented.
13. **HSBC interest (Phase 16, OPEN QUESTION).** The tax treatment of UK-source interest of a German resident (and whether the gross interest, which is what the statement shows, is the right basis for SBK and the tax return) is not decided. The app records the gross credit, payment date and the TO date from the statement and nothing else. Status: unverified, no rule implemented.
14. **German capital-gains tax and solidarity surcharge on bank interest in the withholding field (Phase 17, OPEN QUESTION).** RVB interest is recorded with the booked Kapitalertragsteuer, Solidaritätszuschlag and (if booked) Kirchensteuer in the withholding field, each named in the comment with its amount and the base it was charged on. How the tax summary should label and use this German tax is open: the existing "not credited" wording was written for foreign tax. Whether savings-lottery prize credits are taxable is the owner's assumption (not taxed) and is not decided; they are never imported. Status: unverified, no calculation changes.
15. **E*TRADE money-market-fund and company-stock dividends (Phase 18, OPEN QUESTION).** Owner decision: money-market-fund income is category Dividends (as is stock-dividend income). Whether German tax and SBK treat fund income as dividends (Dividenden) or as fund distributions (Investmenterträge), how the US withholding tax is credited (treaty, section 32d(5) EStG), and what the "reportable for the prior year" early-January items mean for the German tax year are NOT decided; the app records the printed payment date and the remark. Status: unverified, no rule implemented.
16. **Stock sales and share deliveries from the stock plan (Phase 19, NOT IN SCOPE).** Deliveries (RSU vesting) and sales are recognised in the Fidelity reports and listed as "not imported". Owner decision 2026-10-20: the shares sold were sold while the owner was employed and taxed at that time, so they are left out of this tool. If they are ever to be recorded (employment income, capital gain or loss), that needs its own decision and rules to verify. The Fidelity money-market and company-stock dividends are recorded as category Dividends with the settled US withholding; their German classification and the credit of the US tax are open (items 12 and 15).
17. **Rental income (Phase 21, OPEN QUESTION).** Australian rental income of a German resident, and the GST-inclusive fees in the managing agent's statements, are NOT decided (unverified). The app records the rent received as gross and the agent's listed costs (management fee, repairs, council and water rates, sundry fees) as expenses, with the `*` (GST-inclusive) count in the comment; whether and how expenses reduce the income for SBK and the tax return, and the treatment of the GST, are open. No rule implemented.
18. **MECU interest and Australian withholding tax (Phase 22, OPEN QUESTION).** The tax treatment of Australian-source interest and of Australian (non-resident) withholding tax for a German resident is NOT decided (unverified). The app records the gross interest, the withholding tax and the net credit exactly as the statement's memo lines give them (and cross-checks them against the annual Payment Summary); it never decides how the Australian tax is treated. Status: unverified, no rule implemented.
19. **Ord Minnett interest and overseas withholding tax (Phase 23, OPEN QUESTION).** The treatment of the Cash Management Trust interest and its overseas (Australian non-resident) withholding tax for a German resident is NOT decided (unverified). The app records the credited interest as gross and the debited tax as withholding, paired by calendar quarter, and cross-checks them with the trust's taxation summary; it decides nothing about the tax. Property-sale credits, share-scheme consideration and stock-sale proceeds are not income here and are notices only; **sales are not imported** (owner decision). Status: unverified, no rule implemented.
20. **Australian statements, consolidated open items (Phases 21 to 24).** (a) Rental income of a German resident, the agent's costs and GST-inclusive fees (item 17); (b) Australian-source interest and Australian withholding tax at MECU (item 18); (c) the same for the Ord Minnett trust (item 19); (d) stock sales, share deliveries and property-sale credits are not recorded, by decision (items 16 and 19); (e) the "large credit" notice threshold (AUD 20,000) is a heuristic, not a rule; (f) existing hand-entered rows are never changed: collisions and near-collisions are only reported (`tools/collision_report.py`), including rows whose gross differs slightly from a statement, and the rental rows booked under the tenant versus the managing agent. Status: all unverified, nothing implemented beyond recording what the statements say.
21. **Deferred by the owner:** PDF extraction (Phase 5 part 2) and the CLAUDE.md update for the new import design; SBK's answers will be supplied by the owner when available.
22. **Joint rental income (Phase 25, OPEN QUESTION).** How the shared rent of the joint account is treated for the tax return and for SBK (the owner's share, joint assessment) is NOT decided (unverified). The importer will record each credit in full and mark the category as joint; it never splits or decides. Status: unverified, no rule implemented.
23. **Rental costs of the joint account (Phase 26, deferred).** House-fee, property-charge and association-fee debits of the joint account are not read, matched or summarised: the owner deferred them until income and expenses are next summarised for the tax return (unverified, no rule implemented).

## Implemented policies
| Policy | Version | Rules | Tests |
|---|---|---|---|
| `sbk-contribution-estimate` | 1.0 (2026 parameters) | SBK-01 to SBK-10, SBK-17 (SBK-11 using SBK's published rate) | `core/test_policies_sbk.py` (hand-calculated) |
| `tax-information` | 1.0 | TAX-01, TAX-02, TAX-03 (reference), TAX-04 | `core/test_policies_tax.py` |

Not implemented (unverified or out of scope): TAX-05 to TAX-10, SBK-13 detail, SBK-14, SBK-15 workflow, SBK-16.

## How rules are implemented
Each verified rule lives in a policy module with a name, version and validity period, its own tests and source references (`core/services/policies/`). Every report built from a policy states the policy version, parameters, assumptions and what was not applied, both on screen and in the CSV. Unverified rules are never coded; they are listed as "not applied". Parameters exist only for verified years.
