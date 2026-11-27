"""Stored-originals check (ADR 0035): for every import batch, where its stored original is (import_files.locate) and
whether the file still has the SHA-256 recorded at import (ImportBatch.sha256, which is the hash of the stored file,
a zip included). A zip must also open and every member must pass its CRC. Prints counts only; changes nothing.
"""
import hashlib
import zipfile

from django.core.management.base import BaseCommand

from core.models import ImportBatch
from core.services import import_files

STATES = ('ok', 'none', 'missing', 'outside', 'hash_mismatch', 'zip_unreadable')


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def check():
    counts = dict.fromkeys(STATES, 0)
    members = 0
    for batch in ImportBatch.objects.order_by('pk'):
        path, state = import_files.locate(batch.stored_path)
        if state != 'ok':
            counts[state] += 1
            continue
        if batch.sha256 and _sha256(path) != batch.sha256:
            counts['hash_mismatch'] += 1
            continue
        if path.suffix == '.zip':
            try:
                with zipfile.ZipFile(path) as archive:
                    if archive.testzip() is not None:
                        counts['zip_unreadable'] += 1
                        continue
                    members += len(archive.infolist())
            except (zipfile.BadZipFile, OSError):
                counts['zip_unreadable'] += 1
                continue
        counts['ok'] += 1
    return counts, members


class Command(BaseCommand):
    help = 'Check every stored original against its recorded SHA-256 (counts only; read only).'

    def handle(self, *args, **opts):
        counts, members = check()
        self.stdout.write('STORED_FILES ' + ' '.join(f'{k}={counts[k]}' for k in STATES) + f' zip_members={members}')
