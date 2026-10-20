"""Text extraction from PDF files (Phase 14). Text layer only: scanned PDFs and OCR are out of scope.

This module only turns bytes into page text. Reading the figures out of that text is done by
core.services.dividend_statements, and the result is staged by core.services.pdf_imports. PDF content is never logged
and never sent to an external service; extraction runs inside this process with pypdf (pure Python).
"""
import io
import logging
import re

from django.utils.translation import gettext

MAX_PDF_BYTES = 5 * 1024 * 1024
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


def extract_pages(raw: bytes, layout: bool = False) -> list[str]:
    """Return the text of each page. Raises PdfError for files that are not readable text PDFs.

    layout=True uses pypdf's layout mode, which keeps the cells of a table row on one line (the default mode can
    separate dates from amounts). Readers that need it say so (Reader.needs_layout)."""
    if len(raw) > MAX_PDF_BYTES:
        raise PdfError(gettext('The PDF is larger than %(mb)s MB.') % {'mb': MAX_PDF_BYTES // 1024 // 1024})
    if not looks_like_pdf(raw):
        raise PdfError(gettext('This is not a PDF file.'))
    from pypdf import PdfReader          # imported here so that CSV-only use never loads it
    try:
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:
            # Many bank PDFs are encrypted only to forbid editing and open with an empty password.
            opened = reader.decrypt('')
            if not opened:
                raise PdfError(gettext('The PDF is password-protected; remove the password and upload it again.'))
        if len(reader.pages) > MAX_PAGES:
            raise PdfError(gettext('The PDF has more than %(n)s pages.') % {'n': MAX_PAGES})
        if layout:
            pages = [(page.extract_text(extraction_mode='layout') or '') for page in reader.pages]
        else:
            pages = [(page.extract_text() or '') for page in reader.pages]
    except PdfError:
        raise
    except Exception as e:              # pypdf raises many error types for damaged files
        if 'cryptography' in str(e):    # AES needs the optional 'cryptography' package, which is not installed
            raise PdfError(gettext('The PDF is AES-encrypted and the library needed to open it is not installed. '
                                   'Remove the encryption (for example by printing the PDF to a new PDF) and upload it again.')) from e
        raise PdfError(gettext('The PDF could not be read (%(kind)s).') % {'kind': type(e).__name__}) from e
    if not any(p.strip() for p in pages):
        raise PdfError(gettext('The PDF has no text layer (probably a scan). OCR is not supported; enter the payment manually.'))
    return pages
