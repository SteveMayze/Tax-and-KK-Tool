# Follow-up prompt for Claude Code: compact signature block with a Name field (Tax summary PDF)

Context: the landscape PDF export (ReportLab, AcroForm) is in place. In the current Tax summary PDF the fields Place (Ort), Date (Datum) and Signature (Unterschrift) each span the full page width, stacked, with the label on the left. Read CLAUDE.md, docs/reporting.md and the PDF code first, confirm scope, list assumptions, propose steps, then STOP for approval before coding (new small phase, short ADR or an addendum to the PDF ADR).

## Change (Tax information summary PDF only; other reports unchanged)

1. **Add a Name field**, label "Name" in both languages (German "Name"), as a fillable text field. Leave blank; never pre-fill.
2. **Layout, revised after reviewing the first result** (the Name / Place+Date / Signature layout from the previous export is the starting point; only the arrangement changes). Build the block as one left-aligned column, **at most one third of the usable page width**, in three rows:
   - Row 1: **Name**, line spanning the full column width.
   - Row 2: **Place (Ort)** and **Date (Datum)** side by side under Name, sharing the column width equally (a small gap between), so the two together end where Name ends.
   - Row 3: **Signature (Unterschrift)** underneath Place and Date, the full column width (the same width as Name), tall enough to sign in (about 12-15 mm).
   - Result: Name, the Place+Date pair and Signature all share the same left and right edges (one tidy block, no ragged right edge). Name, Place and Date are single-line height; consistent row spacing; labels bilingual as now.
   - Use named constants (column fraction of usable width, gap, signature height) so it is easy to tweak. If the one-third column leaves Place or Date too narrow for a typical value ("Frankfurt am Main", "25.10.2026") at the field font size, tell me and propose the smallest adjustment instead of silently widening.
3. Keep everything fillable in a PDF viewer (AcroForm text fields for Name, Place, Date; the existing signature field or box for Signature), tab order Name, Place, Date, Signature, and still usable printed and signed by hand. Use named constants for the widths (fraction of usable width) so they are easy to adjust.
4. Layout check: the block must not split across pages. Also review the current page break: the disclaimer and signature block sit alone on page 2 of the sample export while page 1 holds the table; if the table leaves room on page 1, the whole block (disclaimer + fields) should follow on the same page, otherwise the whole block moves together, with at least the last table rows kept with it if that is simple.
5. **Tests**: pypdf shows fields Name, Place, Date, Signature on the Tax summary PDF and none on other reports; Name and Signature widths are equal and <= 1/3 of the usable width; Place and Date have equal widths, their combined span (with gap) equals the Name width; left edges of Name, Place and Signature coincide; field order as above; English and German; block on one page; existing tests still pass, CSV/HTML unchanged. Render the page to an image and look at it, report real results.
6. Update docs/reporting.md (and the ADR) for the new layout; a new German term only if needed, via docs/glossary.md.

Report in the usual end-of-phase format, then STOP.
