"""Phase 21: managing-agent rental statements (AUD). Synthetic PDFs only: invented agent, tenant, street and figures, worked
out by hand in the comments. The fixture imitates the structure of the real statements (Money In/Out/You Received, the
rent entry whose lines wrap, cost lines before "Total", sundry fee and owner withdrawal after it)."""
import datetime
from decimal import Decimal as D
from pathlib import Path
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from core.models import Payment
from core.services import hodges_rental, pdf_imports
from core.services import imports as svc
from core.services import statement_readers as sr
from core.services.rates import FakeRateProvider

from .test_pdf_imports import UploadDirMixin
from .test_pdf_support import make_pdf

AGENT = 'EXAMPLE AGENT'
D1 = datetime.date

WRAPPED_RECEIPT = ['5/03 EXAMPLE TENANT, 1 EXAMPLE STREET 4000', 'Rented at $1,000.00 per month',
                   'Rent paid to 15/03/2025 with part payment of $10.00 (previously paid to 01/03/2025 + $5.00) , rent increased to',
                   '$1,100.00 on 01/04/25', '$1,000.00']
INLINE_RECEIPT = ['Rent paid to 30/04/2025 with part payment of $10.00 (previously paid to 15/03/2025 + $5.00) $800.00']


def statement(receipts=(WRAPPED_RECEIPT, INLINE_RECEIPT), costs=('Repairs - lock * $120.00', 'Management Fee * $180.00'), total='$300.00',
              money_in='$1,800.00', money_out='$312.50', received='$1,487.50', sundry=('Sundry fee * $12.50',), after=(), number='12',
              statement_date='31 Mar 2025', withdrawal='Withdrawal to owner by cheque $1,487.50', total_in='$1,800.00'):
    """Two receipts 1,000.00 + 800.00 = 1,800.00; costs 120.00 + 180.00 = 300.00 (the Total line); sundry 12.50 (not in Total):
    Money Out 312.50; You Received 1,800.00 - 312.50 = 1,487.50."""
    lines = ['EXAMPLE AGENT PTY LTD', 'Tax Invoice', f'Statement #{number}', statement_date, f'Money In {money_in}', f'Money Out {money_out}',
             f'You Received {received}', 'Date Description Money Out Money In', 'Balance brought forward $5.00']
    for receipt in receipts:
        lines += receipt
    lines += [*costs, f'Total {total} {total_in}', 'Sundry charges', *sundry]
    if withdrawal:
        lines += [withdrawal, '[bank transfer to: EXAMPLE BANK (000000) - ***000]']
    lines += ['Balance carried forward $5.00', 'GST summary', 'Total Tax on income received $0.00', 'Total Tax on fees $29.77', '( * includes Tax)', *after]
    return [lines]


def read(pages):
    return sr.read_statement(make_pdf(pages))


@override_settings(RENTAL_ORGANISATION=AGENT)
class HodgesReaderTests(SimpleTestCase):
    def test_two_receipts_a_wrapped_line_costs_a_starred_repair_and_a_withdrawal_give_one_row(self):     # A2, A3, A4, A8
        outcome = read(statement())
        self.assertEqual(outcome.reader_id, 'hodges_rental', outcome.error)
        (row,) = outcome.result.rows
        d = row.data
        self.assertEqual((d['gross_amount'], d['expenses'], d['net_amount'], d['withholding_tax']), ('1800.00', '312.50', '1487.50', '0'))
        self.assertEqual((d['payment_date'], d['organisation'], d['category'], d['currency'], d['frequency']),
                         ('2025-03-31', AGENT, 'Rental', 'AUD', 'monthly'))
        self.assertEqual((d['income_period_start'], d['income_period_end']), ('2025-03-02', '2025-04-30'))
        self.assertEqual(d['comment'], 'Rental statement (PDF import). 3 cost line(s) flagged * include GST (no GST split recorded).')
        self.assertEqual(outcome.result.notices, ['Owner withdrawal not imported (1, statement dated 2025-03-31).'])      # not staged, noticed

    def test_the_withdrawal_is_neither_income_nor_expense(self):
        no_withdrawal = read(statement(withdrawal='')).result
        self.assertEqual(no_withdrawal.rows[0].data['expenses'], '312.50')
        self.assertEqual(no_withdrawal.notices, [])

    def test_the_total_line_that_excludes_the_sundry_fee_is_not_the_check(self):                  # A5
        outcome = read(statement())
        self.assertEqual(outcome.error, '')
        # Money Out is Total (300.00) + sundry (12.50); a Money Out equal to the Total alone is refused
        bad = read(statement(money_out='$300.00', received='$1,500.00'))
        self.assertIn('Money Out', bad.error)

    def test_a_statement_that_does_not_close_is_refused_naming_the_block_not_the_figures(self):  # A1, G9
        outcome = read(statement(received='$1,487.51'))
        self.assertIsNone(outcome.result)
        self.assertIn('Money In minus Money Out', outcome.error)
        self.assertFalse(any(ch.isdigit() for ch in outcome.error), outcome.error)
        self.assertIn('cost lines do not add up to the Total', read(statement(total='$301.00', money_in='$1,800.00')).error)
        self.assertIn('rent entries do not add up to Money In', read(statement(money_in='$1,801.00', total_in='$1,801.00', received='$1,488.50')).error)

    def test_a_short_final_period_and_a_two_month_statement_get_the_printed_period(self):        # A6
        short = statement(receipts=(['5/01 EXAMPLE TENANT, 1 EXAMPLE STREET 4000',
                                     'Rent paid to 17/01/2026 with part payment of $10.00 (previously paid to 20/12/2025 + $5.00) $400.00'],),
                          costs=('Management Fee * $40.00',), total='$40.00', money_in='$400.00', total_in='$400.00', sundry=(), money_out='$40.00',
                          received='$360.00', withdrawal='')
        d = read(short).result.rows[0].data
        self.assertEqual((d['income_period_start'], d['income_period_end']), ('2025-12-21', '2026-01-17'))
        two = read(statement()).result.rows[0].data
        self.assertEqual((two['income_period_start'], two['income_period_end']), ('2025-03-02', '2025-04-30'))

    def test_an_arrears_line_is_refused_naming_the_label(self):                                  # A7, G12
        outcome = read(statement(costs=('Rent arrears owing * $120.00', 'Management Fee * $180.00')))
        self.assertIsNone(outcome.result)
        self.assertIn('Rent arrears owing', outcome.error)
        self.assertNotIn('120', outcome.error)

    def test_an_unknown_line_after_the_total_is_refused_naming_it(self):
        outcome = read(statement(sundry=('Sundry fee * $12.50', 'Letting fee $10.00')))
        self.assertIn('Letting fee', outcome.error)

    def test_a_money_in_entry_that_is_not_rent_is_refused(self):
        other = ['5/03 EXAMPLE TENANT, 1 EXAMPLE STREET 4000', 'Part payment of bond received', '$1,000.00']
        self.assertIn('not rent', read(statement(receipts=(other, INLINE_RECEIPT))).error)

    def test_costs_without_a_star_are_expenses_too(self):                                         # council and water rates
        pages = statement(costs=('Council Rates 2025/2026 - 3rd instalment - EXAMPLE CITY $120.00', 'Management Fee * $180.00'))
        d = read(pages).result.rows[0].data
        self.assertEqual(d['expenses'], '312.50')
        self.assertIn('2 cost line(s) flagged', d['comment'])           # the management fee and the sundry fee are flagged; the rates are not

    def test_the_organisation_comes_from_the_setting_and_is_required(self):
        with override_settings(RENTAL_ORGANISATION=''):
            outcome = read(statement())
        self.assertIsNone(outcome.result)
        self.assertIn('DJANGO_RENTAL_ORGANISATION', outcome.error)
        with override_settings(RENTAL_ORGANISATION='Another Agent'):
            self.assertEqual(read(statement()).result.rows[0].data['organisation'], 'Another Agent')

    def test_the_agent_name_is_not_in_the_reader_or_its_tests(self):
        forbidden = ['Real' + 'estate']      # the agent's own name is only ever read from the setting
        for path in (Path(hodges_rental.__file__), Path(__file__)):
            text = path.read_text()
            for word in forbidden:
                self.assertNotIn(word, text, path.name)

    def test_other_documents_are_not_claimed(self):
        self.assertIsNone(read([['Tax Invoice for something else']]).reader_id)

    def test_fingerprint_is_statement_number_period_end_and_received(self):
        a, b, c = read(statement()).result, read(statement(statement_date='1 Apr 2025')).result, read(statement(number='13')).result
        self.assertEqual(a.fingerprint, b.fingerprint)
        self.assertNotEqual(a.fingerprint, c.fingerprint)


@override_settings(RENTAL_ORGANISATION=AGENT)
class HodgesStagingTests(UploadDirMixin, TestCase):
    PROVIDER = FakeRateProvider({('AUD', D1(2025, 3, 31)): D('0.6')})

    def test_real_chain_pdf_to_payment_with_expenses(self):
        batch = pdf_imports.stage_pdf_batch([('stmt.pdf', make_pdf(statement()))], self.PROVIDER)
        self.assertEqual(batch.rows.get().status, 'valid')
        user = get_user_model().objects.create_user('u', password='p')
        self.client.force_login(user)
        self.assertIn(self.client.post(reverse('import_commit', args=[batch.pk])).status_code, (200, 302))
        p = Payment.objects.get()
        self.assertEqual((p.gross_amount, p.expenses, p.net_amount, p.withholding_tax, p.category.name, p.frequency),
                         (D('1800.00'), D('312.50'), D('1487.50'), D('0'), 'Rental', 'monthly'))
        self.assertEqual((p.income_period_start, p.income_period_end, p.currency), (D1(2025, 3, 2), D1(2025, 4, 30), 'AUD'))
        self.assertTrue(any('Owner withdrawal' in w for w in batch.warnings), batch.warnings)

    def test_a_reissued_statement_is_staged_once(self):
        a, b = statement(), statement()
        b[0].append('Printed again')
        batch = pdf_imports.stage_pdf_batch([('one.pdf', make_pdf(a)), ('two.pdf', make_pdf(b))], self.PROVIDER)
        self.assertEqual(batch.rows.count(), 1)
        self.assertTrue(any('same statement as one.pdf' in w for w in batch.warnings))

    def test_a_refused_statement_stages_nothing(self):
        with self.assertRaisesRegex(svc.ImportFileError, 'Money In minus Money Out'):
            pdf_imports.stage_pdf_batch([('bad.pdf', make_pdf(statement(received='$1,487.51')))], self.PROVIDER)


SAMPLES = Path(__file__).resolve().parent.parent / 'local' / 'samples'


@skipUnless((SAMPLES / 'Hodges').is_dir(), 'owner-supplied rental statements are not present (they are never committed)')
@override_settings(RENTAL_ORGANISATION=AGENT)
class LocalHodgesTests(SimpleTestCase):
    """Reads the owner's real statements; prints counts only. If local/samples/expected/hodges.csv exists
    (payment_date,income_period_start,income_period_end,gross_amount,expenses,net_amount) the rows must equal it."""

    def test_every_file_is_staged_and_matches_the_owner_checked_rows(self):
        files = sorted((SAMPLES / 'Hodges').glob('*.pdf'))
        rows = []
        for path in files:
            outcome = sr.read_statement(path.read_bytes())
            self.assertEqual((outcome.reader_id, outcome.error), ('hodges_rental', ''), path.name[:12])
            d = outcome.result.rows[0].data
            rows.append((d['payment_date'], d['income_period_start'], d['income_period_end'], d['gross_amount'], d['expenses'], d['net_amount']))
        print(f'\nHodges: {len(files)} files staged, {len(rows)} rows')
        expected_file = SAMPLES / 'expected' / 'hodges.csv'
        if expected_file.is_file():
            expected = [tuple(l.split(',')) for l in expected_file.read_text().splitlines()[1:] if l.strip()]
            self.assertEqual(sorted(rows), sorted(expected))
        else:
            print('Hodges: no expected file (local/samples/expected/hodges.csv); rows not compared')
