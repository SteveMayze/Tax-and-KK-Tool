"""Text extraction from PDF files (Phase 14). Text layer only: scanned PDFs and OCR are out of scope.

This module only turns bytes into page text. Reading the figures out of that text is done by
core.services.dividend_statements, and the result is staged by core.services.pdf_imports. PDF content is never logged
and never sent to an external service; extraction runs inside this process with pypdf (pure Python).
"""
import io

from django.utils.translation import gettext

MAX_PDF_BYTES = 5 * 1024 * 1024
MAX_PAGES = 30


class PdfError(Exception):
    """The file cannot be read as a text PDF. The message is safe to show (it never contains document text)."""


def looks_like_pdf(raw: bytes) -> bool:
    return raw[:5] == b'%PDF-'


def extract_pages(raw: bytes) -> list[str]:
    """Return the text of each page. Raises PdfError for files that are not readable text PDFs."""
    if len(raw) > MAX_PDF_BYTES:
        raise PdfError(gettext('The PDF is larger than %(mb)s MB.') % {'mb': MAX_PDF_BYTES // 1024 // 1024})
    if not looks_like_pdf(raw):
        raise PdfError(gettext('This is not a PDF file.'))
    from pypdf import PdfReader          # imported here so that CSV-only use never loads it
    try:
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:
            raise PdfError(gettext('The PDF is password-protected; remove the password and upload it again.'))
        if len(reader.pages) > MAX_PAGES:
            raise PdfError(gettext('The PDF has more than %(n)s pages.') % {'n': MAX_PAGES})
        pages = [(page.extract_text() or '') for page in reader.pages]
    except PdfError:
        raise
    except Exception as e:              # pypdf raises many error types for damaged files
        raise PdfError(gettext('The PDF could not be read (%(kind)s).') % {'kind': type(e).__name__}) from e
    if not any(p.strip() for p in pages):
        raise PdfError(gettext('The PDF has no text layer (probably a scan). OCR is not supported; enter the payment manually.'))
    return pages
