# Glossary: report headings and terms (English / German)

Single source for the wording of the reports (Phase 12) and for the information popups on the report headings (Phase 13). Report headings, popups and the German interface must use these strings; nothing is translated ad hoc.

**Status values** (the owner approved this glossary on 2026-10-19)
- **verified (SBK page)**: the German wording is quoted from an SBK page the repo already cites (`docs/rules/sbk-contribution-rules.md`, [S5]); read 2026-10-19.
- **approved by owner 2026-10-19 (wording proposed)**: my proposal, approved by the owner as the working wording. It is not taken from an SBK or statute text and must not be treated as an official term.

Nothing here is legal advice. The app's output is not an SBK assessment or a tax calculation.

Sources used below: **SBK-F** = https://www.sbk.org/versicherung-tarife/beitraege/freiwillig-versicherte/ ; **SBK-B** = https://www.sbk.org/versicherung-tarife/beitraege/beitragssatz/ ; rule files in `docs/rules/` (SBK-xx, TAX-xx).

## A. The 14 columns of the SBK estimate report

| # | English label | German label | Explanation (English, shown in the info popup) | Explanation (German, shown in the info popup) | Source | Status |
|---|---|---|---|---|---|---|
| 1 | Employment | Arbeitsentgelt | Income from employment, counted in the month it is paid (payment date). | Einkommen aus Beschäftigung, wird in dem Monat angesetzt, in dem es gezahlt wird (Zahlungsdatum). | SBK-01, BVSz §3 via `docs/rules/` (German word from the app's category mapping label). SBK-F names only "geringfügige Beschäftigung" | approved by owner 2026-10-19 (wording proposed) |
| 2 | Pension | Renten und Versorgungsbezüge | Pensions and company pensions, counted in the month they are paid. | Renten und Betriebsrenten, werden in dem Monat angesetzt, in dem sie gezahlt werden. | SBK-F: "Renten und Versorgungsbezüge, zum Beispiel Betriebsrenten" | verified (SBK page) |
| 3 | Self-employed | Einkünfte aus selbstständiger Tätigkeit | Profit from self-employment: the annual surplus after your entered costs, divided over the months you entered. | Gewinn aus selbstständiger Tätigkeit: der Jahresüberschuss nach den von Ihnen eingegebenen Kosten, verteilt auf die von Ihnen eingegebenen Monate. | SBK-F: "Einkünfte aus selbstständiger Tätigkeit"; SBK-05 | verified (SBK page) |
| 4 | Rental | Einkünfte aus Vermietung und Verpachtung | Rental surplus after your entered costs, divided over the months you entered. | Mietüberschuss nach den von Ihnen eingegebenen Kosten, verteilt auf die von Ihnen eingegebenen Monate. | SBK-F: "Einkünfte aus Vermietung und Verpachtung"; SBK-05 | verified (SBK page) |
| 5 | Capital | Einkünfte aus Kapitalvermögen | Interest and dividends: annual surplus after the 51 EUR flat costs (or your higher proven costs), divided over the months you entered. | Zinsen und Dividenden: Jahresüberschuss nach der Kostenpauschale von 51 EUR (oder Ihren höheren nachgewiesenen Kosten), verteilt auf die von Ihnen eingegebenen Monate. | SBK-F: "Einkünfte aus Kapitalvermögen, zum Beispiel Zins- und Dividendenerträge"; SBK-03 | verified (SBK page) |
| 6 | One-off (1/12) | Einmalige Einnahmen (1/12) | A one-off amount spread at one twelfth per month for twelve months, starting with the month of receipt. | Ein einmaliger Betrag, verteilt mit einem Zwölftel pro Monat über zwölf Monate, beginnend mit dem Monat des Zuflusses. | SBK-06 (BVSz §5(3)); the phrase "Einmalzahlung" is not on SBK-F | approved by owner 2026-10-19 (wording proposed) |
| 7 | Base before limits | Beitragspflichtige Einnahmen vor Begrenzung | The month's total of the income types above, before the minimum and maximum are applied. | Die Summe der oben genannten Einkunftsarten im Monat, bevor Mindest- und Höchstgrenze angewendet werden. | SBK-01, SBK-07 | approved by owner 2026-10-19 (wording proposed) |
| 8 | Assessed base | Beitragsbemessungsgrundlage | The monthly amount the contribution is calculated on, after the minimum and maximum. | Der monatliche Betrag, auf dem der Beitrag berechnet wird, nach Anwendung von Mindest- und Höchstgrenze. | SBK-08, SBK-09 | approved by owner 2026-10-19 (wording proposed) |
| 9 | Limit applied | Angewandte Grenze (Mindest- / Höchstgrenze) | Shows whether the legal minimum base ("minimum") or the ceiling ("maximum") replaced your income. Ceiling 2026: 5,812.50 EUR per month; minimum 1,318.33 EUR per month. | Zeigt, ob die gesetzliche Mindestbemessungsgrundlage („Mindestgrenze“) oder die Obergrenze („Höchstgrenze“) Ihr Einkommen ersetzt hat. Beitragsbemessungsgrenze 2026: 5.812,50 EUR pro Monat; Mindestbemessungsgrundlage: 1.318,33 EUR pro Monat. | SBK-F: "Beitragsbemessungsgrenze von monatlich 5.812,50 €"; "Die untere Grenze zur Beitragsberechnung liegt bei monatlich 1.318,33 €"; the words "Beitragsbemessungsgrenze" and "untere Grenze" are quoted from the page, the label as a whole is my wording | approved by owner 2026-10-19 (wording proposed) |
| 10 | Health: general part | Krankenversicherung: allgemeiner Anteil (14,6 %) | Health contribution at the general rate of 14.6 % of the assessed base (the app uses the general rate as an upper bound until SBK confirms yours). | Krankenversicherungsbeitrag zum allgemeinen Satz von 14,6 % der Bemessungsgrundlage (die Anwendung nimmt den allgemeinen Satz als Obergrenze, bis die SBK Ihren Satz bestätigt). | SBK-10; SBK-F "allgemeiner Beitragssatz" (that page quotes 18,4 % including the additional contribution) | approved by owner 2026-10-19 (wording proposed) |
| 11 | Health: additional contribution | Krankenversicherung: Zusatzbeitrag (3,8 %) | SBK's additional contribution, 3.8 % of the assessed base; it can change during a year. | Zusatzbeitrag der SBK, 3,8 % der Bemessungsgrundlage; er kann sich im Laufe eines Jahres ändern. | SBK-B: "Darin enthalten ist ein Zusatzbeitrag von 3,8 Prozent."; the word "Zusatzbeitrag" is quoted from the page, the label as a whole is my wording | approved by owner 2026-10-19 (wording proposed) |
| 12 | Health total | Krankenversicherung gesamt | General part plus additional contribution. SBK's own table calls the health-insurance amount "Krankenkassen-Beitrag". | Allgemeiner Anteil plus Zusatzbeitrag. In der Tabelle der SBK heißt der Krankenversicherungsbetrag „Krankenkassen-Beitrag“. | SBK-F table; SBK-17 | approved by owner 2026-10-19 (wording proposed) |
| 13 | Care insurance | Pflegeversicherung | Care-insurance contribution on the same base (4.2 % assumed: age 23 or over, no children). | Beitrag zur Pflegeversicherung auf derselben Grundlage (angenommen 4,2 %: Alter 23 oder älter, keine Kinder). | SBK-F: "Pflegeversicherung", "Pflegekassen-Beitrag"; "Für Versicherte über 23 Jahren und ohne Kinder beträgt der Beitragssatz 4,2 %." | verified (SBK page) |
| 14 | Total contribution | Gesamtbeitrag | Health total plus care insurance for the month. | Krankenversicherung gesamt plus Pflegeversicherung für den Monat. | SBK-F table: "Gesamtbeitrag/Monat" | verified (SBK page) |

Note: SBK-F writes the care-insurance age as "23 Jahren" and the child relief as "unter 25 Jahren"; I did not reconcile this (see SBK-11 in the rules register).

## B. Other headings and terms that appear on the reports and pages

All are **approved by owner 2026-10-19 (wording proposed)** unless stated. Where the repo's rule files already use a German word, that word is used.

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
| Important notice | Wichtiger Hinweis | PDF of the tax information summary (Phase 33, wording proposed, awaiting owner review) |
| Place / Date / Signature | Ort / Datum / Unterschrift | PDF signature block; English mode shows "Place (Ort)", "Date (Datum)", "Signature (Unterschrift)" |
| Tax assessment / Tax return | Steuerbescheid / Steuererklärung | PDF notice |
| Page x of y | Seite x von y | PDF footer |
| General financial summary, not an official assessment or tax calculation | Allgemeine Finanzübersicht, keine amtliche Festsetzung oder Steuerberechnung | PDF footer (proposed, awaiting owner review) |
| Notice text (PDF, tax summary) | Dieser Bericht darf nicht für sich allein verwendet werden. Er ist zusammen mit dem jeweiligen Steuerbescheid bzw. der Steuererklärung zu lesen. Er zeigt die in diesem Programm erfassten Bruttoeinnahmen; Steuern, Abzüge, Quellensteuern, Kosten und persönliche Verhältnisse sind nicht vollständig berücksichtigt, die Zahlen können daher von den festgesetzten abweichen. Er ist eine allgemeine Informationszusammenstellung, keine Steuerberechnung, keine Steuerberatung und kein amtlicher Bescheid. | proposed 2026-10-25, awaiting owner review; English source text in `core/services/report_pdf.py` |

## D. Every other report heading and title (derived)

Generated from the reports themselves and checked by a test (`core/test_i18n.py`): every German heading and title on the report pages must appear in this file. They combine the approved terms above; status for all rows: **derived from approved terms, owner may amend**.

| English | German |
|---|---|
| Year | Jahr |
| Payments | Zahlungen |
| Months with payments | Monate mit Zahlungen |
| Gains EUR | Gewinne EUR |
| Losses EUR (signed) | Verluste EUR (mit Vorzeichen) |
| Corrections / reversals EUR (signed) | Korrekturen / Stornierungen EUR (mit Vorzeichen) |
| Gross EUR (signed sum) | Brutto EUR (Summe mit Vorzeichen) |
| Net EUR | Netto EUR |
| Withholding tax EUR | Einbehaltene Steuer (Quellensteuer) EUR |
| Expenses EUR | Ausgaben EUR |
| Unallocated EUR | Nicht zugeordnet EUR |
| Gross EUR / 12 | Brutto EUR / 12 |
| Net EUR / 12 | Netto EUR / 12 |
| Payments without net | Zahlungen ohne Netto |
| Unconverted payments | Nicht umgerechnete Zahlungen |
| Annual summary | Jahresübersicht |
| Month | Monat |
| Gross EUR | Brutto EUR |
| Monthly breakdown | Monatsübersicht |
| ID | ID |
| Payment date | Zahlungsdatum |
| Reporting month | Berichtsmonat |
| Organisation | Organisation |
| Category | Kategorie |
| Type | Art |
| Frequency | Häufigkeit |
| Currency | Währung |
| Gross (original) | Brutto (Original) |
| Net (original) | Netto (Original) |
| Conversion | Umrechnung |
| Rate (EUR per 1 unit) | Kurs (EUR je 1 Einheit) |
| Rate date | Kursdatum |
| Rate source | Kursquelle |
| Withholding tax (original) | Einbehaltene Steuer (Quellensteuer) (Original) |
| Expenses (original) | Ausgaben (Original) |
| Unallocated (original) | Nicht zugeordnet (Original) |
| Monthly equivalent gross EUR (recurring only) | Brutto-Monatsäquivalent EUR (nur wiederkehrende) |
| Income period start | Beginn des Einkommenszeitraums |
| Income period end | Ende des Einkommenszeitraums |
| Import batch | Importvorgang |
| Comment | Kommentar |
| Payment-level detail | Einzelne Zahlungen |
| Share of gross | Anteil am Brutto |
| By organisation | Nach Organisation |
| By category | Nach Kategorie |
| Organisation by category | Organisation nach Kategorie |
| Original currency | Originalwährung |
| Gross (original currency) | Brutto (Originalwährung) |
| Net (original currency) | Netto (Originalwährung) |
| Withholding tax (original currency) | Einbehaltene Steuer (Quellensteuer) (Originalwährung) |
| Expenses (original currency) | Ausgaben (Originalwährung) |
| Unallocated (original currency) | Nicht zugeordnet (Originalwährung) |
| Converted payments | Umgerechnete Zahlungen |
| Gross EUR (converted only) | Brutto EUR (nur umgerechnete) |
| Net EUR (converted only) | Netto EUR (nur umgerechnete) |
| Original-currency summary | Übersicht nach Originalwährung |
| Gross monthly equivalent EUR | Brutto-Monatsäquivalent EUR |
| Net monthly equivalent EUR | Netto-Monatsäquivalent EUR |
| Recurring payments | Wiederkehrende Zahlungen |
| One-off items excluded | Einmalige Posten ausgeschlossen |
| Recurring without net | Wiederkehrende ohne Netto |
| Normalised monthly recurring income | Normalisierte monatliche wiederkehrende Einnahmen |
| Issue | Befund |
| Payment ID | Zahlungs-ID |
| Rate | Kurs |
| Missing data and reconciliation | Fehlende Daten und Abgleich |
| SBK contribution estimate | Schätzung des SBK-Beitrags |
| Income type | Einkunftsart |
| Organisation country | Land der Organisation |
| Gross EUR (converted, signed sum) | Brutto EUR (umgerechnet, Summe mit Vorzeichen) |
| of which losses EUR (shown separately, not netted across categories) | davon Verluste EUR (getrennt ausgewiesen, nicht zwischen Kategorien verrechnet) |
| Original gross by currency | Originalbrutto je Währung |
| Withholding tax EUR (information, not credited) | Einbehaltene Steuer (Quellensteuer) EUR (nur zur Information, nicht angerechnet) |
| Manual-rate payments | Zahlungen mit manuellem Kurs |
| Flags | Hinweise |
| Tax information summary | Steuerübersicht (Information) |
| Check | Prüfung |
| Amount EUR | Betrag EUR |
| Rule | Regel |
| Result | Ergebnis |
| Note | Notiz |
| Tax checks (verified rules) | Steuerprüfungen (geprüfte Regeln) |

## C. Number, date and CSV formats (decided 2026-10-19)
- **Screen and printed reports** follow the selected language: German `1.234,50` and `19.10.2026`; English `1,234.50` and `2026-10-19` as today. Amounts show their ISO currency code after the number, in their own currency.
- **CSV exports** are **language-independent in format**: comma separator, dot decimal, no thousands separator, ISO dates, 2 decimals (the same as the stored values, rounded for export only). CSV headings and labels are **always English** (owner decision 2026-10-19: the CSV is mainly for bulk data input), so exports from either language can be mixed. A `Language` and a `Format` row in each CSV states this.
