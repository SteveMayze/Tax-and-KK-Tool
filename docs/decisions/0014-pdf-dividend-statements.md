# ADR 0014: PDF extraction for Australian dividend statements

Status: accepted (Phase 14, 2026-10-19; owner answers: mostly statements, sometimes quarterly or yearly reports; OCR out of scope; record only the dividend paid, no franking detail, and no withholding tax is expected for Australian securities).

## Context
The owner supplied 54 text-based dividend and distribution advices from about 16 issuers (registries: Computershare, MUFG, Automic, company-specific) plus bank-account PDFs (Revolut). The figures needed are the same everywhere; their arrangement in the extracted text is not (labels before values, one value per line, column headings above a totals row, dates above or below their labels).

## Decisions
1. **Library: pypdf 6.21.1**, pure Python with no dependencies, pinned in `requirements.txt`. Text layer only; scans are refused ("OCR is not supported"). Nothing is sent to an external service.
2. **What is read:** payment date, ASX code, total payment (gross), amount paid (net), withholding tax. Franking information is ignored on purpose (owner decision).
3. **Anchors, not per-company parsers.** The reader looks for labelled net payment, the largest figure of the holding table (the total is never smaller than its parts), labelled withholding, payment date (inline, or labels first with the dates later or earlier, mapped by label order), the ASX code, plus two column layouts (Australian tax deducted, total net distribution). Several anchors for the same figure must agree. This read all 54 supplied statements with the right figures, with four deliberate refusals (below).
4. **Withholding = gross - net**, accepted only when a withholding-tax line states the same amount. It is never assumed zero. (All 54 supplied statements: 0.)
5. **Refusals are specific.** Scheme consideration (CSR takeover payment) and bonus share plan statements (NAB) are recognised and refused with advice; every other failure also refuses with the reason and stages nothing. Statements uploaded together are staged individually; the refused ones are listed as warnings.
6. **Staging is shared with CSV.** New `ImportRow.source_name` and `provenance` (page and sanitised source line per field), `ImportBatch.kind`; the zip of originals (or the single PDF) is the protected download. Organisation = ASX code, category `Dividends`, frequency `one_off`, currency `AUD`; the owner can change any of them per row.
7. **Dividend reinvestment plans** (Woolworths) are staged with a comment, because the dividend is still paid and is income; the owner can exclude the row. Whether reinvested dividends count for SBK is not decided (unverified, like the other loss/credit questions).
8. **Tests** build synthetic PDFs by hand (`core/test_pdf_support.py`) that imitate each layout's structure with invented figures worked out in the test file. An optional local test reads the real samples when present and checks consistency without printing amounts.

## Consequences
New layouts for new issuers will often work unchanged; when one does not, it is refused with a reason rather than misread. Adding a refusal reason or an anchor is a small change plus a synthetic fixture.
