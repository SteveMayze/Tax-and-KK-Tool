"""Phase 25: routing, matching rules and the statement grammar of the joint account. Synthetic PDFs only: invented holder,
account numbers, names and figures, worked out by hand in the docstrings. Corner-case ids (J1 ...) are in the test names."""
import datetime
import re
import tempfile
from decimal import Decimal as D
from pathlib import Path
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from core.models import StatementRule
from core.services import pdf_imports, rule_preview, rvb_account, rvb_joint, statement_rules as rules_svc
from core.services import statement_readers as sr
from core.services.dividend_statements import UnsupportedStatement

from .test_pdf_imports import UploadDirMixin
from .test_pdf_support import make_pdf
from .test_rvb_account import PROVIDER, closing_statement, ordinary_statement

JOINT = '7777770001'
OTHER = '1234567890'


def hdr(account=JOINT, number='4/2025', spaced=False):
    kontonummer = 'K ontonummer' if spaced else 'Kontonummer'
    nr = 'Ko ntoausz ug  N r. ' if spaced else 'Kontoauszug Nr. '
    return ['EUR-Konto', f'{kontonummer} {account}', 'EXAMPLE BANK eG', f'{nr}{number}']


def booking(day, text, amount, sign, who, *purpose, month='02', pn='931'):
    return [f'{day}.{month}. {day}.{month}. {text} PN:{pn} {amount} {sign}', who, *purpose, 'EREF: 0000000000001234']


def statement(account=JOINT, spaced=False, neuer='1.250,00', bookings=None):
    """alter 1.000,00 + 800,00 (rent) - 450,00 (card) - 100,00 (fee) = 1.250,00 (default)"""
    bookings = bookings if bookings is not None else [
        *booking('03', 'Gutschrift', '800,00', 'H', 'EXAMPLE TENANT', 'Miete Februar'),
        *booking('10', 'Kartenzahlung', '450,00', 'S', 'EXAMPLE SHOP', 'Mietwagen'),
        *booking('20', 'Entgelte', '100,00', 'S', 'EXAMPLE BANK', 'Kontofuehrung')]
    return [[*hdr(account, spaced=spaced), 'alter Kontostand vom 31.01.2025 1.000,00 H', *bookings,
             f'neuer Kontostand vom 28.02.2025 {neuer} H']]


def two_sheets(carry_out='1.800,00', carry_in='1.800,00', sheet_in=1, neuer='1.250,00', out_sheet=2):
    """alter 1.000,00 + 800,00 = 1.800,00 (sheet 1 carry); - 450,00 - 100,00 = 1.250,00"""
    first = [*hdr(), 'alter Kontostand vom 31.01.2025 1.000,00 H', *booking('03', 'Gutschrift', '800,00', 'H', 'EXAMPLE TENANT', 'Miete'),
             f'Übertrag auf Blatt {out_sheet} {carry_out} H']
    second = [*hdr(), f'Übertrag von Blatt {sheet_in} {carry_in} H', *booking('10', 'Kartenzahlung', '450,00', 'S', 'EXAMPLE SHOP'),
              *booking('20', 'Entgelte', '100,00', 'S', 'EXAMPLE BANK'), f'neuer Kontostand vom 28.02.2025 {neuer} H']
    return [first, second]


def layout(pages):
    return pages


def plain(account):
    """The same layout with only booking types the Phase 17 reader accepts (a card payment would refuse it)."""
    return statement(account=account, bookings=[
        *booking('03', 'Gutschrift', '800,00', 'H', 'EXAMPLE TENANT', 'Miete Februar'),
        *booking('10', 'Sepa-Überweisung', '450,00', 'S', 'EXAMPLE PERSON'),
        *booking('20', 'Dauerauftrag', '100,00', 'S', 'EXAMPLE PERSON')])


def read(pages):
    return sr.read_statement(make_pdf(pages))


def rule(label='r1', kind='tenant_rent', pattern='example tenant', match_on='either', organisation='EXAMPLE TENANT', **kw):
    return StatementRule.objects.create(label=label, kind=kind, pattern=pattern, match_on=match_on, organisation=organisation, **kw)


@override_settings(JOINT_RENTAL_ACCOUNT=JOINT)
class RoutingTests(TestCase):
    def test_J1_the_joint_account_is_claimed_by_the_joint_reader_only(self):
        outcome = read(statement())
        self.assertEqual((outcome.reader_id, outcome.error), ('rvb_joint', ''))
        self.assertEqual(outcome.result.rows, [])

    def test_J1_the_same_layout_with_another_account_stays_with_the_other_reader_only(self):
        outcome = read(plain(OTHER))
        self.assertEqual((outcome.reader_id, outcome.error), ('rvb_giro', ''))

    def test_J1_with_the_setting_empty_nothing_changes_for_any_file(self):
        with override_settings(JOINT_RENTAL_ACCOUNT=''):
            self.assertEqual(read(plain(JOINT)).reader_id, 'rvb_giro')
            self.assertEqual(read(plain(OTHER)).reader_id, 'rvb_giro')
            self.assertEqual(read(closing_statement()).reader_id, 'rvb_giro')

    def test_the_other_readers_files_are_untouched_by_a_configured_joint_account(self):
        self.assertEqual(read(closing_statement()).reader_id, 'rvb_giro')
        self.assertEqual(read(ordinary_statement()).reader_id, 'rvb_giro')

    def test_a_different_account_with_the_same_leading_digits_is_not_the_joint_account(self):
        self.assertEqual(read(plain(JOINT[:-1] + '2')).reader_id, 'rvb_giro')
        self.assertEqual(read(plain(JOINT + '1')).reader_id, 'rvb_giro')

    def test_only_one_reader_claims_in_every_case(self):
        for account in (JOINT, OTHER):
            pages = plain(account)
            claims = [r.id for r in sr.READERS if r.recognises(__import__('core.services.pdf_text', fromlist=['x']).extract_pages(make_pdf(pages), layout=True))]
            self.assertEqual(len(claims), 1, claims)

    def test_J17_letter_spaced_headers_are_still_recognised_and_read(self):
        outcome = read(statement(spaced=True))
        self.assertEqual((outcome.reader_id, outcome.error), ('rvb_joint', ''))


class SettingTests(SimpleTestCase):
    def test_a_non_digit_account_setting_stops_start_up_without_echoing_it(self):
        import importlib, os
        from unittest import mock
        from django.core.exceptions import ImproperlyConfigured
        from config import settings as base
        with mock.patch.dict(os.environ, {'DJANGO_JOINT_RENTAL_ACCOUNT': 'DE12 3456'}):
            with self.assertRaises(ImproperlyConfigured) as ctx:
                importlib.reload(base)
        self.assertNotIn('3456', str(ctx.exception))
        importlib.reload(base)


class NormaliseTests(SimpleTestCase):
    def test_J4_three_spellings_normalise_to_the_same_string(self):
        forms = {rules_svc.normalise(t) for t in ('Jürgen Köhler', 'JUERGEN KOEHLER', 'Juergen Koehler')}
        self.assertEqual(forms, {'juergen koehler'})

    def test_J4_hyphens_spaces_and_sharp_s(self):
        self.assertEqual(rules_svc.normalise('Groß-Müller   Straße'), 'gross mueller strasse')
        self.assertEqual(rules_svc.normalise('Müller', stripped=True), 'muller')

    def test_J4_a_rule_matches_every_spelling_including_the_bare_vowel(self):
        compiled = rules_svc.compile_pattern('jürgen köhler')
        for text in ('Jürgen Köhler', 'JUERGEN KOEHLER', 'Juergen Koehler', 'Jurgen Kohler', 'J urgen  KOHLER'.replace('J u', 'Ju')):
            self.assertTrue(rules_svc.pattern_matches(compiled, text), text)
        self.assertFalse(rules_svc.pattern_matches(compiled, 'Jan Kohl'))

    def test_an_empty_matching_pattern_and_an_invalid_one_are_rejected(self):
        for bad in ('', '   ', 'a*', '(x|)', '^', '(unclosed'):
            with self.assertRaises(rules_svc.RuleError, msg=bad):
                rules_svc.compile_pattern(bad)

    def test_a_pattern_keeps_its_regex_syntax(self):
        compiled = rules_svc.compile_pattern(r'miete\s+\d{2}')
        self.assertTrue(rules_svc.pattern_matches(compiled, 'MIETE 03'))


class RuleModelTests(TestCase):
    def test_the_model_rejects_a_bad_pattern_a_missing_organisation_and_reversed_dates(self):
        with self.assertRaises(ValidationError) as ctx:
            StatementRule(label='x', kind='tenant_rent', pattern='a*', organisation='').save()
        self.assertEqual(set(ctx.exception.message_dict), {'pattern', 'organisation'})
        with self.assertRaises(ValidationError):
            rule(valid_from=datetime.date(2025, 5, 1), valid_to=datetime.date(2025, 4, 1))
        self.assertEqual(StatementRule.objects.count(), 0)

    def test_the_migration_seeds_no_rule(self):
        self.assertEqual(StatementRule.objects.count(), 0)

    def test_validity_dates_limit_a_rule(self):
        rule(valid_from=datetime.date(2025, 3, 1), valid_to=datetime.date(2025, 3, 31))
        rules = rules_svc.load_rules()
        self.assertEqual(rules_svc.matching_rules(rules, datetime.date(2025, 2, 28), 'EXAMPLE TENANT', ''), [])
        self.assertEqual(len(rules_svc.matching_rules(rules, datetime.date(2025, 3, 15), 'EXAMPLE TENANT', '')), 1)

    def test_inactive_rules_are_not_loaded(self):
        rule(active=False)
        self.assertEqual(rules_svc.load_rules(), [])

    def test_match_on_limits_where_the_pattern_is_searched(self):
        rule(match_on='purpose', pattern='rent march')
        rules = rules_svc.load_rules()
        self.assertIsNone(rules_svc.match_credit(rules, datetime.date(2025, 3, 1), 'RENT MARCH', 'other'))
        self.assertIsNotNone(rules_svc.match_credit(rules, datetime.date(2025, 3, 1), 'x', 'Rent March'))

    def test_J11_a_booking_matched_by_rules_of_different_kinds_is_a_conflict(self):
        rule('a', 'tenant_rent', 'example tenant')
        rule('b', 'service_charge_settlement', 'nebenkosten')
        rules = rules_svc.load_rules()
        with self.assertRaises(rules_svc.RuleConflict):
            rules_svc.match_credit(rules, datetime.date(2025, 3, 1), 'EXAMPLE TENANT', 'Nebenkosten 2024')
        self.assertEqual(rules_svc.match_credit(rules, datetime.date(2025, 3, 1), 'EXAMPLE TENANT', 'Miete').kind, 'tenant_rent')

    def test_two_tenants_on_one_booking_is_a_conflict_but_the_same_tenant_twice_is_not(self):
        rule('a', pattern='example tenant', organisation='EXAMPLE TENANT')
        rule('b', pattern='tenant', organisation='EXAMPLE TENANT')
        rule('c', pattern='example', organisation='EXAMPLE OTHER')
        rules = rules_svc.load_rules()
        with self.assertRaises(rules_svc.RuleConflict):
            rules_svc.match_credit(rules, datetime.date(2025, 3, 1), 'EXAMPLE TENANT', '')
        self.assertEqual(rules_svc.match_credit([r for r in rules if r.label != 'c'], datetime.date(2025, 3, 1), 'EXAMPLE TENANT', '').organisation,
                         'EXAMPLE TENANT')


@override_settings(JOINT_RENTAL_ACCOUNT=JOINT)
class GrammarTests(TestCase):
    def test_J2_a_household_statement_with_unmatched_lines_is_nothing_to_import(self):
        outcome = read(statement())
        self.assertEqual((outcome.reader_id, outcome.error, outcome.result.rows), ('rvb_joint', '', []))
        self.assertEqual(len(outcome.result.notices), 1)                  # the "Miete" purpose, with no rule to match it (J12)
        self.assertIn('possible rent not matched', outcome.result.notices[0])
        self.assertEqual(outcome.result.period, (datetime.date(2025, 1, 31), datetime.date(2025, 2, 28)))

    def test_the_bookings_are_parsed_with_counterparty_purpose_and_without_reference_lines(self):
        from core.services import pdf_text
        s = rvb_joint.read_statement(pdf_text.extract_pages(make_pdf(statement()), layout=True))
        self.assertEqual([(b.booking_date, b.amount, b.counterparty, b.purpose) for b in s.bookings],
                         [(datetime.date(2025, 2, 3), D('800.00'), 'EXAMPLE TENANT', 'Miete Februar'),
                          (datetime.date(2025, 2, 10), D('-450.00'), 'EXAMPLE SHOP', 'Mietwagen'),
                          (datetime.date(2025, 2, 20), D('-100.00'), 'EXAMPLE BANK', 'Kontofuehrung')])
        self.assertEqual((s.number, s.year), ('4', '2025'))

    def test_a_value_date_that_is_not_a_calendar_date_does_not_refuse_the_statement(self):
        bookings = ['28.02. 30.02. Entgelte PN:802 100,00 S', 'EXAMPLE BANK']
        outcome = read(statement(neuer='900,00', bookings=bookings))
        self.assertEqual((outcome.reader_id, outcome.error), ('rvb_joint', ''))
        bad_booking_date = ['30.02. 28.02. Entgelte PN:802 100,00 S', 'EXAMPLE BANK']
        self.assertIn('could not be read', read(statement(neuer='900,00', bookings=bad_booking_date)).error)

    def test_J16_two_sheets_with_consistent_carries_are_read(self):
        outcome = read(two_sheets())
        self.assertEqual((outcome.reader_id, outcome.error), ('rvb_joint', ''))

    def test_J16_a_corrupted_carry_amount_is_refused_naming_the_page_not_the_figures(self):
        outcome = read(two_sheets(carry_out='1.801,00'))
        self.assertIn('Page 1', outcome.error)
        self.assertNotRegex(outcome.error, r'\d,\d{2}')

    def test_J16_a_carry_in_that_differs_from_the_carry_out_is_refused(self):
        outcome = read(two_sheets(carry_in='1.700,00'))
        self.assertIn('Page 2', outcome.error)

    def test_J16_wrong_sheet_numbers_are_refused(self):
        self.assertIn('Page 2', read(two_sheets(sheet_in=2)).error)
        self.assertIn('Page 2', read(two_sheets(out_sheet=3)).error)

    def test_J16_a_carry_out_without_a_continuation_is_refused(self):
        pages = two_sheets()
        pages[1] = [l for l in pages[1] if not l.startswith('Übertrag')]
        self.assertTrue(read(pages).error)

    def test_a_broken_running_balance_is_refused_with_a_reason(self):
        outcome = read(statement(neuer='1.251,00'))
        self.assertEqual(outcome.result, None)
        self.assertIn('do not add up', outcome.error)
        self.assertNotRegex(outcome.error, r'\d,\d{2}')

    def test_J2_a_booking_line_that_cannot_be_parsed_is_refused_naming_page_and_position(self):
        bad = [*booking('03', 'Gutschrift', '800,00', 'H', 'EXAMPLE TENANT'), '10.02. 10.02. Kartenzahlung PN:931 450,00 X', 'EXAMPLE SHOP']
        outcome = read(statement(bookings=bad))
        self.assertIn('Page 1: booking 2 could not be read', outcome.error)

    def test_dates_without_a_year_resolve_across_a_year_end(self):
        pages = [[*hdr(), 'alter Kontostand vom 30.12.2024 1.000,00 H', *booking('31', 'Gutschrift', '10,00', 'H', 'A', month='12'),
                  *booking('02', 'Gutschrift', '10,00', 'H', 'B', month='01'), 'neuer Kontostand vom 03.01.2025 1.020,00 H']]
        from core.services import pdf_text
        s = rvb_joint.read_statement(pdf_text.extract_pages(make_pdf(pages), layout=True))
        self.assertEqual([b.booking_date for b in s.bookings], [datetime.date(2024, 12, 31), datetime.date(2025, 1, 2)])

    def test_J17_letter_spacing_does_not_stop_number_reading(self):
        from core.services import pdf_text
        pages = pdf_text.extract_pages(make_pdf(statement(spaced=True)), layout=True)
        self.assertEqual(rvb_joint.account_number(pages), JOINT)
        self.assertEqual(rvb_joint.read_statement(pages).number, '4')

    def test_J22_the_fingerprint_is_the_statement_number_year_and_closing_balance(self):
        a = read(statement()).result.fingerprint
        self.assertTrue(a)
        self.assertEqual(a, read(statement()).result.fingerprint)
        self.assertNotEqual(a, read(statement(neuer='1.249,00', bookings=[
            *booking('03', 'Gutschrift', '800,00', 'H', 'EXAMPLE TENANT'), *booking('10', 'Kartenzahlung', '551,00', 'S', 'X')])).result.fingerprint)

    def test_J11_a_credit_matching_rules_of_two_kinds_is_reported_not_staged(self):
        rule('a', 'tenant_rent', 'example tenant')
        rule('b', 'service_charge_settlement', 'miete')
        outcome = read(statement())
        self.assertEqual(outcome.result.rows, [])
        self.assertEqual(len(outcome.result.notices), 1)
        self.assertIn('rules that disagree', outcome.result.notices[0])


@override_settings(JOINT_RENTAL_ACCOUNT=JOINT)
class AccountPrivacyTests(UploadDirMixin, TestCase):
    def test_the_account_number_is_masked_and_never_shown(self):
        self.assertEqual(rvb_joint.mask_account(JOINT), '****01')
        outcome = read(statement())
        self.assertNotIn(JOINT, repr(outcome))
        for text in (outcome.error, *outcome.result.notices):
            self.assertNotRegex(text, r'\d{6,}')

    def test_the_upload_pages_and_logs_do_not_show_the_account_number(self):
        user = get_user_model().objects.create_user('u', password='p')
        self.client.force_login(user)
        from django.core.files.uploadedfile import SimpleUploadedFile
        with self.assertLogs(level='DEBUG') as logs:
            import logging
            logging.getLogger('core').debug('start')
            r = self.client.post(reverse('import_upload'), {'file': [SimpleUploadedFile('a.pdf', make_pdf(statement()))]}, follow=True)
        page = r.content.decode()
        self.assertNotIn(JOINT, page)
        self.assertNotRegex(' '.join(logs.output), JOINT)
        self.assertIn('1 statement recognised, no income.', page)

    def test_the_real_chain_stages_nothing_yet_and_creates_no_batch(self):
        with self.assertRaises(pdf_imports.NothingToImport) as ctx:
            pdf_imports.stage_pdf_batch([('joint.pdf', make_pdf(statement()))], PROVIDER)
        self.assertIn('1 statement recognised, no income.', str(ctx.exception))

    def test_J22_the_same_statement_twice_counts_once(self):
        with self.assertRaises(pdf_imports.NothingToImport) as ctx:
            pdf_imports.stage_pdf_batch([('a.pdf', make_pdf(statement())), ('b.pdf', make_pdf(statement()))], PROVIDER)
        self.assertIn('1 statement recognised', str(ctx.exception))


@override_settings(JOINT_RENTAL_ACCOUNT=JOINT)
class RulePreviewTests(TestCase):
    def test_counts_per_rule_and_conflicts_without_names_or_amounts(self):
        rule('Secret Label', 'tenant_rent', 'example tenant')
        rule('b', 'service_charge_settlement', 'miete')
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, 'a.pdf').write_bytes(make_pdf(statement()))
            Path(folder, 'b.pdf').write_bytes(make_pdf(statement(account=OTHER)))
            text = rule_preview.render(rule_preview.preview(folder))
        self.assertIn('1 joint-account statements, 1 other, 0 not readable', text)
        self.assertIn('Credit lines read: 1', text)
        self.assertRegex(text, r'Rule #\d+ \(tenant_rent\): 1 lines in 1 statements \(4/2025\)')
        self.assertIn('Lines matched by more than one rule: 1, of which conflicts (not staged): 1', text)
        for forbidden in ('Secret Label', 'EXAMPLE', '800', JOINT):
            self.assertNotIn(forbidden, text)

    def test_no_rules_is_said_plainly(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIn('No active rules.', rule_preview.render(rule_preview.preview(folder)))


SAMPLES = Path(__file__).resolve().parent.parent / 'local' / 'samples'


@skipUnless((SAMPLES / 'RVB-joint').is_dir(), 'owner-supplied joint-account statements are not present (they are never committed)')
class LocalJointTests(TestCase):
    """Reads the owner's real statements; asserts counts only, prints nothing. The account number is taken from the first file."""

    def test_every_statement_is_read_and_the_chain_has_no_gaps(self):
        from core.services import pdf_text
        files = sorted((SAMPLES / 'RVB-joint').glob('*.pdf'))
        account = rvb_joint.account_number(pdf_text.extract_pages(files[0].read_bytes(), layout=True))
        with override_settings(JOINT_RENTAL_ACCOUNT=account):
            outcomes = [sr.read_statement(f.read_bytes()) for f in files]
        self.assertEqual([o.error for o in outcomes if o.error], [])
        self.assertEqual({o.reader_id for o in outcomes}, {'rvb_joint'})
        items = [(f.name, o.reader_id, o.result.continuity) for f, o in zip(files, outcomes)]
        self.assertEqual(sr.continuity_notes(items), [])
