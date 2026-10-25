"""PDF rendering of a Report (Phase 33, ADR 0034): landscape A4, built with reportlab.

Nothing is calculated here: the caller passes the finished Report and its display cells (the same text the
HTML page shows), so the PDF cannot disagree with the page. The Tax information summary gets a boxed disclaimer
and a signature block with fillable fields (AcroForm: text fields for place and date, a real signature field for the
signature); every other report gets a one-line footer. The text is translated with gettext in the active language.
The file is built in memory and never written to disk.
"""
import io
from xml.sax.saxutils import escape

from django.utils.translation import gettext as _
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject, NumberObject, TextStringObject
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from reportlab.platypus import (BaseDocTemplate, Flowable, Frame, KeepTogether, PageTemplate, Paragraph, Spacer, Table,
                                TableStyle)

PAGE = landscape(A4)
MARGIN = 12 * mm
FONT, BOLD = 'Helvetica', 'Helvetica-Bold'
INK = colors.HexColor('#1a1a1a')
GREY = colors.HexColor('#555555')
HEADER_BG = colors.HexColor('#e6e6e6')
TOTAL_BG = colors.HexColor('#f2f2f2')
SIGNATURE_FIELD = 'signature'


def _style(name, size=9, **kw):
    return ParagraphStyle(name, fontName=kw.pop('fontName', FONT), fontSize=size, leading=kw.pop('leading', size * 1.25),
                          textColor=kw.pop('textColor', INK), **kw)


STYLES = {
    'title': _style('title', 16, fontName=BOLD, spaceAfter=2 * mm),
    'meta': _style('meta', 8, textColor=GREY, spaceAfter=3 * mm),
    'h2': _style('h2', 10, fontName=BOLD, spaceBefore=2 * mm, spaceAfter=1 * mm),
    'basis_label': _style('basis_label', 8, fontName=BOLD),
    'basis': _style('basis', 8),
    'note': _style('note', 8, textColor=GREY, spaceAfter=1 * mm),
    'box': _style('box', 8.5),
    'box_title': _style('box_title', 9, fontName=BOLD, spaceAfter=1 * mm),
    'label': _style('label', 9, fontName=BOLD),
}


def disclaimer_paragraphs():
    """The full notice of the tax summary (also read by tests)."""
    return [
        _('This report must not be used on its own. It must be read together with the respective tax assessment '
          '(Steuerbescheid) or tax return (Steuererklärung).'),
        _('It shows the gross income as recorded in this tool. It does not take into account all taxes, deductions, '
          'withholding, costs or individual circumstances, so the figures can differ from the assessed ones.'),
        _('It is a general information summary, not a tax calculation, tax advice or an official assessment.'),
    ]


def footer_text():
    return _('General financial summary, not an official assessment or tax calculation')


def _boxed(title, paragraphs, width):
    cells = [[Paragraph(escape(title), STYLES['box_title'])]] + [[Paragraph(escape(p), STYLES['box'])] for p in paragraphs]
    t = Table(cells, colWidths=[width])
    t.setStyle(TableStyle([('BOX', (0, 0), (-1, -1), 1, INK), ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fafafa')),
                          ('LEFTPADDING', (0, 0), (-1, -1), 4 * mm), ('RIGHTPADDING', (0, 0), (-1, -1), 4 * mm),
                          ('TOPPADDING', (0, 0), (-1, -1), 1.2 * mm), ('BOTTOMPADDING', (0, 0), (-1, -1), 1.2 * mm)]))
    return t


# One left-aligned column (Phase 34): Name, then Place and Date side by side, then Signature, all with the same
# left and right edges. Widths as a fraction of the usable page width.
COLUMN_FRACTION = 1 / 3
GAP = 6 * mm           # between Place and Date
LINE_H = 7 * mm        # Name, Place and Date: single-line height
SIGN_H = 14 * mm       # room to sign in
LABEL_H = 4.5 * mm
ROW_GAP = 3 * mm
FIELD_FONT = 11


class SignatureBlock(Flowable):
    """Name (full column width); Place and Date side by side under it, sharing the column width; Signature under both,
    full column width. Name, Place and Date are text fields, created in that order (tab order Name, Place, Date), then
    the signature field that is laid over the blank signature box afterwards (reportlab cannot create one).
    Nothing is pre-filled."""

    def __init__(self, labels, width):
        super().__init__()
        self.labels, self.width = labels, width       # labels: name -> text; width: usable page width
        self.column = width * COLUMN_FRACTION
        self.height = 2 * (LABEL_H + LINE_H) + LABEL_H + SIGN_H + 2 * ROW_GAP

    def wrap(self, availWidth, availHeight):
        return self.width, self.height

    def _field(self, name, x, y, w, h):
        c = self.canv
        c.setStrokeColor(INK)
        c.setLineWidth(0.4)
        c.line(x, y, x + w, y)
        c.acroForm.textfield(name=name, x=x, y=y, width=w, height=h, borderWidth=0, fillColor=None, borderColor=None,
                             textColor=INK, fontName=FONT, fontSize=FIELD_FONT, forceBorder=False, relative=True)

    def _label(self, x, y, name):
        c = self.canv
        c.setFont(BOLD, 9)
        c.setFillColor(INK)
        c.drawString(x, y + 1.2 * mm, self.labels[name])

    def draw(self):
        c, col = self.canv, self.column
        half = (col - GAP) / 2
        y = self.height - LABEL_H                                   # row 1: Name
        self._label(0, y, 'name')
        self._field('name', 0, y - LINE_H, col, LINE_H)
        y -= LINE_H + ROW_GAP + LABEL_H                             # row 2: Place and Date
        for i, name in enumerate(('place', 'date')):
            x = i * (half + GAP)
            self._label(x, y, name)
            self._field(name, x, y - LINE_H, half, LINE_H)
        y -= LINE_H + ROW_GAP + LABEL_H                             # row 3: Signature
        self._label(0, y, SIGNATURE_FIELD)
        c.setStrokeColor(INK)
        c.setLineWidth(0.6)
        c.rect(0, y - SIGN_H, col, SIGN_H)
        self.canv._signature_rect = c.absolutePosition(0, y - SIGN_H) + c.absolutePosition(col, y)


class _NumberedCanvas(canvas.Canvas):
    """Two passes, so every page can say "Page x of y"."""

    def __init__(self, *a, footer='', page_label=None, **kw):
        super().__init__(*a, **kw)
        self._saved, self._footer, self._label = [], footer, page_label

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            self.setFont(FONT, 7.5)
            self.setFillColor(GREY)
            self.drawString(MARGIN, 7 * mm, self._footer)
            self.drawRightString(PAGE[0] - MARGIN, 7 * mm, self._label(self._pageNumber, total))
            super().showPage()
        super().save()


def _widths(headers, body, total_width, font_size):
    """Column widths in proportion to the widest cell (capped), shrunk or grown to fill the frame."""
    n = len(headers)
    natural = []
    for i in range(n):
        longest_word = max((stringWidth(w, BOLD, font_size) for w in str(headers[i]).split()), default=0)
        widest = max([stringWidth(str(r[i]), FONT, font_size) for r in body] + [0])
        natural.append(min(max(widest, longest_word) + 6, 70 * mm))
    scale = total_width / sum(natural)
    return [w * scale for w in natural]


def render(report, headers, rows, totals, *, language, with_signature, generated_text, filtered_note=None):
    """headers: [label]; rows/totals: lists of (text, css-class) cells as on the HTML page. Returns PDF bytes."""
    width = PAGE[0] - 2 * MARGIN
    n = len(headers)
    font = 8 if n <= 8 else 7 if n <= 12 else 6
    cell = _style('cell', font, leading=font * 1.2)
    cell_r = _style('cell_r', font, leading=font * 1.2, alignment=2)
    head = _style('head', font, fontName=BOLD, leading=font * 1.2)
    head_r = _style('head_r', font, fontName=BOLD, leading=font * 1.2, alignment=2)
    total = _style('total', font, fontName=BOLD, leading=font * 1.2)
    total_r = _style('total_r', font, fontName=BOLD, leading=font * 1.2, alignment=2)

    story = [Paragraph(escape(report.title), STYLES['title']),
             Paragraph(escape(generated_text), STYLES['meta'])]
    if with_signature:
        story += [_boxed(_('Important notice'), disclaimer_paragraphs(), width), Spacer(1, 3 * mm)]

    story.append(Paragraph(escape(_('Basis')), STYLES['h2']))
    basis = Table([[Paragraph(escape(str(k)), STYLES['basis_label']), Paragraph(escape(str(v)), STYLES['basis'])]
                   for k, v in report.basis], colWidths=[45 * mm, width - 45 * mm])
    basis.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('TOPPADDING', (0, 0), (-1, -1), 0.6),
                               ('BOTTOMPADDING', (0, 0), (-1, -1), 0.6), ('LEFTPADDING', (0, 0), (-1, -1), 0)]))
    story += [basis, Spacer(1, 3 * mm)]

    if rows:
        aligns = [a == 'num' for _t, a in rows[0]]
        data = [[Paragraph(escape(str(h)), head_r if aligns[i] else head) for i, h in enumerate(headers)]]
        for r in rows:
            data.append([Paragraph(escape(t), cell_r if aligns[i] else cell) for i, (t, _a) in enumerate(r)])
        if totals:
            data.append([Paragraph(escape(t), total_r if aligns[i] else total) for i, (t, _a) in enumerate(totals)])
        body = [[t for t, _a in r] for r in rows] + ([[t for t, _a in totals]] if totals else [])
        table = Table(data, colWidths=_widths(headers, body, width, font), repeatRows=1)
        style = [('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#999999')), ('BACKGROUND', (0, 0), (-1, 0), HEADER_BG),
                 ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 2), ('RIGHTPADDING', (0, 0), (-1, -1), 2),
                 ('TOPPADDING', (0, 0), (-1, -1), 1.5), ('BOTTOMPADDING', (0, 0), (-1, -1), 1.5)]
        if totals:
            style.append(('BACKGROUND', (0, -1), (-1, -1), TOTAL_BG))
        table.setStyle(TableStyle(style))
        story.append(table)
    else:
        story.append(Paragraph(escape(_('No payments match this filter') if report.no_match else _('No data for this period.')),
                               STYLES['basis']))

    if report.notes:
        notes = [Paragraph(escape(str(note)), STYLES['note']) for note in report.notes]
        story += [Spacer(1, 3 * mm), KeepTogether([Paragraph(escape(_('Notes')), STYLES['h2']), notes[0]])] + notes[1:]

    if with_signature:
        labels = {'name': _('Name'), 'place': _('Place (Ort)'), 'date': _('Date (Datum)'),
                  SIGNATURE_FIELD: _('Signature (Unterschrift)')}
        # The notice and the fields never separate across pages: if they fit under the table on its last page they follow
        # it there, otherwise they move together (the last table rows are not pulled along; reportlab cannot split a
        # table to keep a few rows with a later flowable).
        story.append(Spacer(1, 4 * mm))
        story.append(KeepTogether([_boxed(_('Important notice'), disclaimer_paragraphs(), width), Spacer(1, 4 * mm),
                                   SignatureBlock(labels, width)]))

    buf = io.BytesIO()
    footer = footer_text()
    page_label = lambda n_, total_: _('Page %(n)s of %(total)s') % {'n': n_, 'total': total_}
    doc = BaseDocTemplate(buf, pagesize=PAGE, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=14 * mm,
                          title=report.title, author='', creator='Tax and Healthcare Tool')
    doc.addPageTemplates([PageTemplate(id='main', frames=[Frame(MARGIN, 14 * mm, width, PAGE[1] - MARGIN - 14 * mm,
                                                               leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)])])
    signature_rects = []

    def make_canvas(*a, **kw):
        c = _NumberedCanvas(*a, footer=footer, page_label=page_label, **kw)
        signature_rects.append(c)
        return c

    doc.build(story, canvasmaker=make_canvas)
    pdf = buf.getvalue()
    if with_signature:
        pdf = _add_signature_field(pdf, signature_rects[0])
    return pdf


def _add_signature_field(pdf, canv):
    """Lay a real /Sig field over the signature box (the last page that drew one), keeping the text fields."""
    rect = None
    page_index = None
    for i, state in enumerate(canv._saved):
        r = state.get('_signature_rect')
        if r:
            rect, page_index = r, i
    if rect is None:
        return pdf
    reader = PdfReader(io.BytesIO(pdf))
    writer = PdfWriter(clone_from=reader)
    page = writer.pages[page_index]
    widget = DictionaryObject({
        NameObject('/Type'): NameObject('/Annot'), NameObject('/Subtype'): NameObject('/Widget'),
        NameObject('/FT'): NameObject('/Sig'), NameObject('/T'): TextStringObject(SIGNATURE_FIELD),
        NameObject('/F'): NumberObject(4),
        NameObject('/Rect'): ArrayObject([FloatObject(round(v, 2)) for v in (rect[0], rect[1], rect[2], rect[3])]),
        NameObject('/P'): page.indirect_reference,
    })
    ref = writer._add_object(widget)
    annots = page.get('/Annots')
    if annots is None:
        page[NameObject('/Annots')] = annots = ArrayObject()
    else:
        annots = annots.get_object()
    annots.append(ref)
    acro = writer._root_object['/AcroForm']
    acro.setdefault(NameObject('/Fields'), ArrayObject())
    acro['/Fields'].append(ref)
    acro[NameObject('/SigFlags')] = NumberObject(0)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
