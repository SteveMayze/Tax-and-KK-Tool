"""Phase 15: reader registry, multi-row results, layout extraction, amount parsers, fingerprints, masking, inventory.
Synthetic PDFs only (invented names and figures)."""
import datetime
import io
import re
import tempfile
from decimal import Decimal as D
from pathlib import Path
from unittest import mock, skipUnless

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.models import ImportBatch
from core.services import amounts, organisations, pdf_imports, pdf_inventory, pdf_text, statement_readers as sr
from core.services import dividend_statements as ds
from core.services import imports as svc
from core.services import interest_statements as it
from core.services.imports import COLUMNS

from .test_pdf_imports import PROVIDER, UploadDirMixin
from .test_pdf_support import ACCEPTED, MUFG_STYLE, fund_statement, make_pdf

SAMPLES = Path(__file__).resolve().parent.parent / 'local' / 'samples'


def example_row(date='2025-05-12', gross='10.00', organisation='EXAMPLE CORP (EXMP)'):
    data = {c: '' for c in COLUMNS}
    data.update(payment_date=date, organisation=organisation, category='Dividends', currency='AUD', gross_amount=gross,
                net_amount=gross, withholding_tax='0', expenses='0', frequency='one_off', comment='Example (PDF import).')
    return sr.StatementRow(data, {'gross_amount': (1, f'Example line {gross}')})


def example_reader(reader_id='example', claim='EXAMPLE-STATEMENT', rows=1, fingerprint=False, not_imported=False):
    """A synthetic reader: claims pages containing `claim`; the first line after it says how many rows to return."""
    def parse(pages):
        n = int(re.search(r'ROWS (\d+)', '\n'.join(pages)).group(1))
        number = re.search(r'NUMBER (\w+)', '\n'.join(pages))
        return sr.StatementResult(rows=[example_row(gross=f'{i + 1}.00') for i in range(n)], notices=['Example notice.'] if not_imported else [],
                                  fingerprint=sr.short_hash(number.group(1)) if fingerprint and number else '',
                                  not_imported=not_imported and n == 0)
    return sr.Reader(reader_id, lambda pages: claim in '\n'.join(pages), parse)


def example_pdf(n, number='A1', extra=()):
    return make_pdf([['EXAMPLE-STATEMENT', f'ROWS {n}', f'NUMBER {number}', *extra]])


class AmountTests(SimpleTestCase):
    def test_us(self):
        for text, value in (('1,234.56', '1234.56'), ('$1,234.56', '1234.56'), ('(1,234.56)', '-1234.56'), ('-12.50', '-12.50'),
                            ('—', '0'), ('-', '0'), ('  7.5  ', '7.5'), ('0.00', '0.00')):
            self.assertEqual(amounts.parse_amount_us(text), D(value), text)
        for bad in ('1.234,56', '(12.00', '12.00)', '1,23.00', '', 'abc'):
            with self.assertRaises(ValueError, msg=bad):
                amounts.parse_amount_us(bad)

    def test_uk(self):
        for text, value in (('1,234.56', '1234.56'), ('£1,234.56', '1234.56'), ('-3.10', '-3.10'), ('0.05', '0.05')):
            self.assertEqual(amounts.parse_amount_uk(text), D(value), text)
        for bad in ('(3.10)', '1.234,56', '3.10 CR', ''):
            with self.assertRaises(ValueError, msg=bad):
                amounts.parse_amount_uk(bad)

    def test_german_with_h_or_s(self):
        for text, value in (('1.234,56 H', '1234.56'), ('1.234,56 S', '-1234.56'), ('0,05H', '0.05'), ('12,00 S', '-12.00')):
            self.assertEqual(amounts.parse_amount_de_with_hs(text), D(value), text)
        for bad in ('1.234,56', '1,234.56 H', '12,00 X', '1.23,00 H'):
            with self.assertRaises(ValueError, msg=bad):
                amounts.parse_amount_de_with_hs(bad)

    def test_spaces_are_squeezed(self):
        self.assertEqual(amounts.squeeze_spaces('  a    b  c '), 'a b c')


class LayoutExtractionTests(SimpleTestCase):
    def test_layout_mode_returns_text_and_keeps_the_refusals(self):
        raw = make_pdf([['Date Details 12.50 100.00']])
        self.assertIn('Details', pdf_text.extract_pages(raw, layout=True)[0])
        with self.assertRaisesRegex(pdf_text.PdfError, 'no text layer'):
            pdf_text.extract_pages(make_pdf([[]]), layout=True)
        with self.assertRaisesRegex(pdf_text.PdfError, 'not a PDF'):
            pdf_text.extract_pages(b'x', layout=True)

    def test_needs_layout_readers_receive_layout_text(self):
        seen = {}
        def parse(pages):
            seen['pages'] = pages
            return sr.StatementResult(rows=[])
        reader = sr.Reader('layouty', lambda pages: True, parse, needs_layout=True)
        with mock.patch.object(sr, 'READERS', [reader]), mock.patch.object(pdf_text, 'extract_pages', wraps=pdf_text.extract_pages) as spy:
            sr.read_statement(example_pdf(0))
        self.assertEqual([c.kwargs.get('layout', False) for c in spy.call_args_list], [False, True])


class MaskingTests(SimpleTestCase):
    def test_digit_runs_of_six_or_more_are_masked(self):
        self.assertEqual(pdf_text.mask_digit_runs('Konto_1234567_2025.01.31.pdf'), 'Konto_######_2025.01.31.pdf')
        self.assertEqual(pdf_text.mask_digit_runs('a12345b'), 'a12345b')


class RegistryTests(SimpleTestCase):
    def test_phase_14_readers_give_the_same_rows_as_the_statement_objects(self):
        for name, (lines, _e) in ACCEPTED.items():
            raw = make_pdf([lines])
            d = ds.parse(pdf_text.extract_pages(raw))
            outcome = sr.read_statement(raw)
            self.assertEqual(outcome.reader_id, 'au_dividend_advice', name)
            (row,) = outcome.result.rows
            self.assertEqual(row.data, d.row_data(COLUMNS), name)
            self.assertEqual(row.provenance, d.provenance_items(), name)
        raw = make_pdf([fund_statement()])
        f = it.parse(pdf_text.extract_pages(raw))
        outcome = sr.read_statement(raw)
        self.assertEqual(outcome.reader_id, 'revolut_flexible_cash_funds')
        (row,) = outcome.result.rows
        self.assertEqual((row.data, row.provenance), (f.row_data(COLUMNS), f.provenance_items()))
        self.assertEqual(outcome.result.period, (f.period_start, f.payment_date))

    def test_unrecognised_file_names_no_reader(self):
        outcome = sr.read_statement(make_pdf([['A letter about nothing in particular.']]))
        self.assertIsNone(outcome.reader_id)
        self.assertIn('not recognised', outcome.error)

    def test_refusal_by_the_chosen_reader_is_kept(self):
        outcome = sr.read_statement(make_pdf([fund_statement(earned='1.6000')]))
        self.assertEqual(outcome.reader_id, 'revolut_flexible_cash_funds')
        self.assertIn('do not add up', outcome.error)

    def test_two_readers_claiming_one_file_are_refused_naming_both(self):
        readers = [example_reader('first'), example_reader('second')]
        with mock.patch.object(sr, 'READERS', readers):
            outcome = sr.read_statement(example_pdf(1))
        self.assertIsNone(outcome.result)
        self.assertIn('first', outcome.error)
        self.assertIn('second', outcome.error)

    def test_the_security_name_tidier_is_shared(self):
        self.assertEqual(organisations.tidy_security_name('EXAMPLE CORP AND SONS LTD'), 'Example Corp and Sons Ltd')
        self.assertEqual(organisations.tidy_security_name('Example Fund'), 'Example Fund')
        self.assertIs(ds._tidy_name, organisations.tidy_security_name)
        self.assertEqual(organisations.BANK_ORGANISATIONS['hsbc_savings'], 'HSBC UK (Flexible Saver)')
        self.assertEqual(organisations.BANK_ORGANISATIONS['rvb_giro'], 'RVB (Girokonto)')


class MultiRowStagingTests(UploadDirMixin, TestCase):
    def stage(self, *files, readers=None):
        with mock.patch.object(sr, 'READERS', readers or [example_reader(fingerprint=True)]):
            return pdf_imports.stage_pdf_batch(list(files), PROVIDER)

    def test_zero_one_and_three_rows(self):
        with self.assertRaises(pdf_imports.NothingToImport) as ctx:
            self.stage(('z.pdf', example_pdf(0)))
        self.assertIn('1 statement recognised, no income', str(ctx.exception))
        self.assertEqual(ImportBatch.objects.count(), 0)
        one = self.stage(('one.pdf', example_pdf(1, 'B1')))
        self.assertEqual(one.rows.count(), 1)
        three = self.stage(('three.pdf', example_pdf(3, 'C1')))
        self.assertEqual(list(three.rows.values_list('line_number', flat=True)), [1, 2, 3])
        self.assertEqual({r.source_name for r in three.rows.all()}, {'three.pdf'})
        self.assertEqual(three.rows.first().provenance['gross_amount']['text'], 'Example line 1.00')

    def test_rows_of_several_files_get_unique_line_numbers_and_the_summary_line(self):
        batch = self.stage(('a.pdf', example_pdf(3, 'A1')), ('b.pdf', example_pdf(0, 'B1')), ('c.pdf', example_pdf(0, 'C1')),
                           ('d.pdf', example_pdf(1, 'D1')))
        self.assertEqual(list(batch.rows.values_list('line_number', flat=True)), [1, 2, 3, 4])
        self.assertEqual(batch.file_counts, {'files': 4, 'staged': 2, 'rows': 4, 'nothing': 2, 'not_imported': 0, 'not_staged': 0})
        self.assertEqual(batch.warnings.count('2 statements recognised, no income.'), 1)
        self.assertEqual(len(batch.warnings), 1)                       # one summary line, not one warning per file
        self.assertEqual(batch.file_name, '2 PDF statements')

    def test_recognised_and_not_imported_is_a_notice_not_an_error(self):
        reader = example_reader(not_imported=True)
        batch = self.stage(('sale.pdf', example_pdf(0, 'S1')), ('div.pdf', example_pdf(1, 'D1')), readers=[reader])
        self.assertTrue(any('recognised and not imported' in w for w in batch.warnings))
        self.assertTrue(any('Example notice. (in 2 statements, for example div.pdf)' in w for w in batch.warnings), batch.warnings)   # the same text is one line

    def test_a_refused_file_next_to_a_nothing_to_import_file_is_an_error(self):
        with self.assertRaisesRegex(svc.ImportFileError, 'nothing was staged.*1 statement recognised, no income'):
            self.stage(('z.pdf', example_pdf(0)), ('letter.pdf', make_pdf([['Something else']])))

    def test_two_files_with_one_fingerprint_are_one_statement(self):
        batch = self.stage(('a-first.pdf', example_pdf(1, 'SAME', ['version 1'])), ('b-reissue.pdf', example_pdf(1, 'SAME', ['version 2'])))
        self.assertEqual(batch.rows.count(), 1)
        self.assertEqual(batch.rows.get().source_name, 'a-first.pdf')
        self.assertTrue(any('b-reissue.pdf' in w and 'same statement as a-first.pdf' in w for w in batch.warnings))

    def test_phase_14_fund_reissue_is_caught_by_its_fingerprint(self):
        a, b = make_pdf([fund_statement()]), make_pdf([fund_statement() + ['Generated again']])
        self.assertNotEqual(a, b)
        batch = pdf_imports.stage_pdf_batch([('one.pdf', a), ('two.pdf', b)], PROVIDER)
        self.assertEqual(batch.rows.count(), 1)
        self.assertTrue(any('same statement as one.pdf' in w for w in batch.warnings))

    def test_all_files_without_income_create_no_batch_through_the_upload_view(self):
        user = get_user_model().objects.create_user('u', password='p')
        self.client.force_login(user)
        patcher = mock.patch('core.views_imports.get_provider', return_value=PROVIDER)
        patcher.start()
        self.addCleanup(patcher.stop)
        with mock.patch.object(sr, 'READERS', [example_reader()]):
            r = self.client.post(reverse('import_upload'), {'file': [SimpleUploadedFile('z.pdf', example_pdf(0))]}, follow=True)
        self.assertRedirects(r, reverse('import_list'))
        self.assertContains(r, 'no income')
        self.assertEqual(ImportBatch.objects.count(), 0)

    def test_upload_message_counts_files_and_rows(self):
        user = get_user_model().objects.create_user('u', password='p')
        self.client.force_login(user)
        patcher = mock.patch('core.views_imports.get_provider', return_value=PROVIDER)
        patcher.start()
        self.addCleanup(patcher.stop)
        files = [SimpleUploadedFile('a.pdf', example_pdf(3, 'A')), SimpleUploadedFile('b.pdf', example_pdf(0, 'B')),
                 SimpleUploadedFile('c.pdf', make_pdf([['Something else']]))]
        with mock.patch.object(sr, 'READERS', [example_reader(fingerprint=True)]):
            r = self.client.post(reverse('import_upload'), {'file': files}, follow=True)
        self.assertContains(r, '1 of 3 PDF files read and staged as 3 rows; 1 recognised with no income or not imported; 1 not staged')

    def test_real_chain_pdf_to_payment(self):
        """PDF bytes -> pdf_text -> reader -> staging -> review -> commit (the Phase 14 readers, unchanged)."""
        user = get_user_model().objects.create_user('u', password='p')
        self.client.force_login(user)
        patcher = mock.patch('core.views_imports.get_provider', return_value=PROVIDER)
        patcher.start()
        self.addCleanup(patcher.stop)
        batch = pdf_imports.stage_pdf_batch([('acme.pdf', make_pdf([MUFG_STYLE]))], PROVIDER)
        self.assertEqual(self.client.get(reverse('import_preview', args=[batch.pk])).status_code, 200)
        r = self.client.post(reverse('import_commit', args=[batch.pk]))
        self.assertIn(r.status_code, (200, 302))
        from core.models import Payment
        self.assertEqual(Payment.objects.count(), 1)


class MaskedNameDisplayTests(UploadDirMixin, TestCase):
    def test_account_like_digits_in_file_names_are_masked_in_review_and_history(self):
        user = get_user_model().objects.create_user('u', password='p')
        self.client.force_login(user)
        patcher = mock.patch('core.views_imports.get_provider', return_value=PROVIDER)
        patcher.start()
        self.addCleanup(patcher.stop)
        batch = pdf_imports.stage_pdf_batch([('Konto_1234567890_2025.pdf', make_pdf([MUFG_STYLE]))], PROVIDER)
        self.assertEqual((batch.file_name, batch.rows.get().source_name), ('Konto_######_2025.pdf', 'Konto_######_2025.pdf'))
        row = batch.rows.get()
        for url in (reverse('import_preview', args=[batch.pk]), reverse('import_list'),
                    reverse('import_row_edit', args=[batch.pk, row.line_number])):
            page = self.client.get(url).content.decode()
            self.assertNotIn('1234567890', page)
            self.assertIn('Konto_######_2025.pdf', page)

    def test_the_stored_original_keeps_its_bytes(self):
        raw = make_pdf([MUFG_STYLE])
        batch = pdf_imports.stage_pdf_batch([('Konto_1234567890.pdf', raw)], PROVIDER)
        self.assertEqual(svc.upload_path(batch).read_bytes(), raw)


class InventoryTests(SimpleTestCase):
    def folder(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        files = {
            'fund_2025-01.pdf': make_pdf([fund_statement(period='Period Jan 1, 2025 - Jan 31, 2025')]),                      # January 2025
            'fund_2025-01_reissued_123456789.pdf': make_pdf([fund_statement(period='Period Jan 1, 2025 - Jan 31, 2025')]),   # same content, other name
            'fund_2025-05.pdf': make_pdf([fund_statement(period='Period Mar 1, 2025 - Mar 31, 2025')]),
            'letter.pdf': make_pdf([['Nothing here']]),
            'acme.pdf': make_pdf([MUFG_STYLE]),
            'notes.txt': b'ignored',
        }
        for name, raw in files.items():
            (root / name).write_bytes(raw)
        (root / 'sub').mkdir()
        (root / 'sub' / 'deep.pdf').write_bytes(make_pdf([MUFG_STYLE]))
        return root

    def test_table_shows_reader_period_outcome_and_flags(self):
        entries = {e.name: e for e in pdf_inventory.inventory(self.folder())}
        self.assertEqual(sorted(entries), ['acme.pdf', 'fund_2025-01.pdf', 'fund_2025-01_reissued_######.pdf', 'fund_2025-05.pdf', 'letter.pdf'])
        fund = entries['fund_2025-01.pdf']
        self.assertEqual((fund.reader, fund.rows, fund.outcome), ('revolut_flexible_cash_funds', 1, 'staged'))
        self.assertEqual(fund.period, (datetime.date(2025, 1, 1), datetime.date(2025, 1, 31)))
        self.assertTrue(any(f.startswith('same content as') for f in entries['fund_2025-01_reissued_######.pdf'].flags))
        self.assertIn('file name period differs from the period read', entries['fund_2025-05.pdf'].flags)  # name says May, period is March
        self.assertTrue(entries['letter.pdf'].outcome.startswith('refused'))
        self.assertEqual(entries['acme.pdf'].reader, 'au_dividend_advice')

    def test_period_gap_is_flagged(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for name, period in (('a.pdf', 'Period Jan 1, 2025 - Jan 31, 2025'), ('b.pdf', 'Period Mar 1, 2025 - Mar 31, 2025')):
            (Path(tmp.name) / name).write_bytes(make_pdf([fund_statement(period=period)]))
        a, b = pdf_inventory.inventory(tmp.name)
        self.assertEqual(a.flags, [])
        self.assertEqual(b.flags, ['period gap of 28 day(s) after a.pdf'])

    def test_recursive_option(self):
        names = {e.name for e in pdf_inventory.inventory(self.folder(), recursive=True)}
        self.assertIn('sub/deep.pdf', names)

    def test_output_has_no_digit_runs_and_no_amounts(self):
        from .tools_loader import load
        out = io.StringIO()
        load().main([str(self.folder()), '--recursive'], out=out)
        text = out.getvalue()
        self.assertIn('revolut_flexible_cash_funds', text)
        self.assertFalse(re.search(r'\d{6,}', text))
        self.assertFalse(re.search(r'\d+[.,]\d{2}\b', text))           # no amount-like figure (dates use '-' and '..')
        self.assertNotIn('Acme', text)                                  # no names from the documents


@skipUnless((SAMPLES / 'RVB').is_dir() or (SAMPLES / 'ETrade').is_dir() or (SAMPLES / 'Fidelity').is_dir(),
            'owner-supplied sample folders are not present (they are never committed)')
class LocalInventoryTests(SimpleTestCase):
    """Runs the inventory over the owner's real folders. Prints and asserts no amounts or names."""

    def entries(self, folder):
        path = SAMPLES / folder
        if not path.is_dir():
            self.skipTest(f'{folder} not present')
        return pdf_inventory.inventory(path)

    def test_rvb_reissued_statements_are_found_by_content(self):
        entries = self.entries('RVB')
        # Until the RVB reader exists (Phase 17) the files are refused; identical text is still detected where it can be read.
        reissued = [e for e in entries if any(f.startswith('same content') for f in e.flags)]
        print(f'\nRVB: {len(entries)} files, {len(reissued)} with the same content as an earlier file '
              f'({sum(1 for e in entries if "AES-encrypted" in e.outcome)} not readable without the cryptography package)')

    def test_etrade_and_fidelity_have_no_period_gaps_and_no_name_mismatches(self):
        for folder in ('ETrade', 'Fidelity'):
            entries = self.entries(folder)
            bad = [e for e in entries if any(f.startswith(('period gap', 'period overlaps', 'file name period')) for f in e.flags)]
            self.assertEqual(bad, [], folder)
            print(f'\n{folder}: {len(entries)} files, readers: {sorted({e.reader or "unrecognised" for e in entries})}, '
                  f'files with a period read: {sum(1 for e in entries if e.period)}')
