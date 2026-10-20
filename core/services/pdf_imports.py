"""Staging of PDF statements for import (Phase 14).

A PDF upload is read into the same staging tables as a CSV upload (ImportBatch / ImportRow), so the review, per-row edit
and exclude, duplicate rule, atomic idempotent commit, history and the protected download of the originals are exactly
the CSV ones. Nothing becomes a payment before the owner confirms. Extraction lives in pdf_text and the readers in statement_readers;
they know nothing about the models. One statement can give zero, one or many rows (Phase 15).
"""
import hashlib
import io
import os
import re
import zipfile
from decimal import Decimal

from django.db import transaction
from django.utils.translation import gettext, ngettext

from core.models import ImportBatch, ImportRow

from . import imports, pdf_text, statement_readers
from .imports import COLUMNS, ImportFileError
from .rates import RateProvider

MAX_FILES = 300
MAX_SKIPPED_SHOWN = 8


class NothingToImport(Exception):
    """Every file was recognised but none holds income (or is deliberately not imported). No batch is created.
    The message is safe to show."""


def _clean_name(name):
    base = ' '.join(os.path.basename(name or 'statement.pdf').split())[:200]
    return base or 'statement.pdf'


def _clean_evidence(text):
    """Source lines are shown in the review and kept in the database: hide long digit runs (reference numbers)."""
    return pdf_text.mask_digit_runs(text)[:160]


def _display_name(name):
    """File names often contain the account number: the name that is shown and kept in the staging masks digit runs."""
    return pdf_text.mask_digit_runs(name)


def _provenance(row):
    return {field: {'page': page, 'text': _clean_evidence(text)} for field, (page, text) in row.provenance.items()}


def _zip(originals):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_STORED) as archive:
        for number, (name, raw) in enumerate(originals, start=1):
            archive.writestr(f'{number:03d}-{name}', raw)
    return buffer.getvalue()


def stage_pdf_batch(files, provider: RateProvider) -> ImportBatch:
    """files: [(file name, bytes)]. Stage every row of every readable statement. Raises ImportFileError (nothing created)
    when no file could be read, and NothingToImport (nothing created) when files were read but hold no income.
    The returned batch carries `file_counts`, a dict for the upload message (not stored)."""
    if not files:
        raise ImportFileError(gettext('No file was uploaded.'))
    if len(files) > MAX_FILES:
        raise ImportFileError(gettext('More than %(n)s files at once.') % {'n': MAX_FILES})
    staged, skipped, seen = [], [], set()                 # skipped: (name, reason) for every file that was not staged
    refused = nothing = not_imported = 0
    statements_seen = {}                                  # (reader id, fingerprint) -> display name of the first file
    notices, continuity = [], []
    for raw_name, raw in sorted(files, key=lambda f: _clean_name(f[0]).lower()):
        name = _clean_name(raw_name)
        shown = _display_name(name)
        digest = hashlib.sha256(raw).hexdigest()
        if digest in seen:
            skipped.append((shown, gettext('the same file was selected twice')))
            continue
        seen.add(digest)
        outcome = statement_readers.read_statement(raw)
        if outcome.result is None:
            refused += 1
            skipped.append((shown, outcome.error))
            continue
        result = outcome.result
        if result.fingerprint:
            key = (outcome.reader_id, result.fingerprint)
            if key in statements_seen:
                skipped.append((shown, gettext('same statement as %(file)s') % {'file': statements_seen[key]}))
                continue
            statements_seen[key] = shown
        notices += [f'{shown}: {n}' for n in result.notices]
        if result.rows:
            staged.append((name, shown, raw, result))
            continuity.append((shown, outcome.reader_id, result.continuity))
        elif result.not_imported:
            not_imported += 1
        else:
            nothing += 1
    if not staged:
        summary = _summary_lines(nothing, not_imported)
        if refused:
            reasons = '; '.join(f'{n}: {r}' for n, r in skipped[:MAX_SKIPPED_SHOWN])
            if len(files) == 1:
                raise ImportFileError(gettext('This PDF was not recognised, so nothing was staged. %(reason)s Enter the payment manually.')
                                      % {'reason': skipped[0][1]})
            raise ImportFileError(' '.join([gettext('None of the %(n)s PDFs was recognised, so nothing was staged. %(reasons)s Enter the payments manually.')
                                            % {'n': len(files), 'reasons': reasons}] + summary))
        raise NothingToImport(' '.join(summary + [gettext('Nothing to import.')] + notices[:MAX_SKIPPED_SHOWN]))
    warnings = [gettext('Not staged: %(file)s (%(reason)s).') % {'file': n, 'reason': r} for n, r in skipped[:MAX_SKIPPED_SHOWN]]
    if len(skipped) > MAX_SKIPPED_SHOWN:
        warnings.append(gettext('%(n)s more files were not staged.') % {'n': len(skipped) - MAX_SKIPPED_SHOWN})
    warnings += _summary_lines(nothing, not_imported)
    warnings += [f'{label}: {text}' for label, text in statement_readers.continuity_notes(continuity)]
    warnings += notices[:MAX_SKIPPED_SHOWN]
    if len(notices) > MAX_SKIPPED_SHOWN:
        warnings.append(gettext('%(n)s more notices were left out.') % {'n': len(notices) - MAX_SKIPPED_SHOWN})

    single = len(staged) == 1
    stored_bytes = staged[0][2] if single else _zip([(n, r) for n, _s, r, _d in staged])
    sha = hashlib.sha256(stored_bytes).hexdigest()
    previous = ImportBatch.objects.filter(sha256=sha, status=ImportBatch.Status.COMMITTED).first()
    if previous:
        warnings.append(gettext('These exact files were already imported as batch #%(n)s. Importing them again will flag every row as a duplicate.')
                        % {'n': previous.pk})
    rows = [(shown, row) for _n, shown, _r, result in staged for row in result.rows]
    stored = None
    try:
        with transaction.atomic():
            batch = ImportBatch.objects.create(
                file_name=staged[0][1] if single else gettext('%(n)s PDF statements') % {'n': len(staged)},
                sha256=sha, warnings=warnings, kind=ImportBatch.Kind.PDF)
            batch.description = f'PDF import #{batch.pk}'
            stored = batch.stored_path = imports.store_upload(stored_bytes, batch, '.pdf' if single else '.zip')
            batch.save()
            ImportRow.objects.bulk_create([
                ImportRow(batch=batch, line_number=number, data=dict(row.data), original=dict(row.data),
                          source_name=shown, provenance=_provenance(row))
                for number, (shown, row) in enumerate(rows, start=1)])
            imports.revalidate_batch(batch, provider)
    except Exception:
        if stored:
            (imports.Path(imports.settings.UPLOAD_DIR) / stored).unlink(missing_ok=True)
        raise
    batch.file_counts = {'files': len(files), 'staged': len(staged), 'rows': len(rows), 'nothing': nothing,
                         'not_imported': not_imported, 'not_staged': len(skipped)}
    return batch


def _summary_lines(nothing, not_imported):
    """One line per outcome, with a count, never one line per file."""
    lines = []
    if nothing:
        lines.append(ngettext('%(n)s statement recognised, no income.', '%(n)s statements recognised, no income.', nothing)
                     % {'n': nothing})
    if not_imported:
        lines.append(ngettext('%(n)s statement recognised and not imported (see the notices).',
                              '%(n)s statements recognised and not imported (see the notices).', not_imported) % {'n': not_imported})
    return lines
