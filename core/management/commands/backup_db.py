from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.services import backup
from core.version import app_version


class Command(BaseCommand):
    help = ('Back up the database and uploaded files into one verified archive (safe while the app runs). SQLite: an '
            'online copy of the file. PostgreSQL: pg_dump -Fc from one exported snapshot, row counts in the same '
            'transaction (ADR 0035).')

    def add_arguments(self, parser):
        parser.add_argument('--label', default='', help='e.g. pre-deploy (lower-case letters, digits, hyphens)')
        parser.add_argument('--prune', action='store_true', help='apply the retention policy afterwards')
        parser.add_argument('--db', default=None, help='SQLite only: another database file')
        parser.add_argument('--uploads', default=None)
        parser.add_argument('--backup-dir', default=None)
        parser.add_argument('--skip-if-empty', action='store_true',
                            help='PostgreSQL: do nothing when the database has no tables yet (first deploy)')

    def handle(self, *args, **opts):
        backup_dir = opts['backup_dir'] or settings.BACKUP_DIR
        uploads = opts['uploads'] or settings.UPLOAD_DIR
        try:
            if settings.USING_POSTGRES and not opts['db'] and opts['skip_if_empty']:
                from django.db import connection
                if 'django_migrations' not in connection.introspection.table_names():
                    self.stdout.write('BACKUP_SKIPPED the database has no tables yet')
                    return
            if settings.USING_POSTGRES and not opts['db']:
                path = backup.create_pg_backup(settings.DATABASES['default'], uploads, backup_dir,
                                               label=opts['label'], version=app_version())
            else:
                path = backup.create_backup(opts['db'] or settings.DATABASES['default']['NAME'], uploads, backup_dir,
                                            label=opts['label'], version=app_version())
            self.stdout.write(f'BACKUP_CREATED {path.name}')
            if opts['prune']:
                removed = backup.prune(backup_dir)
                self.stdout.write(f'PRUNED {len(removed)} old backup(s)')
        except backup.BackupError as e:
            raise CommandError(str(e))
