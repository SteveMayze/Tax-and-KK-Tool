"""Phase 12: language setting, formats, German reports and the language-independent CSV. Synthetic data only."""
import datetime
import gettext
import re
from decimal import Decimal as D
from html import unescape
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import translation

from core.models import AssessmentSettings
from core.services import i18n, reports
from core.services.conversion import convert_payment

from .test_helpers import make_payment

ROOT = Path(settings.BASE_DIR)
LOCALE = ROOT / 'core' / 'locale' / 'de' / 'LC_MESSAGES'


def glossary_tables():
    """(section A rows: {english: german}, every cell of every table)."""
    text = (ROOT / 'docs' / 'glossary.md').read_text()
    cells, section_a = set(), {}
    for line in text.splitlines():
        if not line.startswith('|') or set(line) <= set('|- '):
            continue
        parts = [c.strip() for c in line.strip().strip('|').split('|')]
        cells.update(parts)
        if len(parts) == 7 and parts[0].isdigit():
            section_a[parts[1]] = parts[2]
    return section_a, cells


def build_data():
    """Payments in several currencies, a loss and an unconverted one."""
    from core.models import IncomeCategory
    IncomeCategory.objects.filter(name='Interest').update(may_be_negative=True, sbk_treatment='capital', tax_income_type='capital')
    IncomeCategory.objects.filter(name='Salary').update(sbk_treatment='employment', tax_income_type='employment')
    for gross, net, ccy, cat, date in [('1234.5', '1234.5', 'EUR', 'Salary', datetime.date(2026, 3, 15)),
                                       ('100', '85', 'AUD', 'Interest', datetime.date(2026, 5, 2)),
                                       ('-40', '-40', 'EUR', 'Interest', datetime.date(2026, 6, 2))]:
        p = make_payment(gross=gross, net=net, currency=ccy, category=cat, date=date, org='Alpha Co',
                         withholding_tax=D('15') if ccy == 'AUD' else D('0'))
        p.save()
        convert_payment(p, manual_rate='0.6') if ccy != 'EUR' else convert_payment(p)
    make_payment(gross='50', currency='GBP', date=datetime.date(2026, 7, 1), org='Alpha Co').save()


class LoggedInTestCase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('lang', password='pw-for-tests-123')
        self.client.force_login(self.user)

    def set_language(self, code):
        return self.client.post(reverse('set_language'), {'language': code, 'next': reverse('report_index')})


class LanguageSettingTests(LoggedInTestCase):
    def test_default_is_english_and_one_setting_switches_the_whole_app(self):
        self.assertEqual(AssessmentSettings.load().language, 'en')
        self.assertContains(self.client.get(reverse('home')), '<html lang="en">')
        r = self.set_language('de')
        self.assertRedirects(r, reverse('report_index'))
        r = self.client.get(reverse('home'))
        self.assertContains(r, '<html lang="de">')
        self.assertContains(r, 'Jahr hinzufügen')                      # takes effect immediately
        self.assertEqual(r['Content-Language'], 'de')
        self.set_language('en')
        self.assertContains(self.client.get(reverse('home')), 'Add year')

    def test_unknown_language_and_foreign_redirect_are_refused(self):
        self.client.post(reverse('set_language'), {'language': 'fr', 'next': 'https://evil.example/'})
        self.assertEqual(AssessmentSettings.load().language, 'en')
        r = self.client.post(reverse('set_language'), {'language': 'de', 'next': 'https://evil.example/'})
        self.assertRedirects(r, reverse('home'))

    def test_changing_language_needs_login_and_post(self):
        self.client.logout()
        self.assertEqual(self.client.post(reverse('set_language'), {'language': 'de'}).status_code, 302)
        self.assertEqual(AssessmentSettings.load().language, 'en')
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('set_language')).status_code, 405)

    def test_selector_is_in_every_page_header(self):
        r = self.client.get(reverse('report_index'))
        self.assertContains(r, 'name="language" value="de"')


class FormatTests(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        build_data()

    def test_helpers(self):
        with translation.override('de'):
            self.assertEqual(i18n.number(D('1234.5')), '1.234,50')
            self.assertEqual(i18n.date_text(datetime.date(2026, 10, 19)), '19.10.2026')
            self.assertEqual(i18n.month_name(3), 'März')
            self.assertEqual(i18n.plain_decimal(D('1.2000')), '1,2')
        with translation.override('en'):
            self.assertEqual(i18n.number(D('1234.5')), '1,234.50')
            self.assertEqual(i18n.date_text(datetime.date(2026, 10, 19)), '2026-10-19')
            self.assertEqual(i18n.month_name(3), 'March')

    def test_amount_and_date_change_format_with_the_setting_and_currency_codes_stay(self):
        url = reverse('month_detail', args=[2026, 3])
        self.assertContains(self.client.get(url), '1,234.50 EUR')
        self.set_language('de')
        r = self.client.get(url)
        self.assertContains(r, '1.234,50 EUR')
        self.assertContains(r, '15.03.2026')
        self.assertContains(r, 'März 2026')
        aud = self.client.get(reverse('month_detail', args=[2026, 5]))
        self.assertContains(aud, '100,00 AUD')                          # own currency, nothing converted
        self.assertContains(aud, '60,00')                               # EUR at the stored rate

    def test_years_and_counts_are_not_given_thousands_separators(self):
        self.set_language('de')
        self.assertContains(self.client.get(reverse('home')), '>2026<')


class ReportLanguageTests(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        build_data()
        self.glossary_a, self.glossary_cells = glossary_tables()

    def page(self, key, lang):
        self.set_language(lang)
        return self.client.get(reverse('report_view', args=[key]) + '?year=2026')

    def test_every_report_renders_in_both_languages(self):
        for key in reports.REPORTS:
            for lang in ('en', 'de'):
                self.assertEqual(self.page(key, lang).status_code, 200, (key, lang))

    def test_headings_and_titles_equal_the_glossary_in_german(self):
        for key, spec in reports.REPORTS.items():
            with translation.override('de'):
                report = spec.build(2026)
            for column in report.columns:
                if column.key.startswith('cat_'):         # the organisation-by-category columns are category names (data)
                    continue
                label = str(column.label)
                stripped = label[:-4] if label.endswith(' EUR') else label      # the 14 SBK columns are the glossary label + " EUR"
                self.assertTrue(label in self.glossary_cells or stripped in self.glossary_cells, (key, label))
            self.assertIn(str(report.title), self.glossary_cells, (key, str(report.title)))

    def test_the_14_sbk_headings_are_exactly_the_glossary_labels(self):
        with translation.override('en'):
            english = [str(c.label) for c in reports.REPORTS['sbk'].build(2026).columns]
        with translation.override('de'):
            german = [str(c.label) for c in reports.REPORTS['sbk'].build(2026).columns]
        wanted = {'Employment', 'Pension', 'Self-employed', 'Rental', 'Capital', 'One-off (1/12)', 'Base before limits',
                  'Assessed base', 'Limit applied', 'Health: general part', 'Health: additional contribution', 'Health total',
                  'Care insurance', 'Total contribution'}
        self.assertEqual(set(self.glossary_a), wanted)
        checked = 0
        for en, de in zip(english, german):
            key = en[:-4] if en.endswith(' EUR') else en
            if key in wanted:
                expected = self.glossary_a[key] + (' EUR' if en.endswith(' EUR') else '')
                self.assertEqual(de, expected)
                checked += 1
        self.assertEqual(checked, 14)

    def test_german_pages_have_no_english_report_text_left(self):
        with translation.override('en'):
            english_texts = set()
            for spec in reports.REPORTS.values():
                rep = spec.build(2026)
                english_texts |= {str(c.label) for c in rep.columns if not c.key.startswith('cat_')} | {str(rep.title)}
                english_texts |= {str(l) for l, _t in rep.basis} | {str(n) for n in rep.notes}
        english_texts = {t for t in english_texts if len(t) > 3}
        for key in reports.REPORTS:
            html = unescape(self.page(key, 'de').content.decode())
            body = html.split('<main>')[1].split('</main>')[0]
            visible = re.sub(r'<[^>]+>', '\n', body)
            for text in english_texts:
                if text in visible and text not in self.same_in_german(text):
                    self.fail(f'{key}: English text left on the German page: {text!r}')
            for word in ('Gross', 'Payments', 'Unconverted', 'Excluded', 'Rounding', 'Currency', 'Basis:'):
                self.assertNotRegex(visible, r'\b' + re.escape(word) + r'\b', (key, word))

    @staticmethod
    def same_in_german(text):
        """English strings that are legitimately identical in German (names, codes)."""
        return {t for t in ('ID', 'Status', 'Version', 'Organisation', 'Basis', 'Normal', 'Information')} if text in (
            'ID', 'Status', 'Version', 'Organisation', 'Basis', 'Normal', 'Information') else set()

    def test_german_sbk_report_uses_german_formats_and_labels(self):
        html = self.page('sbk', 'de').content.decode()
        self.assertIn('Beitragsbemessungsgrundlage EUR', html)
        self.assertIn('1.318,33', html)                                 # the legal minimum base, German formatted
        self.assertIn('Mindestgrenze', html)
        self.assertIn('Krankenversicherung 14,6%', html)                 # percentages use the decimal comma too
        self.assertIn('NICHT von der SBK bestätigt', html)
        self.assertIn('KEINE Beitragsfestsetzung', html)

    def test_switching_back_restores_english_output(self):
        english = self.page('annual', 'en').content.decode()
        self.page('annual', 'de')
        again = self.page('annual', 'en').content.decode()
        strip = lambda h: re.sub(r'Generated [^<]*', '', re.sub(r'csrfmiddlewaretoken" value="[^"]*"', '', h))
        self.assertEqual(strip(english), strip(again))
        self.assertIn('Gross EUR (signed sum)', again)


class CsvIsLanguageIndependentTests(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        build_data()

    def csv(self, key, lang):
        self.set_language(lang)
        r = self.client.get(reverse('report_csv', args=[key]) + '?year=2026')
        self.assertEqual(r.status_code, 200)
        return r.content.decode()

    def test_german_setting_gives_the_same_csv_as_english(self):
        norm = lambda t: re.sub(r'Generated \(UTC\),[^\r\n]*', '', t)
        for key in reports.REPORTS:
            self.assertEqual(norm(self.csv(key, 'en')), norm(self.csv(key, 'de')), key)

    def test_csv_format_rows_headings_numbers_and_dates(self):
        text = self.csv('payments', 'de')
        self.assertIn('Report format version,2', text)
        self.assertIn('Language,English (CSV headings are always English)', text)
        self.assertIn('Format,Comma-separated; decimal point;', text)
        header = text.split('\r\n\r\n')[1].split('\r\n')[0]
        self.assertTrue(header.startswith('ID,Payment date,'))
        self.assertIn(',1234.50,', text)                                 # dot decimal, no thousands separator
        self.assertIn('2026-03-15', text)                                # ISO date
        self.assertNotIn(';', header)

    def test_formula_injection_protection_is_unchanged(self):
        p = make_payment(gross='5', org='=cmd()', date=datetime.date(2026, 4, 1))
        p.save()
        self.assertIn("'=cmd()", self.csv('payments', 'de'))


class TranslationFilesTests(SimpleTestCase):
    def test_every_message_is_translated_with_matching_placeholders(self):
        text = (LOCALE / 'django.po').read_text()
        self.assertNotIn('#, fuzzy', text)
        entries = re.findall(r'^msgid ((?:"(?:[^"\\]|\\.)*"\n)+)msgstr ((?:"(?:[^"\\]|\\.)*"\n?)+)', text, flags=re.M)
        self.assertGreater(len(entries), 500)
        field = re.compile(r'%\((\w+)\)[sdr]|%%')
        for msgid, msgstr in entries:
            if msgid == '""\n':
                continue
            idv = ''.join(re.findall(r'"((?:[^"\\]|\\.)*)"', msgid))
            strv = ''.join(re.findall(r'"((?:[^"\\]|\\.)*)"', msgstr))
            self.assertTrue(strv, f'untranslated: {idv}')
            self.assertEqual(sorted(field.findall(idv)), sorted(field.findall(strv)), idv)

    def test_compiled_catalogue_is_in_sync_with_the_po_file(self):
        mo = LOCALE / 'django.mo'
        self.assertTrue(mo.exists(), 'run: msgfmt -o core/locale/de/LC_MESSAGES/django.mo core/locale/de/LC_MESSAGES/django.po')
        cat = gettext.GNUTranslations(mo.open('rb'))
        po = (LOCALE / 'django.po').read_text()
        ids = [''.join(re.findall(r'"((?:[^"\\]|\\.)*)"', m)).replace('\\"', '"').replace('\\n', '\n').replace('\\\\', '\\')
               for m in re.findall(r'^msgid ((?:"(?:[^"\\]|\\.)*"\n)+)msgstr ', po, flags=re.M)]
        for i in ids:
            if i:
                self.assertIn(i, cat._catalog, f'.mo is stale, missing: {i[:60]}')

    def test_the_image_build_ships_the_translations(self):
        containerfile = (ROOT / 'Containerfile').read_text()
        self.assertIn('COPY core ./core', containerfile)                # the locale folder lives under core/
        for name in ('.containerignore', '.dockerignore'):
            ignored = (ROOT / name).read_text().split()
            self.assertNotIn('*.mo', ignored)
            self.assertNotIn('locale', ignored)
        tracked = __import__('subprocess').run(['git', 'ls-files', 'core/locale'], cwd=ROOT, capture_output=True, text=True).stdout
        if tracked:
            self.assertIn('core/locale/de/LC_MESSAGES/django.mo', tracked)
