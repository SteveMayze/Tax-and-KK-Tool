"""Text extraction from PDF files (Phase 14). Text layer only: scanned PDFs and OCR are out of scope.

This module only turns bytes into page text. Reading the figures out of that text is done by
core.services.dividend_statements, and the result is staged by core.services.pdf_imports. PDF content is never logged
and never sent to an external service; extraction runs inside this process with pypdf (pure Python).
"""
import io
import logging
import re

from django.utils.translation import gettext

MAX_PDF_BYTES = 16 * 1024 * 1024         # one MECU statement is 12 MB (barcode pages)
MAX_PAGES = 30


# pypdf logs warnings about fonts and damaged objects; they say nothing useful here and must not reach the logs.
logging.getLogger('pypdf').setLevel(logging.ERROR)


class PdfError(Exception):
    """The file cannot be read as a text PDF. The message is safe to show (it never contains document text)."""


def looks_like_pdf(raw: bytes) -> bool:
    return raw[:5] == b'%PDF-'


def mask_digit_runs(text: str) -> str:
    """Hide digit runs of six or more (account, reference and statement numbers) in anything that is shown or kept."""
    return re.sub(r'\d{6,}', '######', text)


XREF_HEADER = re.compile(rb'(\d+) (\d+)[ ]*\r?\n')
XREF_ENTRY = re.compile(rb'\d{10} \d{5} [nf](?: \r| \n|\r\n)')


def repair_xref_counts(raw: bytes) -> bytes | None:
    """In-memory repair of one known defect: a cross-reference subsection header that declares fewer entries than the table
    lists (the MECU statements: "0 N" over N+1 entries), which makes pypdf stop with "Could not read Null object".
    Only that count is corrected, and only when the table is intact; nothing else in the file is touched and the result is
    never stored. Returns None when there is nothing it can repair (garbage tables stay refused)."""
    changes, pos = [], 0
    for m in re.finditer(rb'(?m)^xref\r?\n', raw):
        p = m.end()
        while (h := XREF_HEADER.match(raw, p)):
            declared, found, q = int(h.group(2)), 0, h.end()
            while (e := XREF_ENTRY.match(raw, q)):
                q, found = e.end(), found + 1
            if found > declared:
                changes.append((h.start(2), h.end(2), str(found).encode()))
            p = q
    if not changes:
        return None
    out, last = bytearray(), 0
    for start, end, text in changes:
        out += raw[last:start] + text
        last = end
    out += raw[last:]
    if len(out) != len(raw) and b'startxref' in raw[changes[-1][1]:]:
        # the table moved bytes in front of a later section or the startxref pointer: offsets would be wrong
        later = re.search(rb'(?m)^xref\r?\n', raw[changes[-1][1]:])
        if later or re.search(rb'startxref\s+(\d+)', raw) and int(re.search(rb'startxref\s+(\d+)', raw).group(1)) > changes[-1][0]:
            return None
    return bytes(out)


def _read_pages(raw: bytes, layout: bool) -> list[str]:
    from pypdf import PdfReader          # imported here so that CSV-only use never loads it
    reader = PdfReader(io.BytesIO(raw))
    if reader.is_encrypted:
        # Many bank PDFs are encrypted only to forbid editing and open with an empty password.
        if not reader.decrypt(''):
            raise PdfError(gettext('The PDF is password-protected; remove the password and upload it again.'))
    if len(reader.pages) > MAX_PAGES:
        raise PdfError(gettext('The PDF has more than %(n)s pages.') % {'n': MAX_PAGES})
    if layout:
        return [(page.extract_text(extraction_mode='layout') or '') for page in reader.pages]
    return [(page.extract_text() or '') for page in reader.pages]


def extract_pages(raw: bytes, layout: bool = False) -> list[str]:
    """Return the text of each page. Raises PdfError for files that are not readable text PDFs.

    layout=True uses pypdf's layout mode, which keeps the cells of a table row on one line (the default mode can
    separate dates from amounts). Readers that need it say so (Reader.needs_layout).

    A file pypdf cannot read goes through repair_xref_counts once (in memory only); undamaged files never do."""
    if len(raw) > MAX_PDF_BYTES:
        raise PdfError(gettext('The PDF is larger than %(mb)s MB.') % {'mb': MAX_PDF_BYTES // 1024 // 1024})
    if not looks_like_pdf(raw):
        raise PdfError(gettext('This is not a PDF file.'))
    try:
        try:
            pages = _read_pages(raw, layout)
        except PdfError:
            raise
        except Exception:
            repaired = repair_xref_counts(raw)
            if repaired is None:
                raise
            pages = _read_pages(repaired, layout)
    except PdfError:
        raise
    except Exception as e:              # pypdf raises many error types for damaged files
        if 'cryptography' in str(e):    # AES needs the 'cryptography' package
            raise PdfError(gettext('The PDF is AES-encrypted and the library needed to open it is not installed. '
                                   'Remove the encryption (for example by printing the PDF to a new PDF) and upload it again.')) from e
        raise PdfError(gettext('The PDF could not be read (%(kind)s).') % {'kind': type(e).__name__}) from e
    if not any(p.strip() for p in pages):
        raise PdfError(gettext('The PDF has no text layer (probably a scan). OCR is not supported; enter the payment manually.'))
    return pages
