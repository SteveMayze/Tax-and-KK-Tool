"""Staging of PDF statements for import (Phase 14).

A PDF upload is read into the same staging tables as a CSV upload (ImportBatch / ImportRow), so the review, per-row edit
and exclude, duplicate rule, atomic idempotent commit, history and the protected download of the originals are exactly
the CSV ones. Nothing becomes a payment before the owner confirms. Extraction itself lives in pdf_text and
dividend_statements and knows nothing about the models.
"""
import hashlib
import io
import os
import re
import zipfile
from decimal import Decimal

from django.db import transaction
from django.utils.translation import gettext

from core.models import ImportBatch, ImportRow

from . import dividend_statements, imports, interest_statements, pdf_text
from .dividend_statements import UnsupportedStatement
from .imports import COLUMNS, ImportFileError
from .rates import RateProvider

MAX_FILES = 300
MAX_SKIPPED_SHOWN = 8


def _clean_name(name):
    base = ' '.join(os.path.basename(name or 'statement.pdf').split())[:200]
    return base or 'statement.pdf'


def _clean_evidence(text):
    """Source lines are shown in the review and kept in the database: hide long digit runs (reference numbers)."""
    return re.sub(r'\d{6,}', '######', text)[:160]


def _read(pages):
    """Recognise the kind of statement and read it. Revolut Flexible Cash Funds statements have their own reader;
    everything else is tried as an Australian dividend or distribution advice."""
    if interest_statements.recognises(pages):
        return interest_statements.parse(pages)
    return dividend_statements.parse(pages)


def _row_data(statement):
    return statement.row_data(COLUMNS)


def _provenance(statement):
    return {field: {'page': page, 'text': _clean_evidence(text)} for field, (page, text) in statement.provenance_items().items()}


def _zip(originals):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_STORED) as archive:
        for number, (name, raw) in enumerate(originals, start=1):
            archive.writestr(f'{number:03d}-{name}', raw)
    return buffer.getvalue()


def stage_pdf_batch(files, provider: RateProvider) -> ImportBatch:
    """files: [(file name, bytes)]. Stage every readable statement; raise ImportFileError (nothing created) if none is."""
    if not files:
        raise ImportFileError(gettext('No file was uploaded.'))
    if len(files) > MAX_FILES:
        raise ImportFileError(gettext('More than %(n)s files at once.') % {'n': MAX_FILES})
    staged, skipped, seen = [], [], set()
    for raw_name, raw in sorted(files, key=lambda f: _clean_name(f[0]).lower()):
        name = _clean_name(raw_name)
        digest = hashlib.sha256(raw).hexdigest()
        if digest in seen:
            skipped.append((name, gettext('the same file was selected twice')))
            continue
        seen.add(digest)
        try:
            dividend = _read(pdf_text.extract_pages(raw))
        except (pdf_text.PdfError, UnsupportedStatement) as e:
            skipped.append((name, str(e)))
            continue
        staged.append((name, raw, dividend))
    if not staged:
        shown = '; '.join(f'{n}: {r}' for n, r in skipped[:MAX_SKIPPED_SHOWN])
        if len(files) == 1:
            raise ImportFileError(gettext('This PDF was not recognised, so nothing was staged. %(reason)s Enter the payment manually.')
                                  % {'reason': skipped[0][1]})
        raise ImportFileError(gettext('None of the %(n)s PDFs was recognised, so nothing was staged. %(reasons)s Enter the payments manually.')
                              % {'n': len(files), 'reasons': shown})
    warnings = [gettext('Not staged: %(file)s (%(reason)s).') % {'file': n, 'reason': r} for n, r in skipped[:MAX_SKIPPED_SHOWN]]
    if len(skipped) > MAX_SKIPPED_SHOWN:
        warnings.append(gettext('%(n)s more files were not staged.') % {'n': len(skipped) - MAX_SKIPPED_SHOWN})

    single = len(staged) == 1
    stored_bytes = staged[0][1] if single else _zip([(n, r) for n, r, _d in staged])
    sha = hashlib.sha256(stored_bytes).hexdigest()
    previous = ImportBatch.objects.filter(sha256=sha, status=ImportBatch.Status.COMMITTED).first()
    if previous:
        warnings.append(gettext('These exact files were already imported as batch #%(n)s. Importing them again will flag every row as a duplicate.')
                        % {'n': previous.pk})
    stored = None
    try:
        with transaction.atomic():
            batch = ImportBatch.objects.create(
                file_name=staged[0][0] if single else gettext('%(n)s PDF statements') % {'n': len(staged)},
                sha256=sha, warnings=warnings, kind=ImportBatch.Kind.PDF)
            batch.description = f'PDF import #{batch.pk}'
            stored = batch.stored_path = imports.store_upload(stored_bytes, batch, '.pdf' if single else '.zip')
            batch.save()
            ImportRow.objects.bulk_create([
                ImportRow(batch=batch, line_number=number, data=_row_data(d), original=_row_data(d),
                          source_name=name, provenance=_provenance(d))
                for number, (name, _raw, d) in enumerate(staged, start=1)])
            imports.revalidate_batch(batch, provider)
    except Exception:
        if stored:
            (imports.Path(imports.settings.UPLOAD_DIR) / stored).unlink(missing_ok=True)
        raise
    return batch
