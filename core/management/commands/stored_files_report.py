from django.core.management.base import BaseCommand

from core.services import import_files
from core.services.pdf_text import mask_digit_runs


class Command(BaseCommand):
    help = ('Report stored import files that no batch refers to, and batches whose file is missing (counts and masked '
            'names only). Nothing is deleted unless --apply is given; run without it first and check the list.')

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='delete exactly the unreferenced files listed')

    def handle(self, *args, **opts):
        report = import_files.orphan_report()
        files = report['unreferenced']
        self.stdout.write(f'Stored files not referenced by any import batch: {len(files)}')
        for p in files:
            self.stdout.write('  ' + mask_digit_runs(p.relative_to(report['root']).as_posix()))
        self.stdout.write(f'Import batches whose stored file is missing on disk: {len(report["missing_batches"])}')
        self.stdout.write(f'Import batches whose stored path is outside the storage directory: {len(report["outside_batches"])}')
        if not opts['apply']:
            self.stdout.write('Dry run: nothing was deleted. Add --apply to delete the unreferenced files listed above.')
            return
        removal = import_files.delete_orphans(files)
        self.stdout.write(f'Deleted: {removal.removed}; already gone: {removal.already_gone}; failed: {removal.failed}.')
