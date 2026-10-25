# Prompt for Claude Code: landscape PDF export of reports, with signature block on the Tax Summary

Read CLAUDE.md, README, docs/reporting.md, docs/glossary.md, docs/decisions/ and `git log` first. Work as one new phase (next free phase number; add an ADR). Follow the "How to work" rules: confirm scope, list assumptions and blocking questions, propose steps, then STOP for my approval before coding.

## Goal
Reports currently export as HTML (screen/print) and CSV (`/reports/<key>.csv`, `core/views_reports.py`, `core/services/report_csv.py`). Add a **PDF export in landscape A4**, downloadable from every report page and the reports index, with the **Tax information summary (`tax_summary`) as the priority**.

## Requirements

1. **PDF for all reports** (`/reports/<key>.pdf?year=...&organisation=...&category=...`, same parameters, validation and error/redirect behaviour as the CSV route). Same data path as the page and CSV (`_build` / `REPORTS`); no figures calculated in the PDF layer. Landscape A4, repeating table header rows, page numbers ("Page x of y"), report title, generation date, the full **basis block** (period, filter, currency, gross/net, rate basis, exclusions, rounding) before the table, notes below it, wide tables (e.g. `cross`, `sbk`) must fit or split sensibly across pages. Follows the interface language (English/German) like the HTML page, with German terms only from `docs/glossary.md`; the filename is language-independent, like the CSV's (`report-<key>-<year or all>[-filtered].pdf`). Generated on demand, streamed to the logged-in user, nothing written to disk, never served as static; same headers as CSV (`Cache-Control: no-store`, `nosniff`), `login_required`, GET only.

2. **Tax summary only: signature block at the end of the last page** (kept together, never split from the last table rows or orphaned onto its own page without at least the closing disclaimer). Three labelled lines with room to write or sign:
   - Ort / Place
   - Datum / Date
   - Unterschrift / Signature
   Labels in the active language, with the German term (Ort, Datum, Unterschrift) always shown (bilingual label in English mode, e.g. "Place (Ort)"). The fields must be **fillable in a PDF viewer**: use real AcroForm fields (text fields for Ort and Datum, a signature field or at least a generous blank signature line/box for Unterschrift) so a signature can be added with Preview, Acrobat or similar. They must also still work when printed and signed by hand. Pre-fill nothing (the owner's name and address are personal data and must not come from code or tracked files; if a name line is wanted, leave it blank).

3. **Disclaimer, Tax summary PDF only (and short form on all other PDFs)**: a clearly visible boxed notice, on the first page near the title AND repeated above the signature block, stating in substance (English and German text via gettext, German wording to be proposed by you for my review):
   - This report must not be used on its own. It must be read together with the respective tax assessment (Steuerbescheid) / tax return (Steuererklärung).
   - It shows **gross income** as recorded in this tool; it does not take into account all taxes, deductions, withholding, costs or individual circumstances, and the figures can differ from the assessed ones.
   - It is a general information summary, not a tax calculation, tax advice or an official assessment.
   Other reports get a one-line footer version ("General financial summary, not an official assessment or tax calculation") consistent with the existing CLAUDE.md statement.

4. **Keep it simple and consistent with the project**: Django, no JS framework, no extra services. Evaluate the PDF library options and recommend one before coding, with trade-offs and any effect on `requirements.txt`, the `Containerfile` and the Ansible/Podman deployment (e.g. WeasyPrint needs system libraries such as Pango; reportlab is pure Python and supports AcroForm fields; browser print-CSS `@page { size: A4 landscape }` needs no dependency but cannot create fillable fields). Check the current version's compatibility with the pinned Python/Django, how it handles fillable and signature fields, and its licence (add to `docs/third-party-notices.md`). Pin the version. If two options are viable, ask me which to use.

5. **UI**: a "PDF" `.btn` link next to the CSV download on report pages (and per report on the index), translated `aria-label`/title per the icon rules, colours via existing CSS tokens, no inline `style=`. Optionally also add a print stylesheet (`@page` landscape) to the HTML report page if cheap; say so if you skip it.

6. **Tests** (run them and report real results): PDF route returns `application/pdf` with a valid PDF for every report key; login required; bad year/filter gives the same error and redirect as CSV; filtered file name; landscape page size; Tax summary PDF contains the disclaimer text and the Ort/Datum/Unterschrift labels and the form fields (inspect with pypdf); other reports contain no signature block; English and German variants; empty result and multi-page table cases; no personal data in output beyond what the report already contains; the existing CSV and HTML outputs are byte-for-byte unchanged (CSV format version stays 2).

7. **Docs**: update `docs/reporting.md` (new route, behaviour, disclaimer, signature block), `docs/glossary.md` for the new German terms, add the ADR, update `CLAUDE.md` UI/reports lines briefly, README if it lists exports.

## Constraints
- Never invent tax rules or numbers; the PDF shows exactly what the report shows.
- Do not change report calculations or the CSV.
- Ask me if any wording of the legal disclaimer or German terms is uncertain.
- End-of-phase report in the usual format (implemented, decisions, files changed, real check results, open issues, how to verify, proposed next phase), then STOP.
