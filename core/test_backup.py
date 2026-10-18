"""Backup / restore: online SQLite copy, manifest, retention, safe restore. Synthetic data, temp dirs only."""
import datetime
import io
import json
import os
import sqlite3
import tarfile
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from core.services import backup

UTC = datetime.timezone.utc


def t(y, m, d, hh=3, mm=15, ss=0):
    return datetime.datetime(y, m, d, hh, mm, ss, tzinfo=UTC)


class Workspace(SimpleTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.db = self.root / 'data' / 'db.sqlite3'
        self.uploads = self.root / 'uploads'
        self.backups = self.root / 'backups'
        self.db.parent.mkdir()
        conn = sqlite3.connect(self.db)
        conn.execute('CREATE TABLE payment (id INTEGER PRIMARY KEY, amount TEXT)')
        conn.executemany('INSERT INTO payment (amount) VALUES (?)', [('10.00',), ('20.50',), ('30.25',)])
        conn.execute('CREATE TABLE empty_table (id INTEGER)')
        conn.commit()
        conn.close()
        (self.uploads / 'imports').mkdir(parents=True)
        (self.uploads / 'imports' / '1-abc.csv').write_text('a,b\n1,2\n')
        (self.uploads / 'imports' / '2-def.csv').write_text('c,d\n3,4\n')

    def make(self, label='', now=None):
        return backup.create_backup(self.db, self.uploads, self.backups, label=label,
                                    now=now or t(2026, 10, 18), version='abc123')


class CreateBackupTests(Workspace):
    def test_archive_layout_manifest_and_permissions(self):
        path = self.make()
        self.assertEqual(path.name, 'backup-20261018-031500.tar.gz')
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.backups.stat().st_mode & 0o777, 0o700)
        with tarfile.open(path) as tar:
            names = sorted(m.name for m in tar.getmembers())
        self.assertEqual(names, ['MANIFEST.json', 'db.sqlite3', 'uploads/imports/1-abc.csv', 'uploads/imports/2-def.csv'])
        with tempfile.TemporaryDirectory() as tmp:
            manifest, out = backup.verify_archive(path, tmp)
        self.assertEqual((manifest['app_version'], manifest['label'], manifest['integrity_check']), ('abc123', '', 'ok'))
        self.assertEqual(manifest['row_counts'], {'empty_table': 0, 'payment': 3})
        self.assertEqual(manifest['created_utc'], '2026-10-18T03:15:00Z')
        self.assertEqual(len(manifest['files']), 3)

    def test_no_staging_or_partial_files_left_behind(self):
        self.make()
        self.assertEqual([p.name for p in self.backups.iterdir()], ['backup-20261018-031500.tar.gz'])

    def test_label_in_name_and_validation(self):
        self.assertEqual(self.make('pre-deploy').name, 'backup-20261018-031500-pre-deploy.tar.gz')
        for bad in ('Pre Deploy', '../x', 'a/b', '-x', 'x' * 40):
            with self.assertRaises(backup.BackupError, msg=bad):
                self.make(bad, now=t(2026, 10, 19))

    def test_refuses_to_overwrite_same_second(self):
        self.make()
        with self.assertRaises(backup.BackupError):
            self.make()

    def test_missing_database(self):
        self.db.unlink()
        with self.assertRaises(backup.BackupError):
            self.make()

    def test_works_without_uploads_directory(self):
        import shutil
        shutil.rmtree(self.uploads)
        with tempfile.TemporaryDirectory() as tmp:
            manifest, _ = backup.verify_archive(self.make(), tmp)
        self.assertEqual(list(manifest['files']), ['db.sqlite3'])

    def test_backup_is_consistent_while_the_database_is_open_and_changing(self):
        writer = sqlite3.connect(self.db)
        writer.execute('BEGIN')
        writer.execute("INSERT INTO payment (amount) VALUES ('99.99')")        # uncommitted
        path = self.make()
        writer.commit()
        writer.close()
        with tempfile.TemporaryDirectory() as tmp:
            manifest, _ = backup.verify_archive(path, tmp)
        self.assertEqual(manifest['row_counts']['payment'], 3)                  # only committed rows

    def test_corrupt_database_is_not_backed_up(self):
        data = bytearray(self.db.read_bytes())
        data[0:16] = b'not a sqlite db!'
        self.db.write_bytes(bytes(data))
        with self.assertRaises(backup.BackupError):
            self.make()
        self.assertEqual([p for p in self.backups.glob('backup-*')], [])

    def test_source_is_not_modified(self):
        before = self.db.read_bytes()
        self.make()
        self.assertEqual(self.db.read_bytes(), before)


class VerifyArchiveTests(Workspace):
    def rewrite(self, path, mutate):
        """Rebuild an archive with a mutation applied to its extracted contents."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            with tarfile.open(path) as tar:
                tar.extractall(tmp, filter='data')
            mutate(tmp)
            with tarfile.open(path, 'w:gz') as tar:
                for p in sorted(tmp.rglob('*')):
                    if p.is_file():
                        tar.add(p, arcname=p.relative_to(tmp).as_posix())

    def verify(self, path):
        with tempfile.TemporaryDirectory() as tmp:
            return backup.verify_archive(path, tmp)

    def test_tampered_upload_is_detected(self):
        path = self.make()
        self.rewrite(path, lambda d: (d / 'uploads/imports/1-abc.csv').write_text('tampered'))
        with self.assertRaisesRegex(backup.BackupError, 'Checksum mismatch'):
            self.verify(path)

    def test_extra_file_is_detected(self):
        path = self.make()
        self.rewrite(path, lambda d: (d / 'uploads/extra.txt').write_text('x'))
        with self.assertRaisesRegex(backup.BackupError, 'do not match the manifest'):
            self.verify(path)

    def test_missing_manifest(self):
        path = self.make()
        self.rewrite(path, lambda d: (d / 'MANIFEST.json').unlink())
        with self.assertRaisesRegex(backup.BackupError, 'Manifest'):
            self.verify(path)

    def test_manifest_row_count_mismatch(self):
        path = self.make()

        def mutate(d):
            m = json.loads((d / 'MANIFEST.json').read_text())
            m['row_counts']['payment'] = 4
            (d / 'MANIFEST.json').write_text(json.dumps(m))
        self.rewrite(path, mutate)
        with self.assertRaisesRegex(backup.BackupError, 'Row counts'):
            self.verify(path)

    def test_database_corruption_detected_even_if_hashes_were_recomputed(self):
        for how in ('header', 'btree'):
            path = self.make(now=t(2026, 10, 18, 3, 15, 1 if how == 'header' else 2))

            def mutate(d):
                raw = bytearray((d / 'db.sqlite3').read_bytes())
                if how == 'header':
                    raw[0:16] = b'not a sqlite db!'
                else:
                    raw[100:140] = b'\xff' * 40               # damage the schema page's b-tree header
                (d / 'db.sqlite3').write_bytes(bytes(raw))
                import hashlib
                m = json.loads((d / 'MANIFEST.json').read_text())
                m['files']['db.sqlite3'] = hashlib.sha256((d / 'db.sqlite3').read_bytes()).hexdigest()
                (d / 'MANIFEST.json').write_text(json.dumps(m))
            self.rewrite(path, mutate)
            with self.assertRaises(backup.BackupError, msg=how):
                self.verify(path)

    def test_path_traversal_and_special_members_rejected(self):
        path = self.backups / 'evil.tar.gz'
        self.backups.mkdir(exist_ok=True)
        for arcname in ('../escape.txt', '/abs/path.txt', 'uploads/../../escape.txt', 'other/file.txt'):
            with tarfile.open(path, 'w:gz') as tar:
                data = b'x'
                info = tarfile.TarInfo(arcname)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            with self.assertRaisesRegex(backup.BackupError, 'Unexpected entry', msg=arcname):
                self.verify(path)
        with tarfile.open(path, 'w:gz') as tar:                         # a symlink is not a regular file
            info = tarfile.TarInfo('uploads/link')
            info.type = tarfile.SYMTYPE
            info.linkname = '/etc/passwd'
            tar.addfile(info)
        with self.assertRaisesRegex(backup.BackupError, 'Unexpected entry'):
            self.verify(path)
        self.assertFalse((self.root / 'escape.txt').exists())

    def test_not_an_archive_and_missing_file(self):
        junk = self.backups / 'junk.tar.gz'
        self.backups.mkdir(exist_ok=True)
        junk.write_bytes(b'this is not a tarball')
        with self.assertRaisesRegex(backup.BackupError, 'cannot be read'):
            self.verify(junk)
        with self.assertRaisesRegex(backup.BackupError, 'not found'):
            self.verify(self.backups / 'nope.tar.gz')


class RestoreTests(Workspace):
    def test_roundtrip_to_new_location_matches_original(self):
        path = self.make()
        target_db, target_up = self.root / 'new' / 'db.sqlite3', self.root / 'new' / 'uploads'
        result = backup.restore_archive(path, target_db, target_up)
        self.assertEqual(result['moved_aside'], [])
        self.assertEqual(backup.inspect_db(target_db), backup.inspect_db(self.db))
        self.assertEqual((target_up / 'imports' / '1-abc.csv').read_text(), 'a,b\n1,2\n')
        self.assertEqual(target_db.stat().st_mode & 0o777, 0o600)

    def test_restore_returns_the_state_at_backup_time(self):
        path = self.make()
        conn = sqlite3.connect(self.db)
        conn.execute("INSERT INTO payment (amount) VALUES ('999')")
        conn.commit()
        conn.close()
        (self.uploads / 'imports' / '1-abc.csv').write_text('changed')
        backup.restore_archive(path, self.db, self.uploads, force=True)
        self.assertEqual(backup.inspect_db(self.db)['row_counts']['payment'], 3)
        self.assertEqual((self.uploads / 'imports' / '1-abc.csv').read_text(), 'a,b\n1,2\n')

    def test_refuses_to_overwrite_existing_data(self):
        path = self.make()
        before = self.db.read_bytes()
        with self.assertRaisesRegex(backup.BackupError, 'refusing to overwrite'):
            backup.restore_archive(path, self.db, self.root / 'other-uploads')
        with self.assertRaisesRegex(backup.BackupError, 'refusing to overwrite'):
            backup.restore_archive(path, self.root / 'fresh.sqlite3', self.uploads)
        self.assertEqual(self.db.read_bytes(), before)

    def test_force_moves_existing_data_aside_instead_of_deleting(self):
        path = self.make()
        conn = sqlite3.connect(self.db)
        conn.execute("INSERT INTO payment (amount) VALUES ('999')")
        conn.commit()
        conn.close()
        result = backup.restore_archive(path, self.db, self.uploads, force=True, now=t(2026, 10, 19, 9, 0, 0))
        aside = sorted(Path(p).name for p in result['moved_aside'])
        self.assertEqual(aside, ['db.sqlite3.before-restore-20261019-090000', 'uploads.before-restore-20261019-090000'])
        self.assertEqual(backup.inspect_db(self.db.parent / 'db.sqlite3.before-restore-20261019-090000')['row_counts']['payment'], 4)
        self.assertTrue((self.root / 'uploads.before-restore-20261019-090000' / 'imports' / '1-abc.csv').exists())

    def test_stale_wal_files_are_moved_aside(self):
        path = self.make()
        wal = Path(f'{self.db}-wal')
        wal.write_bytes(b'stale wal')
        backup.restore_archive(path, self.db, self.uploads, force=True, now=t(2026, 10, 19))
        self.assertFalse(wal.exists())

    def test_failed_verification_changes_nothing(self):
        path = self.make()
        with tarfile.open(path) as tar:
            pass
        path.write_bytes(path.read_bytes()[:50])                         # truncated archive
        before = self.db.read_bytes()
        with self.assertRaises(backup.BackupError):
            backup.restore_archive(path, self.db, self.uploads, force=True)
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual([p.name for p in self.db.parent.iterdir()], ['db.sqlite3'])


class PruneTests(Workspace):
    def names(self):
        return sorted(p.name for p in self.backups.iterdir() if p.is_file())

    def test_retention_policy(self):
        now = t(2026, 10, 18)
        stamps = [now - datetime.timedelta(days=d) for d in range(0, 40)]          # one per day for 40 days
        stamps += [t(2026, 4, 2), t(2026, 4, 20), t(2025, 11, 15), t(2025, 10, 5), t(2025, 9, 15), t(2024, 1, 1)]
        for s in stamps:
            self.make(now=s)
        self.make('pre-deploy', now=t(2026, 10, 1, 12, 0, 0))              # labelled, 17 days old
        self.make('pre-deploy', now=t(2026, 8, 1, 12, 0, 0))               # labelled, 78 days old
        removed = backup.prune(self.backups, now=now)
        kept = set(self.names())
        for day in range(14):                                               # the last 14 calendar days
            self.assertIn(f'backup-{(now - datetime.timedelta(days=day)):%Y%m%d}-031500.tar.gz', kept)
        self.assertNotIn('backup-20260916-031500.tar.gz', kept)             # 32 days old, not the newest of September
        self.assertIn('backup-20260930-031500.tar.gz', kept)                # newest of September
        self.assertIn('backup-20261001-120000-pre-deploy.tar.gz', kept)     # labelled and recent
        self.assertIn('backup-20260801-120000-pre-deploy.tar.gz', kept)     # newest of August (monthly rule)
        self.assertIn('backup-20260420-031500.tar.gz', kept)                # newest of April
        self.assertNotIn('backup-20260402-031500.tar.gz', kept)
        self.assertIn('backup-20251115-031500.tar.gz', kept)                # 11 months ago: inside the 12-month window
        self.assertNotIn('backup-20251005-031500.tar.gz', kept)             # 12 months ago: outside it
        self.assertNotIn('backup-20250915-031500.tar.gz', kept)
        self.assertNotIn('backup-20240101-031500.tar.gz', kept)
        self.assertEqual(len(removed) + len(kept), len(stamps) + 2)
        self.assertEqual(backup.prune(self.backups, now=now), [])           # idempotent

    def test_labelled_backups_survive_30_days_even_when_not_newest_of_their_day(self):
        now = t(2026, 10, 18)
        self.make(now=t(2026, 10, 10, 3, 0, 0))
        self.make('pre-deploy', now=t(2026, 10, 10, 1, 0, 0))
        backup.prune(self.backups, now=now, keep_days=1, keep_months=0)
        self.assertEqual(self.names(), ['backup-20261010-010000-pre-deploy.tar.gz'])

    def test_only_backup_files_are_ever_touched(self):
        self.make(now=t(2020, 1, 1))
        (self.backups / 'notes.txt').write_text('keep me')
        (self.backups / 'backup-notadate.tar.gz').write_text('keep me too')
        (self.backups / 'subdir').mkdir()
        backup.prune(self.backups, now=t(2026, 10, 18), keep_days=0, keep_months=0)
        self.assertEqual(self.names(), ['backup-notadate.tar.gz', 'notes.txt'])
        self.assertTrue((self.backups / 'subdir').is_dir())

    def test_missing_directory(self):
        self.assertEqual(backup.prune(self.root / 'nowhere'), [])
        self.assertEqual(backup.list_backups(self.root / 'nowhere'), [])

    def test_list_backups_newest_first(self):
        self.make(now=t(2026, 1, 1))
        self.make(now=t(2026, 3, 1))
        self.make(now=t(2026, 2, 1))
        self.assertEqual([p.name[7:15] for p in backup.list_backups(self.backups)], ['20260301', '20260201', '20260101'])

    def test_parse_name(self):
        self.assertEqual(backup.parse_name('backup-20261018-031500.tar.gz'), (t(2026, 10, 18), ''))
        self.assertEqual(backup.parse_name('backup-20261018-031500-pre-deploy.tar.gz')[1], 'pre-deploy')
        for bad in ('backup-2026.tar.gz', 'x.tar.gz', 'backup-20261018-031500.zip'):
            self.assertIsNone(backup.parse_name(bad))


class ManagementCommandTests(Workspace):
    def run_cmd(self, *args):
        out = io.StringIO()
        call_command(*args, stdout=out)
        return out.getvalue()

    def test_backup_then_verify_then_restore(self):
        out = self.run_cmd('backup_db', '--db', str(self.db), '--uploads', str(self.uploads),
                           '--backup-dir', str(self.backups), '--label', 'pre-deploy', '--prune')
        self.assertRegex(out, r'BACKUP_CREATED backup-\d{8}-\d{6}-pre-deploy\.tar\.gz')
        self.assertIn('PRUNED 0', out)
        name = backup.list_backups(self.backups)[0].name
        out = self.run_cmd('restore_backup', name, '--backup-dir', str(self.backups))
        self.assertIn('VERIFIED integrity=ok checksums=ok files=3 tables=2', out)
        self.assertIn('ROWS payment=3', out)
        self.assertNotIn('10.00', out)                                      # no data values are printed
        out = self.run_cmd('restore_backup', name, '--backup-dir', str(self.backups), '--target-db',
                           str(self.root / 'drill' / 'db.sqlite3'), '--target-uploads', str(self.root / 'drill' / 'up'))
        self.assertIn('RESTORED', out)

    def test_errors_become_command_errors(self):
        with self.assertRaises(CommandError):
            self.run_cmd('backup_db', '--db', str(self.root / 'missing.sqlite3'), '--backup-dir', str(self.backups))
        with self.assertRaises(CommandError):
            self.run_cmd('restore_backup', 'nope.tar.gz', '--backup-dir', str(self.backups))
        name = self.make().name
        with self.assertRaisesRegex(CommandError, 'target-uploads'):
            self.run_cmd('restore_backup', name, '--backup-dir', str(self.backups), '--target-db', str(self.root / 'x.sqlite3'))
        with self.assertRaisesRegex(CommandError, 'refusing to overwrite'):
            self.run_cmd('restore_backup', name, '--backup-dir', str(self.backups), '--target-db', str(self.db),
                         '--target-uploads', str(self.uploads))

    def test_archive_name_cannot_escape_the_backup_directory(self):
        outside = self.root / 'outside.tar.gz'
        outside.write_bytes(self.make().read_bytes())
        with self.assertRaises(CommandError):
            self.run_cmd('restore_backup', '../outside.tar.gz', '--backup-dir', str(self.backups / 'sub'))
