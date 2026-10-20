"""Phase 28: lifecycle of stored import files. Synthetic data only; real files in a temporary UPLOAD_DIR."""
import datetime
import shutil
import tempfile
import io
import re
from decimal import Decimal as D
from unittest import mock
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import ImportBatch, ImportDeletion, ImportRow, Payment, ReportingYear, SourceDocument
from django.core.management import call_command

from core.services import import_files
from core.services import imports as svc
from core.services.rates import FakeRateProvider

PROVIDER = FakeRateProvider({})


def csv_for(*dates, org='Acme Test GmbH'):
    head = 'payment_date,organisation,category,currency,gross_amount,net_amount,frequency,income_period_start,income_period_end,comment\n'
    return (head + ''.join(f'{d},{org},Salary,EUR,100.00,,monthly,,,\n' for d in dates)).encode()


class LifecycleBase(TestCase):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.mkdtemp()
        self._ov = override_settings(UPLOAD_DIR=self._tmp)
        self._ov.enable()
        self.addCleanup(self._ov.disable)
        self.addCleanup(shutil.rmtree, self._tmp, True)
        self.client.force_login(get_user_model().objects.create_user('t', password='pw-for-tests-123'))

    def committed(self, *dates, org='Acme Test GmbH'):
        batch = svc.stage_batch(csv_for(*dates, org=org), 'my statement.csv', PROVIDER)
        return svc.commit_batch(batch)

    def stored(self, batch):
        return Path(self._tmp) / batch.stored_path


class YearDeleteTests(LifecycleBase):
    def test_reproduction_option_off_leaves_everything(self):
        batch = self.committed('2024-03-15')
        file = self.stored(batch)
        r = self.client.post(reverse('year_delete', args=[2024]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(ReportingYear.objects.filter(year=2024).exists())
        self.assertEqual(Payment.objects.count(), 0)
        self.assertTrue(ImportBatch.objects.filter(pk=batch.pk).exists())
        self.assertTrue(file.is_file())

    def test_option_on_removes_the_batch_and_the_file_from_disk(self):
        batch = self.committed('2024-03-15', '2024-04-15')
        file = self.stored(batch)
        self.client.post(reverse('year_delete', args=[2024]), {'delete_imports': 'on'})
        self.assertFalse(ReportingYear.objects.filter(year=2024).exists())
        self.assertFalse(ImportBatch.objects.filter(pk=batch.pk).exists())
        self.assertEqual(ImportRow.objects.count(), 0)
        self.assertEqual(SourceDocument.objects.count(), 0)
        self.assertFalse(file.exists())
        self.assertEqual(list(Path(self._tmp, 'imports').iterdir()), [])
        log = ImportDeletion.objects.get()
        self.assertEqual((log.kind, log.batches, log.files_removed, log.files_failed), ('year', 1, 1, 0))

    def test_a_batch_that_also_supports_another_year_is_kept_and_named(self):
        shared = self.committed('2024-12-15', '2025-01-15')
        only = self.committed('2024-05-15', org='Other Test Ltd')
        page = self.client.get(reverse('year_delete', args=[2024]))
        text = page.content.decode()
        self.assertIn('kept: also used by other years', text)
        self.assertIn('stored file and import history are deleted', text)
        self.client.post(reverse('year_delete', args=[2024]), {'delete_imports': 'on'})
        self.assertTrue(ImportBatch.objects.filter(pk=shared.pk).exists())
        self.assertTrue(self.stored(shared).is_file())
        self.assertEqual(Payment.objects.filter(import_batch=shared).count(), 1)     # the 2025 payment survives with its link
        self.assertFalse(ImportBatch.objects.filter(pk=only.pk).exists())

    def test_confirmation_page_has_the_box_unticked_and_masks_file_names(self):
        batch = self.committed('2024-03-15')
        ImportBatch.objects.filter(pk=batch.pk).update(file_name='statement 1234567890.pdf')
        text = self.client.get(reverse('year_delete', args=[2024])).content.decode()
        self.assertIn('name="delete_imports"', text)
        self.assertNotIn('checked', text.split('delete_imports')[1].split('>')[0])
        self.assertNotRegex(text, r'\d{6,}')
        self.assertIn('######', text)

    def test_year_without_imports_deletes_as_before(self):
        y = ReportingYear.objects.create(year=2020)
        r = self.client.post(reverse('year_delete', args=[2020]), {'delete_imports': 'on'})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(ReportingYear.objects.filter(pk=y.pk).exists())
        self.assertEqual(ImportDeletion.objects.count(), 0)

    def test_get_never_deletes(self):
        batch = self.committed('2024-03-15')
        self.client.get(reverse('year_delete', args=[2024]), {'delete_imports': 'on'})
        self.assertTrue(ReportingYear.objects.filter(year=2024).exists())
        self.assertTrue(self.stored(batch).is_file())

    def test_outside_path_batch_is_kept_not_deleted(self):
        batch = self.committed('2024-03-15')
        ImportBatch.objects.filter(pk=batch.pk).update(stored_path='../../../etc/hosts')
        self.client.post(reverse('year_delete', args=[2024]), {'delete_imports': 'on'})
        self.assertTrue(ImportBatch.objects.filter(pk=batch.pk).exists())
        self.assertTrue(Path('/etc/hosts').exists())

    def test_missing_file_is_reported_as_already_gone(self):
        batch = self.committed('2024-03-15')
        self.stored(batch).unlink()
        self.client.post(reverse('year_delete', args=[2024]), {'delete_imports': 'on'})
        log = ImportDeletion.objects.get()
        self.assertEqual((log.files_removed, log.files_already_gone, log.files_failed), (0, 1, 0))
        self.assertFalse(ImportBatch.objects.filter(pk=batch.pk).exists())


class BatchDeleteTests(LifecycleBase):
    def test_delete_stored_file_keeps_history_rows_and_payments(self):
        batch = self.committed('2024-03-15')
        file = self.stored(batch)
        self.client.post(reverse('import_delete_file', args=[batch.pk]))
        batch.refresh_from_db()
        self.assertFalse(file.exists())
        self.assertEqual((batch.stored_path, batch.status), ('', 'committed'))
        self.assertIsNotNone(batch.original_removed_at)
        self.assertEqual(batch.rows.count(), 1)
        self.assertEqual(Payment.objects.filter(import_batch=batch).count(), 1)
        r = self.client.get(reverse('import_file', args=[batch.pk]))
        self.assertEqual(r.status_code, 410)
        self.assertIn('original file was removed', r.content.decode())
        self.assertIn('original removed on', self.client.get(reverse('import_list')).content.decode())
        self.assertEqual(ImportDeletion.objects.get().kind, 'batch_file')

    def test_delete_completely_removes_batch_rows_history_and_file_but_no_payment(self):
        batch = self.committed('2024-03-15')
        file = self.stored(batch)
        self.client.post(reverse('import_delete', args=[batch.pk]))
        self.assertFalse(ImportBatch.objects.filter(pk=batch.pk).exists())
        self.assertEqual(ImportRow.objects.count(), 0)
        self.assertFalse(file.exists())
        payment = Payment.objects.get()
        self.assertIsNone(payment.import_batch)
        self.assertIsNotNone(payment.source_document)                 # still referenced by the payment, so kept
        self.assertEqual(ImportDeletion.objects.get().payments_kept, 1)

    def test_confirmation_names_what_is_kept_and_removed_and_needs_post(self):
        batch = self.committed('2024-03-15')
        for name in ('import_delete', 'import_delete_file'):
            r = self.client.get(reverse(name, args=[batch.pk]))
            text = r.content.decode()
            self.assertIn('What will be removed', text)
            self.assertIn('What stays', text)
            self.assertIn('1 payment(s)', text)
            self.assertIn('csrfmiddlewaretoken', text)
            self.assertTrue(self.stored(batch).is_file())
            self.assertTrue(ImportBatch.objects.filter(pk=batch.pk).exists())

    def test_csrf_is_enforced(self):
        from django.test import Client
        batch = self.committed('2024-03-15')
        c = Client(enforce_csrf_checks=True)
        c.force_login(get_user_model().objects.get())
        for name in ('import_delete', 'import_delete_file'):
            self.assertEqual(c.post(reverse(name, args=[batch.pk])).status_code, 403)
        self.assertTrue(self.stored(batch).is_file())

    def test_login_required(self):
        batch = self.committed('2024-03-15')
        self.client.logout()
        for name in ('import_delete', 'import_delete_file'):
            self.assertEqual(self.client.post(reverse(name, args=[batch.pk])).status_code, 302)
        self.assertTrue(ImportBatch.objects.filter(pk=batch.pk).exists())

    def test_same_statement_is_a_duplicate_before_and_uploadable_as_new_after(self):
        batch = self.committed('2024-03-15')
        again = svc.stage_batch(csv_for('2024-03-15'), 'again.csv', PROVIDER)
        self.assertTrue(any('already imported' in w for w in again.warnings))
        self.assertEqual(again.rows.get().status, 'duplicate')
        again.delete()
        self.client.post(reverse('import_delete', args=[batch.pk]))
        fresh = svc.stage_batch(csv_for('2024-03-15'), 'again.csv', PROVIDER)
        self.assertFalse(any('already imported' in w for w in fresh.warnings))

    def test_delete_file_only_keeps_the_already_imported_memory(self):
        batch = self.committed('2024-03-15')
        import_files.delete_batch_file(batch)
        again = svc.stage_batch(csv_for('2024-03-15'), 'again.csv', PROVIDER)
        self.assertTrue(any('already imported' in w for w in again.warnings))

    def test_path_outside_storage_is_refused_and_nothing_changes(self):
        batch = self.committed('2024-03-15')
        ImportBatch.objects.filter(pk=batch.pk).update(stored_path='../../../etc/hosts')
        batch.refresh_from_db()
        for fn in (import_files.delete_batch_file, import_files.delete_batch):
            with self.assertRaises(import_files.StoredPathRefused):
                fn(batch)
        self.assertTrue(ImportBatch.objects.filter(pk=batch.pk).exists())
        self.assertTrue(Path('/etc/hosts').exists())
        self.assertEqual(ImportDeletion.objects.count(), 0)

    def test_symlink_inside_storage_pointing_outside_is_refused(self):
        batch = self.committed('2024-03-15')
        outside = Path(tempfile.mkdtemp()) / 'x.csv'
        outside.write_bytes(b'keep')
        self.addCleanup(shutil.rmtree, outside.parent, True)
        file = self.stored(batch)
        file.unlink()
        file.symlink_to(outside)
        with self.assertRaises(import_files.StoredPathRefused):
            import_files.delete_batch(batch)
        self.assertTrue(outside.is_file())

    def test_missing_file_does_not_crash_and_is_reported(self):
        batch = self.committed('2024-03-15')
        self.stored(batch).unlink()
        r = self.client.post(reverse('import_delete', args=[batch.pk]), follow=True)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(ImportBatch.objects.filter(pk=batch.pk).exists())
        self.assertEqual(ImportDeletion.objects.get().files_already_gone, 1)
        batch = self.committed('2024-04-15', org='Other Test Ltd')
        self.stored(batch).unlink()
        removal = import_files.delete_batch_file(batch)
        self.assertEqual((removal.removed, removal.already_gone, removal.failed), (0, 1, 0))

    def test_failed_file_removal_after_the_database_change_is_reported_and_logged(self):
        batch = self.committed('2024-03-15')
        file = self.stored(batch)
        with mock.patch.object(Path, 'unlink', side_effect=PermissionError), self.assertLogs('core.services.import_files', 'ERROR'):
            r = self.client.post(reverse('import_delete_file', args=[batch.pk]), follow=True)
        self.assertIn('could not be removed', r.content.decode())
        batch.refresh_from_db()
        self.assertEqual(batch.stored_path, '')
        self.assertIsNotNone(batch.original_removed_at)              # the history says the original was removed
        self.assertTrue(file.exists())                               # ... and the leftover is found by the orphan report
        self.assertEqual(ImportDeletion.objects.get().files_failed, 1)
        self.assertEqual(import_files.orphan_report()['unreferenced'], [file.resolve()])

    def test_unattributed_batch_is_listed_and_deletable(self):
        batch = self.committed('2024-03-15')
        self.client.post(reverse('year_delete', args=[2024]))
        text = self.client.get(reverse('import_list')).content.decode()
        self.assertIn('unattributed', text)
        self.client.post(reverse('import_delete', args=[batch.pk]))
        self.assertFalse(self.stored(batch).exists())

    def test_preview_batch_can_be_deleted_too(self):
        batch = svc.stage_batch(csv_for('2024-03-15'), 'p.csv', PROVIDER)
        self.client.post(reverse('import_delete', args=[batch.pk]))
        self.assertEqual(ImportBatch.objects.count(), 0)
        self.assertEqual(list(Path(self._tmp, 'imports').iterdir()), [])


class OrphanCommandTests(LifecycleBase):
    def run_cmd(self, *args):
        out = io.StringIO()
        call_command('stored_files_report', *args, stdout=out)
        return out.getvalue()

    def make_orphans(self):
        kept = self.committed('2024-03-15')
        base = Path(self._tmp, 'imports')
        (base / '77-0123456789ab.pdf').write_bytes(b'orphan one')
        (base / '78-abcdef012345.zip').write_bytes(b'orphan two')
        gone = self.committed('2024-04-15', org='Other Test Ltd')
        self.stored(gone).unlink()
        return kept

    def test_dry_run_deletes_nothing_and_prints_counts_and_masked_names_only(self):
        kept = self.make_orphans()
        out = self.run_cmd()
        self.assertIn('not referenced by any import batch: 2', out)
        self.assertIn('stored file is missing on disk: 1', out)
        self.assertIn('Dry run', out)
        self.assertNotRegex(out, r'\d{6,}')
        self.assertNotRegex(out, r'\d+[.,]\d{2}')
        self.assertEqual(len(list(Path(self._tmp, 'imports').iterdir())), 3)
        self.assertTrue(self.stored(kept).is_file())

    def test_apply_removes_exactly_the_listed_orphans(self):
        kept = self.make_orphans()
        out = self.run_cmd('--apply')
        self.assertIn('Deleted: 2', out)
        self.assertEqual([p.name for p in Path(self._tmp, 'imports').iterdir()], [self.stored(kept).name])
        self.assertEqual(ImportBatch.objects.count(), 2)              # the batch with the missing file is only reported
        self.assertEqual(ImportDeletion.objects.get().kind, 'orphans')

    def test_apply_with_nothing_to_do(self):
        self.committed('2024-03-15')
        out = self.run_cmd('--apply')
        self.assertIn('Deleted: 0', out)
        self.assertEqual(ImportDeletion.objects.count(), 0)


class TransactionTests(LifecycleBase):
    def test_database_error_leaves_the_file_untouched(self):
        batch = self.committed('2024-03-15')
        with mock.patch.object(import_files, '_drop_batch', side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                import_files.delete_batch(batch)
        self.assertTrue(self.stored(batch).is_file())
        self.assertTrue(ImportBatch.objects.filter(pk=batch.pk).exists())
