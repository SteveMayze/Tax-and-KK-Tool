"""Phase 13: design tokens, buttons, inputs, report layout and information popups. Synthetic data only."""
import re
import subprocess
import sys
from html import unescape
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import translation

from core import glossary
from core.models import AnnualInput, ConversionEvent, ImportBatch, IncomeCategory, Payment, ReportingMonth, ReportingYear
from core.services import report_csv, reports
from core.services.conversion import convert_payment

from .test_helpers import make_payment
from .test_i18n import build_data, glossary_tables

ROOT = Path(settings.BASE_DIR)
CSS = ROOT / 'core' / 'static' / 'core' / 'base.css'


class LoggedIn(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('vis', password='pw-for-tests-123')
        self.client.force_login(self.user)

    def language(self, code):
        self.client.post(reverse('set_language'), {'language': code, 'next': '/'})


class DesignTokenTests(SimpleTestCase):
    def test_every_text_pair_meets_wcag_aa(self):
        sys.path.insert(0, str(ROOT / 'tools'))
        try:
            import check_contrast
        finally:
            sys.path.pop(0)
        results, _unused = check_contrast.check()
        self.assertGreaterEqual(len(results), 20)
        failing = [r for r in results if not r[4]]
        self.assertEqual(failing, [])

    def test_the_script_runs_standalone_and_fails_on_a_bad_pair(self):
        ok = subprocess.run([sys.executable, str(ROOT / 'tools' / 'check_contrast.py')], capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stdout)
        sys.path.insert(0, str(ROOT / 'tools'))
        try:
            import check_contrast
        finally:
            sys.path.pop(0)
        bad = CSS.read_text().replace('--color-text-muted: #4a5b66', '--color-text-muted: #aaaaaa')
        self.assertTrue(any(not r[4] for r in check_contrast.check(bad)[0]))

    def test_colours_are_only_defined_as_tokens(self):
        css = CSS.read_text()
        after_root = css.split('}', 1)[1]
        self.assertEqual(re.findall(r'#[0-9a-fA-F]{3,8}\b', after_root), ['#000'])      # only the print stylesheet's black
        self.assertIn('var(--color-primary)', css)

    def test_palette_is_blue_teal(self):
        css = CSS.read_text()
        self.assertIn('--color-primary: #0b6b66', css)        # teal
        self.assertIn('--color-heading: #0b3a5b', css)        # deep blue

    def test_print_stylesheet_hides_controls_but_not_the_table(self):
        css = CSS.read_text()
        printed = css.split('@media print', 1)[1]
        for selector in ('.info-btn', 'nav', 'button'):
            self.assertIn(selector, printed)
        self.assertNotIn('table { display: none', printed)
        self.assertIn('thead { display: table-header-group', printed)

    def test_inputs_have_sensible_sizes(self):
        css = CSS.read_text()
        self.assertIn('min-width: 20ch', css)
        self.assertIn('min-height: 6.5em', css)               # about 4 rows
        self.assertIn('field-sizing: content', css)


class NoInlineStylesTests(LoggedIn):
    def test_rendered_main_screens_have_no_style_attributes(self):
        build_data()
        month = ReportingMonth.objects.get(year__year=2026, month=5)
        payment = Payment.objects.get(payment_date__month=5)
        batch = ImportBatch.objects.create(file_name='x.csv')
        urls = [reverse('home'), reverse('year_detail', args=[2026]), reverse('month_detail', args=[2026, 5]),
                reverse('payment_add', args=[2026, 5]), reverse('payment_edit', args=[payment.pk]),
                reverse('payment_detail', args=[payment.pk]), reverse('payment_delete', args=[payment.pk]),
                reverse('payment_recalculate', args=[payment.pk]), reverse('payment_correct_rate', args=[payment.pk]),
                reverse('report_index'), reverse('organisation_list'), reverse('category_list'),
                reverse('category_add'), reverse('assessment_settings'), reverse('annual_inputs', args=[2026]),
                reverse('import_list'), reverse('import_preview', args=[batch.pk]), reverse('import_commit', args=[batch.pk]),
                reverse('import_discard', args=[batch.pk]), reverse('reconciliation')]
        urls += [reverse('report_view', args=[k]) + '?year=2026' for k in reports.REPORTS]
        for lang in ('en', 'de'):
            self.language(lang)
            for url in urls:
                r = self.client.get(url)
                self.assertEqual(r.status_code, 200, url)
                self.assertNotRegex(r.content.decode(), r'\sstyle\s*=', url)
        self.client.logout()
        self.assertNotRegex(self.client.get(reverse('login')).content.decode(), r'\sstyle\s*=')


class InfoPopupTests(LoggedIn):
    def setUp(self):
        super().setUp()
        build_data()
        self.section_a = self.parse_section_a()

    @staticmethod
    def parse_section_a():
        text = (ROOT / 'docs' / 'glossary.md').read_text()
        rows = []
        for line in text.splitlines():
            if line.startswith('|'):
                parts = [c.strip() for c in line.strip().strip('|').split('|')]
                if len(parts) == 7 and parts[0].isdigit():
                    rows.append(parts)
        return rows

    def test_glossary_document_and_popup_data_agree(self):
        rows = self.section_a
        self.assertEqual(len(rows), 14)
        self.assertEqual(len(glossary.ENTRIES), 14)
        for row, entry in zip(rows, glossary.ENTRIES):
            _n, en, de, text_en, text_de, source, status = row
            self.assertEqual((en, de, text_en, text_de, source), (entry['en'], entry['de'], entry['text_en'],
                                                                    entry['text_de'], entry['source']))
            self.assertEqual(status, str(glossary.STATUS[entry['status']]))

    def page(self, lang):
        self.language(lang)
        return self.client.get(reverse('report_view', args=['sbk']) + '?year=2026').content.decode()

    def test_each_of_the_14_headings_has_a_focusable_button_and_a_popover_with_the_glossary_text(self):
        for lang in ('en', 'de'):
            html = self.page(lang)
            for row in self.section_a:
                _n, en, de, text_en, text_de, source, status = row
                key = next(e['key'] for e in glossary.ENTRIES if e['en'] == en)
                label, text = (de, text_de) if lang == 'de' else (en, text_en)
                button = re.search(r'<button type="button" class="info-btn" popovertarget="info-%s" aria-label="([^"]*)">i</button>' % key, html)
                self.assertIsNotNone(button, (lang, key))
                self.assertIn(unescape(button.group(1)), (f'Information: {label}',))
                pop = re.search(r'<div id="info-%s" popover[^>]*>(.*?)</div>' % key, html, flags=re.S)
                self.assertIsNotNone(pop, (lang, key))
                body = unescape(pop.group(1))
                self.assertIn(f'<h3>{label}</h3>', body)
                self.assertIn(f'<p>{text}</p>', body)
                self.assertIn(source, body)
                with translation.override(lang):
                    expected_status = str(glossary.entry(key, lang)['status'])
                self.assertEqual(expected_status == status, lang == 'en')       # German shows the translated status
                self.assertIn(expected_status, body)

    def test_buttons_are_real_buttons_inside_the_headings(self):
        html = self.page('en')
        headers = re.findall(r'<th[^>]*>(.*?)</th>', html, flags=re.S)
        with_info = [h for h in headers if 'info-btn' in h]
        self.assertEqual(len(with_info), 14)
        self.assertTrue(all(h.count('<button') == 1 and 'popovertarget' in h for h in with_info))

    def test_other_reports_have_no_info_icons(self):
        self.language('en')
        for key in ('annual', 'category', 'payments', 'tax_summary'):
            self.assertNotIn('info-btn', self.client.get(reverse('report_view', args=[key])).content.decode())

    def test_escape_closes_because_popovers_are_native(self):
        # Popovers in the default "auto" state close on Escape and on a click outside; no script is involved.
        html = self.page('en')
        self.assertIn(' popover ', html)
        self.assertNotIn('popover="manual"', html)
        self.assertNotIn('onclick', html)

    def test_icons_and_popups_are_not_in_the_csv(self):
        self.language('de')
        text = self.client.get(reverse('report_csv', args=['sbk']) + '?year=2026').content.decode()
        header = text.split('\r\n\r\n')[1].split('\r\n')[0]
        self.assertNotIn('Information', text)
        self.assertNotIn('popover', text)
        self.assertEqual(header.split(',')[0], 'Month')
        with translation.override('en'):
            labels = [str(c.label) for c in reports.REPORTS['sbk'].build(2026).columns]
        self.assertEqual(header.split(','), [l if ',' not in l else l for l in labels] if not any(',' in l for l in labels) else header.split(','))


class ReportLayoutTests(LoggedIn):
    def setUp(self):
        super().setUp()
        build_data()

    def test_notes_come_after_the_table_and_basis_stays_before_it(self):
        for key in reports.REPORTS:
            self.language('en')
            html = self.client.get(reverse('report_view', args=[key]) + '?year=2026').content.decode()
            table_end = html.find('</table>')
            if table_end < 0:
                table_end = html.find('No data for this period.')
            self.assertGreater(table_end, 0, key)
            basis = html.find('id="basis-heading"')
            self.assertTrue(0 < basis < html.find('<table class="report-table"') if '<table class="report-table"' in html else basis > 0, key)
            with translation.override('en'):
                has_notes = bool(reports.REPORTS[key].build(2026).notes)
            notes = html.find('class="report-notes"')
            if has_notes:
                self.assertGreater(notes, table_end, key)
            else:
                self.assertEqual(notes, -1, key)
            self.assertNotIn('<p class="note">', html[:table_end].split('id="basis-heading"')[1].split('<table')[0], key)

    def test_totals_row_uses_a_class_not_an_inline_style(self):
        self.language('en')
        html = self.client.get(reverse('report_view', args=['category']) + '?year=2026').content.decode()
        self.assertIn('<tr class="total-row">', html)


class ActionsNeedPostTests(LoggedIn):
    def setUp(self):
        super().setUp()
        build_data()
        self.p = Payment.objects.get(payment_date__month=5)

    def test_get_never_deletes_or_recalculates(self):
        before = (Payment.objects.count(), ReportingMonth.objects.count(), ReportingYear.objects.count(),
                  ConversionEvent.objects.count(), self.p.rate)
        cat = IncomeCategory.objects.create(name='Unused')
        for url in (reverse('payment_delete', args=[self.p.pk]), reverse('payment_recalculate', args=[self.p.pk]),
                    reverse('payment_correct_rate', args=[self.p.pk]), reverse('month_delete', args=[2026, 5]),
                    reverse('year_delete', args=[2026]), reverse('category_delete', args=[cat.pk])):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200, url)
            self.assertContains(r, 'method="post"')
        self.p.refresh_from_db()
        after = (Payment.objects.count(), ReportingMonth.objects.count(), ReportingYear.objects.count(),
                 ConversionEvent.objects.count(), self.p.rate)
        self.assertEqual(before, after)
        self.assertTrue(IncomeCategory.objects.filter(pk=cat.pk).exists())

    def test_actions_that_only_accept_post_refuse_get(self):
        year = ReportingYear.objects.get(year=2026)
        inp = AnnualInput.objects.create(year=year, treatment='capital')
        for url in (reverse('annual_input_delete', args=[2026, inp.pk]), reverse('convert_pending'), reverse('year_add'),
                    reverse('month_add', args=[2026, 8]), reverse('set_language')):
            self.assertEqual(self.client.get(url).status_code, 405, url)
        self.assertTrue(AnnualInput.objects.filter(pk=inp.pk).exists())

    def test_delete_buttons_are_post_forms_with_csrf(self):
        html = self.client.get(reverse('payment_delete', args=[self.p.pk])).content.decode()
        form = re.search(r'<form method="post">(.*?)</form>', html, flags=re.S).group(1)
        self.assertIn('csrfmiddlewaretoken', form)
        self.assertIn('class="btn-danger"', form)


class NoteFieldTests(LoggedIn):
    def test_payment_note_accepts_500_characters_and_renders_four_rows(self):
        ReportingMonth.for_date(__import__('datetime').date(2026, 3, 1))
        page = self.client.get(reverse('payment_add', args=[2026, 3])).content.decode()
        self.assertRegex(page, r'<textarea name="comment" cols="40" rows="4"')
        note = ('Zeile eins. ' * 60)[:600]
        data = {'payment_date': '2026-03-15', 'organisation_name': 'Note Co', 'category_name': 'Salary', 'currency': 'EUR',
                'gross_amount': '10.00', 'net_amount': '', 'frequency': 'monthly', 'comment': note}
        r = self.client.post(reverse('payment_add', args=[2026, 3]), data)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Payment.objects.get().comment, note.strip())

    def test_other_note_fields_are_text_areas_that_hold_a_paragraph(self):
        year = ReportingYear.objects.create(year=2026)
        paragraph = 'x' * 800
        r = self.client.post(reverse('annual_inputs', args=[2026]), {
            'treatment': 'capital', 'costs_eur': '10', 'first_month': '1', 'last_month': '12', 'note': paragraph})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(AnnualInput.objects.get().note, paragraph)
        page = self.client.get(reverse('annual_inputs', args=[2026])).content.decode()
        self.assertRegex(page, r'<textarea name="note" cols="40" rows="4"')
        self.client.post(reverse('year_notes', args=[2026]), {'notes': paragraph})
        year.refresh_from_db()
        self.assertEqual(year.notes, paragraph)
        self.assertRegex(self.client.get(reverse('year_detail', args=[2026])).content.decode(), r'<textarea name="notes" cols="40" rows="4"')

    def test_names_get_a_wide_input(self):
        page = self.client.get(reverse('category_add')).content.decode()
        self.assertIn('class="field-wide"', page)
        ReportingMonth.for_date(__import__('datetime').date(2026, 3, 1))
        page = self.client.get(reverse('payment_add', args=[2026, 3])).content.decode()
        self.assertEqual(page.count('class="field-wide"'), 2)           # organisation and category


class ButtonStyleTests(LoggedIn):
    def test_actions_are_buttons_with_consistent_styles(self):
        build_data()
        p = Payment.objects.get(payment_date__month=5)
        month = self.client.get(reverse('month_detail', args=[2026, 5])).content.decode()
        self.assertIn('class="btn btn-primary btn-icon" aria-label="Add payment"', month)       # icon-only (Phase 29)
        self.assertIn('class="btn btn-secondary btn-icon" aria-label="Edit"', month)
        self.assertIn('class="btn btn-danger btn-icon" aria-label="Delete"', month)
        detail = self.client.get(reverse('payment_detail', args=[p.pk])).content.decode()
        self.assertIn('class="btn btn-secondary btn-icon" aria-label="Edit"', detail)
        for text in ('Recalculate from source', 'Correct rate manually'):
            self.assertRegex(detail, r'class="btn btn-secondary">(<svg.*?</svg>)?\s*' + text)
        report = self.client.get(reverse('report_view', args=['annual'])).content.decode()
        self.assertIn('title="Download CSV"', report)                         # visible text stays "CSV"
        self.assertRegex(report, r'title="Download CSV"><svg.*?</svg>CSV</a>')
        form = self.client.get(reverse('payment_edit', args=[p.pk])).content.decode()
        self.assertIn('class="btn btn-secondary">Cancel', form)
        self.assertRegex(form, r'<button type="submit">(<svg.*?</svg>)?Save payment</button>')            # styled primary by the stylesheet
