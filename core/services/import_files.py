"""Lifecycle of the stored originals of imports (Phase 28, ADR 0029, docs/imports.md).

The app never removes an original on its own initiative. These functions run only from a confirmed POST by the
owner (or the explicit --apply of the orphan command). Each one changes the database in one transaction and
removes files only after that transaction has committed; a file that cannot be removed is reported and logged,
never swallowed. Paths are resolved inside UPLOAD_DIR and refused if they leave it. Only counts are logged or
recorded: no file names, no amounts, no contents.
"""
import logging
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.models import ImportBatch, ImportDeletion, Payment

log = logging.getLogger(__name__)

IMPORTS_SUBDIR = 'imports'


class StoredPathRefused(Exception):
    """The stored path points outside the storage directory; nothing was changed."""


class NothingStored(Exception):
    """The batch has no stored original (never stored, discarded, or already removed)."""


@dataclass
class Removal:
    kind: str
    batches: int = 0
    removed: int = 0
    already_gone: int = 0
    failed: int = 0
    refused_batches: int = 0
    payments_kept: int = 0
    kept_shared: int = 0
    failed_paths: list = field(default_factory=list)


def _root() -> Path:
    return Path(settings.UPLOAD_DIR).resolve()


def locate(stored_path: str):
    """(path, state) with state 'none' (no path stored), 'ok', 'missing' (not on disk) or 'outside' (escapes UPLOAD_DIR)."""
    if not stored_path:
        return None, 'none'
    root = _root()
    full = (root / stored_path).resolve()
    if root not in full.parents:
        return None, 'outside'
    return (full, 'ok') if full.is_file() else (None, 'missing')


def _unlink(paths, removal: Removal):
    """Remove files after the database change has committed; count what happened."""
    for path in paths:
        try:
            path.unlink()
            removal.removed += 1
        except FileNotFoundError:
            removal.already_gone += 1
        except OSError as e:
            removal.failed += 1
            removal.failed_paths.append(path)
            log.error('Stored import file could not be removed (%s).', type(e).__name__)


def _record(removal: Removal):
    ImportDeletion.objects.create(
        kind=removal.kind, batches=removal.batches, files_removed=removal.removed,
        files_already_gone=removal.already_gone, files_failed=removal.failed, payments_kept=removal.payments_kept)
    log.info('Import files deleted: kind=%s batches=%s removed=%s already_gone=%s failed=%s payments_kept=%s',
             removal.kind, removal.batches, removal.removed, removal.already_gone, removal.failed, removal.payments_kept)


def payment_count(batch: ImportBatch) -> int:
    return Payment.objects.filter(import_batch=batch).count()


def delete_batch_file(batch: ImportBatch) -> Removal:
    """Remove the stored original; keep the batch, its rows and its history ("original removed")."""
    path, state = locate(batch.stored_path)
    if state == 'none':
        raise NothingStored
    if state == 'outside':
        raise StoredPathRefused
    removal = Removal('batch_file', batches=1, payments_kept=payment_count(batch))
    with transaction.atomic():
        batch.stored_path = ''
        batch.original_removed_at = timezone.now()
        batch.save(update_fields=['stored_path', 'original_removed_at'])
    _unlink([path] if path else [], removal)
    removal.already_gone += 1 if state == 'missing' else 0      # not on disk: the record is corrected, nothing to remove
    _record(removal)
    return removal


def _drop_batch(batch: ImportBatch):
    """Database part of deleting one batch (inside the caller's transaction). Payments are never deleted."""
    doc = batch.source_document
    batch.delete()                                              # staged rows go with it; payments keep existing, unlinked
    if doc and not Payment.objects.filter(source_document=doc).exists() and not ImportBatch.objects.filter(source_document=doc).exists():
        doc.delete()


def delete_batch(batch: ImportBatch) -> Removal:
    """Remove the batch completely: staged rows, history line, file. Payments it created stay."""
    path, state = locate(batch.stored_path)
    if state == 'outside':
        raise StoredPathRefused
    removal = Removal('batch', batches=1, payments_kept=payment_count(batch))
    with transaction.atomic():
        _drop_batch(batch)
    _unlink([path] if path else [], removal)
    removal.already_gone += 1 if state == 'missing' else 0
    _record(removal)
    return removal


def year_batches(year):
    """Import batches that contributed payments to the year, each with its payment counts in and outside it.
    Attribution comes from the payments themselves (Payment.import_batch), so it must be read before they are deleted."""
    ids = set(Payment.objects.filter(month__year=year, import_batch__isnull=False).values_list('import_batch', flat=True))
    out = []
    for batch in ImportBatch.objects.filter(pk__in=ids):
        mine = Payment.objects.filter(import_batch=batch, month__year=year).count()
        elsewhere = Payment.objects.filter(import_batch=batch).exclude(month__year=year).count()
        out.append({'batch': batch, 'in_year': mine, 'elsewhere': elsewhere, 'exclusive': elsewhere == 0})
    return out


def delete_year(year, delete_imports=False) -> Removal:
    """Delete the year with its months and payments; with delete_imports also the batches used by this year only."""
    removal = Removal('year')
    paths = []
    with transaction.atomic():
        doomed = []
        if delete_imports:
            for item in year_batches(year):          # read before the payments (and with them the link) are gone
                batch = item['batch']
                path, state = locate(batch.stored_path)
                if not item['exclusive']:
                    removal.kept_shared += 1
                elif state == 'outside':
                    removal.refused_batches += 1
                else:
                    doomed.append(batch)
                    removal.already_gone += 1 if state == 'missing' else 0
                    if path:
                        paths.append(path)
        year.delete()
        for batch in doomed:
            _drop_batch(batch)
        removal.batches = len(doomed)
    _unlink(paths, removal)
    if removal.batches or removal.failed:
        _record(removal)
    return removal


# ------------------------------------------------------------------ orphans

def orphan_report():
    """Read only. Files under UPLOAD_DIR/imports that no batch refers to, and batches whose file is not on disk."""
    root = _root()
    base = root / IMPORTS_SUBDIR
    referenced = set()
    missing, outside = [], []
    for batch in ImportBatch.objects.exclude(stored_path=''):
        path, state = locate(batch.stored_path)
        if state == 'ok':
            referenced.add(path)
        elif state == 'missing':
            missing.append(batch.pk)
        elif state == 'outside':
            outside.append(batch.pk)
    unreferenced = []
    if base.is_dir():
        for p in sorted(base.rglob('*')):
            if p.is_file() and not p.is_symlink() and p.resolve() not in referenced:
                unreferenced.append(p)
    return {'unreferenced': unreferenced, 'missing_batches': missing, 'outside_batches': outside, 'root': root}


def delete_orphans(paths) -> Removal:
    """Remove exactly the given unreferenced files (each re-checked: inside the imports directory, still unreferenced)."""
    base = _root() / IMPORTS_SUBDIR
    still = {p for p in orphan_report()['unreferenced']}
    removal = Removal('orphans')
    todo = []
    for p in paths:
        p = Path(p)
        if p in still and base in p.resolve().parents:
            todo.append(p)
    _unlink(todo, removal)
    if todo:
        _record(removal)
    return removal
