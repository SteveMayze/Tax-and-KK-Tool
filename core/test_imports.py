"""CSV import. Synthetic data only; uploads go to a temp dir; all rates come from fakes/mocks."""
import datetime
import shutil
import tempfile
from decimal import Decimal as D
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from core.models import (
    ConversionEvent, ExchangeRateRecord, ImportBatch, ImportRow, IncomeCategory, Organisation, Payment,
    ReportingMonth)
from core.services import imports as svc
from core.services.rates import FakeRateProvider, ProviderError

from .test_helpers import make_payment

HEADER = 'payment_date,organisation,category,currency,gross_amount,net_amount,frequency,comment,exchange_rate,rate_date'
D1 = datetime.date(2024, 3, 15)
D2 = datetime.date(2024, 3, 28)


def csv_text(*rows, header=HEADER):
    return '\n'.join([header, *rows]) + '\n'


def csv_bytes(*rows, **kw):
    return csv_text(*rows, **kw).encode('utf-8')


GOOD = '2024-03-15,Acme Test GmbH,Salary,EUR,1000.00,700.00,monthly,hello,,'
GBP = '2024-03-15,Brit Test Ltd,Pension,GBP,500.00,,monthly,,,'


def prov(**kw):
    return FakeRateProvider({('GBP', D1): D('1.2'), ('GBP', D2): D('1.25'), ('USD', D1): D('0.9')}, **kw)


class UploadDirMixin:
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.mkdtemp()
        self._ov = override_settings(UPLOAD_DIR=self._tmp)
        self._ov.enable()
        self.addCleanup(self._ov.disable)
        self.addCleanup(shutil.rmtree, self._tmp, True)


# ------------------------------------------------------------------ parsing

class ParseTests(SimpleTestCase):
    def test_basic_parse_bom_quotes_and_blank_lines(self):
        raw = '﻿' + csv_text(GOOD, '', ',,,,,,,,,', '2024-03-16,"Quoted, Name",Other,USD,"5.50",,one_off,"multi\nline",,')
        rows, warnings = svc.parse_csv(raw.encode())
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][1]['organisation'], 'Quoted, Name')
        self.assertEqual(rows[1][1]['comment'], 'multi\nline')
        self.assertEqual(warnings, [])

    def test_header_order_case_and_extra_columns(self):
        raw = 'Gross_Amount, CURRENCY ,frequency,category,Organisation,payment_date,mystery\n10,EUR,monthly,Salary,X,2024-01-01,zzz\n'
        rows, warnings = svc.parse_csv(raw.encode())
        self.assertEqual(rows[0][1]['gross_amount'], '10')
        self.assertEqual(rows[0][1]['organisation'], 'X')
        self.assertIn('mystery', warnings[0])

    def test_file_level_errors(self):
        bad = {
            b'': 'empty', b'\n\n': 'empty', b'payment_date,organisation\n1,2\n': 'Missing required',
            csv_bytes(header=HEADER): 'no data rows', HEADER.encode(): 'no data rows',
            b'\xff\xfe\x00bad': 'binary', b'a,b\n\xe9\n': 'UTF-8',
            ('payment_date,payment_date,organisation,category,currency,gross_amount,frequency\n').encode(): 'Duplicate column',
        }
        for raw, text in bad.items():
            with self.assertRaises(svc.ImportFileError, msg=raw) as cm:
                svc.parse_csv(raw)
            self.assertIn(text.lower(), str(cm.exception).lower(), raw)

    def test_size_and_row_limits(self):
        with override_settings(IMPORT_MAX_BYTES=50):
            with self.assertRaises(svc.ImportFileError):
                svc.parse_csv(csv_bytes(GOOD))
        with override_settings(IMPORT_MAX_ROWS=2):
            svc.parse_csv(csv_bytes(GOOD, GOOD))
            with self.assertRaises(svc.ImportFileError) as cm:
                svc.parse_csv(csv_bytes(GOOD, GOOD, GOOD))
            self.assertIn('More than 2', str(cm.exception))

    def test_extra_cells_flagged_structurally(self):
        rows, _ = svc.parse_csv(csv_bytes(GOOD + ',extra,cells,here'))
        self.assertTrue(rows[0][1]['_structural'])

    def test_template_is_parseable_and_valid(self):
        rows, _ = svc.parse_csv(svc.TEMPLATE_CSV.encode())
        self.assertEqual(len(rows), 3)


# ------------------------------------------------------------------ validation

class ValidateRowTests(TestCase):
    def base(self, **over):
        row = {c: '' for c in svc.COLUMNS}
        row.update(payment_date='2024-03-15', organisation='Acme', category='Salary', currency='EUR',
                   gross_amount='100', frequency='monthly')
        row.update(over)
        return row

    def test_valid_row_cleaned_and_new_names_flagged(self):
        errors, notes, c = svc.validate_row(self.base(organisation='  New   Co ', net_amount='80.5', currency='eur'))
        self.assertEqual(errors, [])
        self.assertEqual((c['organisation'], c['currency'], c['gross_amount'], c['net_amount']), ('New Co', 'EUR', D('100'), D('80.5')))
        self.assertEqual(notes, ['New organisation "New Co" will be created.'])  # Salary is seeded, so not new

    def test_existing_names_matched_case_insensitively(self):
        Organisation.objects.create(name='Acme')
        _, notes, _ = svc.validate_row(self.base(organisation='ACME', category='salary'))
        self.assertEqual(notes, [])

    def test_field_errors(self):
        cases = [
            ({'payment_date': ''}, 'payment_date: required'), ({'payment_date': '15/03/2024'}, 'YYYY-MM-DD'),
            ({'payment_date': '2024-02-30'}, 'not a real date'), ({'payment_date': '20240315'}, 'YYYY-MM-DD'),
            ({'organisation': ''}, 'organisation: required'), ({'category': ''}, 'category: required'),
            ({'currency': 'JPY'}, 'Unsupported currency'), ({'currency': ''}, 'currency'),
            ({'gross_amount': '1,000.00'}, 'plain number'), ({'gross_amount': '€100'}, 'plain number'),
            ({'gross_amount': '1e3'}, 'plain number'), ({'gross_amount': 'NaN'}, 'plain number'),
            ({'gross_amount': ''}, 'gross_amount: required'), ({'gross_amount': '0'}, 'must be positive'),
            ({'gross_amount': '-5'}, 'must be positive'), ({'gross_amount': '1.00001'}, 'decimal places'),
            ({'net_amount': 'abc'}, 'net_amount: use a plain number'), ({'net_amount': '-1'}, 'same sign'),
            ({'frequency': 'weekly'}, 'frequency: must be one of'), ({'frequency': ''}, 'frequency'),
            ({'income_period_start': '2024-03-31', 'income_period_end': '2024-03-01'}, 'before its start'),
            ({'exchange_rate': '0.9'}, 'EUR rows always use rate 1'),
            ({'currency': 'USD', 'exchange_rate': '0'}, 'must be positive'),
            ({'currency': 'USD', 'exchange_rate': 'x'}, 'exchange_rate: use a plain number'),
            ({'currency': 'USD', 'rate_date': '2024-03-14'}, 'only meaningful together'),
            ({'organisation': 'x' * 201}, 'longer than 200'),
        ]
        for over, text in cases:
            errors, _, c = svc.validate_row(self.base(**over))
            self.assertIsNone(c, over)
            self.assertTrue(any(text in e for e in errors), (over, errors))

    def test_frequency_aliases(self):
        for value in ('Half-Yearly', 'half yearly', 'ONE_OFF', 'One-Off'):
            self.assertEqual(svc.validate_row(self.base(frequency=value))[2]['frequency'], value.lower().replace('-', '_').replace(' ', '_'))

    def test_inactive_names_invalid(self):
        Organisation.objects.create(name='Old Co', active=False)
        IncomeCategory.objects.filter(name='Other').update(active=False)
        errors, _, _ = svc.validate_row(self.base(organisation='old co', category='Other'))
        self.assertEqual(sum('inactive' in e for e in errors), 2)

    def test_structural_error_makes_row_invalid(self):
        rows, _ = svc.parse_csv(csv_bytes(GOOD + ',extra,cells,here'))
        errors, _, cleaned = svc.validate_row(rows[0][1])
        self.assertIsNone(cleaned)
        self.assertIn('cells', errors[0])

    def test_validation_has_no_side_effects(self):
        svc.validate_row(self.base(organisation='Brand New', category='Brand New Cat'))
        self.assertFalse(Organisation.objects.filter(name='Brand New').exists())
        self.assertEqual((Payment.objects.count(), ReportingMonth.objects.count()), (0, 0))


# ------------------------------------------------------------------ staging & review (service)

class StagingTests(UploadDirMixin, TestCase):
    def stage(self, *rows, provider=None, **kw):
        return svc.stage_batch(csv_bytes(*rows, **kw), '../../evil name.csv', provider or prov())

    def test_stage_creates_no_payments_and_stores_file_safely(self):
        b = self.stage(GOOD, GBP)
        self.assertEqual((Payment.objects.count(), Organisation.objects.count(), ReportingMonth.objects.count()), (0, 0, 0))
        self.assertEqual(b.rows.count(), 2)
        self.assertEqual(b.status, 'preview')
        self.assertEqual(b.file_name, 'evil name.csv')              # directory parts stripped
        p = svc.upload_path(b)
        self.assertEqual(p.parent, Path(self._tmp).resolve() / 'imports')
        self.assertEqual(p.name, f'{b.pk}-{b.sha256[:12]}.csv')     # never the user's name
        self.assertEqual(p.stat().st_mode & 0o077, 0)               # owner-only permissions
        self.assertEqual(p.read_bytes(), csv_bytes(GOOD, GBP))

    def test_row_statuses_and_messages(self):
        b = self.stage(GOOD, '2024-03-15,Acme Test GmbH,Salary,EUR,-1,,monthly,,,', GBP)
        r = {x.line_number: x for x in b.rows.all()}
        self.assertEqual([r[2].status, r[3].status, r[4].status], ['valid', 'invalid', 'valid'])
        self.assertTrue(r[3].errors)
        self.assertIn('New organisation "Brit Test Ltd" will be created.', r[4].notes)

    def test_proposed_conversions(self):
        b = self.stage(GOOD, GBP, '2024-03-15,X,Salary,USD,10,,monthly,,0.95,2024-03-14',
                       '2024-03-15,Y,Salary,AUD,10,,monthly,,,')
        rows = {x.line_number: x for x in b.rows.all()}
        self.assertEqual((rows[2].rate, rows[2].rate_provider), (D('1'), 'identity'))
        self.assertEqual((rows[3].rate, rows[3].rate_provider, rows[3].rate_date), (D('1.2'), 'fake', D1))
        self.assertTrue(rows[4].rate_is_manual)
        self.assertEqual((rows[4].rate, rows[4].rate_date), (D('0.95'), datetime.date(2024, 3, 14)))
        self.assertIn('No rate', rows[5].rate_error)
        self.assertIsNone(rows[5].rate)
        self.assertEqual(ExchangeRateRecord.objects.count(), 0)     # preview records nothing

    def test_one_lookup_per_currency_and_date(self):
        p = prov()
        self.stage(GBP, GBP.replace('500.00', '600.00'), GBP.replace('Brit', 'Other'), provider=p)
        self.assertEqual(p.calls, [('GBP', D1)])

    def test_weekend_label_in_proposal(self):
        sat = datetime.date(2024, 3, 16)
        p = FakeRateProvider({('GBP', sat): D('1.2')}, date_overrides={('GBP', sat): D1})
        b = self.stage('2024-03-16,X,Salary,GBP,10,,monthly,,,', provider=p)
        row = b.rows.get()
        self.assertEqual(row.rate_date, D1)
        self.assertIn('differs from payment date', row.rate_notes)

    def test_provider_error_marks_no_rate_not_invalid(self):
        b = self.stage(GBP, provider=prov(fail=True))
        row = b.rows.get()
        self.assertEqual(row.status, 'valid')
        self.assertIn('Fake provider failure', row.rate_error)

    def test_duplicates_against_existing_and_within_file(self):
        existing = make_payment(gross='1000', date=D1); existing.save()
        b = self.stage(GOOD.replace('1000.00', '1000'), GBP, GBP, GBP.replace('500.00', '501'))
        rows = {x.line_number: x for x in b.rows.all()}
        self.assertEqual(rows[2].status, 'duplicate')
        self.assertEqual(rows[2].duplicate_of_payment_id, existing.pk)
        self.assertEqual(rows[3].status, 'valid')
        self.assertEqual((rows[4].status, rows[4].duplicate_of_line), ('duplicate', 3))
        self.assertEqual(rows[5].status, 'valid')                       # different amount
        self.assertFalse(rows[2].will_import)

    def test_duplicate_key_ignores_case_and_decimals(self):
        b = self.stage(GOOD, GOOD.replace('Acme Test GmbH', 'acme  test gmbh').replace('1000.00', '1000.0000'))
        self.assertEqual([x.status for x in b.rows.all()], ['valid', 'duplicate'])

    def test_duplicate_needs_same_all_four_fields(self):
        base = '2024-03-15,Acme,Salary,EUR,100,,monthly,,,'
        variants = ['2024-03-16,Acme,Salary,EUR,100,,monthly,,,', '2024-03-15,Other,Salary,EUR,100,,monthly,,,',
                    '2024-03-15,Acme,Salary,GBP,100,,monthly,,,', '2024-03-15,Acme,Salary,EUR,101,,monthly,,,',
                    '2024-03-15,Acme,Pension,EUR,100,,monthly,,,']  # category differs: still a duplicate by the rule
        b = self.stage(base, *variants)
        self.assertEqual([x.status for x in b.rows.all()], ['valid', 'valid', 'valid', 'valid', 'valid', 'duplicate'])

    def test_keep_duplicate_and_exclude_flow(self):
        b = self.stage(GOOD, GOOD)
        second = b.rows.get(line_number=3)
        self.assertEqual(svc.summary(b)['importing'], 1)
        svc.set_keep_duplicate(second, True)
        self.assertEqual(svc.summary(b)['importing'], 2)
        first = b.rows.get(line_number=2)
        svc.set_excluded(first, True, prov())                # excluded rows are not duplicate sources
        second.refresh_from_db()
        self.assertEqual(second.status, 'valid')
        self.assertEqual(svc.summary(b)['importing'], 1)
        svc.set_excluded(first, False, prov())
        second.refresh_from_db()
        self.assertEqual(second.status, 'duplicate')

    def test_update_row_revalidates_and_fixes(self):
        b = self.stage('2024-03-15,Acme,Salary,EUR,abc,,monthly,,,')
        row = b.rows.get()
        self.assertEqual(row.status, 'invalid')
        data = dict(row.data, gross_amount='100')
        svc.update_row(row, data, prov())
        row.refresh_from_db()
        self.assertEqual((row.status, row.errors), ('valid', []))
        self.assertEqual(row.original['gross_amount'], 'abc')       # original kept
        self.assertEqual(row.rate, D('1'))

    def test_editing_a_row_clears_structural_error(self):
        b = self.stage(GOOD + ',a,b')
        row = b.rows.get()
        self.assertEqual(row.status, 'invalid')
        svc.update_row(row, {k: v for k, v in row.data.items() if k != '_structural'}, prov())
        row.refresh_from_db()
        self.assertEqual(row.status, 'valid')

    def test_same_file_warning_after_commit(self):
        b = self.stage(GOOD)
        svc.commit_batch(b)
        again = self.stage(GOOD)
        self.assertTrue(any('already imported' in w for w in again.warnings))
        self.assertEqual(again.rows.get().status, 'duplicate')

    def test_unusable_file_creates_nothing(self):
        with self.assertRaises(svc.ImportFileError):
            svc.stage_batch(b'nope', 'x.csv', prov())
        self.assertEqual(ImportBatch.objects.count(), 0)
        self.assertFalse(list(Path(self._tmp).rglob('*.csv')))

    def test_stage_failure_rolls_back_and_removes_file(self):
        with mock.patch.object(svc, 'revalidate_batch', side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                svc.stage_batch(csv_bytes(GOOD), 'x.csv', prov())
        self.assertEqual((ImportBatch.objects.count(), ImportRow.objects.count()), (0, 0))
        self.assertFalse(list(Path(self._tmp).rglob('*.csv')))


# ------------------------------------------------------------------ commit

class CommitTests(UploadDirMixin, TestCase):
    def stage(self, *rows, provider=None):
        return svc.stage_batch(csv_bytes(*rows), 'f.csv', provider or prov())

    def test_commit_creates_payments_with_links_rates_and_audit(self):
        b = self.stage(GOOD, GBP, '2024-03-15,X,Salary,USD,10,,monthly,,0.95,')
        svc.commit_batch(b)
        b.refresh_from_db()
        self.assertEqual((b.status, b.imported_count, b.skipped_count, b.unconverted_count), ('committed', 3, 0, 0))
        eur, gbp, usd = Payment.objects.order_by('id')
        self.assertEqual((eur.gross_eur, eur.net_eur, eur.rate_source), (D('1000'), D('700'), 'identity'))
        self.assertEqual((gbp.gross_eur, gbp.rate, gbp.rate_source, gbp.rate_date), (D('600'), D('1.2'), 'fake', D1))
        self.assertEqual((usd.rate, usd.rate_source, usd.gross_eur), (D('0.95'), 'manual', D('9.5')))
        for p in (eur, gbp, usd):
            self.assertEqual((p.import_batch_id, p.source_document_id), (b.pk, b.source_document_id))
            self.assertEqual(p.conversion_events.get().kind, 'initial')
            self.assertIn(f'Import batch #{b.pk}', p.conversion_events.get().reason)
        self.assertEqual(b.source_document.sha256, b.sha256)
        self.assertEqual(eur.comment, 'hello')
        self.assertEqual(str(eur.month), '2024-03')
        self.assertTrue(Organisation.objects.filter(name='Brit Test Ltd').exists())
        self.assertNotIn(None, set(b.rows.values_list('created_payment_id', flat=True)))

    def test_commit_applies_previewed_rate_without_new_lookup(self):
        p = prov()
        b = self.stage(GBP, provider=p)
        calls = len(p.calls)
        changed = FakeRateProvider({('GBP', D1): D('9.99')})
        with mock.patch('core.services.rates.get_provider', return_value=changed):
            svc.commit_batch(b)
        self.assertEqual(Payment.objects.get().rate, D('1.2'))
        self.assertEqual(len(p.calls), calls)
        self.assertEqual(changed.calls, [])

    def test_provenance_copied_from_provider_quote(self):
        class Rich(FakeRateProvider):
            def get_rate(self, c, d):
                q = super().get_rate(c, d)
                from dataclasses import replace
                return replace(q, source_url='https://api.example.test/x', raw_response='{"rate":1.2}')
        b = self.stage(GBP, provider=Rich({('GBP', D1): D('1.2')}))
        svc.commit_batch(b)
        rec = Payment.objects.get().rate_record
        self.assertEqual((rec.source_url, rec.raw_response, rec.requested_date), ('https://api.example.test/x', '{"rate":1.2}', D1))

    def test_rows_without_rate_import_unconverted(self):
        b = self.stage(GBP, provider=prov(fail=True))
        svc.commit_batch(b)
        p = Payment.objects.get()
        self.assertEqual(p.conversion_status, 'pending')
        self.assertEqual(Payment.objects.get().conversion_events.count(), 0)
        b.refresh_from_db()
        self.assertEqual(b.unconverted_count, 1)

    def test_skips_excluded_and_unkept_duplicates(self):
        b = self.stage(GOOD, GOOD, GBP, '2024-03-15,Z,Salary,EUR,5,,monthly,,,')
        svc.set_excluded(b.rows.get(line_number=5), True, prov())
        svc.commit_batch(b)
        self.assertEqual(Payment.objects.count(), 2)
        b.refresh_from_db()
        self.assertEqual((b.imported_count, b.skipped_count), (2, 2))
        self.assertFalse(Organisation.objects.filter(name='Z').exists())     # excluded row creates nothing

    def test_commit_blocked_by_invalid_rows_but_allowed_when_excluded(self):
        b = self.stage(GOOD, '2024-03-15,Q,Salary,EUR,oops,,monthly,,,')
        with self.assertRaises(svc.ImportStateError) as cm:
            svc.commit_batch(b)
        self.assertIn('3', str(cm.exception))
        b.refresh_from_db()
        self.assertEqual((b.status, Payment.objects.count()), ('preview', 0))
        svc.set_excluded(b.rows.get(line_number=3), True, prov())
        svc.commit_batch(b)
        self.assertEqual(Payment.objects.count(), 1)

    def test_commit_is_atomic(self):
        b = self.stage(GOOD, GBP, '2024-04-02,Late Co,Other,EUR,5,,monthly,,,')
        real = Payment.save
        calls = {'n': 0}

        def flaky(self_, *a, **k):
            calls['n'] += 1
            if calls['n'] == 3:
                raise RuntimeError('disk full')
            return real(self_, *a, **k)
        with mock.patch.object(Payment, 'save', flaky):
            with self.assertRaises(RuntimeError):
                svc.commit_batch(b)
        b.refresh_from_db()
        self.assertEqual(b.status, 'preview')
        for model in (Payment, Organisation, ExchangeRateRecord, ConversionEvent):
            self.assertEqual(model.objects.count(), 0, model)
        self.assertEqual(ReportingMonth.objects.count(), 0)
        self.assertFalse(b.rows.exclude(created_payment=None).exists())
        svc.commit_batch(b)                       # and can be retried
        self.assertEqual(Payment.objects.count(), 3)

    def test_commit_twice_imports_once(self):
        b = self.stage(GOOD)
        svc.commit_batch(b)
        with self.assertRaises(svc.ImportStateError):
            svc.commit_batch(b)
        self.assertEqual(Payment.objects.count(), 1)

    def test_changed_rules_between_preview_and_commit_roll_back(self):
        b = self.stage(GOOD)
        Organisation.objects.create(name='Acme Test GmbH', active=False)   # became inactive after staging
        with self.assertRaises(svc.ImportStateError):
            svc.commit_batch(b)
        self.assertEqual(Payment.objects.count(), 0)
        self.assertEqual(ImportBatch.objects.get(pk=b.pk).status, 'preview')

    def test_new_names_reuse_case_insensitively_within_batch(self):
        b = self.stage(GOOD.replace('Acme Test GmbH', 'Same Co'), GOOD.replace('Acme Test GmbH', 'same co').replace('1000.00', '1001'))
        svc.commit_batch(b)
        self.assertEqual(Organisation.objects.filter(name__iexact='same co').count(), 1)

    def test_no_changes_after_commit(self):
        b = self.stage(GOOD)
        svc.commit_batch(b)
        row = b.rows.get()
        for call in (lambda: svc.update_row(row, row.data, prov()), lambda: svc.set_excluded(row, True, prov()),
                     lambda: svc.refresh_rates(b, prov()), lambda: svc.discard_batch(b)):
            with self.assertRaises(svc.ImportStateError):
                call()

    def test_discard_removes_rows_and_file(self):
        b = self.stage(GOOD)
        path = svc.upload_path(b)
        svc.discard_batch(b)
        b.refresh_from_db()
        self.assertEqual((b.status, b.rows.count(), path.exists(), b.stored_path), ('discarded', 0, False, ''))
        self.assertEqual(Payment.objects.count(), 0)

    def test_refresh_rates_requests_again(self):
        p = prov()
        b = self.stage(GBP, provider=p)
        newer = FakeRateProvider({('GBP', D1): D('1.3')})
        svc.refresh_rates(b, newer)
        self.assertEqual(b.rows.get().rate, D('1.3'))
        self.assertEqual(len(newer.calls), 1)

    def test_row_edit_reuses_quote_without_new_lookup(self):
        p = prov()
        b = self.stage(GBP, p and GBP.replace('Brit', 'Other'), provider=p)
        n = len(p.calls)
        row = b.rows.get(line_number=2)
        svc.update_row(row, dict(row.data, comment='note'), p)
        self.assertEqual(len(p.calls), n)

    def test_summary_lists_new_names_once(self):
        b = self.stage(GOOD.replace('Acme Test GmbH', 'Nova'), GOOD.replace('Acme Test GmbH', 'NOVA').replace('1000.00', '1'),
                       GOOD.replace('Salary', 'Brand New Cat'))
        s = svc.summary(b)
        self.assertEqual(s['new_organisations'], ['Acme Test GmbH', 'Nova'])
        self.assertEqual(s['new_categories'], ['Brand New Cat'])


# ------------------------------------------------------------------ views

class ImportViewTests(UploadDirMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user('t', password='pw-for-tests-123')
        self.client.force_login(self.user)
        patcher = mock.patch('core.views_imports.get_provider', return_value=prov())
        patcher.start()
        self.addCleanup(patcher.stop)

    def upload(self, *rows, follow=False, **kw):
        f = SimpleUploadedFile('my statement.csv', csv_bytes(*rows, **kw), content_type='text/csv')
        return self.client.post(reverse('import_upload'), {'file': f}, follow=follow)

    def test_all_views_require_login_and_correct_methods(self):
        b = svc.stage_batch(csv_bytes(GOOD), 'f.csv', prov())
        urls = [reverse(n) for n in ('import_list', 'import_upload', 'import_template')] + [
            reverse('import_preview', args=[b.pk]), reverse('import_file', args=[b.pk]),
            reverse('import_refresh_rates', args=[b.pk]), reverse('import_commit', args=[b.pk]),
            reverse('import_discard', args=[b.pk]), reverse('import_row_edit', args=[b.pk, 2]),
            reverse('import_row_toggle', args=[b.pk, 2, 'exclude'])]
        self.client.logout()
        for url in urls:
            for m in (self.client.get, self.client.post):
                r = m(url)
                self.assertEqual(r.status_code, 302, url)
                self.assertTrue(r.url.startswith(reverse('login')), url)
        self.assertEqual(Payment.objects.count(), 0)
        self.assertEqual(ImportBatch.objects.get().status, 'preview')
        self.client.force_login(self.user)
        for name in ('import_refresh_rates',):
            self.assertEqual(self.client.get(reverse(name, args=[b.pk])).status_code, 405)
        self.assertEqual(self.client.get(reverse('import_row_toggle', args=[b.pk, 2, 'exclude'])).status_code, 405)
        self.assertEqual(self.client.post(reverse('import_row_toggle', args=[b.pk, 2, 'bogus'])).status_code, 404)

    def test_upload_redirects_to_preview_and_shows_rows(self):
        r = self.upload(GOOD, GBP, follow=True)
        self.assertContains(r, 'nothing has been imported yet')
        self.assertContains(r, 'Acme Test GmbH')
        self.assertContains(r, 'New organisation &quot;Brit Test Ltd&quot; will be created.')
        self.assertContains(r, '1.2 (fake, 2024-03-15)')
        self.assertContains(r, '= 600.00 EUR')
        self.assertEqual(Payment.objects.count(), 0)

    def test_bad_uploads_show_errors_and_create_no_batch(self):
        for raw, text in ((b'garbage', 'Missing required'), (b'', 'empty')):
            f = SimpleUploadedFile('x.csv', raw)
            r = self.client.post(reverse('import_upload'), {'file': f})
            self.assertContains(r, text)
        r = self.client.post(reverse('import_upload'), {})
        self.assertContains(r, 'This field is required')
        self.assertEqual(ImportBatch.objects.count(), 0)

    def test_invalid_row_shown_with_message_and_commit_blocked(self):
        self.upload(GOOD, '2024-03-15,Q,Salary,EUR,oops,,monthly,,,')
        b = ImportBatch.objects.get()
        r = self.client.get(reverse('import_preview', args=[b.pk]))
        self.assertContains(r, 'gross_amount: use a plain number')
        r = self.client.post(reverse('import_commit', args=[b.pk]), follow=True)
        self.assertContains(r, 'still invalid')
        self.assertEqual(Payment.objects.count(), 0)

    def test_cell_text_is_escaped(self):
        self.upload('2024-03-15,<script>alert(1)</script>,Salary,EUR,1,,monthly,,,')
        r = self.client.get(reverse('import_preview', args=[ImportBatch.objects.get().pk]))
        self.assertNotContains(r, '<script>alert(1)</script>')
        self.assertContains(r, '&lt;script&gt;')

    def test_full_workflow_upload_fix_exclude_keep_commit(self):
        existing = make_payment(gross='1000', date=D1); existing.save()
        self.upload(
            GOOD.replace('1000.00', '1000'),                       # line 2: duplicate of existing
            '2024-03-15,Typo Co,Salary,EUR,abc,,monthly,,,',       # line 3: invalid -> fix
            GBP,                                                   # line 4: fine
            '2024-03-15,Skip Me,Other,EUR,7,,one_off,,,',          # line 5: exclude
            '2024-03-28,Brit Test Ltd,Pension,GBP,500.00,,monthly,,,')  # line 6: other date, rate 1.25
        b = ImportBatch.objects.get()
        url = lambda n, *a: reverse(n, args=[b.pk, *a])
        # fix line 3
        r = self.client.get(url('import_row_edit', 3))
        self.assertContains(r, 'value="abc"')
        r = self.client.post(url('import_row_edit', 3), dict(
            payment_date='2024-03-15', organisation='Typo Co', category='Salary', currency='EUR',
            gross_amount='250', net_amount='', frequency='monthly', income_period_start='',
            income_period_end='', comment='fixed', exchange_rate='', rate_date=''), follow=True)
        self.assertContains(r, 'Line 3 updated')
        # a bad edit stays invalid, with the message
        r = self.client.post(url('import_row_edit', 5), dict(
            payment_date='nope', organisation='Skip Me', category='Other', currency='EUR', gross_amount='7',
            frequency='one_off'), follow=True)
        self.assertContains(r, 'YYYY-MM-DD')
        # exclude line 5, keep the duplicate on line 2
        self.client.post(url('import_row_toggle', 5, 'exclude'))
        self.client.post(url('import_row_toggle', 2, 'keep'))
        # confirmation page summary
        r = self.client.get(url('import_commit'))
        self.assertContains(r, 'Import 4 payment(s)')
        self.assertContains(r, 'New organisations will be created')
        self.assertContains(r, 'Brit Test Ltd')
        self.assertContains(r, 'Typo Co')
        self.assertNotContains(r, 'Skip Me')
        self.assertEqual(Payment.objects.count(), 1)               # still nothing imported
        # commit
        r = self.client.post(url('import_commit'), follow=True)
        self.assertContains(r, 'Imported 4 payment(s)')
        self.assertEqual(Payment.objects.count(), 5)
        self.assertEqual(Payment.objects.filter(import_batch=b).count(), 4)
        gbp = sorted(Payment.objects.filter(currency='GBP'), key=lambda p: p.payment_date)
        self.assertEqual([(p.rate, p.gross_eur) for p in gbp], [(D('1.2'), D('600')), (D('1.25'), D('625'))])
        self.assertEqual(Payment.objects.get(organisation__name='Typo Co').comment, 'fixed')
        self.assertFalse(Organisation.objects.filter(name='Skip Me').exists())
        # appears in the month page and totals
        r = self.client.get(reverse('month_detail', args=[2024, 3]))
        self.assertContains(r, 'Typo Co')
        # double submit does not import again
        r = self.client.post(url('import_commit'), follow=True)
        self.assertContains(r, 'can no longer be changed')
        self.assertEqual(Payment.objects.count(), 5)
        # history
        r = self.client.get(reverse('import_list'))
        self.assertContains(r, 'Imported')
        self.assertContains(r, 'my statement.csv')

    def test_commit_with_unconverted_rows_shows_warning(self):
        with mock.patch('core.views_imports.get_provider', return_value=prov(fail=True)):
            self.upload(GBP)
        b = ImportBatch.objects.get()
        r = self.client.get(reverse('import_commit', args=[b.pk]))
        self.assertContains(r, 'saved <em>unconverted</em>')
        self.client.post(reverse('import_commit', args=[b.pk]))
        self.assertEqual(Payment.objects.get().conversion_status, 'pending')

    def test_refresh_rates_view(self):
        self.upload(GBP)
        b = ImportBatch.objects.get()
        with mock.patch('core.views_imports.get_provider', return_value=FakeRateProvider({('GBP', D1): D('1.4')})):
            r = self.client.post(reverse('import_refresh_rates', args=[b.pk]), follow=True)
        self.assertContains(r, '1.4 (fake')

    def test_problems_filter(self):
        self.upload(GOOD, '2024-03-15,Q,Salary,EUR,oops,,monthly,,,')
        b = ImportBatch.objects.get()
        r = self.client.get(reverse('import_preview', args=[b.pk]) + '?show=problems')
        self.assertContains(r, 'oops')
        self.assertNotContains(r, 'hello')

    def test_discard_view(self):
        self.upload(GOOD)
        b = ImportBatch.objects.get()
        self.assertContains(self.client.get(reverse('import_discard', args=[b.pk])), 'Yes, discard')
        self.assertEqual(ImportBatch.objects.get().status, 'preview')
        self.client.post(reverse('import_discard', args=[b.pk]))
        self.assertEqual(ImportBatch.objects.get().status, 'discarded')
        self.assertEqual(self.client.get(reverse('import_file', args=[b.pk])).status_code, 404)

    def test_original_file_download_is_protected_and_safe(self):
        self.upload(GOOD)
        b = ImportBatch.objects.get()
        r = self.client.get(reverse('import_file', args=[b.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b''.join(r.streaming_content), csv_bytes(GOOD))
        self.assertIn(f'import-{b.pk}.csv', r['Content-Disposition'])
        self.assertNotIn('statement', r['Content-Disposition'])
        self.assertEqual(r['X-Content-Type-Options'], 'nosniff')
        # a tampered stored path outside UPLOAD_DIR is never served
        ImportBatch.objects.filter(pk=b.pk).update(stored_path='../../../etc/hosts')
        self.assertEqual(self.client.get(reverse('import_file', args=[b.pk])).status_code, 404)

    def test_template_download(self):
        r = self.client.get(reverse('import_template'))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.decode().startswith('payment_date,organisation'))
        self.assertIn('attachment', r['Content-Disposition'])

    def test_contents_are_not_logged(self):
        with self.assertNoLogs(level='DEBUG') if hasattr(self, 'assertNoLogs') else mock.MagicMock():
            self.upload('2024-03-15,Secret Employer Ltd,Salary,EUR,123456.78,,monthly,,,')
            b = ImportBatch.objects.get()
            self.client.post(reverse('import_commit', args=[b.pk]))
