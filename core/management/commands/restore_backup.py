import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.services import backup


class Command(BaseCommand):
    help = ('Verify a backup archive, and optionally restore it. Without a target it only verifies (checksums, '
            'database integrity or pg_restore --list, row counts) and changes nothing. SQLite archives restore into '
            '--target-db (existing data moved aside with --force). PostgreSQL archives restore only into --new-db, an '
            'EMPTY database created beforehand on the platform side; --swap then renames the live database aside '
            '(never dropped) and needs --confirm-swap SWAP (ADR 0035).')

    def add_arguments(self, parser):
        parser.add_argument('archive', help='backup file name (looked up in the backup directory) or a full path')
        parser.add_argument('--target-db', default=None, help='SQLite: the database file to restore into')
        parser.add_argument('--new-db', default=None, help='PostgreSQL: an empty database to restore into')
        parser.add_argument('--target-uploads', default=None)
        parser.add_argument('--force', action='store_true', help='move existing targets aside instead of refusing')
        parser.add_argument('--swap', action='store_true', help='PostgreSQL: replace the live database by --new-db')
        parser.add_argument('--confirm-swap', default='', help='must be SWAP together with --swap')
        parser.add_argument('--backup-dir', default=None)

    def handle(self, *args, **opts):
        archive = Path(opts['archive'])
        if not archive.is_absolute():
            archive = Path(opts['backup_dir'] or settings.BACKUP_DIR) / archive.name
        try:
            if not opts['target_db'] and not opts['new_db']:
                with tempfile.TemporaryDirectory() as tmp:
                    manifest, _ = backup.verify_archive(archive, tmp)
                counts = manifest['row_counts']
                check = 'pg_restore=ok' if backup.archive_engine(manifest) == backup.POSTGRESQL else 'integrity=ok'
                self.stdout.write('VERIFIED %s checksums=ok files=%d tables=%d version=%s created=%s engine=%s' % (
                    check, len(manifest['files']), len(counts), manifest.get('app_version'), manifest.get('created_utc'),
                    backup.archive_engine(manifest)))
                self.stdout.write('ROWS ' + ' '.join(f'{t}={n}' for t, n in sorted(counts.items()) if n))
                return
            if not opts['target_uploads']:
                raise CommandError('--target-uploads is required together with --target-db or --new-db.')
            if opts['new_db']:
                if not settings.USING_POSTGRES:
                    raise CommandError('--new-db needs the PostgreSQL settings (DJANGO_DB_HOST).')
                if opts['swap'] and opts['confirm_swap'] != 'SWAP':
                    raise CommandError('--swap replaces the live database; add --confirm-swap SWAP to do it.')
                result = backup.restore_pg_archive(archive, settings.DATABASES['default'], opts['new_db'],
                                                   opts['target_uploads'], force=opts['force'], swap=opts['swap'])
                self.stdout.write(f'RESTORED created={result["manifest"].get("created_utc")} into={result["new_db"]}')
                if result['swapped_aside_db']:
                    self.stdout.write(f'SWAPPED live database renamed aside to {result["swapped_aside_db"]}')
            else:
                result = backup.restore_archive(archive, opts['target_db'], opts['target_uploads'], force=opts['force'])
                self.stdout.write(f'RESTORED created={result["manifest"].get("created_utc")}')
            for p in result['moved_aside']:
                self.stdout.write(f'MOVED_ASIDE {p}')
        except backup.BackupError as e:
            raise CommandError(str(e))
