"""Source documents of payments, for the adviser report (Phase 41, ADR 0037). Read only.

A payment points to the document it came from through its import row (`ImportRow.created_payment`) and that row's
batch. A single-PDF batch is one document, identified by the SHA-256 of the stored file (the batch's recorded hash). A
zip batch holds several PDFs named `NNN-<name>`; the row's `source_name` is the masked name, so the member is the one
whose masked name equals it (two members with the same masked name cannot be told apart: the payment is then
"ambiguous", never guessed). Member hashes are computed by streaming the stored member; no text is read or kept.
The same statement in two batches has the same hash and is one document. A CSV batch is a source of kind CSV.
Files are reached only through `import_files.locate`; a missing file is a state, not an error. Nothing is written.
"""
import hashlib
import zipfile
from dataclasses import dataclass, field

from django.utils.translation import gettext as _

from core.models import ImportBatch, ImportRow

from . import import_files, pdf_text

CHUNK = 400
PAGE_FIELDS = ('gross_amount', 'payment_date')


@dataclass
class PaymentSource:
    ref: str = ''             # 'D03' or '' when there is none
    page: int | None = None
    reason: str = ''          # when ref is '': why there is no source document
    settled_elsewhere: bool = False   # withholding may come from another statement of the same upload (Q41.4)

    def text(self):
        if not self.ref:
            return _('none: %(reason)s') % {'reason': self.reason}
        out = self.ref + (f' p.{self.page}' if self.page else '')
        return out + (' *' if self.settled_elsewhere else '')


@dataclass
class Document:
    key: tuple
    kind: str                 # 'pdf' | 'csv'
    name: str = ''
    sha256: str = ''
    uploaded: object = None
    state: str = ''
    organisations: set = field(default_factory=set)
    first_payment: object = None
    payments: int = 0
    ref: str = ''
    batch_ids: set = field(default_factory=set)
    stored_path: str = ''     # where the original can be read (relative to UPLOAD_DIR); '' when it cannot
    member: str = ''          # real member name inside a stored zip, '' for a single PDF
    zip_sha256: str = ''      # recorded hash of the whole stored file the document is read from


@dataclass
class Sources:
    per_payment: dict
    documents: list
    without: dict             # reason -> count
    any_settled_elsewhere: bool = False


def _members(batch):
    """masked member name -> [(sha256, size, real name)] for a stored zip batch, or None when the file cannot be read."""
    path, state = import_files.locate(batch.stored_path)
    if state != 'ok':
        return None
    out = {}
    try:
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                digest, size = hashlib.sha256(), 0
                with archive.open(info) as handle:
                    for block in iter(lambda: handle.read(1 << 20), b''):
                        digest.update(block)
                        size += len(block)
                name = pdf_text.mask_digit_runs(info.filename.split('-', 1)[-1])
                out.setdefault(name, []).append((digest.hexdigest(), size, info.filename))
    except (zipfile.BadZipFile, OSError):
        return None
    return out


def _file_state(batch):
    if batch.original_removed_at:
        return _('removed on %(date)s') % {'date': batch.original_removed_at.date().isoformat()}
    if not batch.stored_path:
        return _('not stored')
    return _('stored') if import_files.locate(batch.stored_path)[1] == 'ok' else _('not found')


def _page(row):
    for name in PAGE_FIELDS:
        entry = (row.provenance or {}).get(name)
        if isinstance(entry, dict) and entry.get('page'):
            return entry['page']
    return None


def _multi_posting(row):
    entry = (row.provenance or {}).get('withholding_tax')
    return isinstance(entry, dict) and ' / ' in (entry.get('text') or '')


def resolve(payments) -> Sources:
    payments = list(payments)
    rows = {}
    ids = [p.pk for p in payments if p.import_batch_id]
    for i in range(0, len(ids), CHUNK):
        for r in ImportRow.objects.filter(created_payment_id__in=ids[i:i + CHUNK]).select_related('batch').order_by('-id'):
            rows[r.created_payment_id] = r
    members, docs, assigned, without = {}, {}, {}, {}
    member = ''

    def lack(p, reason):
        assigned[p.pk] = PaymentSource(reason=reason)
        without[reason] = without.get(reason, 0) + 1

    for p in payments:
        member = ''
        if not p.import_batch_id:
            lack(p, _('batch deleted') if p.source_document_id else _('entered by hand'))
            continue
        row = rows.get(p.pk)
        batch = row.batch if row else p.import_batch
        if batch.kind == ImportBatch.Kind.CSV:
            key, kind, sha, name = ('csv', batch.sha256 or f'batch-{batch.pk}'), 'csv', batch.sha256, batch.file_name
        elif row is None:
            lack(p, _('no import row'))
            continue
        elif not batch.stored_path.endswith('.zip'):
            key, kind, sha, name, member = ('pdf', batch.sha256), 'pdf', batch.sha256, batch.file_name, ''
        else:
            if batch.pk not in members:
                members[batch.pk] = None if batch.original_removed_at else _members(batch)
            found = (members[batch.pk] or {}).get(row.source_name)
            if found is not None and len(found) > 1:
                lack(p, _('ambiguous (two files with the same shown name)'))
                continue
            sha = found[0][0] if found else ''
            member = found[0][2] if found else ''
            key = ('pdf', sha) if sha else ('pdf-unhashed', batch.pk, row.source_name)
            kind, name = 'pdf', row.source_name
        doc = docs.get(key)
        if doc is None:
            doc = docs[key] = Document(key, kind, pdf_text.mask_digit_runs(name or ''), sha)
        doc.batch_ids.add(batch.pk)
        readable = (kind == 'pdf' and sha and not batch.original_removed_at and
                    import_files.locate(batch.stored_path)[1] == 'ok' and (member or not batch.stored_path.endswith('.zip')))
        if readable and not doc.stored_path:
            doc.stored_path, doc.member, doc.zip_sha256 = batch.stored_path, member, batch.sha256
        states = {_file_state(b) for b in [batch]}
        doc.state = doc.state if doc.state == _('stored') else sorted(states)[0]
        doc.organisations.add(p.organisation.name)
        doc.payments += 1
        doc.first_payment = min(filter(None, [doc.first_payment, p.payment_date]))
        assigned[p.pk] = PaymentSource(ref=key, page=_page(row) if row else None,
                                       settled_elsewhere=bool(row and kind == 'pdf' and _multi_posting(row)))
    ordered = sorted(docs.values(), key=lambda d: (d.first_payment, d.name, d.sha256 or str(d.key)))
    width = 2 if len(ordered) < 100 else 3
    by_key = {}
    for n, doc in enumerate(ordered, start=1):
        doc.ref = f'D{n:0{width}d}'
        by_key[doc.key] = doc.ref
    for ps in assigned.values():
        if ps.ref:
            ps.ref = by_key[ps.ref]
    return Sources(assigned, ordered, without, any(ps.settled_elsewhere for ps in assigned.values()))
