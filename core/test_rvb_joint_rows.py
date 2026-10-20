"""Phase 26: rent rows from the joint account. Synthetic PDFs only (invented tenants, shops, accounts and figures); every
expected figure is worked out in the test. Corner-case ids (J3 ...) are in the test names."""
import datetime
from decimal import Decimal as D
from pathlib import Path
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import IncomeCategory, Organisation, Payment, StatementRule
from core.services import pdf_imports, rvb_joint
from core.services import statement_readers as sr

from .test_pdf_imports import UploadDirMixin
from .test_pdf_support import make_pdf
from .test_rvb_account import PROVIDER
from .test_rvb_joint import JOINT, OTHER, hdr, rule

CATEGORY = 'Rental (joint)'


def de(amount):
    return f'{amount:,.2f}'.replace(',', '#').replace('.', ',').replace('#', '.')


def stmt(*items, opening=D('1000.00'), number='3/2025', start='28.02.2025', end='31.03.2025', pages=None):
    """items: (day, month, text, signed amount, counterparty, purpose...). The closing balance is worked out from the items."""
    lines, balance = [], opening
    for day, month, text, amount, who, *purpose in items:
        balance += amount
        lines += [f'{day}.{month}. {day}.{month}. {text} PN:931 {de(abs(amount))} {"H" if amount > 0 else "S"}', who, *purpose,
                  'EREF: 0000000000001234']
    return [[*hdr(number=number), f'alter Kontostand vom {start} {de(opening)} H', *lines, f'neuer Kontostand vom {end} {de(balance)} H']]


def rent(day, month, amount, who='EXAMPLE TENANT', *purpose):
    return (day, month, 'Gutschrift', D(amount), who, *(purpose or ('Miete',)))


def debit(day, month, amount, who, *purpose):
    return (day, month, 'Lastschrift', -D(amount), who, *purpose)


@override_settings(JOINT_RENTAL_ACCOUNT=JOINT, JOINT_RENTAL_CATEGORY=CATEGORY)
class RowTestCase(TestCase):
    def setUp(self):
        super().setUp()
        IncomeCategory.objects.create(name=CATEGORY)
        # one text "counterparty | purpose": the tenant's rent, but not a settlement (which has its own rule), so no conflict
        rule('tenant', 'tenant_rent', r'^(?!.*nebenkosten).*example tenant', match_on='combined')

    def read(self, *items, **kw):
        outcome = sr.read_statement(make_pdf(stmt(*items, **kw)))
        self.assertEqual(outcome.error, '')
        return outcome.result


class RentRowTests(RowTestCase):
    def test_J3_J5_J6_J7_two_credits_a_rest_payment_a_relative_a_settlement_and_a_look_alike(self):
        rule('settle', 'service_charge_settlement', 'nebenkosten', match_on='purpose', organisation='EXAMPLE TENANT')
        result = self.read(
            rent('03', '03', '800.00', 'EXAMPLE TENANT', 'Miete Maerz'),                   # rent for the month
            rent('28', '03', '800.00', 'EXAMPLE TENANT', 'Miete April'),                   # next month paid early: its own row
            rent('29', '03', '45.50', 'EXAMPLE TENANT', 'Rest Miete'),                     # a rest payment after an increase: its own row
            rent('15', '03', '800.00', 'EXAMPLE RELATIVE', 'Miete fuer Example Tenant'),   # paid by a relative, tenant named in the purpose
            rent('20', '03', '312.40', 'EXAMPLE TENANT', 'Nebenkosten 2024'),              # service-charge back-payment
            rent('21', '03', '99.00', 'EXAMPLE STRANGER', 'Miete Garage'),                 # look-alike: a notice only
            debit('10', '03', '55.00', 'EXAMPLE CAR HIRE', 'Mietwagen'))
        self.assertEqual([(r.data['payment_date'], r.data['gross_amount'], r.data['frequency']) for r in result.rows],
                         [('2025-03-03', '800.00', 'monthly'), ('2025-03-28', '800.00', 'monthly'), ('2025-03-29', '45.50', 'monthly'),
                          ('2025-03-15', '800.00', 'monthly'), ('2025-03-20', '312.40', 'one_off')])
        first = result.rows[0].data
        self.assertEqual((first['organisation'], first['category'], first['currency'], first['net_amount'], first['withholding_tax'],
                          first['expenses'], first['income_period_start']), ('EXAMPLE TENANT', CATEGORY, 'EUR', '800.00', '0', '0', ''))
        self.assertIn('Rent received directly from tenant, joint account, whole amount', first['comment'])
        self.assertIn('Purpose names the month: März.', first['comment'])
        self.assertNotIn('month:', result.rows[2].data['comment'])                      # Q26.3: no month named, none derived
        self.assertIn('service-charge settlement', result.rows[4].data['comment'])
        self.assertEqual(len(result.notices), 1)
        self.assertIn('possible rent not matched', result.notices[0])
        self.assertEqual(result.meta['ignored'], 1)                                     # the car-hire debit

    def test_J5_Echtzeit_and_standing_order_credits_are_rent_and_a_debit_is_never(self):
        result = self.read(('03', '03', 'Echtzeit-Gutschrift', D('800.00'), 'EXAMPLE TENANT', 'Miete'),
                           ('04', '03', 'Dauerauftrag', D('800.00'), 'EXAMPLE TENANT', 'Miete'),
                           ('05', '03', 'Sepa-Überweisung', D('-800.00'), 'EXAMPLE TENANT', 'Miete'))
        self.assertEqual(len(result.rows), 2)
        self.assertEqual(result.notices, [])

    def test_J21_identical_credits_on_one_day_are_both_staged(self):
        self.assertEqual(len(self.read(rent('03', '03', '800.00'), rent('03', '03', '800.00')).rows), 2)

    def test_no_amount_rule_a_changed_rent_is_still_rent(self):
        result = self.read(rent('03', '03', '650.00'), rent('04', '03', '700.00'))
        self.assertEqual([r.data['gross_amount'] for r in result.rows], ['650.00', '700.00'])

    def test_provenance_cites_the_booking_and_the_sanitised_counterparty_and_purpose(self):
        (row,) = self.read(rent('03', '03', '800.00', 'EXAMPLE TENANT', 'Miete Maerz 20250001')).rows
        self.assertEqual(row.provenance['payment_date'][0], 1)
        self.assertIn('Gutschrift', row.provenance['gross_amount'][1])
        self.assertIn('EXAMPLE TENANT / Miete Maerz ######', row.provenance['gross_amount'][1])
        self.assertNotIn('EREF', row.provenance['gross_amount'][1])


class DepositTests(RowTestCase):
    def test_J8_a_labelled_deposit_and_rent_summing_to_the_credit_stages_the_rent_only(self):
        # 1.530,00 deposit + 850,00 rent = 2.380,00
        result = self.read(rent('03', '03', '2380.00', 'EXAMPLE TENANT', 'Kaution 1.530,00 EUR Miete 850,00 EUR'))
        (row,) = result.rows
        self.assertEqual((row.data['gross_amount'], row.data['net_amount']), ('850.00', '850.00'))
        self.assertIn('Rent part of a combined credit of 2380.00 EUR', row.data['comment'])
        self.assertEqual(len(result.notices), 1)
        self.assertIn('deposit part (1530.00 EUR) is not income', result.notices[0])

    def test_J8_either_order_and_plain_figures(self):
        (row,) = self.read(rent('03', '03', '2380.00', 'EXAMPLE TENANT', 'Miete: 850 Kaution: 1530')).rows
        self.assertEqual(row.data['gross_amount'], '850.00')

    def test_J8_a_sum_that_does_not_match_leaves_the_credit_out_and_the_statement_is_still_staged(self):
        result = self.read(rent('03', '03', '2300.00', 'EXAMPLE TENANT', 'Kaution 1.530,00 Miete 850,00'),
                           rent('04', '03', '850.00'))
        self.assertEqual([r.data['gross_amount'] for r in result.rows], ['850.00'])
        self.assertTrue(any('could not be split' in n for n in result.notices))

    def test_J8_a_deposit_without_both_labelled_figures_is_not_staged(self):
        for purpose in ('Kaution', 'Kaution 1530', 'Kaution 1.530,00 Miete'):
            result = self.read(rent('03', '03', '1530.00', 'EXAMPLE TENANT', purpose))
            self.assertEqual(result.rows, [], purpose)
            self.assertIn('could not be split', result.notices[0])


class TenantChangeTests(RowTestCase):
    def test_J3_two_rules_with_validity_dates_attribute_credits_to_the_right_tenant(self):
        StatementRule.objects.all().delete()
        rule('old', pattern='old tenant', organisation='EXAMPLE OLD TENANT', valid_to=datetime.date(2025, 3, 15))
        rule('new', pattern='new tenant', organisation='EXAMPLE NEW TENANT', valid_from=datetime.date(2025, 3, 16))
        result = self.read(rent('03', '03', '800.00', 'EXAMPLE OLD TENANT'), rent('20', '03', '820.00', 'EXAMPLE NEW TENANT'),
                           rent('18', '03', '800.00', 'EXAMPLE OLD TENANT'),        # outside the old tenant's range, no other rule
                           rent('10', '03', '820.00', 'EXAMPLE NEW TENANT'))        # before the new tenant's range
        self.assertEqual([(r.data['organisation'], r.data['gross_amount']) for r in result.rows],
                         [('EXAMPLE OLD TENANT', '800.00'), ('EXAMPLE NEW TENANT', '820.00')])
        self.assertEqual(len(result.notices), 2)
        self.assertTrue(all('possible rent not matched' in n for n in result.notices))


class SettlementConflictTests(RowTestCase):
    def test_J11_a_tenant_rule_that_also_matches_the_settlement_makes_a_conflict_not_a_guess(self):
        StatementRule.objects.all().delete()
        rule('tenant', 'tenant_rent', 'example tenant')                               # matches the counterparty of every credit
        rule('settle', 'service_charge_settlement', 'nebenkosten', match_on='purpose', organisation='EXAMPLE TENANT')
        result = self.read(rent('03', '03', '800.00'), rent('20', '03', '312.40', 'EXAMPLE TENANT', 'Nebenkosten 2024'))
        self.assertEqual([r.data['gross_amount'] for r in result.rows], ['800.00'])
        self.assertIn('rules that disagree', result.notices[0])


class DebitsAndNoiseTests(RowTestCase):
    def test_J10_debits_of_every_kind_stage_nothing_and_give_no_notice(self):
        result = self.read(debit('02', '03', '300.00', 'EXAMPLE PROPERTY MANAGER', 'Wohngeld Hausgeld'),
                           debit('03', '03', '120.00', 'EXAMPLE CITY', 'Grundbesitzabgaben GRDABG'),
                           debit('04', '03', '60.00', 'EXAMPLE LANDLORDS CLUB', 'Jahresbeitrag Miete'),
                           debit('05', '03', '55.00', 'EXAMPLE CAR HIRE', 'Mietwagen'))
        self.assertEqual((result.rows, result.notices, result.meta['ignored']), ([], [], 4))

    def test_J12_J13_car_rental_funds_purchase_and_transfers_give_nothing(self):
        result = self.read(debit('02', '03', '55.00', 'EXAMPLE CAR HIRE', 'Mietwagen'),
                           debit('03', '03', '500.00', 'EXAMPLE FUND', 'Fondskauf'),
                           (  '04', '03', 'Dauerauftrag', D('100.00'), 'EXAMPLE OWNER', 'Umbuchung'),
                           (  '05', '03', 'Gutschrift', D('25.00'), 'EXAMPLE TAX OFFICE', 'Erstattung'))
        self.assertEqual((result.rows, result.notices, result.meta['ignored']), ([], [], 4))


class RefusalTests(RowTestCase):
    def test_J2_an_unparseable_booking_line_is_refused_with_page_and_position(self):
        pages = stmt(rent('03', '03', '800.00'))
        pages[0].insert(-1, '10.03. 10.03. Lastschrift PN:931 55,00 X')
        outcome = sr.read_statement(make_pdf(pages))
        self.assertIn('Page 1: booking 2 could not be read', outcome.error)

    def test_a_missing_category_explains_what_to_create_and_stages_nothing(self):
        IncomeCategory.objects.all().delete()
        outcome = sr.read_statement(make_pdf(stmt(rent('03', '03', '800.00'))))
        self.assertIsNone(outcome.result)
        self.assertIn('DJANGO_JOINT_RENTAL_CATEGORY', outcome.error)
        self.assertIn(CATEGORY, outcome.error)
        self.assertEqual(IncomeCategory.objects.count(), 0)           # the importer never creates it

    def test_a_statement_without_rent_does_not_need_the_category(self):
        IncomeCategory.objects.all().delete()
        outcome = sr.read_statement(make_pdf(stmt(debit('02', '03', '300.00', 'EXAMPLE MANAGER', 'Hausgeld'))))
        self.assertEqual(outcome.error, '')


class DatesAndStagingTests(UploadDirMixin, RowTestCase):
    def stage(self, *named):
        return pdf_imports.stage_pdf_batch([(n, make_pdf(p)) for n, p in named], PROVIDER)

    def test_J14_dates_without_a_year_resolve_across_a_year_end_and_for_a_first_statement(self):
        december = stmt(rent('31', '12', '800.00'), rent('02', '01', '800.00'), start='30.11.2024', end='03.01.2025')
        result = sr.read_statement(make_pdf(december)).result
        self.assertEqual([r.data['payment_date'] for r in result.rows], ['2024-12-31', '2025-01-02'])
        first = stmt(rent('30', '12', '800.00'), start='29.12.2024', end='31.01.2025')       # the first one starts at the end of the year before
        self.assertEqual(sr.read_statement(make_pdf(first)).result.rows[0].data['payment_date'], '2024-12-30')

    def test_the_real_chain_pdf_to_review_to_payment_with_the_tenant_created_in_germany(self):
        batch = self.stage(('joint.pdf', stmt(rent('03', '03', '800.00'), debit('04', '03', '30.00', 'EXAMPLE SHOP'))))
        self.assertEqual(batch.rows.count(), 1)
        self.assertIn('1 booking ignored (not rent).', batch.warnings)
        user = get_user_model().objects.create_user('u', password='p')
        self.client.force_login(user)
        self.client.post(reverse('import_commit', args=[batch.pk]))
        p = Payment.objects.get()
        self.assertEqual((p.gross_amount, p.net_amount, p.currency, p.category.name, p.organisation.name, p.frequency, p.payment_date),
                         (D('800.00'), D('800.00'), 'EUR', CATEGORY, 'EXAMPLE TENANT', 'monthly', datetime.date(2025, 3, 3)))
        self.assertEqual(Organisation.objects.get(name='EXAMPLE TENANT').country, 'DE')
        self.assertEqual(p.gross_eur, D('800.00'))

    def test_J22_uploading_the_same_statement_twice_stages_it_once(self):
        again = stmt(rent('03', '03', '800.00'))
        again[0].append('Gedruckt am 02.04.2025')                       # other bytes, same statement
        batch = self.stage(('a.pdf', stmt(rent('03', '03', '800.00'))), ('b.pdf', again))
        self.assertEqual(batch.rows.count(), 1)
        self.assertTrue(any('same statement as a.pdf' in w for w in batch.warnings), batch.warnings)

    def test_continuity_flags_a_gap_between_statements_of_the_account(self):
        a = stmt(rent('03', '03', '800.00'), opening=D('1000.00'))                          # closes 1.800,00 on 31.03.2025
        b = stmt(rent('03', '05', '800.00'), opening=D('1900.00'), start='30.04.2025', end='31.05.2025', number='4/2025')
        batch = self.stage(('a.pdf', a), ('b.pdf', b))
        self.assertTrue(any('opening balance does not match' in w for w in batch.warnings), batch.warnings)

    def test_no_digit_run_of_six_or_more_from_the_account_is_shown(self):
        batch = self.stage(('a.pdf', stmt(rent('03', '03', '800.00'))))
        self.assertNotIn(JOINT, ' '.join(batch.warnings))


@override_settings(JOINT_RENTAL_ACCOUNT=JOINT, JOINT_RENTAL_CATEGORY=CATEGORY)
class PhaseSeventeenUnchangedTests(TestCase):
    def test_the_other_account_still_goes_to_the_phase_17_reader(self):
        pages = stmt(rent('03', '03', '800.00'))
        pages[0][1] = pages[0][1].replace(JOINT, OTHER)
        self.assertEqual(sr.read_statement(make_pdf(pages)).reader_id, 'rvb_giro')
