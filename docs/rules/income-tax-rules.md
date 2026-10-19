# German income-tax rules relevant to the annual return

Kept separate from SBK rules: the two define income differently (see README). The app does **not** calculate tax. This register records what has and has not been verified so a later phase does not invent rules.

Sources (retrieved 2026-10-18), all on https://www.gesetze-im-internet.de/ unless noted:
- [T1] EStG §2 (estg/__2.html), §2a, §20 (estg/__20.html), §21, §22, §23 (estg/__23.html), §32b (estg/__32b.html), §32d (estg/__32d.html), §34d (estg/__34d.html)
- [T2] Secondary guides (Haufe, lohnsteuer-kompakt.de, steuergo.de) for currency conversion and holding periods: **not authoritative**

## Rules
| ID | Rule | Source | Status |
|---|---|---|---|
| TAX-01 | For business, farming and self-employment income the **profit** is taxed; for the other Einkunftsarten (employment, capital, rental, other) the **surplus of receipts over Werbungskosten**. For capital income §20(9) replaces the normal Werbungskosten rules. | T1 §2(2) | VERIFIED |
| TAX-02 | **Sparer-Pauschbetrag: 1,000 EUR** (2,000 EUR jointly assessed) deducted from capital income; actual costs are excluded. It cannot exceed the netted capital income. | T1 §20(9) | VERIFIED |
| TAX-03 | **Flat tax on capital income 25 %** (plus solidarity surcharge and church tax where applicable), reduced by creditable foreign tax per §32d(5). | T1 §32d(1) | VERIFIED (surcharge, church tax and the exceptions in §32d(2) not analysed) |
| TAX-04 | **Private sale gains (§23):** if the total gain of the calendar year is **less than 1,000 EUR** (Freigrenze, since 2024; 600 EUR before), none is taxed; at or above 1,000 EUR the whole gain is taxable. Losses only offset gains of the same type and year. | T1 §23(3) | VERIFIED for the Freigrenze and loss rule. Holding periods (1 year for assets such as crypto, 10 years for property) from T2 only: SECONDARY |
| TAX-05 | **Foreign income:** definition of foreign income for credit purposes is in §34d; credit/deduction of foreign tax in §34c. Whether and how foreign income is taxable depends on the **double-taxation treaty** with the source country (UK, Australia, USA). | T1 §34d; §34c not read | **UNVERIFIED**: no treaty text read; do not implement |
| TAX-06 | **Progression reservation (§32b):** income exempt in Germany under a treaty may still raise the tax rate on other income. | T1 §32b | Rule exists (VERIFIED); applicability to the user's income **UNVERIFIED** |
| TAX-07 | **Negative foreign income** may be restricted (§2a, third-country losses). | T1 §2a | Rule exists; scope not analysed. UNVERIFIED |
| TAX-08 | **Currency conversion for the return:** per T2, foreign income is converted at the rate for the day of payment (ECB reference rate acceptable), with the simplification of the BMF monthly "Umsatzsteuer-Umrechnungskurse" (R 34c EStR), and a BMF letter (03.05.2018) accepting an annual average for wages in foreign currency. | T2 only | **SECONDARY / UNVERIFIED**: the original EStR/BMF texts were not read; do not implement. Note this matches the app's current approach (payment-date ECB rate) only if confirmed |
| TAX-09 | **Which Anlage** (N, KAP, V, SO, AUS, etc.) each income belongs on, and whether a foreign pension, UK interest or Australian rental income is taxable in Germany. | not researched | **UNVERIFIED / YOUR INPUT** |
| TAX-11 | **Loss-offset rules** (Phase 11): how capital losses (§20(6) EStG: loss pot, carry-forward, offset limits), private-sale losses (§23(3): same type and year only; carry-back/forward) and foreign losses (§2a) are offset, and how losses count for SBK contributions. Open questions: which loss pots exist, whether a loss carries forward or back, whether the annual loss of one category may reduce another, and whether SBK uses losses at all. | §20(6), §23(3), §2a not analysed here (TAX-04 states only the same-type, same-year offset for private sales) | **UNVERIFIED / YOUR INPUT**: not implemented. The app records losses as negative payments in categories marked "may be negative", shows them signed and separately, floors negative SBK surpluses at 0 and nets nothing across categories |
| TAX-10 | **Expenses** (rental costs, depreciation, work costs): need the user's records; the app stores none. | EStG §9, §9a, §7 not read | UNVERIFIED; needs a data-model decision |

## What this means for the app
- Verified and simple enough to implement as separate policies: TAX-02 (Sparer-Pauschbetrag cap), TAX-03 (rate, informational), TAX-04 (Freigrenze check).
- Not implementable now: anything involving treaties, foreign-tax credit, progression reservation, conversion rules, Anlage mapping. These need your adviser or the original texts.
- The sensible output for the return is an **informational summary per income type and country** (gross received, converted amounts, rates and dates used, flagged items) for you or your adviser, not a tax figure.

## Implementation status (policy `tax-information` 1.0)
Implemented as checks, with no tax amount: TAX-02 (Sparer-Pauschbetrag usage, single or joint per your setting), TAX-04 (Freigrenze check; enter the GAIN, not the proceeds), TAX-03 as a reference rate. The information summary groups income by tax income type (your category mapping) and organisation country, with flags for foreign, unmapped and unconverted items. Everything else in this register is listed on the outputs as "not applied".

## Open items for you
1. **Mapping:** map each category to a tax income type (Categories page). The country comes from the organisation; if it is blank it is taken from the payment currency (AUD = AU, GBP = GB, USD = US; flagged in the output). EUR is never inferred, so set the country on organisations paid in EUR. YOUR INPUT.
2. **Currency conversion for tax:** confirm with your adviser which rate to use; the app stores the ECB rate of the payment date.
3. **Withholding tax and expenses** (recorded per payment since Phase 10) are shown as information and are NOT credited or deducted: treaty and foreign-tax-credit rules are not implemented (status: unverified; see docs/rules/README.md, open item 9).
3b. **Expenses** and **joint-assessment** status (setting exists; default single).
4. **Foreign treaty questions** (UK, AU, US) are for a tax adviser; the app lists them as "not applied".
