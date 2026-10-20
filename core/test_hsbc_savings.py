"""Phase 16: HSBC UK savings statements (GBP). Synthetic PDFs only: invented holder and figures, worked out by hand.

The fixture imitates the structure of the real table (cells at their own positions, a date line, a description line,
a "TO <date>" line carrying the amount and balance, brought/carried forward rows, letter-spaced headings)."""
import datetime
import tempfile
from decimal import Decimal as D
from pathlib import Path
from unittest import mock, skipUnless

from django.test import SimpleTestCase, TestCase

from core.models import ImportBatch, Payment
from core.services import hsbc_savings, pdf_imports, pdf_text
from core.services import imports as svc
from core.services import statement_readers as sr
from core.services.rates import FakeRateProvider

from .test_pdf_imports import UploadDirMixin
from .test_pdf_support import make_pdf

D1 = datetime.date
PROVIDER = FakeRateProvider({('GBP', D1(2025, 1, 31)): D('1.2'), ('GBP', D1(2025, 2, 28)): D('1.2'), ('GBP', D1(2025, 3, 31)): D('1.2'),
                             ('GBP', D1(2025, 4, 30)): D('1.2'), ('GBP', D1(2025, 5, 31)): D('1.2')})
X_DATE, X_TYPE, X_DESC, X_OUT, X_IN, X_BAL = 30, 95, 130, 330, 400, 480


def cells(*pairs):
    return list(pairs)


def head(sheet='7', period='01 January 2025 to 31 March 2025', summary=True, spaced=False, opening='1,000.00', pin='510.60', pout='7.50', closing='1,503.10'):
    lines = [[(30, 'EXAMPLE BANK UK')], [(30, 'Statement of Account')], [(30, period)]]
    if summary:
        word = (lambda w: w) if not spaced else (lambda w: w[:3] + ' ' + w[3:])
        lines += [[(30, f'{word("Opening")} Balance £{opening}')], [(30, f'Payments In £{pin}')],
                  [(30, f'Payments Out £{pout}')], [(30, f'{word("Closing")} Balance £{closing}')]]
    lines += [[(30, 'Account Nam e'), (200, 'Sortcode'), (300, 'Account Num ber'), (420, 'Sheet Num ber')],
              [(30, 'EXAMPLE HOLDER'), (200, '00-00-00'), (300, '12345678'), (420, sheet)]]
    return lines


TABLE_HEADER = cells((X_DATE, 'Date'), (X_TYPE, 'Paym ent t ype and det ails'), (X_OUT, '£ Paid out'), (X_IN, '£ Paid in'), (X_BAL, '£ Balance'))


def bf(balance, date='01 Jan 25'):
    return cells((X_DATE, date), (X_DESC, 'BALANCE BROUGHT FORWARD'), (X_BAL, f'{balance}.'))


def cf(balance, date='31 Mar 25'):
    return cells((X_DATE, date), (X_DESC, 'BALANCE CARRIED FORWARD'), (X_BAL, balance))


def interest(date, to, amount, balance):
    return [cells((X_DATE, date), (X_TYPE, 'CR'), (X_DESC, 'GROSS INTEREST')), cells((X_DESC, f'TO {to}'), (X_IN, amount), (X_BAL, balance))]


def transfer(date, amount, balance, out=False):
    return [cells((X_DATE, date), (X_TYPE, 'ONL'), (X_DESC, '000000 11111111')),
            cells((X_DESC, 'INTERNET TRANSFER'), (X_OUT if out else X_IN, amount), (X_BAL, balance))]


# 1,000.00 +3.00 = 1,003.00; +500.00 transfer = 1,503.00; +4.50 = 1,507.50; -7.50 transfer = 1,500.00; +3.10 = 1,503.10
ROWS = [*interest('31 Jan 25', '31JAN2025', '3.00', '1,003.00'), *transfer('10 Feb 25', '500.00', '1,503.00'),
        *interest('28 Feb 25', '28FEB2025', '4.50', '1,507.50'), *transfer('05 Mar 25', '7.50', '1,500.00', out=True),
        *interest('31 Mar 25', '31MAR2025', '3.10', '1,503.10')]


def statement(rows=ROWS, **kw):
    return [[*head(**{k: v for k, v in kw.items() if k in ('sheet', 'period', 'summary', 'spaced', 'opening', 'pin', 'pout', 'closing')}),
             TABLE_HEADER, bf(kw.get('bf', '1,000.00')), *rows, cf(kw.get('cf', '1,503.10'))]]


def charge_after():
    return [cells((X_DATE, '15 Feb 25'), (X_TYPE, 'DR'), (X_DESC, 'ACCOUNT CHARGE')), cells((X_OUT, '2.00'), (X_BAL, '1,001.00'))]


def read(pages_lines):
    return sr.read_statement(make_pdf(pages_lines))


class HsbcReaderTests(SimpleTestCase):
    def test_three_interest_credits_become_three_rows_and_the_transfers_are_not_staged(self):
        outcome = read(statement())
        self.assertEqual(outcome.reader_id, 'hsbc_savings', outcome.error)
        rows = outcome.result.rows
        self.assertEqual([(r.data['payment_date'], r.data['gross_amount'], r.data['income_period_end']) for r in rows],
                         [('2025-01-31', '3.00', '2025-01-31'), ('2025-02-28', '4.50', '2025-02-28'), ('2025-03-31', '3.10', '2025-03-31')])
        for r in rows:
            d = r.data
            self.assertEqual((d['currency'], d['category'], d['frequency'], d['organisation'], d['withholding_tax'], d['expenses'],
                              d['income_period_start'], d['net_amount'] == d['gross_amount'], d['comment']),
                             ('GBP', 'Interest', 'monthly', 'HSBC UK (Flexible Saver)', '0', '0', '', True, 'Gross interest (PDF import).'))

    def test_layout_mode_keeps_each_table_row_on_one_line(self):
        raw = make_pdf(statement())
        plain = '\n'.join(pdf_text.extract_pages(raw))
        layout = '\n'.join(pdf_text.extract_pages(raw, layout=True))
        self.assertTrue(any('TO 31JAN2025' in l and '3.00' in l and '1,003.00' in l for l in layout.splitlines()))
        self.assertIn('GROSS INTEREST', plain)

    def test_provenance_cites_page_and_both_source_lines_with_digit_runs_masked(self):
        row = read(statement()).result.rows[0]
        page, text = row.provenance['gross_amount']
        self.assertEqual(page, 1)
        self.assertEqual(text, '31 Jan 25 CR GROSS INTEREST / TO 31JAN2025 3.00 1,003.00')
        self.assertEqual(set(row.provenance), {'payment_date', 'gross_amount', 'income_period_end'})

    def test_period_fingerprint_and_continuity(self):
        result = read(statement()).result
        self.assertEqual(result.period, (D1(2025, 1, 1), D1(2025, 3, 31)))
        self.assertEqual((result.continuity.sequence, result.continuity.opening, result.continuity.closing),
                         (7, D('1000.00'), D('1503.10')))
        same = read(statement(period='01 January 2025 to 31 March 2025 (re-issued)')).result
        self.assertEqual(result.fingerprint, same.fingerprint)
        self.assertNotEqual(result.fingerprint, read(statement(sheet='8')).result.fingerprint)

    def test_letter_spaced_summary_headings_do_not_prevent_recognition(self):          # G8
        outcome = read(statement(spaced=True))
        self.assertEqual(len(outcome.result.rows), 3, outcome.error)

    def test_a_statement_without_a_summary_block_is_read_from_the_table_alone(self):
        self.assertEqual(len(read(statement(summary=False)).result.rows), 3)

    def test_a_readable_summary_that_disagrees_refuses_the_statement(self):
        outcome = read(statement(pin='510.61'))
        self.assertIsNone(outcome.result)
        self.assertIn('summary block does not agree', outcome.error)

    def test_a_balance_wrong_by_one_penny_is_refused_naming_the_row_not_the_figures(self):
        rows = [*interest('31 Jan 25', '31JAN2025', '3.00', '1,003.00'), *transfer('10 Feb 25', '500.00', '1,503.00'),
                *interest('28 Feb 25', '28FEB2025', '4.50', '1,507.51')]
        outcome = read(statement(rows, summary=False, cf='1,507.51'))
        self.assertIn('row 3', outcome.error)
        self.assertFalse(any(ch.isdigit() for ch in outcome.error.replace('row 3', '')), outcome.error)

    def test_an_interest_credit_that_did_not_raise_the_balance_by_its_amount_is_refused(self):   # H4
        rows = interest('31 Jan 25', '31JAN2025', '3.00', '1,002.00')
        outcome = read(statement(rows, summary=False, cf='1,002.00'))
        self.assertIn('row 1', outcome.error)

    def test_an_unknown_row_type_is_refused_naming_the_type_text(self):                   # G12, H7
        outcome = read(statement([*interest('31 Jan 25', '31JAN2025', '3.00', '1,003.00'), *charge_after(), ], summary=False, cf='1,001.00'))
        self.assertIsNone(outcome.result)
        self.assertIn('ACCOUNT CHARGE', outcome.error)
        self.assertIn('Row 2', outcome.error)

    def test_a_transfer_that_fits_neither_direction_is_refused(self):
        outcome = read(statement(transfer('10 Feb 25', '500.00', '1,600.00'), summary=False, cf='1,600.00'))
        self.assertIn('running balance', outcome.error)

    def test_a_row_without_a_date_cannot_hide_a_credit(self):
        undated = interest('31 Jan 25', '31JAN2025', '3.00', '1,003.00')
        undated[0] = cells((X_TYPE, 'CR'), (X_DESC, 'GROSS INTEREST'))
        outcome = read(statement(undated, summary=False, cf='1,003.00'))
        self.assertIsNone(outcome.result)                                   # the skipped credit breaks the balance chain

    def test_brought_and_carried_forward_rows_must_pair_up(self):
        lines = statement()
        del lines[0][-1]
        self.assertIsNone(read(lines).result)

    def test_a_table_that_continues_on_page_two_with_a_repeated_header_stages_every_credit_once(self):   # H6
        page1 = [*head(summary=False), TABLE_HEADER, bf('1,000.00'), *interest('31 Jan 25', '31JAN2025', '3.00', '1,003.00'),
                 *transfer('10 Feb 25', '500.00', '1,503.00'), cf('1,503.00', '10 Feb 25')]
        page2 = [*head(summary=False), TABLE_HEADER, bf('1,503.00', '10 Feb 25'), *interest('28 Feb 25', '28FEB2025', '4.50', '1,507.50'),
                 *interest('31 Mar 25', '31MAR2025', '3.00', '1,510.50'), cf('1,510.50')]
        outcome = read([page1, page2])
        self.assertEqual([r.data['gross_amount'] for r in outcome.result.rows], ['3.00', '4.50', '3.00'], outcome.error)
        self.assertEqual(outcome.result.continuity.closing, D('1510.50'))

    def test_a_continuation_page_with_a_repeated_header_but_no_markers_is_read(self):
        page1 = [*head(summary=False), TABLE_HEADER, bf('1,000.00'), *interest('31 Jan 25', '31JAN2025', '3.00', '1,003.00')]
        page2 = [*head(summary=False), TABLE_HEADER, *interest('28 Feb 25', '28FEB2025', '4.50', '1,007.50'), cf('1,007.50', '28 Feb 25')]
        outcome = read([page1, page2])
        self.assertEqual(len(outcome.result.rows), 2, outcome.error)

    def test_balances_that_do_not_chain_across_pages_are_refused(self):
        page1 = [*head(summary=False), TABLE_HEADER, bf('1,000.00'), *interest('31 Jan 25', '31JAN2025', '3.00', '1,003.00'), cf('1,003.00', '31 Jan 25')]
        page2 = [*head(summary=False), TABLE_HEADER, bf('1,004.00', '31 Jan 25'), cf('1,004.00')]
        self.assertIn('continue', read([page1, page2]).error)

    def test_other_statements_are_not_claimed(self):
        self.assertFalse(hsbc_savings.recognises(['A letter. Paid in Paid out Balance £']))
        self.assertIsNone(read([[['A letter about something else']][0]]).reader_id)


class HsbcStagingTests(UploadDirMixin, TestCase):
    def stage(self, *named):
        return pdf_imports.stage_pdf_batch([(n, make_pdf(p)) for n, p in named], PROVIDER)

    def test_real_chain_pdf_to_staged_rows_to_payments(self):
        batch = self.stage(('hsbc.pdf', statement()))
        self.assertEqual(batch.rows.count(), 3)
        self.assertEqual(set(batch.rows.values_list('status', flat=True)), {'valid'})
        self.assertEqual(batch.rows.first().rate, D('1.2'))
        self.assertEqual(Payment.objects.count(), 0)

    def next_statement(self, sheet, opening, rows, closing, start, end):
        return statement(rows, sheet=sheet, summary=False, **{'bf': opening, 'cf': closing}) if False else [[
            *head(sheet=sheet, summary=False), TABLE_HEADER, bf(opening, start), *rows, cf(closing, end)]]

    def test_consecutive_statements_with_a_missing_sheet_number_give_a_gap_warning(self):
        first = self.next_statement('7', '1,000.00', interest('31 Jan 25', '31JAN2025', '3.00', '1,003.00'), '1,003.00', '01 Jan 25', '31 Jan 25')
        third = self.next_statement('9', '1,003.00', interest('30 Apr 25', '30APR2025', '3.00', '1,006.00'), '1,006.00', '31 Jan 25', '30 Apr 25')
        batch = self.stage(('a.pdf', first), ('b.pdf', third))
        self.assertTrue(any('after a.pdf' in w and 'skip from 7 to 9' in w and 'connect' in w for w in batch.warnings), batch.warnings)

    def test_unconnected_balances_warn(self):
        first = self.next_statement('7', '1,000.00', interest('31 Jan 25', '31JAN2025', '3.00', '1,003.00'), '1,003.00', '01 Jan 25', '31 Jan 25')
        second = self.next_statement('8', '1,500.00', interest('30 Apr 25', '30APR2025', '3.00', '1,503.00'), '1,503.00', '31 Jan 25', '30 Apr 25')
        batch = self.stage(('a.pdf', first), ('b.pdf', second))
        self.assertTrue(any('opening balance does not match the closing balance of a.pdf' in w for w in batch.warnings), batch.warnings)
        self.assertFalse(any('1,000' in w or '1,500' in w for w in batch.warnings))

    def test_consecutive_statements_that_connect_give_no_warning(self):
        first = self.next_statement('7', '1,000.00', interest('31 Jan 25', '31JAN2025', '3.00', '1,003.00'), '1,003.00', '01 Jan 25', '31 Jan 25')
        second = self.next_statement('8', '1,003.00', interest('28 Feb 25', '28FEB2025', '3.00', '1,006.00'), '1,006.00', '31 Jan 25', '28 Feb 25')
        batch = self.stage(('a.pdf', first), ('b.pdf', second))
        self.assertEqual(batch.warnings, [])
        self.assertEqual(batch.rows.count(), 2)

    def test_the_same_statement_uploaded_twice_is_staged_once(self):
        a = statement()
        b = statement(period='01 January 2025 to 31 March 2025 (copy)')
        batch = self.stage(('one.pdf', a), ('two.pdf', b))
        self.assertEqual(batch.rows.count(), 3)
        self.assertTrue(any('same statement as one.pdf' in w for w in batch.warnings))
        again = self.stage(('one.pdf', a), ('same-bytes.pdf', a))
        self.assertEqual(again.rows.count(), 3)

    def test_a_refused_statement_stages_nothing(self):
        with self.assertRaisesRegex(svc.ImportFileError, 'ACCOUNT CHARGE'):
            self.stage(('c.pdf', statement([*interest('31 Jan 25', '31JAN2025', '3.00', '1,003.00'), *charge_after()], summary=False, cf='1,001.00')))
        self.assertEqual(ImportBatch.objects.count(), 0)


SAMPLES = Path(__file__).resolve().parent.parent / 'local' / 'samples'


@skipUnless((SAMPLES / 'HSBC').is_dir(), 'owner-supplied HSBC statements are not present (they are never committed)')
class LocalHsbcTests(SimpleTestCase):
    """Reads the owner's real statements. Prints counts only. If local/samples/expected/hsbc.csv exists (the owner's
    checked rows: payment_date,income_period_end,gross_amount), the staged rows must equal it."""

    def test_every_file_is_staged_and_matches_the_owner_checked_rows(self):
        files = sorted((SAMPLES / 'HSBC').glob('*.pdf'))
        self.assertTrue(files)
        staged = []
        for path in files:
            outcome = sr.read_statement(path.read_bytes())
            self.assertEqual((outcome.reader_id, outcome.error), ('hsbc_savings', ''), path.name[:12])
            self.assertTrue(outcome.result.rows)
            staged += [(r.data['payment_date'], r.data['income_period_end'], r.data['gross_amount']) for r in outcome.result.rows]
        print(f'\nHSBC: {len(files)} files staged, {len(staged)} interest rows')
        expected_file = SAMPLES / 'expected' / 'hsbc.csv'
        if expected_file.is_file():
            expected = [tuple(line.split(',')) for line in expected_file.read_text().splitlines()[1:] if line.strip()]
            self.assertEqual(sorted(staged), sorted(expected))
        else:
            print('HSBC: no expected file (local/samples/expected/hsbc.csv); rows not compared')
