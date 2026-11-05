"""Review-page prompts (ADR 0040): a missing ASX code is asked for, and the country of a NEW organisation is confirmed at
import. Synthetic text only."""
import datetime
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import ImportBatch, ImportRow, Organisation, Payment
from core.services import imports as svc
from core.services import org_countries, pdf_imports
from core.services.rates import FakeRateProvider

from .test_pdf_imports import PROVIDER, UploadDirMixin
from .test_pdf_support import DATE_PAID, MUFG_STYLE, make_pdf

NO_CODE = [l for l in DATE_PAID if not l.startswith('T 0000003')] + [
    'This distribution advice relates to the distribution payment for your holding in Example Property Group and is']
PROVIDER = FakeRateProvider({('AUD', datetime.date(2025, 2, 27)): D('0.6'), ('AUD', datetime.date(2025, 5, 12)): D('0.6'),
                             ('USD', datetime.date(2025, 5, 12)): D('0.9')})


class Staging(UploadDirMixin, TestCase):
    def stage(self, lines, name='a.pdf'):
        return pdf_imports.stage_pdf_batch([(name, make_pdf([lines]))], PROVIDER)


class MissingCodeTests(Staging):
    def test_a_statement_without_an_asx_code_stages_one_blocked_row_with_the_explanation(self):
        batch = self.stage(NO_CODE)
        row = batch.rows.get()
        self.assertEqual((row.status, row.data['organisation'], row.data['gross_amount']), ('invalid', '', '108.00'))
        text = ' '.join(row.errors)
        self.assertIn('The ASX code was not found in this statement', text)
        self.assertIn('"Example Property Group"', text)
        self.assertNotIn('_org_hint', row.data)
        with self.assertRaises(svc.ImportStateError):
            svc.commit_batch(batch)

    def test_editing_the_organisation_makes_the_row_committable(self):
        batch = self.stage(NO_CODE)
        row = batch.rows.get()
        data = {k: v for k, v in row.data.items() if not k.startswith('_')}
        data['organisation'] = 'Example Property Group (EPG)'
        svc.update_row(row, data, PROVIDER)
        row.refresh_from_db()
        self.assertEqual((row.status, row.errors), ('valid', []))
        svc.commit_batch(batch)
        self.assertEqual(Payment.objects.get().organisation.name, 'Example Property Group (EPG)')

    def test_existing_organisation_is_proposed_only_when_exactly_one_matches(self):
        text = lambda: ' '.join(self.stage(NO_CODE, 'z%d.pdf' % Organisation.objects.count()).rows.get().errors)
        self.assertNotIn('Existing organisation', text())
        Organisation.objects.create(name='Example Property Group (EPG)')
        self.assertIn('Existing organisation that starts with this name (not applied', text())
        self.assertIn('Example Property Group (EPG)', text())
        Organisation.objects.create(name='Example Property Group Trust (EPT)')
        self.assertNotIn('Existing organisation', text())

    def test_other_missing_anchors_still_refuse(self):
        for drop in ('DATE PAID', 'NET PAYMENT'):
            lines = [l for l in NO_CODE if not l.startswith(drop)]
            with self.assertRaises(svc.ImportFileError):
                self.stage(lines)

    def test_statements_with_a_code_are_unchanged(self):
        row = self.stage(DATE_PAID).rows.get()
        self.assertEqual((row.status, row.data['organisation']), ('valid', 'Example Property Group (EPG)'))


class CountryTests(Staging):
    def rows(self, batch, *specs):
        for i, (org, ccy, reader) in enumerate(specs, start=1):
            ImportRow.objects.create(batch=batch, line_number=i, data={'organisation': org, 'currency': ccy}, original={},
                                     status='valid', reader_country=reader)

    def test_proposal_order_reader_then_currency_then_blank_and_eur_is_never_inferred(self):
        batch = ImportBatch.objects.create()
        self.rows(batch, ('From Reader', 'USD', 'DE'), ('From Currency', 'GBP', ''), ('Euro Only', 'EUR', ''), ('Nothing', 'JPY', ''))
        new, blank = org_countries.review(batch)
        got = {n['name']: (n['proposed'], n['source']) for n in new}
        self.assertEqual(got, {'From Reader': ('DE', 'reader'), 'From Currency': ('GB', 'currency'),
                               'Euro Only': ('', ''), 'Nothing': ('', '')})
        self.assertEqual(blank, [])

    def test_control_only_for_new_organisations_and_existing_ones_are_never_changed_by_default(self):
        Organisation.objects.create(name='Has Country', country='FR')
        Organisation.objects.create(name='Blank One')
        batch = ImportBatch.objects.create()
        self.rows(batch, ('Has Country', 'AUD', 'AU'), ('Blank One', 'AUD', 'AU'), ('Brand New', 'AUD', 'AU'))
        new, blank = org_countries.review(batch)
        self.assertEqual([n['name'] for n in new], ['Brand New'])
        self.assertEqual([(b['name'], b['proposed'], b['fill']) for b in blank], [('Blank One', 'AU', False)])

    def test_invalid_code_is_rejected_and_nothing_saved(self):
        batch = self.stage(MUFG_STYLE)
        with self.assertRaises(org_countries.CountryError):
            org_countries.save_choices(batch, {'acme mining limited (acm)': 'XX'}, [])
        batch.refresh_from_db()
        self.assertEqual(batch.organisation_countries, {})
        self.assertEqual(org_countries.clean_code(' au '), 'AU')
        self.assertEqual(org_countries.clean_code(''), '')

    def test_commit_stores_the_confirmed_country_and_the_proposal_when_untouched(self):
        batch = self.stage(MUFG_STYLE)
        new, _b = org_countries.review(batch)
        self.assertEqual((new[0]['proposed'], new[0]['country']), ('AU', 'AU'))
        svc.commit_batch(batch)
        self.assertEqual(Organisation.objects.get().country, 'AU')

    def test_owner_choice_wins_and_blank_means_unknown(self):
        for choice, expected in (('NZ', 'NZ'), ('', '')):
            Payment.objects.all().delete()
            Organisation.objects.all().delete()
            batch = self.stage(MUFG_STYLE, f'{choice or "blank"}.pdf')
            org_countries.save_choices(batch, {'acme mining limited (acm)': choice}, [])
            svc.commit_batch(batch)
            self.assertEqual(Organisation.objects.get().country, expected)

    def test_existing_organisation_is_not_overwritten_and_optional_fill_only_when_ticked(self):
        Organisation.objects.create(name='Acme Mining Limited (ACM)', country='FR')
        batch = self.stage(MUFG_STYLE)
        org_countries.save_choices(batch, {'acme mining limited (acm)': 'AU'}, ['acme mining limited (acm)'])
        svc.commit_batch(batch)
        self.assertEqual(Organisation.objects.get().country, 'FR')
        Payment.objects.all().delete()
        Organisation.objects.all().delete()
        Organisation.objects.create(name='Acme Mining Limited (ACM)')
        batch = self.stage(MUFG_STYLE, 'second.pdf')
        svc.commit_batch(batch)                                    # not ticked: stays blank
        self.assertEqual(Organisation.objects.get().country, '')
        Payment.objects.all().delete()
        batch = self.stage(MUFG_STYLE, 'third.pdf')
        org_countries.save_choices(batch, {}, ['acme mining limited (acm)'])
        svc.commit_batch(batch)
        self.assertEqual(Organisation.objects.get().country, 'AU')

    def test_resolve_organisation_uses_the_given_country_for_new_ones_only(self):
        from core.services import lookups
        self.assertEqual(lookups.resolve_organisation('Plain Name', country='GB').country, 'GB')
        self.assertEqual(lookups.resolve_organisation('Plain Name', country='US').country, 'GB')       # existing: unchanged


class CountryViewTests(Staging):
    def setUp(self):
        super().setUp()
        self.client.force_login(get_user_model().objects.create_user('u', password='p'))

    def test_preview_shows_the_control_and_saving_changes_nothing_else(self):
        batch = self.stage(MUFG_STYLE)
        page = self.client.get(reverse('import_preview', args=[batch.pk]))
        self.assertContains(page, 'Country of organisations')
        before = list(batch.rows.values_list('data', 'status'))
        self.client.post(reverse('import_countries', args=[batch.pk]),
                         {'org_key': ['acme mining limited (acm)'], 'org_country': ['nz']})
        batch.refresh_from_db()
        self.assertEqual(batch.organisation_countries['new'], {'acme mining limited (acm)': 'NZ'})
        self.assertEqual(before, list(batch.rows.values_list('data', 'status')))
        bad = self.client.post(reverse('import_countries', args=[batch.pk]),
                               {'org_key': ['acme mining limited (acm)'], 'org_country': ['QQ']}, follow=True)
        self.assertContains(bad, 'not an ISO 3166-1 alpha-2')
        batch.refresh_from_db()
        self.assertEqual(batch.organisation_countries['new'], {'acme mining limited (acm)': 'NZ'})

    def test_organisations_page_proposal_changes_nothing_until_confirmed(self):
        from core.models import Organisation as O
        from .test_policies_tax import add
        aud = O.objects.create(name='Aussie Only')
        mixed = O.objects.create(name='Mixed')
        eur = O.objects.create(name='Euro Only')
        for org, ccy in ((aud, 'AUD'), (mixed, 'AUD'), (mixed, 'GBP'), (eur, 'EUR')):
            add(100, 'Interest', org.name, '', currency=ccy, rate=None if ccy == 'EUR' else '0.6')
        page = self.client.get(reverse('organisation_countries'))
        self.assertContains(page, 'Aussie Only')
        self.assertNotContains(page, 'Mixed</td>')
        self.assertNotContains(page, 'Euro Only</td>')
        aud.refresh_from_db()
        self.assertEqual(aud.country, '')
        self.client.post(reverse('organisation_countries'), {'org': [aud.pk, mixed.pk, eur.pk]})
        aud.refresh_from_db(); mixed.refresh_from_db(); eur.refresh_from_db()
        self.assertEqual((aud.country, mixed.country, eur.country), ('AU', '', ''))


class StoredCountryReportTests(TestCase):
    def test_a_stored_country_changes_only_the_flag_text_never_an_amount(self):
        from core.services.policies import tax
        from .test_policies_tax import add, map_tax
        map_tax(Interest='capital')
        add(100, 'Interest', 'Aussie Bank', '', currency='AUD', rate='0.6')
        before, _ = tax.tax_summary_rows(2026)
        Organisation.objects.update(country='AU')
        after, _ = tax.tax_summary_rows(2026)
        strip = lambda rows: [{k: v for k, v in r.items() if k != 'flags'} for r in rows]
        self.assertEqual(strip(before), strip(after))
        self.assertIn('taken from the payment currency', before[0]['flags'])
        self.assertNotIn('taken from the payment currency', after[0]['flags'])
