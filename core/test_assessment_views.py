import datetime
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import AnnualInput, AssessmentSettings, IncomeCategory, ReportingYear

from .test_policies_sbk import add, build_2026


class AssessmentViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('t', password='pw-for-tests-123')
        self.client.force_login(self.user)

    def test_login_required_and_methods(self):
        ReportingYear.objects.create(year=2026)
        i = AnnualInput.objects.create(year=ReportingYear.objects.get(year=2026), treatment='rental')
        urls = [reverse('assessment_settings'), reverse('annual_inputs', args=[2026]),
                reverse('annual_input_delete', args=[2026, i.pk]), reverse('report_view', args=['sbk']) + '?year=2026',
                reverse('report_csv', args=['tax_checks']) + '?year=2026']
        self.client.logout()
        for url in urls:
            for m in (self.client.get, self.client.post):
                r = m(url)
                self.assertEqual(r.status_code, 302, url)
                self.assertTrue(r.url.startswith(reverse('login')), url)
        self.assertTrue(AnnualInput.objects.filter(pk=i.pk).exists())
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('annual_input_delete', args=[2026, i.pk])).status_code, 405)

    def test_settings_page_shows_decisions_and_saves(self):
        r = self.client.get(reverse('assessment_settings'))
        self.assertContains(r, 'not confirmed with SBK')
        self.assertContains(r, 'upper-bound')
        self.assertContains(r, '5812.50')
        self.assertContains(r, 'verified 2026-10-18')
        r = self.client.post(reverse('assessment_settings'), {
            'kv_rate': 'reduced', 'kv_rate_confirmed': 'on', 'pflege': 'base'}, follow=True)
        self.assertContains(r, 'Assessment settings saved')
        s = AssessmentSettings.load()
        self.assertEqual((s.kv_rate, s.kv_rate_confirmed, s.pflege, s.joint_assessment), ('reduced', True, 'base', False))
        self.assertNotContains(r, 'is <strong>not confirmed with SBK</strong>')

    def test_settings_rejects_invalid_choices(self):
        r = self.client.post(reverse('assessment_settings'), {'kv_rate': 'weird', 'pflege': 'childless'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(AssessmentSettings.load().kv_rate, 'general')

    def test_annual_inputs_create_replace_validate_delete(self):
        ReportingYear.objects.create(year=2026)
        url = reverse('annual_inputs', args=[2026])
        self.assertContains(self.client.get(url), 'defaults apply')
        r = self.client.post(url, {'treatment': 'rental', 'costs_eur': '600', 'first_month': '7', 'last_month': '12', 'note': 'since July'}, follow=True)
        self.assertContains(r, 'since July')
        r = self.client.post(url, {'treatment': 'rental', 'costs_eur': '650', 'first_month': '7', 'last_month': '12'}, follow=True)
        self.assertEqual(AnnualInput.objects.count(), 1)                       # replaced, not duplicated
        self.assertEqual(AnnualInput.objects.get().costs_eur, D('650'))
        for bad, text in [({'treatment': 'rental', 'costs_eur': '1', 'first_month': '9', 'last_month': '3'}, 'before the first month'),
                          ({'treatment': 'rental', 'costs_eur': '-5', 'first_month': '1', 'last_month': '12'}, 'greater than or equal to 0'),
                          ({'treatment': 'rental', 'costs_eur': '1', 'first_month': '13', 'last_month': '12'}, 'less than or equal to 12'),
                          ({'treatment': 'pension', 'costs_eur': '1', 'first_month': '1', 'last_month': '12'}, 'valid choice')]:
            r = self.client.post(url, bad)
            self.assertContains(r, text, msg_prefix=str(bad))
        self.assertEqual(AnnualInput.objects.count(), 1)
        i = AnnualInput.objects.get()
        self.client.post(reverse('annual_input_delete', args=[2026, i.pk]))
        self.assertEqual(AnnualInput.objects.count(), 0)

    def test_annual_inputs_unknown_year_404(self):
        self.assertEqual(self.client.get(reverse('annual_inputs', args=[1999])).status_code, 404)

    def test_category_mapping_form_and_list(self):
        cat = IncomeCategory.objects.get(name='Rental')
        self.assertContains(self.client.get(reverse('category_list')), 'not mapped')
        r = self.client.post(reverse('category_edit', args=[cat.pk]), {
            'name': 'Rental', 'active': 'on', 'sbk_treatment': 'rental', 'tax_income_type': 'rental'}, follow=True)
        cat.refresh_from_db()
        self.assertEqual((cat.sbk_treatment, cat.tax_income_type), ('rental', 'rental'))
        self.assertContains(r, 'Rental income')
        r = self.client.post(reverse('category_edit', args=[cat.pk]), {'name': 'Rental', 'active': 'on', 'sbk_treatment': 'nonsense'})
        self.assertContains(r, 'valid choice')
        cat.refresh_from_db()
        self.assertEqual(cat.sbk_treatment, 'rental')
        self.client.post(reverse('category_edit', args=[cat.pk]), {'name': 'Rental', 'active': 'on'})   # clearing = unmapped
        cat.refresh_from_db()
        self.assertEqual((cat.sbk_treatment, cat.tax_income_type), ('', ''))

    def test_seeded_categories_start_unmapped(self):
        self.assertFalse(IncomeCategory.objects.exclude(sbk_treatment='').exists())
        self.assertFalse(IncomeCategory.objects.exclude(tax_income_type='').exists())

    def test_sbk_report_page_and_csv(self):
        build_2026()
        r = self.client.get(reverse('report_view', args=['sbk']) + '?year=2026')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'SBK contribution estimate')
        self.assertContains(r, '4,747.40')
        self.assertContains(r, '3,865.12')
        self.assertContains(r, 'NOT an SBK assessment')
        self.assertContains(r, 'NOT confirmed with SBK')
        self.assertContains(r, reverse('annual_inputs', args=[2026]))
        self.assertContains(r, 'Other (1 payment(s)')
        c = self.client.get(reverse('report_csv', args=['sbk']) + '?year=2026')
        self.assertEqual(c['Content-Disposition'], 'attachment; filename="report-sbk-2026.csv"')
        self.assertIn('4747.40', c.content.decode())

    def test_sbk_report_for_unverified_year_redirects_with_message(self):
        add(100, datetime.date(2025, 5, 1), 'Pension')
        for name in ('report_view', 'report_csv'):
            r = self.client.get(reverse(name, args=['sbk']) + '?year=2025', follow=True)
            self.assertRedirects(r, reverse('report_index'))
            self.assertContains(r, 'No verified SBK parameters for 2025')

    def test_sbk_requires_a_year(self):
        r = self.client.get(reverse('report_view', args=['sbk']), follow=True)
        self.assertContains(r, 'needs a specific year')

    def test_tax_pages_render(self):
        add(100, datetime.date(2026, 5, 1), 'Interest')
        for key in ('tax_summary', 'tax_checks'):
            r = self.client.get(reverse('report_view', args=[key]) + '?year=2026')
            self.assertEqual(r.status_code, 200, key)
            self.assertContains(r, 'Double-taxation treaties')
        self.assertEqual(self.client.get(reverse('report_view', args=['tax_summary'])).status_code, 200)   # all years allowed

    def test_report_index_lists_new_reports(self):
        r = self.client.get(reverse('report_index'))
        for title in ('SBK contribution estimate', 'Tax information summary', 'Tax checks (verified rules)'):
            self.assertContains(r, title)
