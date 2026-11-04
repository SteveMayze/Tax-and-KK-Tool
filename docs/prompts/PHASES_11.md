# PHASES_11.md: Tax and Healthcare Tool, Phases 40 to 42 (adviser report: income as recorded, with sources)

Save this file as `docs/prompts/PHASES_11.md`. **Do not edit or overwrite `PHASES.md` to `PHASES_10.md`.** If you find an error in them, record it in your end-of-phase report. Phases 1 to 34 are implemented (Phase 20 deliberately not) and the app is in production.

How to use: open a session in the `Tax-and-KK-Tool` repo and say "Read `docs/prompts/PHASES_11.md` and `CLAUDE.md`. Do only Phase 40" (then 41, 42). One phase per session, then stop and report.

**These phases are independent of `PHASES_10.md` (storage on /u01 and PostgreSQL), which is ON HOLD until this report is accepted by the tax adviser.** Do not start, continue or rebase onto any Phase 35 to 39 work. Phase numbers 35 to 39 and ADR 0035 stay reserved for it; this file uses phases 40 to 42 and ADR 0036 onwards (verify the sequence). Keep the code database-agnostic (ORM only, no raw SQL, no SQLite-specific behaviour) and reach stored files only through `core/services/import_files.py` (`locate`), never by building a path, so the later move of the upload directory and of the database is not affected.

## Why these phases

The owner took the PDF "Tax information summary" for 2025 to the tax adviser, who could not work with it. The report tries to be too clever about German tax law and its figures cannot be traced back to their source:

1. It groups payments by the category's `tax_income_type` mapping (labels such as "Other income, e.g. pensions (section 22)", "Capital assets (section 20)") and by an **inferred country** (`effective_country`, which takes the country from the payment currency when the organisation has none; the report even carries a flag saying so). The owner has no pension in Australia or Germany for 2025, yet the "pension" row holds payments from four countries. The adviser sees a label that does not match the source.
2. Interest, dividends and capital gains (profits from sales of shares) are not shown as such.
3. German income is in the report, but the adviser handles it separately. There is no way to leave it out.
4. Withholding tax appears only as one EUR column "information, not credited".
5. There is no reference to the originating statement, and the statements are not delivered with the report.

The fix is to report **what is recorded, in the categories the owner records it in, per original currency, with the taxes withheld and the source documents**, and to leave every legal interpretation to the adviser. This is a change to one report. It is not a tax rule and it is not a classification: the tool still decides nothing about what is taxable, exempt or creditable.

## Standing rules

1. Read first: `CLAUDE.md` (all of it applies: Decimal only, keep originals, state the basis of every figure, never guess a legal or SBK rule, no real network in tests, synthetic test data only, no inline `style=`, CSS tokens only, `.btn` classes, translated strings, no new JS framework), `docs/reporting.md`, `docs/imports.md`, `docs/glossary.md`, `docs/rules/README.md` and `income-tax-rules.md`, ADR 0011, 0012, 0013, 0014, 0015, 0029, 0031, 0033 and 0034, and the code named in each phase.
2. One phase only, in order. End with the end-of-phase report (what was done, key decisions, files changed, checks with real results, deviations, open issues, how to verify by hand, proposed next scope) and **stop for "go"**.
3. **Ask first.** Put the phase's questions in your first reply together with what you found when you verified the current state. If unanswered, use the stated default, say so at the top of your work and continue.
4. **Verify the current state.** This file was written from a read of the code and of the adviser-rejected PDF, not from running the code. Where it says "verify", read the code, say what you found and adapt if it differs.
5. **Do not overwrite or discard existing work.** Do not modify the owner's database, any stored payment, category, organisation or mapping, or any stored original. Read-only checks against the development database are allowed where a phase says so. Never invent financial data, rates, dates or classifications.
6. **Privacy (highest priority).** The owner's real category, organisation, security and file names, amounts and counts come only from the database at runtime. Nothing from the owner's data or from the rejected PDF goes into tracked files, test names, fixtures, docs, ADRs or commit messages: use invented names ("EXAMPLE BANK", "EXAMPLE MONEY MARKET FUND", "EXAMPLE STOCK CO"). Findings from the real data go into the conversation only. Review staged files before every commit.
7. **Unchanged behaviour stays unchanged.** Every page, report, CSV and PDF that a phase does not name is identical afterwards (add a golden comparison over a synthetic dataset for the other reports' HTML, CSV and PDF text), and existing tests stay green. Where a test must change, list it and say why. The SBK estimate, the tax checks and the policy code behind them (`core/services/policies/tax.py`, `docs/rules/`) are **not changed**.
8. **Acceptance criteria** are checkable statements, each needing a test or a demonstrated command. Report each as met, not met or not verifiable here, with evidence. Every corner-case id gets a test named after it.
9. **Deployment is untouched** (nothing under `infra/`, the Containerfile or the Makefile). No `make deploy`. No schema change: if you find you need one, stop and ask. No new dependency (reportlab, pypdf and the standard library `zipfile` are enough).
10. Update the documentation `CLAUDE.md` asks for, and add an ADR with the next free number (expected 0036; 0035 is reserved). Never delete an old ADR; a superseded decision is marked in the new ADR and in a one-line note at the top of the old one.
11. Language (Phase 12): all new text through gettext, English and German, `makemessages` and `msgfmt`, commit both. German terms come from `docs/glossary.md` section B; where a term is missing, propose one, mark it "proposed, awaiting the owner's review" (as ADR 0034 did) and list it in the report. CSV stays English.
12. Execution mode for all three phases: **[LOCAL]**. They need the owner's development data and stored originals to check against. Work on the branch of Q40.1.

---

## Phase 40: Rework the report content and add the currency filter

### Goal

The report with key `tax_summary` (title "Tax information summary", same URL, CSV and PDF routes, signature block and notice of ADR 0034 unchanged) is rebuilt so that it shows **income as recorded**:

- grouped only by **stored category name**, **stored organisation name** and **original currency**;
- with **interest, dividends and capital gains** visible under their own category names whenever payments exist;
- with **taxes withheld** shown as their own section, in the original currency and in EUR;
- filterable by **original currency** (include or exclude), in addition to the Phase 30 organisation and category filters, so that German income (EUR) can be left out.

Source references and the package are Phases 41 and 42. In this phase the payment list has no source column yet.

### What the report must show (replaces the current table)

Verify how `Report`, `Column`, `_display`, `report_csv` and `report_pdf` handle a report with more than one table; make the **smallest extension** that lets this report carry several titled tables, each with its own columns, rows and totals. Every figure is computed in a service, never in a template or in the PDF layer (financial principle 2).

**Basis block** (above the tables): period; "Income as recorded; no tax classification, no country inference, no treaty or credit rules applied"; amounts are **gross as recorded** and **withholding tax as recorded**; EUR at each payment's stored rate with the existing rate-basis line (counts per source of rate) and the count of unconverted payments left out of EUR totals; the `Filter` row (see below); the names of active categories that have no payment in the selection; a note that amounts are the stored values and a payment edited after import may differ from its statement; rounding line as today.

**Table 1: Income by category and currency.** One row per (category, original currency): category (as stored) | currency | payments | gross (original currency) | of which negative payments (original currency) | withholding tax (original currency) | gross EUR | withholding tax EUR | unconverted payments. A subtotal line per category in EUR only (original-currency amounts are never added across currencies). Order: category name, then currency.

**Table 2: Income by organisation.** One row per (category, organisation, currency) with the same amount columns. No country column. Order: category, organisation, currency.

**Table 3: Taxes withheld.** Only payments whose recorded withholding is not zero, grouped as in Table 2, with original-currency and EUR amounts, and a total per currency and in EUR. A note says: "Withholding tax as recorded from the statement. A zero or a missing row means none is recorded, not that none was withheld. Not credited; no treaty or foreign-tax-credit rule is applied."

**Table 4: Payments.** One row per payment, ordered by payment date then organisation then id: date | category | organisation | currency | gross | withholding | rate | rate date | rate source | gross EUR | withholding EUR | kind (normal, correction, reversal) | comment. Corrections and reversals are listed as they are stored.

**Notes and signature block:** the notice and the signature block of ADR 0034 as they are. Keep only those of the current "Not applied" lines that are still true for the new content (treaties and foreign-tax credit not applied, withholding not credited, conversion basis not verified against what the authorities require, losses shown as recorded and not netted, no tax calculated); remove the lines about Anlage mapping, "policy tax-information 1.0" and income-type grouping, because this report no longer uses them.

**Not shown:** `tax_income_type`, `sbk_treatment`, any "section" or "Anlage" wording, the organisation country, the inferred-country flag. Capital gains are shown only if payments exist in the category; nothing is derived from share sales (README item 16: sales are not imported).

### The currency filter

Extend `ReportFilter` (`core/services/report_filter.py`) with `currency_codes` (tuple of upper-case ISO codes) and `currency_mode` (`include` or `exclude`), applied once in `ReportFilter.apply` by the payment's **original** `currency`. Parameters: `currency=EUR&currency=USD` (repeatable) and `currency_mode=include|exclude`. Semantics: ticked codes with mode include show only those currencies; with mode exclude hide them; nothing ticked is no restriction in either mode. The currency group is combined with organisation and category by AND. The `Filter` basis row, the CSV `Filter` row and the PDF basis say which codes and which mode, and state: "Filtered by the payment's original currency, not by country or source; a payment in an excluded currency is left out of every table, whatever its source." Options in the form: every currency with at least one payment (any year), each with its payment count for the selected year, one query.

### Questions for the owner (defaults in brackets)

- **Q40.1 Branch.** [Default: `git switch -c feature/adviser-report` from `main`; commits on that branch only; no merge, no push unless I say so, no deployment.]
- **Q40.2 Replace or add.** [Default: replace the content of the existing `tax_summary` report; same key, URL, title and file names. The old grouping by income type is no longer reachable from the reports; the policy code stays because the SBK estimate and tax checks use it. Verify who else calls `tax_summary_rows`, `POLICY_VERSION` and `NOT_APPLIED` and report; delete nothing.]
- **Q40.3 Where the currency filter shows.** [Default: its form group (check boxes plus two radio buttons "Show only the ticked currencies" / "Hide the ticked currencies", default "Show only") appears on this report only. The parameter is parsed by the shared filter and, wherever the shared filter is applied, it is honoured and described in the `Filter` row; with no currency parameter nothing else changes. Say what you verify about the other reports and the reports index page.]
- **Q40.4 Columns.** [Default: as listed above; expenses and net amounts are not shown (rental costs are deferred by the owner, README); the payment comment is included in Table 4 because it carries the statement's own wording (for example named withholding lines). Say if a column does not fit the landscape page at the smallest font; then propose the narrowest change.]
- **Q40.5 Empty categories.** [Default: categories with no payment in the selection are named in one basis line, not shown as zero rows.]
- **Q40.6 CSV.** [Default: the CSV of this report is the payment-level table (Table 4) after a header block with the basis and `Filter` rows, with the category-by-currency totals in a second block. Verify how the CSV format version is defined; if it is per file type, raise it for this report only and document it; if it is global, ask.]
- **Q40.7 German terms.** [Default: from `docs/glossary.md`; proposed terms flagged as in ADR 0034.]

### Part A: verify and explain (read only, report in one message before changing code)

1. Read and summarise: `policy_reports.tax_info_summary`, `policies/tax.py` (`tax_summary_rows`, `effective_country`), `report_filter.py`, `reports._payments`, `report_csv.py`, `report_pdf.py`, `views_reports._build` and its routes, `_report_filter.html` and `_filter_group.html`, the aggregation services, and the tests `test_report_pdf.py`, `test_report_filters.py`, `test_policies_tax.py`, `test_breakdown.py`, `test_loss.py`, `test_visual.py`, `test_assessment_views.py` (which assert the current table).
2. **Why the "pension" row had payments.** Against the development database, **read only**, for calendar year 2025: list (in the conversation only; category and organisation names are allowed there, amounts are not needed) which categories feed each income-type row of the current report, how each category is mapped, and which organisation countries were set or inferred. Say which category or mapping put the payments under the section-22 label, and that nothing was changed. If the answer is a mapping the owner may want to correct for the SBK estimate or the tax checks, say so as a separate remark; this phase does not change mappings.
3. State whether any category named like capital gains has payments in 2025, and which categories could carry gains or losses (`may_be_negative`). Do not draw conclusions about tax.
4. Which parts of the current report's text will be removed and which kept.

### Corner cases (every id needs a test)

- **T1 Stored fields only.** On a synthetic dataset, changing a category's `tax_income_type` or `sbk_treatment`, or an organisation's `country`, changes no row, figure or label of this report (compare before and after).
- **T2 No legal wording.** The rendered HTML, CSV and PDF text of this report contain none of: "section", "§", "Anlage", "Einkunftsart", "pension" (as a label) or the TaxIncomeType labels, with a synthetic category named Interest that is mapped to the "other" income type.
- **T3 Sums.** For every (category, currency), the original-currency gross and withholding equal the sum of the payments listed in Table 4; EUR equals the sum of the stored EUR amounts; original-currency amounts of different currencies are never added.
- **T4 Interest, dividends, capital gains.** Synthetic payments in categories named Interest, Dividends and Capital gains each appear as their own rows with their stored names, in each currency they occur in.
- **T5 Empty categories named.** Active categories without payments in the selection are named in the basis line; a filter that leaves a category empty names it.
- **T6 Negative payments.** A negative payment in a `may_be_negative` category is shown signed in its own category and counted in "of which negative"; nothing is netted across categories; no loss rule is applied.
- **T7 Taxes withheld.** A payment with withholding appears in Table 3 with original and EUR amounts and a total per currency; a payment with zero withholding does not; the zero-means-not-recorded note is present.
- **T8 Currency include.** Mode include with one code lists only that currency in every table and total.
- **T9 Currency exclude.** Mode exclude with EUR removes every EUR payment from every table, total and count; the basis says so.
- **T10 Nothing ticked** is no restriction in both modes; **excluding every currency** gives the "no payments match" message, empty tables and totals of 0.
- **T11 Bad parameters.** Unknown, lower-case-only-invalid, over-long, or unsupported codes and an unknown mode give an error in the same style and place as the existing filter errors, never a 500, echoing at most 10 characters; repeated and lower-case valid codes are normalised to one URL.
- **T12 Combination.** Currency AND organisation AND category combine as in Phase 30 (OR within a group, AND between groups); the filter is applied once in `ReportFilter.apply`.
- **T13 Query string survives** through the year form, Show, Clear filters, the CSV and PDF links, the signature-block page and the language switch.
- **T14 Table totals agree.** The EUR totals of Tables 1, 2 and 4 are equal to each other and, for the same year and filter, to the totals of the existing aggregation services and of the payments page (oracle test).
- **T15 Unconverted and manual-rate payments** are listed and marked in Table 4, left out of EUR totals with the count stated, and counted in the basis.
- **T16 Corrections and reversals** appear with their kind.
- **T17 Other outputs identical.** Golden comparison: every other report's HTML, CSV and PDF text is identical to before on the synthetic dataset; the SBK estimate and tax check pages are untouched.
- **T18 PDF.** Landscape A4, header rows repeat on every page, the notice and signature block (name, place, date, signature fields) are unchanged and ADR 0034's tests stay green, "Page x of y" present; an organisation name with characters outside WinAnsi does not crash the export.
- **T19 No payments.** A year or filter with no payments renders all outputs with the message, not an error.
- **T20 Basics.** Login required, GET only, no state change, no inline `style=`, labels for every form control, form works without JavaScript, print hides the filter form.

### Acceptance criteria

- The 2025 report generated from the development database contains no income-type or "section" wording, no country, and shows each recorded category, currency and organisation with its withholding; excluding EUR removes all EUR payments from every table (checked by hand and reported with counts only).
- T1 to T20 pass; all earlier tests pass unchanged except those listed with a reason; no schema change; no file under `infra/` touched; no new dependency; no real name or amount in any tracked file.

### Stop and report

End-of-phase report as in the standing rules, plus: the answers to Part A, the list of changed tests with reasons, the German terms proposed, what the owner should look at in the new PDF, and a statement of whether the stored data contains any capital gains for 2025 (counts only).

---

## Phase 41: Source references for every payment

### Goal

Every payment in the report points to the **document it came from**, with a stable reference, and the report ends with an index of those documents. No document is delivered yet (Phase 42).

### What is stored today (verify; the file was written from a read of `models.py`, `pdf_imports.py` and `import_files.py`)

- `Payment.import_batch` (nullable, cleared if the batch is deleted completely) and `ImportRow.created_payment` link a payment to the staged row it came from. `ImportRow.source_name` is the **masked** display name of the file, and `ImportRow.provenance` holds per field the page and a sanitised source line.
- `ImportBatch` holds `file_name`, `sha256`, `kind` (CSV or PDF), `stored_path` (relative to `UPLOAD_DIR`; a **single PDF**, or a **zip of the originals** when several PDFs were uploaded together), `original_removed_at` (Phase 28, ADR 0029) and `description`.
- `Payment.source_document` and the `SourceDocument` model exist; verify whether anything fills them.
- Hand-entered payments have no batch. CSV payments have a CSV batch. Some Fidelity and Ord Minnett payments are settled across several statements of one upload (the withholding of one event may come from another file than the income line).

### What the report adds

- In Table 4 a **Source** column: the reference of the document and the page (for example `D03 p.2`), or `none` with the reason: "entered by hand", "CSV import", "batch deleted", "original removed".
- In Tables 2 and 3 a **Documents** column listing the references that make up each row.
- A final table **Source documents**: reference | organisation(s) | kind (PDF statement, CSV file) | file name as displayed (masked) | date first uploaded | SHA-256 (first 12 hex characters in the PDF, full in the CSV) | state of the stored original (stored, removed on date, not stored) | payments in this report. Basis line: the number of payments without a source document and why.
- The CSV carries the same references and the full hash.

### Questions for the owner (defaults in brackets)

- **Q41.1 Identity of a document.** [Default: one document is one PDF file, identified by the SHA-256 of its bytes (for a zip batch, of the member file); the same statement uploaded in two batches is one document. References `D01`, `D02`, ... are assigned per report in a fixed order (earliest payment date in the report, then masked file name, then hash) so the same selection always gives the same numbers.]
- **Q41.2 CSV batches.** [Default: listed as a source of kind "CSV file (your own import file)", with name and hash, but **not** treated as a supporting document in Phase 42, because it is the owner's own spreadsheet and may hold more than the report shows.]
- **Q41.3 Page numbers only.** [Default: the page from `provenance` is shown; the source line text is never printed in the report.]
- **Q41.4 Payments resting on more than one file.** [Default: if the data records every file a payment rests on, list them all; if it records only the row's own file, show that file and add the note "withholding may be settled from another statement of the same upload". Never guess.]

### Tasks

1. **Verify** the chain payment → import row → batch → stored original, for a single-PDF batch, a zip batch (how the member is found: by the stored member name or by `source_name`; whether two members can share one masked name), a CSV batch, a hand-entered payment, a batch with `original_removed_at` set and a payment whose batch was deleted. Report what is and is not recoverable, with counts for the development database (no names).
2. **Service** (new module `core/services/report_sources.py` or the place that fits; verify) taking a payment set and returning, per payment, its source reference(s) and, for the set, the document index. It resolves files only through `import_files.locate`, computes member hashes by reading the stored file (stream; no document text is read, logged or kept), and treats a missing file as state "not found", not as an error. ORM only.
3. Add the columns and the index table to the report (HTML, CSV, PDF) through the same display path, no figures or references computed in the PDF layer.
4. Tests, docs (`docs/reporting.md`, `docs/imports.md` one paragraph on how a payment is tied to its file), ADR.

### Corner cases (every id needs a test)

- **S1 Single PDF batch:** payment points to one document with its page.
- **S2 Zip batch:** each payment points to the right member; a member found by name; two members with the same masked name are told apart (hash), or the case is reported and the payments show "ambiguous" rather than a guess.
- **S3 CSV batch:** reference of kind CSV, not counted as a statement.
- **S4 Hand-entered payment:** `none: entered by hand`, counted in the basis.
- **S5 Original removed** (`original_removed_at` set, or the file missing on disk): the reference and index row remain with the state; the report still builds.
- **S6 Batch deleted completely:** `none: batch deleted`.
- **S7 Settled across files:** per Q41.4, tested with a synthetic Fidelity-style upload of two statements.
- **S8 Shared documents:** two payments from one statement share one reference; the same statement in two batches gives one reference.
- **S9 Deterministic numbering:** the same selection gives the same references twice; a changed filter renumbers only through the stated order, and the index lists only documents used by the payments in the selection.
- **S10 Privacy:** displayed file names are masked (digit runs of six or more); no source line text, no unmasked digit run and no stored path appears in HTML, CSV or PDF.
- **S11 Totals unchanged:** adding the source columns changes no figure of Phase 40's tables.
- **S12 Other outputs identical** (golden comparison as in Phase 40).

### Acceptance criteria

- Every payment row of the 2025 report shows a reference or a stated reason; the index lists each referenced document once; S1 to S12 pass; no schema change; no stored file, payment or batch is modified (check file hashes before and after, counts only).

### Stop and report

End-of-phase report as in the standing rules, plus the counts for the development database (payments with a source, by kind; without a source, by reason; originals present, removed or missing), so the owner knows before Phase 42 what the package can hold.

---

## Phase 42: PDF package with the originating documents

### Goal

From the tax information summary the owner can download **one package** for the adviser: the PDF report and, byte for byte, the original statements it refers to, with an index that ties them together.

### Package contents

A ZIP file `report-tax_summary-<year or all>[-filtered]-package.zip` containing:

- the report PDF, exactly as `/reports/tax_summary.pdf` produces it for the same parameters (interface language);
- a folder `sources/` with every referenced statement PDF **unchanged** (no repair, no redaction, no re-compression of content), named `<reference>_<masked file name>.pdf`;
- `index.csv`: reference | file name in the package | file name as displayed (masked) | SHA-256 | size | state | payments in the report. Headings in English;
- a short plain-text `README.txt` (English, or German in German mode): what the package is, that it is general information and not a tax calculation, how to verify hashes. No figures.

Only documents referenced by the payments **in the selection** are included, so excluding EUR also drops the documents that only support EUR payments. CSV batches are not included (Q41.2). A document whose original is removed or missing is listed in `index.csv` and in the confirmation page as missing and the package is still built.

### Questions for the owner (defaults in brackets)

- **Q42.1 Form of the package.** [Default: a ZIP as above. Alternatives, not built unless I choose them: (a) one merged PDF with the originals appended after the report, with bookmarks per reference; (b) the originals embedded in the report PDF as file attachments with pypdf. Both are larger risks for a viewer or the adviser's software to drop or fail on; say what you would recommend after trying the ZIP.]
- **Q42.2 Entry point.** [Default: a button "PDF with source documents" on the report page next to the PDF button, opening a **confirmation page** (GET) that lists the number of documents, the total size, the missing originals, the active filter, and a warning in plain language that the statements contain account numbers and other personal data and that the package leaves the app unprotected once downloaded; then a "Download package" link. No data changes, so GET is acceptable; login required.]
- **Q42.3 Size limit.** [Default: refuse above a configurable limit (`DJANGO_REPORT_PACKAGE_MAX_MB`, default 100) with a message that offers the report without sources. Verify the memory and disk available to the container in `docs/deployment.md`; build the zip into a temporary file that is removed after streaming, not in memory.]
- **Q42.4 File names inside the package.** [Default: masked names as displayed (Q41), prefixed with the reference. The hashes in `index.csv` let the owner match them to the unmasked originals.]

### Tasks

1. **Verify** the PDF route and `_build` in `views_reports.py`, how the response is streamed, `import_files.locate`, and how a zip member is read from a stored zip batch.
2. **Service** `core/services/report_package.py`: takes the same parameters as the report, builds the temporary zip, returns a streaming response helper and a summary (counts, size, missing). For each document it reads the stored bytes, **checks the SHA-256 against the recorded hash** (batch `sha256` for a single PDF; for a zip member, the hash computed when the reference was resolved) and refuses to include a file whose hash differs, listing it as "changed on disk, not included". It never writes into `UPLOAD_DIR` and never alters a stored file.
3. **Views and templates:** the confirmation page and the download route (login, GET, `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, `Content-Disposition: attachment`), buttons with visible text, translated strings (English and German), no inline `style=`.
4. **Tests,** docs (`docs/reporting.md`, `docs/deployment.md` one paragraph on the size limit and temporary file), ADR (package form, the personal-data warning, the hash check, what was rejected and why).

### Corner cases (every id needs a test)

- **K1 Contents.** The zip holds the report PDF, `index.csv`, `README.txt` and one file per referenced statement; each original is byte-identical to the stored file (compare SHA-256) for a single-PDF batch and for a member of a zip batch.
- **K2 Hash mismatch.** A stored file changed on disk is not included, is listed as changed, and the page and `index.csv` say so.
- **K3 Missing or removed original.** Listed as missing; the package is still built; the confirmation page lists them before download.
- **K4 Filter applied.** Documents that support only excluded payments are absent; the report PDF in the package equals the PDF route's output for the same parameters (compare the extracted text).
- **K5 Safe names.** Package member names are generated by us from the reference and a sanitised masked name; a stored name with path separators, `..`, control characters or very long text cannot escape the folder or collide (zip-slip test).
- **K6 Size limit.** Above the limit the download is refused with the message and the report-only link; the temporary file is removed after both a normal and an interrupted download.
- **K7 Nothing to package.** A selection with no referenced statements offers the report PDF only and says why; no empty zip.
- **K8 Confirmation page.** It shows counts, size, missing originals, the active filter and the personal-data warning; it prints no document text, no unmasked digit run and no stored path.
- **K9 Read only.** Stored files, import batches and payments are unchanged after a download (hash and count comparison); `UPLOAD_DIR` gains no file.
- **K10 Language.** English and German confirmation page, `README.txt` and report PDF; `index.csv` headings stay English.
- **K11 Basics.** Login required, GET only, other users or anonymous get the login redirect, response headers as above.
- **K12 Other outputs identical** (golden comparison as in Phase 40).

### Acceptance criteria

- With the development database and its stored originals, the 2025 package opens, the originals match their recorded hashes, and the references in the report PDF match the files in `sources/` (checked by hand and reported with counts only).
- K1 to K12 pass; no schema change; no stored file modified; nothing under `infra/` touched; no new dependency.

### Stop and report

End-of-phase report as in the standing rules, plus: the size of the 2025 package and how long it took to build on the development machine, what the owner must check before handing it to the adviser (the personal data in the statements), and whether the on-hold Phases 35 to 39 are affected in any way (they should not be). Then wait for "go".
