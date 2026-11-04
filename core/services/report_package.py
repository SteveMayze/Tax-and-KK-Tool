"""ZIP package for the adviser: the report PDF plus the original statements it refers to (Phase 42, ADR 0038).

Read only. Originals are copied byte for byte (never repaired, redacted or recompressed in content); each one is
hashed first and refused when it no longer matches the recorded hash ("changed on disk"). Member names are made here
from the reference and a sanitised masked name, never taken from a stored path. The zip is built in an anonymous
temporary file (removed when closed, even after an interrupted download), not in memory, and nothing is ever written
under UPLOAD_DIR. Stored files are reached only through `import_files.locate`.
"""
import csv
import hashlib
import io
import re
import tempfile
import zipfile
from dataclasses import dataclass, field

from django.conf import settings
from django.utils.translation import gettext as _

from . import import_files, report_csv

CHUNK = 1 << 20
SAFE = re.compile(r'[^A-Za-z0-9._# -]')
INCLUDED, MISSING, CHANGED = 'included', 'missing', 'changed'


@dataclass
class Item:
    ref: str
    name: str                 # masked, as displayed
    sha256: str
    payments: int
    status: str = MISSING
    state: str = ''
    size: int = 0
    member_name: str = ''     # name inside the package, '' when not included


@dataclass
class Summary:
    items: list = field(default_factory=list)

    @property
    def included(self):
        return [i for i in self.items if i.status == INCLUDED]

    @property
    def total_size(self):
        return sum(i.size for i in self.included)

    @property
    def problems(self):
        return [i for i in self.items if i.status != INCLUDED]


def max_bytes():
    return int(getattr(settings, 'REPORT_PACKAGE_MAX_MB', 100)) * 1024 * 1024


def member_name(ref, masked_name):
    """sources/<ref>_<sanitised masked name>.pdf; no path separators, no dots-only parts, bounded length."""
    base = masked_name.replace('\\', '/').rsplit('/', 1)[-1]
    base = re.sub(r'\.pdf$', '', base, flags=re.I)
    base = SAFE.sub('_', base).strip(' .')[:80] or 'statement'
    return f'sources/{ref}_{base}.pdf'


def _open(doc):
    """(file object, size) for the stored original of a document, or None. Zip members are opened inside the zip."""
    path, state = import_files.locate(doc.stored_path)
    if state != 'ok':
        return None
    if not doc.member:
        return open(path, 'rb')
    archive = zipfile.ZipFile(path)
    try:
        return _ClosingMember(archive, archive.open(doc.member))
    except KeyError:
        archive.close()
        return None


class _ClosingMember:
    def __init__(self, archive, handle):
        self.archive, self.handle = archive, handle

    def read(self, n=-1):
        return self.handle.read(n)

    def close(self):
        self.handle.close()
        self.archive.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _hash(doc):
    """(sha256, size) of the stored original as it is on disk now, or None when it cannot be read."""
    try:
        handle = _open(doc)
        if handle is None:
            return None
        digest, size = hashlib.sha256(), 0
        with handle:
            for block in iter(lambda: handle.read(CHUNK), b''):
                digest.update(block)
                size += len(block)
        # a stored zip as a whole must still equal its recorded hash, or a changed member could go unnoticed
        if doc.member:
            whole = hashlib.sha256()
            path, _state = import_files.locate(doc.stored_path)
            with open(path, 'rb') as f:
                for block in iter(lambda: f.read(CHUNK), b''):
                    whole.update(block)
            if whole.hexdigest() != doc.zip_sha256:
                return '', size
        return digest.hexdigest(), size
    except (OSError, zipfile.BadZipFile):
        return None


def inspect(sources):
    """Summary of what a package would hold. Reads (hashes) the stored files; writes nothing."""
    summary = Summary()
    for doc in sources.documents:
        if doc.kind != 'pdf':
            continue
        item = Item(doc.ref, doc.name, doc.sha256, doc.payments, state=doc.state)
        found = _hash(doc) if doc.stored_path else None
        if found is None:
            item.status, item.state = MISSING, doc.state if doc.state != _('stored') else _('not found')
        elif found[0] != doc.sha256:
            item.status, item.state, item.size = CHANGED, _('changed on disk, not included'), found[1]
        else:
            item.status, item.size = INCLUDED, found[1]
            item.member_name = member_name(doc.ref, doc.name)
        summary.items.append(item)
    return summary


def _index_csv(summary):
    out = io.StringIO()
    w = csv.writer(out, lineterminator='\r\n')
    w.writerow(['Reference', 'File name in the package', 'File name as displayed (masked)', 'SHA-256', 'Size (bytes)', 'State',
                'Payments in the report'])
    for i in summary.items:
        w.writerow([i.ref, report_csv.safe_text(i.member_name), report_csv.safe_text(i.name), i.sha256,
                    i.size if i.status == INCLUDED else '', report_csv.safe_text(i.state if i.status != INCLUDED else 'stored'),
                    i.payments])
    return out.getvalue()


def readme_text():
    return '\n'.join([
        _('Tax information summary: package for the adviser'), '',
        _('This package holds the report as a PDF, the original statements the report refers to, and an index.'),
        _('The report is a general information summary of income as recorded. It is not a tax calculation, tax advice '
          'or an official assessment.'), '',
        _('Files:'),
        '  ' + _('the report PDF: the same file the tool produces for the same period and filter.'),
        '  ' + _('sources/: the original statement PDFs, unchanged, named with the reference used in the report (D01, D02, ...).'),
        '  ' + _('index.csv: reference, file name, SHA-256, size, state and number of payments for each statement.'), '',
        _('To check a file, compute its SHA-256 and compare it with index.csv, for example "shasum -a 256 <file>" on '
          'macOS or Linux, or "certutil -hashfile <file> SHA256" on Windows.'), '',
        _('The statements can contain account numbers and other personal data. Handle this package accordingly.'), ''])


def build(summary, report_pdf: bytes, pdf_name: str, sources):
    """A seekable anonymous temporary file holding the zip, positioned at the start. The caller closes it."""
    tmp = tempfile.TemporaryFile()
    try:
        with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(pdf_name, report_pdf)
            archive.writestr('index.csv', _index_csv(summary))
            archive.writestr('README.txt', readme_text())
            docs = {d.ref: d for d in sources.documents}
            for item in summary.included:
                doc = docs[item.ref]
                handle = _open(doc)
                if handle is None:
                    raise OSError('original vanished')
                with handle, archive.open(zipfile.ZipInfo(item.member_name), 'w') as out:
                    for block in iter(lambda: handle.read(CHUNK), b''):
                        out.write(block)
        tmp.seek(0)
        return tmp
    except BaseException:
        tmp.close()
        raise
