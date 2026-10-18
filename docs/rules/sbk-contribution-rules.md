# SBK contribution rules (voluntary member)

SBK (Siemens-Betriebskrankenkasse) is a statutory health insurer. For voluntary members the contribution base is set by **§240 SGB V** and the GKV-Spitzenverband's **Beitragsverfahrensgrundsätze Selbstzahler (BVSz)** and its **Katalog von Einnahmen**. Care insurance (Pflegeversicherung) follows the same assessment (BVSz §1(2)).

Sources (retrieved 2026-10-18):
- [S1] §240 SGB V: https://www.gesetze-im-internet.de/sgb_5/__240.html
- [S2] BVSz, "zuletzt geändert am 20. März 2024" (11th amendment, in force 2024-04-01): https://informationsportal.de/wp-content/uploads/2024-03-20_Beitragsverfahrensgrundsaetze_Selbstzahler_11.Aenderung_final_Stand_01.04.2024_barrierefrei.pdf. **A newer amendment may exist; not checked.**
- [S3] GKV-Spitzenverband, Katalog von Einnahmen (11 Dec 2023): https://informationsportal.de/wp-content/uploads/2023-12-11_Katalog_Beitragseinnahmen_240SGBV_barrierefrei-1.pdf
- [S4] §223 SGB V, §241 SGB V, §242 SGB V, §55 and §57 SGB XI, §18 SGB IV at https://www.gesetze-im-internet.de/ (sgb_5/__223.html etc.)
- [S5] SBK page for voluntary members, 2026 figures: https://www.sbk.org/versicherung-tarife/beitraege/freiwillig-versicherte/ and https://www.sbk.org/versicherung-tarife/beitraege/beitragssatz/
- [S6] Sozialversicherungs-Rechengrößenverordnung 2026 (BGBl. 2025 I Nr. 278, 26 Nov 2025) as summarised by Deutsche Rentenversicherung: https://www.deutsche-rentenversicherung.de/DRV/DE/Ueber-uns-und-Presse/Presse/Meldungen/2025/250910-sv-rechengroessen-vo-2026.html

## Rules
| ID | Rule | Source | Status |
|---|---|---|---|
| SBK-01 | Contributions reflect the member's **entire economic capacity**. Countable income is all income and funds that are or can be used for living, **regardless of tax treatment**. The list is open-ended. | S1 §240(1); S2 §2(1), §3(1) | VERIFIED |
| SBK-02 | Income types that are taxed as "surplus of income over Werbungskosten" count **after deducting Werbungskosten** (costs of acquiring, securing and maintaining the income). Not for wages, pensions, Versorgungsbezüge. | S2 §3(1b) | VERIFIED |
| SBK-03 | For **capital income** the Werbungskosten are a flat **51 EUR per calendar year** unless higher actual costs are proven. (This is *not* the 1,000 EUR tax Sparer-Pauschbetrag.) Loss netting for capital income follows §20(6) EStG. | S2 §3(1b) S3-4 | VERIFIED (loss-netting detail not analysed) |
| SBK-04 | Catalogue treatment: interest and dividends from capital assets, capital income, rental/lease income: **contribution-liable**. Gains from private sale transactions (§22 Nr.2 / §23 EStG): liable, allocated as one-off income. Gains from sale of a business or shares in a corporation: liable (BSG 18.01.2018). Child benefit: not liable. | S3 | VERIFIED (catalogue is not exhaustive; foreign-pension rows not analysed) |
| SBK-05 | **Allocation to months.** Earned income and rental income of a calendar year: **annual amount divided by the number of calendar months in which it was earned**. Capital income earned alongside such income: same. Capital income *without* earned/rental income: the amount received in the **last proven calendar year**, divided by the months in which it was received. | S2 §5(2) | VERIFIED. **Conflicts with the Phase 2 "always / 12" decision** |
| SBK-06 | **One-off income** is allocated at **1/12 of the expected amount for twelve months** (from the month of receipt if not foreseeable). Severance, capital-sum payments and Versorgungsbezüge have their own rules (1/120 over 120 months, etc.). | S2 §5(3)-(5) | VERIFIED |
| SBK-07 | Contributions are assessed per **calendar day = 1/30 of the month's income**, capped at 1/30 of the monthly contribution assessment ceiling; a month counts as 30 days. | S2 §3(2), §8(1); S4 §223(2)-(3) | VERIFIED |
| SBK-08 | **Ceiling 2026: 5,812.50 EUR per month** (69,750 per year). Set annually by ordinance. | S4 §223 (ceiling by ordinance); S5; S6 | VERIFIED for 2026 (ordinance summarised by DRV; SBK page agrees) |
| SBK-09 | **Minimum 2026: 1/90 of the monthly Bezugsgröße per day = 1,318.33 EUR per month** (Bezugsgröße 3,955 EUR). Applies to voluntary members. | S1 §240(4); S2 §3(3); S5; S6 | VERIFIED for 2026 |
| SBK-10 | **General rate 14.6 %** (§241). **Reduced rate 14.0 %** applies to income types without sick-pay entitlement (§243). SBK page: 17.8 % reduced / 18.4 % general **including** SBK's additional contribution, i.e. **additional contribution 3.8 %**. Which rate applies depends on the type of income. | S4 §241, §242; S5 | General rate and SBK's 18.4 % / 17.8 % VERIFIED on SBK page. §243 text not read (14.0 % inferred from S5): re-verify. SBK's additional contribution can change during a year |
| SBK-11 | **Care insurance 2026** per SBK: **3.6 %** base (member with one child, or under 23); **4.2 %** for members aged 23+ without children (0.6-point surcharge); relief of 0.25 points per child under 25 from the second child (up to the fifth). | S5; S4 §55(3) for surcharge and relief structure | **CONFLICT:** the §55(1) text fetched from gesetze-im-internet.de shows base **3.4 %**; SBK and secondary sources show 3.6 %. The legal basis for 3.6 % (ordinance/later law) was not located. Confirm with SBK before coding. |
| SBK-12 | Contributions are paid **in EUR only** ("Eine Beitragszahlung in fremder Währung ist nicht zulässig"), due by the **15th of the following month**. | S2 §11(1) S.3, §10(1); S5 | VERIFIED (payment). **Conversion of foreign-currency income: not specified in S2 or S3.** |
| SBK-13 | **Foreign income:** nothing in S2/S3 excludes it; SBK-01 (all income, regardless of tax treatment) applies. Foreign pensions have their own rates (half rate) in specific cases (S2 §7(3), §228(1) S.2 SGB V), mainly for self-employed members. | S2 §3(1), §7(3) | VERIFIED that it is not excluded; detail of foreign pensions NOT analysed |
| SBK-14 | **Spouse income:** if the spouse is not in a statutory fund, the spouse's income is included, with a split rule and child deductions. The app does not store a spouse's income. | S2 §2(4)-(5) | VERIFIED. YOUR INPUT |
| SBK-15 | **Proof:** rental and self-employment income via the latest income tax assessment; capital income via bank statements/certificates; if proof is not provided the ceiling applies. The contribution is provisional until the tax assessment arrives. | S1 §240(1),(4a); S2 §6, §6a; S5 | VERIFIED |
| SBK-17 | **Calculation and rounding:** contribution = monthly assessable income x rate, **rounded to 2 decimals, half-up** (third decimal 5-9 rounds up). Health insurance = **additional contribution** (rate x the sum of all assessable income, then rounded) **plus** the other rounded components. Per-day amounts are used unrounded and multiplied by the days of membership (30-day month). | S2 §9(1), (1a), (2) | VERIFIED |
| SBK-16 | Where the income of a hauptberuflich self-employed member or others is ranked, ordering and rate choice follow S2 §7(3) and §238a SGB V. | S2 §7(3) | VERIFIED (exists); not analysed |

## Worked examples (from SBK-05 and SBK-06; illustrative, not an assessment)
- Rental income of 6,000 EUR received over 12 months: 500 EUR per month. If received only in July to December: 6,000 / 6 = **1,000** per month (not 500).
- A one-off capital sum of 12,000 EUR taxable under §23: **1,000 EUR per month for 12 months** from the month of receipt.
- Total monthly base = sum of the month's allocations, then limited to 1,318.33 to 5,812.50 EUR (2026).

## What I can and cannot say about the "annual total / 12" figure
Phase 2 decided the opening-page estimate is annual total / 12. SBK-05 and SBK-06 show the assessed monthly amount is built per income type and is **not** always annual / 12. Annual / 12 equals the SBK result only when each income stream was earned in all 12 months and nothing is one-off. The app's figure must therefore stay labelled "average of actuals, not an SBK assessment" until you decide (see below).

## Implementation status (policy `sbk-contribution-estimate` 1.0)
Implemented: SBK-01 to SBK-10 and SBK-17 (SBK-11 with SBK's published 3.6 % / 4.2 %). The category-to-treatment mapping, annual costs and months earned are user data. Estimate year: 2026 only. Open items are tracked in [README.md](README.md#still-open-your-input-or-verification).

Interpretation made in code (flagged in every output, to be confirmed with SBK): the annual surplus of self-employed, rental and capital income is divided by the months from "first month" to "last month" entered (default 1 to 12) and applied to those months only. One-off income is spread over the 12 months starting with the month of receipt, including one-offs of the previous year. Negative surpluses count as 0.
