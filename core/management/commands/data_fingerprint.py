import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.services import backup


class Command(BaseCommand):
    help = ('Print row counts and content hashes of the live data, or of the data inside a backup archive (--archive). '
            'Two instances hold the same data when the FINGERPRINT lines are identical. Prints no row contents.')

    def add_arguments(self, parser):
        parser.add_argument('--archive', default=None, help='backup file name (looked up in the backup directory)')
        parser.add_argument('--backup-dir', default=None)

    def handle(self, *args, **opts):
        try:
            if opts['archive']:
                archive = Path(opts['backup_dir'] or settings.BACKUP_DIR) / Path(opts['archive']).name
                with tempfile.TemporaryDirectory() as tmp:
                    _, out = backup.verify_archive(archive, tmp)
                    info = backup.fingerprint(out / backup.DB_NAME, out / backup.UPLOADS)
            else:
                info = backup.fingerprint(settings.DATABASES['default']['NAME'], settings.UPLOAD_DIR)
        except backup.BackupError as e:
            raise CommandError(str(e))
        self.stdout.write('FINGERPRINT rows=%d content=%s uploads=%d:%s' % (
            info['rows'], info['content_sha256'], info['upload_files'], info['uploads_sha256']))
        self.stdout.write('TABLES ' + ' '.join(f'{t}={n}' for t, n in sorted(info['row_counts'].items()) if n))
