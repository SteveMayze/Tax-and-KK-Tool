# ADR 0024: Close-out of the Australian statements (Phases 21 to 23)

Status: accepted (Phase 24, 2026-10-20; owner answer: collisions with rows already entered by hand or from CSV are reported only; any deletion is a separate decision by the owner).

## Decisions recorded from Phases 21 to 23
1. **Rental statements (ADR 0021):** one row per statement, gross = rent received, expenses = the listed costs and sundry fees (council and water rates included), payment date = statement date, income period from the paid-to dates, organisation from the setting `DJANGO_RENTAL_ORGANISATION` (the managing agent), the owner withdrawal is a notice only.
2. **MECU (ADR 0022):** one row per interest credit, bonus interest and term-deposit interest, gross/withholding from the memo lines (gross - withholding = credit), term-deposit interest from the term-deposit section only, years from the statement date, every balance proved; the one-entry cross-reference defect is repaired in memory (pikepdf was evaluated and not adopted, see ADR 0022).
3. **Ord Minnett (ADR 0023):** interest rows are made by the reader's batch step with exact-repeat dedupe across overlapping monthly and financial-year statements and pairing of the withholding debit by calendar quarter; sales are never imported.
4. **Common mechanisms:** readers claim files by structure; a reader may have a batch step (`settle`) run before files are classified; notices carry dates only; the fingerprints are those listed in `docs/imports.md`.

## Close-out checks (Phase 24)
- The inventory over the three folders shows no refused file: rental 11 staged; MECU 24 staged (two file names carry each other's month, flagged); Ord Minnett 8 staged and 17 nothing to import (5 files carry notices; the financial-year statements overlap the monthly ones by design).
- `tools/collision_report.py` was added (read only, counts only). On the owner's database all 11 rental rows and 8 of 8 Ord Minnett rows already exist exactly; 8 of the 27 MECU rows exist exactly, 19 have no counterpart (the hand-made CSV did not hold bonus interest and term-deposit interest); a few database rows of the MECU and Ord Minnett organisations have no exact staged counterpart.
- The Phase 14 samples give identical rows through the registry (new local test `core/test_sample_regression.py`, because the Phase 14 local tests look in a folder that no longer exists and have been skipping since the samples were reorganised).

## Consequences
Nothing in the owner's data is modified. The rows in the database that have no exact counterpart (MECU, Ord Minnett) are the owner's to inspect; the review flags exact collisions as duplicates when the PDFs are imported. All open rules items are consolidated in `docs/rules/README.md` item 20.
