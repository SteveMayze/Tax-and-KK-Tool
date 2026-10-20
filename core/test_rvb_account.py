"""Phase 17: RVB current-account statements (EUR). Synthetic PDFs only: invented holder, account and figures, worked out by
hand in the comments. The fixtures imitate the structure of the real statements (balance rows, booking lines with value
date and posting code, detail lines, the Anlage 1 block)."""
import datetime
from decimal import Decimal as D
from pathlib import Path
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.models import Payment
from core.services import imports as svc
from core.services import pdf_imports, rvb_account
from core.services import statement_readers as sr

from .test_pdf_imports import UploadDirMixin
from .test_pdf_support import make_pdf


def header(number='4/2025', account='1234567890', garbled=False):
    if garbled:
        return ['Kontokorrent', f'Kontonummer {account}', 'E X A M P L E  B A N K  e G', '?????????????????????????????',
                f'Ko ntoau szug  N r. {number}', 'IBAN: DE00 0000 0000 0000 0000 00']
    return ['Kontokorrent', f'Kontonummer {account}', 'EXAMPLE BANK eG', f'Kontoauszug Nr. {number}', 'IBAN: DE00 0000 0000 0000 0000 00']


def anlage(interest, taxes=(), base='40,00', extra=(), summe='50,00', period=('01.01.2025', '31.03.2025'), end='31.03.2025'):
    lines = ['Entgeltinfos zum Konto', 'Anlage 1', 'Buchungstag: ' + end, 'Wert: ' + end, f'Kontoabschluss vom {period[0]} bis {period[1]} für Konto 1234567890']
    lines += [f'{rate}% HABENZINSEN bis {until} {amount} H' for rate, until, amount in interest]
    for kind, amount in taxes:
        lines.append(f'> {kind} {amount} S')
        if kind == 'Kapitalertragsteuer' and base:
            lines.append(f'> aus {base} Habenzins')
    lines += list(extra)
    lines.append(f'Summe Abschlussposten per {end} EUR {summe} H')
    return lines


INTEREST = [('1,50000', '31.01.', '20,00'), ('1,50000', '28.02.', '18,00'), ('2,00000', '31.03.', '12,00')]       # 20 + 18 + 12 = 50


def closing_statement(taxes=(('Solid.-Zuschlag', '0,55', 'EUR 10,00-KapSt per 31.03.2025 KT1'),
                             ('Kapitalertragsteuer', '10,00', 'EUR 40,00 Habenzins per 31.03.2025 KT1')),
                      neuer='1.089,45', block_taxes=(('Kapitalertragsteuer', '10,00'), ('Solidaritätszuschlag', '0,55')),
                      interest=INTEREST, summe='50,00', booked='50,00', extra_bookings=(), block_extra=(), base='40,00', hdr=None,
                      neuer_date='31.03.2025', booking_dates='31.03. 31.03.'):
    """alter 1.000,00 +200,00 (standing order) -150,00 (Umbuchung) = 1.050,00; +50,00 interest = 1.100,00; -0,55 -10,00 tax = 1.089,45"""
    lines = [*(hdr or header()), 'alter Kontostand vom 31.12.2024 1.000,00 H',
             '15.01. 15.01. Dauerauftrag PN:801 200,00 H', 'Max Muster', '10.02. 10.02. Umbuchung PN:802 150,00 S', 'Max Muster',
             *extra_bookings, f'{booking_dates} Abschluss lt. Anlage 1 PN:803 {booked} H']
    for text, amount, base_line in taxes:
        lines += [f'{booking_dates} {text} aus PN:804 {amount} S', base_line]
    lines += [f'neuer Kontostand vom {neuer_date} {neuer} H', *anlage(interest, block_taxes, base, block_extra, summe)]
    return [lines]


def ordinary_statement(neuer='925,00', credit_details=('Herzlichen Glückwunsch zu', 'Ihrem Gewinn Los 1234567'), hdr=None, bookings=()):
    """alter 1.000,00 +5,00 credit -100,00 transfer +20,00 standing order = 925,00"""
    lines = [*(hdr or header('2/2025')), 'alter Kontostand vom 31.01.2025 1.000,00 H',
             '05.02. 05.02. Gutschrift PN:900 5,00 H', *credit_details,
             '10.02. 10.02. Sepa-Überweisung PN:901 100,00 S', 'Max Muster', '15.02. 15.02. Dauerauftrag PN:902 20,00 H', *bookings,
             f'neuer Kontostand vom 28.02.2025 {neuer} H']
    return [lines]


def read(pages):
    return sr.read_statement(make_pdf(pages))


class RvbClosingTests(SimpleTestCase):
    def test_closing_with_three_interest_lines_and_a_booked_tax_pair(self):
        outcome = read(closing_statement())
        self.assertEqual(outcome.reader_id, 'rvb_giro', outcome.error)
        (row,) = outcome.result.rows
        d = row.data
        self.assertEqual((d['payment_date'], d['income_period_start'], d['income_period_end'], d['currency'], d['category'], d['frequency'],
                          d['organisation']), ('2025-03-31', '2025-01-01', '2025-03-31', 'EUR', 'Interest', 'quarterly', 'RVB (Girokonto)'))
        self.assertEqual((d['gross_amount'], d['withholding_tax'], d['net_amount'], d['expenses']), ('50.00', '10.55', '39.45', '0'))
        self.assertIn('Tax charged on 40.00 of the 50.00 interest', d['comment'])
        self.assertIn('Kapitalertragsteuer 10.00 + Solidaritätszuschlag 0.55', d['comment'])
        self.assertIn('Value date 2025-03-31', d['comment'])

    def test_provenance_cites_the_booking_the_interest_lines_and_the_tax_bookings(self):
        (row,) = read(closing_statement()).result.rows
        self.assertEqual(row.provenance['payment_date'], (1, '31.03. 31.03. Abschluss lt. Anlage 1 PN:803 50,00 H'))
        self.assertEqual(row.provenance['gross_amount'][1].count('HABENZINSEN'), 3)
        self.assertIn('Kapitalertragsteuer aus', row.provenance['withholding_tax'][1])
        self.assertEqual(row.provenance['net_amount'][1], 'Summe Abschlussposten per 31.03.2025 EUR 50,00 H')

    def test_closing_without_tax_has_gross_equal_net_and_the_balance_closes(self):
        pages = closing_statement(taxes=(), neuer='1.100,00', block_taxes=())
        (row,) = read(pages).result.rows
        self.assertEqual((row.data['gross_amount'], row.data['net_amount'], row.data['withholding_tax']), ('50.00', '50.00', '0'))
        self.assertNotIn('Withholding as booked', row.data['comment'])

    def test_a_kirchensteuer_line_is_included_and_named(self):
        taxes = (('Solid.-Zuschlag', '0,55', 'EUR 10,00-KapSt per 31.03.2025 KT1'),
                 ('Kirchensteuer', '0,80', 'EUR 10,00-KapSt per 31.03.2025 KT1'),
                 ('Kapitalertragsteuer', '10,00', 'EUR 40,00 Habenzins per 31.03.2025 KT1'))
        pages = closing_statement(taxes=taxes, neuer='1.088,65', block_taxes=(('Kapitalertragsteuer', '10,00'), ('Solidaritätszuschlag', '0,55'), ('Kirchensteuer', '0,80')))
        (row,) = read(pages).result.rows
        self.assertEqual((row.data['withholding_tax'], row.data['net_amount']), ('11.35', '38.65'))     # 10.00 + 0.55 + 0.80
        self.assertIn('Kapitalertragsteuer 10.00 + Solidaritätszuschlag 0.55 + Kirchensteuer 0.80', row.data['comment'])

    def test_tax_on_the_whole_interest_says_so(self):
        taxes = (('Kapitalertragsteuer', '12,50', 'EUR 50,00 Habenzins per 31.03.2025 KT1'),)
        pages = closing_statement(taxes=taxes, neuer='1.087,50', block_taxes=(('Kapitalertragsteuer', '12,50'),), base='50,00')
        (row,) = read(pages).result.rows
        self.assertIn('Tax charged on 50.00 of the 50.00 interest', row.data['comment'])

    def test_value_date_and_year_end_booking(self):
        pages = closing_statement(taxes=(), neuer='1.100,00', block_taxes=(), neuer_date='02.01.2026', booking_dates='30.12. 02.01.')
        (row,) = read(pages).result.rows
        self.assertEqual(row.data['payment_date'], '2025-12-30')                       # booking date, year from the statement
        self.assertIn('Value date 2026-01-02', row.data['comment'])

    def test_interest_lines_that_do_not_add_to_the_booked_amount_are_refused(self):         # R2
        outcome = read(closing_statement(interest=[('1,5', '31.01.', '20,00'), ('1,5', '28.02.', '17,00'), ('2,0', '31.03.', '12,00')]))
        self.assertIn('do not agree', outcome.error)

    def test_an_unknown_debit_line_in_the_closing_block_is_refused_naming_the_text(self):    # R8, G12
        outcome = read(closing_statement(block_extra=('Kontoführung 2,50 S',)))
        self.assertIn('Kontoführung', outcome.error)
        self.assertNotIn('2,50', outcome.error)

    def test_an_unknown_booking_text_is_refused_naming_the_text(self):
        outcome = read(closing_statement(extra_bookings=('12.02. 12.02. Kontoführungsentgelt PN:810 2,50 S',), neuer='1.086,95'))
        self.assertIsNone(outcome.result)
        self.assertIn('Kontoführungsentgelt', outcome.error)
        self.assertNotIn('2,50', outcome.error)

    def test_tax_in_the_block_must_agree_with_the_booked_tax(self):
        outcome = read(closing_statement(block_taxes=(('Kapitalertragsteuer', '11,00'), ('Solidaritätszuschlag', '0,55'))))
        self.assertIn('tax lines of the closing block do not agree', outcome.error)

    def test_a_base_larger_than_the_interest_or_missing_is_refused(self):
        self.assertIn('larger than the interest', read(closing_statement(base='60,00')).error)
        self.assertIn('base', read(closing_statement(base='')).error)

    def test_the_stated_base_under_a_tax_booking_must_agree(self):
        taxes = (('Solid.-Zuschlag', '0,55', 'EUR 10,00-KapSt per 31.03.2025 KT1'),
                 ('Kapitalertragsteuer', '10,00', 'EUR 41,00 Habenzins per 31.03.2025 KT1'))
        self.assertIn('base stated under a tax booking', read(closing_statement(taxes=taxes)).error)

    def test_a_closing_booking_without_its_block_is_refused(self):
        lines = closing_statement()[0]
        cut = lines.index('Entgeltinfos zum Konto')
        self.assertIn('no readable Anlage 1 block', read([lines[:cut]]).error)

    def test_the_balance_must_close_in_a_closing_too(self):
        self.assertIn('do not add up', read(closing_statement(neuer='1.089,46')).error)


class RvbOrdinaryStatementTests(SimpleTestCase):
    def test_transfers_standing_order_and_a_prize_give_nothing_to_import_and_one_notice(self):
        outcome = read(ordinary_statement())
        self.assertEqual((outcome.reader_id, outcome.result.rows), ('rvb_giro', []), outcome.error)
        self.assertEqual(outcome.result.notices, ['Savings-lottery prize credit, not imported.'])
        self.assertFalse(any(ch.isdigit() for n in outcome.result.notices for ch in n))          # no amounts

    def test_a_broken_balance_is_refused_not_reported_as_empty(self):                           # R9
        outcome = read(ordinary_statement(neuer='925,01'))
        self.assertIsNone(outcome.result)
        self.assertIn('do not add up', outcome.error)

    def test_an_ordinary_credit_is_a_notice_of_its_own(self):
        outcome = read(ordinary_statement(credit_details=('Max Muster', 'Rueckzahlung')))
        self.assertEqual(outcome.result.notices, ['A credit (Gutschrift) that is not interest, not imported.'])

    def test_an_unknown_booking_text_refuses_the_statement(self):
        outcome = read(ordinary_statement(bookings=('16.02. 16.02. Mystery PN:903 0,00 H',)))
        self.assertIn('Mystery', outcome.error)

    def test_a_statement_that_is_not_an_account_statement_is_not_claimed(self):
        self.assertIsNone(read([['Ein Brief ohne Salden']]).reader_id)

    def test_garbled_headers_and_rules_do_not_change_the_result(self):                         # G8
        clean, garbled = read(closing_statement()), read(closing_statement(hdr=header(garbled=True)))
        self.assertEqual(garbled.reader_id, 'rvb_giro', garbled.error)
        self.assertEqual(clean.result.rows[0].data, garbled.result.rows[0].data)
        self.assertEqual(read(ordinary_statement(hdr=header(garbled=True))).result.notices, read(ordinary_statement()).result.notices)

    def test_the_bank_name_is_not_used(self):
        a = read(closing_statement()).result.rows[0].data['organisation']
        b = read(closing_statement(hdr=header(garbled=True))).result.rows[0].data['organisation']
        self.assertEqual(a, b)


def year_of_statements():
    """12 monthly statements for 2025 with chained balances; March, June, September and December are interest closings (5,00)."""
    out, balance = [], D('1000.00')
    for month in range(1, 13):
        end = (datetime.date(2025, month % 12 + 1, 1) if month < 12 else datetime.date(2026, 1, 1)) - datetime.timedelta(days=1)
        prev_end = datetime.date(2025, month, 1) - datetime.timedelta(days=1)
        fmt = lambda v: f'{v:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
        lines = [*header(f'{month}/2025'), f'alter Kontostand vom {prev_end:%d.%m.%Y} {fmt(balance)} H', f'05.{month:02d}. 05.{month:02d}. Dauerauftrag PN:900 10,00 H']
        balance += 10
        closing = month % 3 == 0
        if closing:
            lines.append(f'{end:%d.%m.} {end:%d.%m.} Abschluss lt. Anlage 1 PN:901 5,00 H')
            balance += 5
        lines.append(f'neuer Kontostand vom {end:%d.%m.%Y} {fmt(balance)} H')
        if closing:
            start = datetime.date(2025, month - 2, 1)
            lines += anlage([('1,0', f'{end:%d.%m.}', '5,00')], period=(f'{start:%d.%m.%Y}', f'{end:%d.%m.%Y}'), summe='5,00', end=f'{end:%d.%m.%Y}')
        out.append((f'statement-{month:02d}.pdf', [lines]))
    return out


class RvbStagingTests(UploadDirMixin, TestCase):
    def stage(self, *named):
        return pdf_imports.stage_pdf_batch([(n, make_pdf(p)) for n, p in named], PROVIDER)

    def test_a_year_of_twelve_statements_gives_four_rows_one_summary_line_and_no_warnings(self):
        batch = self.stage(*year_of_statements())
        self.assertEqual(batch.rows.count(), 4)
        self.assertEqual(batch.warnings, ['8 statements recognised, no income.'])
        self.assertEqual(batch.file_counts['nothing'], 8)

    def test_two_files_with_the_same_text_and_different_bytes_stage_one_statement(self):           # G7
        a, b = closing_statement(), closing_statement()
        b[0].append('Gedruckt am 02.04.2025')
        self.assertNotEqual(make_pdf(a), make_pdf(b))
        batch = self.stage(('one.pdf', a), ('two.pdf', b))
        self.assertEqual(batch.rows.count(), 1)
        self.assertTrue(any('two.pdf' in w and 'same statement as one.pdf' in w for w in batch.warnings), batch.warnings)

    def test_prize_notices_from_many_files_are_one_line(self):
        batch = self.stage(('a.pdf', ordinary_statement()), ('b.pdf', closing_statement()),
                           ('c.pdf', ordinary_statement(hdr=header('3/2025'))))
        prize = [w for w in batch.warnings if 'prize' in w]
        self.assertEqual(len(prize), 1)
        self.assertIn('in 2 statements', prize[0])

    def test_all_ordinary_statements_create_no_batch_but_report_the_notice(self):
        with self.assertRaises(pdf_imports.NothingToImport) as ctx:
            self.stage(('a.pdf', ordinary_statement()))
        self.assertIn('1 statement recognised, no income.', str(ctx.exception))
        self.assertIn('prize', str(ctx.exception))

    def test_real_chain_pdf_to_payment_with_withholding(self):
        batch = self.stage(('closing.pdf', closing_statement()))
        user = get_user_model().objects.create_user('u', password='p')
        self.client.force_login(user)
        r = self.client.post(reverse('import_commit', args=[batch.pk]))
        self.assertIn(r.status_code, (200, 302))
        p = Payment.objects.get()
        self.assertEqual((p.gross_amount, p.withholding_tax, p.net_amount, p.expenses, p.frequency), (D('50.00'), D('10.55'), D('39.45'), D('0'), 'quarterly'))
        self.assertEqual((p.income_period_start, p.income_period_end, p.currency), (datetime.date(2025, 1, 1), datetime.date(2025, 3, 31), 'EUR'))

    def test_a_refused_statement_stages_nothing(self):
        with self.assertRaisesRegex(svc.ImportFileError, 'do not add up'):
            self.stage(('x.pdf', closing_statement(neuer='1.089,46')))


from core.services.rates import FakeRateProvider
PROVIDER = FakeRateProvider({})

SAMPLES = Path(__file__).resolve().parent.parent / 'local' / 'samples'


@skipUnless((SAMPLES / 'RVB').is_dir(), 'owner-supplied RVB statements are not present (they are never committed)')
class LocalRvbTests(SimpleTestCase):
    """Reads the owner's real statements. Prints counts only. If local/samples/expected/rvb.csv exists (the owner's checked rows:
    payment_date,income_period_start,income_period_end,gross_amount,withholding_tax,net_amount) the rows must equal it."""

    def test_closings_are_staged_the_others_have_nothing_to_import_and_none_is_refused(self):
        files = sorted((SAMPLES / 'RVB').glob('*.pdf'))
        rows, refused, empty, texts = [], 0, 0, {}
        for path in files:
            outcome = sr.read_statement(path.read_bytes())
            if outcome.result is None:
                refused += 1
                continue
            texts.setdefault(outcome.result.fingerprint, []).append(path.name)
            if outcome.result.rows:
                d = outcome.result.rows[0].data
                rows.append((d['payment_date'], d['income_period_start'], d['income_period_end'], d['gross_amount'], d['withholding_tax'], d['net_amount']))
            else:
                empty += 1
        duplicates = sum(len(v) - 1 for v in texts.values())
        print(f'\nRVB: {len(files)} files, {len(rows)} closings staged, {empty} with nothing to import, {refused} refused, '
              f'{duplicates} duplicate(s) by fingerprint')
        self.assertEqual(refused, 0)
        expected_file = SAMPLES / 'expected' / 'rvb.csv'
        if expected_file.is_file():
            expected = [tuple(l.split(',')) for l in expected_file.read_text().splitlines()[1:] if l.strip()]
            self.assertEqual(sorted(set(rows)), sorted(set(expected)))
        else:
            print('RVB: no expected file (local/samples/expected/rvb.csv); rows not compared')
