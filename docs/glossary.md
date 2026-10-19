# Glossary: report headings and terms (English / German)

Single source for the wording of the reports (Phase 12) and for the information popups on the report headings (Phase 13). Report headings, popups and the German interface must use these strings; nothing is translated ad hoc.

**Status values**
- **verified (SBK page)**: the German wording is quoted from an SBK page the repo already cites (`docs/rules/sbk-contribution-rules.md`, [S5]); read 2026-10-19.
- **proposed, needs owner review**: my proposal. It is not taken from an SBK or statute text. Please correct it; nothing German marked "proposed" should be treated as an official term.

Nothing here is legal advice. The app's output is not an SBK assessment or a tax calculation.

Sources used below: **SBK-F** = https://www.sbk.org/versicherung-tarife/beitraege/freiwillig-versicherte/ ; **SBK-B** = https://www.sbk.org/versicherung-tarife/beitraege/beitragssatz/ ; rule files in `docs/rules/` (SBK-xx, TAX-xx).

## A. The 14 columns of the SBK estimate report

| # | English label | German label | Explanation (shown in the info popup, in the selected language) | Source | Status |
|---|---|---|---|---|---|
| 1 | Employment | Arbeitsentgelt | Income from employment, counted in the month it is paid (payment date). | SBK-01, BVSz §3 via `docs/rules/` (German word from the app's category mapping label). SBK-F names only "geringfügige Beschäftigung" | proposed, needs owner review |
| 2 | Pension | Renten und Versorgungsbezüge | Pensions and company pensions, counted in the month they are paid. | SBK-F: "Renten und Versorgungsbezüge, zum Beispiel Betriebsrenten" | verified (SBK page) |
| 3 | Self-employed | Einkünfte aus selbstständiger Tätigkeit | Profit from self-employment: the annual surplus after your entered costs, divided over the months you entered. | SBK-F: "Einkünfte aus selbstständiger Tätigkeit"; SBK-05 | verified (SBK page) |
| 4 | Rental | Einkünfte aus Vermietung und Verpachtung | Rental surplus after your entered costs, divided over the months you entered. | SBK-F: "Einkünfte aus Vermietung und Verpachtung"; SBK-05 | verified (SBK page) |
| 5 | Capital | Einkünfte aus Kapitalvermögen | Interest and dividends: annual surplus after the 51 EUR flat costs (or your higher proven costs), divided over the months you entered. | SBK-F: "Einkünfte aus Kapitalvermögen, zum Beispiel Zins- und Dividendenerträge"; SBK-03 | verified (SBK page) |
| 6 | One-off (1/12) | Einmalige Einnahmen (1/12) | A one-off amount spread at one twelfth per month for twelve months, starting with the month of receipt. | SBK-06 (BVSz §5(3)); the phrase "Einmalzahlung" is not on SBK-F | proposed, needs owner review |
| 7 | Base before limits | Beitragspflichtige Einnahmen vor Begrenzung | The month's total of the income types above, before the minimum and maximum are applied. | SBK-01, SBK-07 | proposed, needs owner review |
| 8 | Assessed base | Beitragsbemessungsgrundlage | The monthly amount the contribution is calculated on, after the minimum and maximum. | SBK-08, SBK-09 | proposed, needs owner review |
| 9 | Limit applied | Angewandte Grenze (Mindest- / Höchstgrenze) | Shows whether the legal minimum base ("minimum") or the ceiling ("maximum") replaced your income. Ceiling 2026: 5,812.50 EUR per month; minimum 1,318.33 EUR per month. | SBK-F: "Beitragsbemessungsgrenze von monatlich 5.812,50 €"; "Die untere Grenze zur Beitragsberechnung liegt bei monatlich 1.318,33 €" | verified (SBK page) for "Beitragsbemessungsgrenze" and "untere Grenze"; the label as a whole is proposed |
| 10 | Health: general part | Krankenversicherung: allgemeiner Anteil (14,6 %) | Health contribution at the general rate of 14.6 % of the assessed base (the app uses the general rate as an upper bound until SBK confirms yours). | SBK-10; SBK-F "allgemeiner Beitragssatz" (that page quotes 18,4 % including the additional contribution) | proposed, needs owner review |
| 11 | Health: additional contribution | Krankenversicherung: Zusatzbeitrag (3,8 %) | SBK's additional contribution, 3.8 % of the assessed base; it can change during a year. | SBK-B: "Darin enthalten ist ein Zusatzbeitrag von 3,8 Prozent." | verified (SBK page) for "Zusatzbeitrag"; the label is proposed |
| 12 | Health total | Krankenversicherung gesamt | General part plus additional contribution. SBK's own table calls the health-insurance amount "Krankenkassen-Beitrag". | SBK-F table; SBK-17 | proposed, needs owner review |
| 13 | Care insurance | Pflegeversicherung | Care-insurance contribution on the same base (4.2 % assumed: age 23 or over, no children). | SBK-F: "Pflegeversicherung", "Pflegekassen-Beitrag"; "Für Versicherte über 23 Jahren und ohne Kinder beträgt der Beitragssatz 4,2 %." | verified (SBK page) |
| 14 | Total contribution | Gesamtbeitrag | Health total plus care insurance for the month. | SBK-F table: "Gesamtbeitrag/Monat" | verified (SBK page) |

Note: SBK-F writes the care-insurance age as "23 Jahren" and the child relief as "unter 25 Jahren"; I did not reconcile this (see SBK-11 in the rules register).

## B. Other headings and terms that appear on the reports and pages

All are **proposed, needs owner review** unless stated. Where the repo's rule files already use a German word, that word is used.

| English | German (proposed) | Notes |
|---|---|---|
| Year / Month | Jahr / Monat | |
| Payment(s) | Zahlung(en) | |
| Payment date | Zahlungsdatum | |
| Reporting month | Berichtsmonat | |
| Organisation | Organisation | |
| Category | Kategorie | |
| Income type | Einkunftsart | `Einkunftsart` is used in `docs/rules/income-tax-rules.md` |
| Organisation country | Land der Organisation | |
| Gross | Brutto | |
| Net | Netto | |
| Gross (original) / Net (original) | Brutto (Original) / Netto (Original) | amount in the payment currency |
| Gross EUR / Net EUR | Brutto EUR / Netto EUR | |
| Gross EUR (signed sum) | Brutto EUR (Summe mit Vorzeichen) | Phase 11 |
| Gains EUR | Gewinne EUR | normal payments above 0 |
| Losses EUR (signed) | Verluste EUR (mit Vorzeichen) | normal payments below 0; Phase 11 |
| Corrections / reversals EUR (signed) | Korrekturen / Stornierungen EUR (mit Vorzeichen) | |
| Withholding tax | Einbehaltene Steuer (Quellensteuer) | "Quellensteuer" is the common term; please confirm |
| Expenses | Ausgaben | alternative: Aufwendungen / Kosten |
| Unallocated | Nicht zugeordnet | gross − net − withholding tax − expenses |
| Gross / 12 | Brutto / 12 | an average of actuals, not a recurring figure |
| Share of gross | Anteil am Brutto | |
| Payments without net | Zahlungen ohne Netto | |
| Unconverted payments | Nicht umgerechnete Zahlungen | |
| Rate (EUR per 1 unit) / Rate date / Rate source | Kurs (EUR je 1 Einheit) / Kursdatum / Kursquelle | ECB reference rate |
| Original currency | Originalwährung | |
| Frequency | Häufigkeit | |
| Monthly / Quarterly / Half-yearly / Yearly / One-off | Monatlich / Vierteljährlich / Halbjährlich / Jährlich / Einmalig | |
| Monthly equivalent | Monatsäquivalent | |
| Recurring payments / One-off items excluded | Wiederkehrende Zahlungen / Einmalige Posten ausgeschlossen | |
| Werbungskosten, Betriebsausgaben, Sparer-Pauschbetrag | (unchanged) | already German in the repo's rule files |
| NOT confirmed with SBK | NICHT von der SBK bestätigt | |
| Planning estimate only; not an SBK assessment and not a tax calculation | Nur eine Planungsschätzung; keine Beitragsfestsetzung der SBK und keine Steuerberechnung | |
| Basis / Period / Currency / Rounding / Excluded or missing | Grundlage / Zeitraum / Währung / Rundung / Ausgeschlossen oder fehlend | basis-block labels |
| Actual payments received / Normalised monthly | Tatsächlich erhaltene Zahlungen / Normalisiert pro Monat | |
| Information only, not credited | Nur zur Information, nicht angerechnet | withholding tax on the tax summary |

## C. Number, date and CSV formats (decided 2026-10-19)
- **Screen and printed reports** follow the selected language: German `1.234,50` and `19.10.2026`; English `1,234.50` and `2026-10-19` as today. Amounts show their ISO currency code after the number, in their own currency.
- **CSV exports** are **language-independent in format**: comma separator, dot decimal, no thousands separator, ISO dates, 2 decimals (the same as the stored values, rounded for export only). Only the *text* (headings, labels) is language-dependent; see the open question below.
