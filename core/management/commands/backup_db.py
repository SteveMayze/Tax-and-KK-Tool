from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.services import backup
from core.version import app_version


class Command(BaseCommand):
    help = 'Back up the SQLite database and uploaded files into one verified archive (safe while the app runs).'

    def add_arguments(self, parser):
        parser.add_argument('--label', default='', help='e.g. pre-deploy (lower-case letters, digits, hyphens)')
        parser.add_argument('--prune', action='store_true', help='apply the retention policy afterwards')
        parser.add_argument('--db', default=None)
        parser.add_argument('--uploads', default=None)
        parser.add_argument('--backup-dir', default=None)

    def handle(self, *args, **opts):
        try:
            path = backup.create_backup(
                opts['db'] or settings.DATABASES['default']['NAME'], opts['uploads'] or settings.UPLOAD_DIR,
                opts['backup_dir'] or settings.BACKUP_DIR, label=opts['label'], version=app_version())
            self.stdout.write(f'BACKUP_CREATED {path.name}')
            if opts['prune']:
                removed = backup.prune(opts['backup_dir'] or settings.BACKUP_DIR)
                self.stdout.write(f'PRUNED {len(removed)} old backup(s)')
        except backup.BackupError as e:
            raise CommandError(str(e))
