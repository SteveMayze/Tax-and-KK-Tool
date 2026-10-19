"""Glossary entries for the 14 SBK report headings (Phase 13 information popups).

Single source for the popup text. docs/glossary.md section A mirrors it; a test (core/test_popups.py) fails when they
differ, so the document and the popups cannot drift apart. Add or change wording in BOTH places, German labels only
with the owner's approval (see docs/glossary.md)."""
from django.utils.translation import gettext_lazy

# status code -> text shown in the popup and in docs/glossary.md (English)
STATUS = {
    'verified': gettext_lazy('verified (SBK page)'),
    'approved': gettext_lazy('approved by owner 2026-10-19 (wording proposed)'),
}

ENTRIES = [
    dict(key='employment', en='Employment', de='Arbeitsentgelt',
         text_en='Income from employment, counted in the month it is paid (payment date).',
         text_de='Einkommen aus Beschäftigung, wird in dem Monat angesetzt, in dem es gezahlt wird (Zahlungsdatum).',
         source='SBK-01, BVSz §3 via `docs/rules/` (German word from the app\'s category mapping label). SBK-F names only "geringfügige Beschäftigung"', status='approved'),
    dict(key='pension', en='Pension', de='Renten und Versorgungsbezüge',
         text_en='Pensions and company pensions, counted in the month they are paid.',
         text_de='Renten und Betriebsrenten, werden in dem Monat angesetzt, in dem sie gezahlt werden.',
         source='SBK-F: "Renten und Versorgungsbezüge, zum Beispiel Betriebsrenten"', status='verified'),
    dict(key='self_employed', en='Self-employed', de='Einkünfte aus selbstständiger Tätigkeit',
         text_en='Profit from self-employment: the annual surplus after your entered costs, divided over the months you entered.',
         text_de='Gewinn aus selbstständiger Tätigkeit: der Jahresüberschuss nach den von Ihnen eingegebenen Kosten, verteilt auf die von Ihnen eingegebenen Monate.',
         source='SBK-F: "Einkünfte aus selbstständiger Tätigkeit"; SBK-05', status='verified'),
    dict(key='rental', en='Rental', de='Einkünfte aus Vermietung und Verpachtung',
         text_en='Rental surplus after your entered costs, divided over the months you entered.',
         text_de='Mietüberschuss nach den von Ihnen eingegebenen Kosten, verteilt auf die von Ihnen eingegebenen Monate.',
         source='SBK-F: "Einkünfte aus Vermietung und Verpachtung"; SBK-05', status='verified'),
    dict(key='capital', en='Capital', de='Einkünfte aus Kapitalvermögen',
         text_en='Interest and dividends: annual surplus after the 51 EUR flat costs (or your higher proven costs), divided over the months you entered.',
         text_de='Zinsen und Dividenden: Jahresüberschuss nach der Kostenpauschale von 51 EUR (oder Ihren höheren nachgewiesenen Kosten), verteilt auf die von Ihnen eingegebenen Monate.',
         source='SBK-F: "Einkünfte aus Kapitalvermögen, zum Beispiel Zins- und Dividendenerträge"; SBK-03', status='verified'),
    dict(key='one_off', en='One-off (1/12)', de='Einmalige Einnahmen (1/12)',
         text_en='A one-off amount spread at one twelfth per month for twelve months, starting with the month of receipt.',
         text_de='Ein einmaliger Betrag, verteilt mit einem Zwölftel pro Monat über zwölf Monate, beginnend mit dem Monat des Zuflusses.',
         source='SBK-06 (BVSz §5(3)); the phrase "Einmalzahlung" is not on SBK-F', status='approved'),
    dict(key='base', en='Base before limits', de='Beitragspflichtige Einnahmen vor Begrenzung',
         text_en="The month's total of the income types above, before the minimum and maximum are applied.",
         text_de='Die Summe der oben genannten Einkunftsarten im Monat, bevor Mindest- und Höchstgrenze angewendet werden.',
         source='SBK-01, SBK-07', status='approved'),
    dict(key='assessed', en='Assessed base', de='Beitragsbemessungsgrundlage',
         text_en='The monthly amount the contribution is calculated on, after the minimum and maximum.',
         text_de='Der monatliche Betrag, auf dem der Beitrag berechnet wird, nach Anwendung von Mindest- und Höchstgrenze.',
         source='SBK-08, SBK-09', status='approved'),
    dict(key='limit', en='Limit applied', de='Angewandte Grenze (Mindest- / Höchstgrenze)',
         text_en='Shows whether the legal minimum base ("minimum") or the ceiling ("maximum") replaced your income. Ceiling 2026: 5,812.50 EUR per month; minimum 1,318.33 EUR per month.',
         text_de='Zeigt, ob die gesetzliche Mindestbemessungsgrundlage („Mindestgrenze“) oder die Obergrenze („Höchstgrenze“) Ihr Einkommen ersetzt hat. Beitragsbemessungsgrenze 2026: 5.812,50 EUR pro Monat; Mindestbemessungsgrundlage: 1.318,33 EUR pro Monat.',
         source='SBK-F: "Beitragsbemessungsgrenze von monatlich 5.812,50 €"; "Die untere Grenze zur Beitragsberechnung liegt bei monatlich 1.318,33 €"; the words "Beitragsbemessungsgrenze" and "untere Grenze" are quoted from the page, the label as a whole is my wording', status='approved'),
    dict(key='kv_general', en='Health: general part', de='Krankenversicherung: allgemeiner Anteil (14,6 %)',
         text_en='Health contribution at the general rate of 14.6 % of the assessed base (the app uses the general rate as an upper bound until SBK confirms yours).',
         text_de='Krankenversicherungsbeitrag zum allgemeinen Satz von 14,6 % der Bemessungsgrundlage (die Anwendung nimmt den allgemeinen Satz als Obergrenze, bis die SBK Ihren Satz bestätigt).',
         source='SBK-10; SBK-F "allgemeiner Beitragssatz" (that page quotes 18,4 % including the additional contribution)', status='approved'),
    dict(key='kv_zusatz', en='Health: additional contribution', de='Krankenversicherung: Zusatzbeitrag (3,8 %)',
         text_en="SBK's additional contribution, 3.8 % of the assessed base; it can change during a year.",
         text_de='Zusatzbeitrag der SBK, 3,8 % der Bemessungsgrundlage; er kann sich im Laufe eines Jahres ändern.',
         source='SBK-B: "Darin enthalten ist ein Zusatzbeitrag von 3,8 Prozent."; the word "Zusatzbeitrag" is quoted from the page, the label as a whole is my wording', status='approved'),
    dict(key='kv', en='Health total', de='Krankenversicherung gesamt',
         text_en='General part plus additional contribution. SBK\'s own table calls the health-insurance amount "Krankenkassen-Beitrag".',
         text_de='Allgemeiner Anteil plus Zusatzbeitrag. In der Tabelle der SBK heißt der Krankenversicherungsbetrag „Krankenkassen-Beitrag“.',
         source='SBK-F table; SBK-17', status='approved'),
    dict(key='pflege', en='Care insurance', de='Pflegeversicherung',
         text_en='Care-insurance contribution on the same base (4.2 % assumed: age 23 or over, no children).',
         text_de='Beitrag zur Pflegeversicherung auf derselben Grundlage (angenommen 4,2 %: Alter 23 oder älter, keine Kinder).',
         source='SBK-F: "Pflegeversicherung", "Pflegekassen-Beitrag"; "Für Versicherte über 23 Jahren und ohne Kinder beträgt der Beitragssatz 4,2 %."', status='verified'),
    dict(key='total', en='Total contribution', de='Gesamtbeitrag',
         text_en='Health total plus care insurance for the month.',
         text_de='Krankenversicherung gesamt plus Pflegeversicherung für den Monat.',
         source='SBK-F table: "Gesamtbeitrag/Monat"', status='verified'),
]
BY_KEY = {e['key']: e for e in ENTRIES}


def entry(key, language):
    """The popup content for a report column key in the given language ('en' or 'de'), or None."""
    e = BY_KEY.get(key)
    if e is None:
        return None
    de = language == 'de'
    return {'key': key, 'label': e['de'] if de else e['en'], 'text': e['text_de'] if de else e['text_en'],
            'source': e['source'], 'status': str(STATUS[e['status']])}
