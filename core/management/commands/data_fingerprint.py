import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from core.services import backup
from core.services import fingerprint as fp

ARCHIVE_ALIAS = 'fingerprint_archive'


class Command(BaseCommand):
    help = ('Print row counts and content hashes of the live data, or of the data inside a backup archive (--archive). '
            'Two instances hold the same data when the FINGERPRINT lines are identical, on SQLite and on PostgreSQL alike '
            '(engine-neutral, through the ORM; ADR 0035). --raw-sqlite gives the older byte-level SQLite fingerprint '
            '(the one recorded before Phase 38). Prints no row contents.')

    def add_arguments(self, parser):
        parser.add_argument('--archive', default=None, help='backup file name (looked up in the backup directory)')
        parser.add_argument('--backup-dir', default=None)
        parser.add_argument('--raw-sqlite', action='store_true',
                            help='the byte-level SQLite fingerprint used up to Phase 37 (SQLite only)')
        parser.add_argument('--per-model', action='store_true', help='also one line per model (counts and hashes)')

    def handle(self, *args, **opts):
        try:
            if opts['archive']:
                archive = Path(opts['backup_dir'] or settings.BACKUP_DIR) / Path(opts['archive']).name
                with tempfile.TemporaryDirectory() as tmp:
                    manifest, out = backup.verify_archive(archive, tmp)
                    if backup.archive_engine(manifest) != backup.SQLITE:
                        raise CommandError('This archive holds a PostgreSQL dump. Restore it into an empty database '
                                           '(on the platform side) and fingerprint that database instead.')
                    if opts['raw_sqlite']:
                        return self._raw(backup.fingerprint(out / backup.DB_NAME, out / backup.UPLOADS))
                    return self._print(self._from_sqlite_file(out / backup.DB_NAME, out / backup.UPLOADS), opts)
            if opts['raw_sqlite']:
                if not settings.DATABASES['default']['ENGINE'].endswith('sqlite3'):
                    raise CommandError('--raw-sqlite needs the SQLite database; this instance uses PostgreSQL.')
                return self._raw(backup.fingerprint(settings.DATABASES['default']['NAME'], settings.UPLOAD_DIR))
            return self._print(fp.fingerprint(settings.UPLOAD_DIR), opts)
        except backup.BackupError as e:
            raise CommandError(str(e))

    def _from_sqlite_file(self, db_file, uploads):
        """Fingerprint a SQLite file through the ORM, by opening it read-only under a temporary connection alias."""
        connections.databases[ARCHIVE_ALIAS] = {**connections.databases['default'], 'ENGINE': 'django.db.backends.sqlite3',
                                                'NAME': f'file:{db_file}?mode=ro', 'OPTIONS': {'uri': True},
                                                'HOST': '', 'PORT': '', 'USER': '', 'PASSWORD': '', 'CONN_MAX_AGE': 0}
        try:
            return fp.fingerprint(uploads, using=ARCHIVE_ALIAS)
        except Exception as e:
            raise CommandError(f'The archived database cannot be read through the current models: {type(e).__name__}') from e
        finally:
            connections[ARCHIVE_ALIAS].close()
            del connections[ARCHIVE_ALIAS]
            connections.databases.pop(ARCHIVE_ALIAS, None)

    def _print(self, info, opts):
        self.stdout.write('FINGERPRINT rows=%d content=%s uploads=%d:%s' % (
            info['rows'], info['content_sha256'], info['upload_files'], info['uploads_sha256']))
        self.stdout.write('MODELS ' + ' '.join(f'{label}={n}' for label, n, _h in info['models'] if n))
        if opts['per_model']:
            for label, n, h in info['models']:
                self.stdout.write(f'MODEL {label} rows={n} sha256={h}')

    def _raw(self, info):
        self.stdout.write('FINGERPRINT rows=%d content=%s uploads=%d:%s' % (
            info['rows'], info['content_sha256'], info['upload_files'], info['uploads_sha256']))
        self.stdout.write('TABLES ' + ' '.join(f'{t}={n}' for t, n in sorted(info['row_counts'].items()) if n))
