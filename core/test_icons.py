"""Phase 29 (ADR 0030): icons for common actions. Synthetic data only."""
import re
import shutil
import tempfile
from html.parser import HTMLParser
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from core.icons import ICONS
from core.models import ImportBatch, Payment
from core.services import imports as svc
from core.services.rates import FakeRateProvider

from .test_i18n import build_data
from .test_import_lifecycle import csv_for

ROOT = Path(settings.BASE_DIR)
TEMPLATES = list((ROOT / 'templates').rglob('*.html')) + list((ROOT / 'core' / 'templates').rglob('*.html'))


class IconSetTests(SimpleTestCase):
    def test_every_icon_named_in_a_template_exists(self):
        used = set()
        for path in TEMPLATES:
            used |= set(re.findall(r'{% icon "([a-z-]+)" %}', path.read_text()))
        self.assertTrue(used)
        self.assertEqual(sorted(used - set(ICONS)), [])

    def test_every_icon_in_the_set_is_used(self):
        used = set()
        for path in TEMPLATES:
            used |= set(re.findall(r'{% icon "([a-z-]+)" %}', path.read_text()))
        self.assertEqual(sorted(set(ICONS) - used), [])

    def test_no_template_has_an_inline_style(self):
        for path in TEMPLATES:
            self.assertNotRegex(path.read_text(), r'\sstyle\s*=', path.name)

    def test_icons_use_no_colour_and_no_external_reference(self):
        for name, markup in ICONS.items():
            self.assertNotRegex(markup, r'#[0-9a-fA-F]{3,8}|url\(|href', name)

    def test_licence_notice_is_present(self):
        self.assertIn('ISC', (ROOT / 'core' / 'icons.py').read_text())
        notice = (ROOT / 'docs' / 'third-party-notices.md').read_text()
        self.assertIn('Lucide Icons and Contributors', notice)
        self.assertIn('Cole Bemis', notice)

    def test_print_stylesheet_hides_buttons_and_links_styled_as_buttons(self):
        printed = (ROOT / 'core' / 'static' / 'core' / 'base.css').read_text().split('@media print', 1)[1]
        self.assertIn('button, .btn', printed)


class Controls(HTMLParser):
    """Collects the links and buttons of a page: their attributes, visible text, whether they hold an icon, and
    the method of the form around a button."""

    def __init__(self):
        super().__init__()
        self.found, self._open, self._forms = [], [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'form':
            self._forms.append((a.get('method') or 'get').lower())
        elif tag in ('a', 'button'):
            self._open.append({'tag': tag, 'attrs': a, 'text': '', 'icon': False, 'form': self._forms[-1] if self._forms else None})
        elif tag == 'svg' and self._open:
            self._open[-1]['icon'] = True
            assert a.get('aria-hidden') == 'true' and a.get('focusable') == 'false'

    def handle_endtag(self, tag):
        if tag == 'form' and self._forms:
            self._forms.pop()
        elif tag in ('a', 'button') and self._open:
            self.found.append(self._open.pop())

    def handle_data(self, data):
        if self._open:
            self._open[-1]['text'] += data


def controls(html):
    p = Controls()
    p.feed(html)
    return p.found


class AccessibleNameTests(TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        ov = override_settings(UPLOAD_DIR=self._tmp)
        ov.enable()
        self.addCleanup(ov.disable)
        self.addCleanup(shutil.rmtree, self._tmp, True)
        self.client.force_login(get_user_model().objects.create_user('ico', password='pw-for-tests-123'))
        build_data()
        self.payment = Payment.objects.get(payment_date__month=5)
        self.batch = svc.commit_batch(svc.stage_batch(csv_for('2024-03-15'), 'file.csv', FakeRateProvider({})))
        self.pages = [reverse(n) for n in ('home', 'organisation_list', 'category_list', 'import_list', 'report_index',
                                            'reconciliation', 'assessment_settings')] + [
            reverse('year_detail', args=[2026]), reverse('month_detail', args=[2026, 5]),
            reverse('payment_detail', args=[self.payment.pk]), reverse('report_view', args=['annual']),
            reverse('import_preview', args=[self.batch.pk]),
        ]

    def language(self, code):
        self.client.post(reverse('set_language'), {'language': code, 'next': '/'})

    def check_all_pages(self):
        icon_only = 0
        for url in self.pages:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)
            for c in controls(response.content.decode()):
                if c['icon'] and not c['text'].strip():
                    icon_only += 1
                    name = c['attrs'].get('aria-label', '')
                    self.assertTrue(name.strip(), (url, c['attrs']))
                    self.assertEqual(c['attrs'].get('title'), name, (url, c['attrs']))
                if c['tag'] == 'button' and c['icon']:
                    self.assertEqual(c['form'], 'post', (url, c['attrs']))        # nothing with an icon changes data via GET
        return icon_only

    def test_icon_only_controls_have_a_name_and_tooltip_in_english(self):
        self.assertGreater(self.check_all_pages(), 10)

    def test_icon_only_controls_have_a_name_and_tooltip_in_german(self):
        self.language('de')
        self.assertGreater(self.check_all_pages(), 10)

    def test_german_names_are_translated(self):
        self.language('de')
        html = self.client.get(reverse('month_detail', args=[2026, 5])).content.decode()
        names = {c['attrs'].get('aria-label') for c in controls(html) if c['icon'] and not c['text'].strip()}
        self.assertTrue({'Bearbeiten', 'Löschen'} <= names, names)
        self.assertNotIn('Edit', names)

    def test_delete_icon_links_still_only_open_the_confirmation_page(self):
        html = self.client.get(reverse('month_detail', args=[2026, 5])).content.decode()
        confirm = reverse('payment_delete', args=[self.payment.pk])
        self.assertTrue(any(c['attrs'].get('href') == confirm for c in controls(html)))
        self.assertEqual(self.client.get(confirm).status_code, 200)
        self.assertTrue(Payment.objects.filter(pk=self.payment.pk).exists())

    def test_logout_stays_a_post_button_beside_the_user_name(self):
        html = self.client.get(reverse('home')).content.decode()
        logout = [c for c in controls(html) if c['attrs'].get('aria-label') == 'Log out']
        self.assertEqual(len(logout), 1)
        self.assertEqual(logout[0]['form'], 'post')
        self.assertIn('>ico<', html)

    def test_no_link_with_an_icon_points_at_a_state_changing_url(self):
        post_only = ('toggle', 'refresh', 'logout', 'language', 'add/')
        for url in self.pages:
            for c in controls(self.client.get(url).content.decode()):
                if c['tag'] == 'a' and c['icon']:
                    href = c['attrs'].get('href', '')
                    self.assertFalse(any(w in href for w in post_only[:4]), (url, href))
