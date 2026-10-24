# ADR 0033: Broker fund income as Interest, and the broker in the organisation

Status: accepted (Phase 32, owner decision 2026-10-24). Supersedes in part ADR 0018 and ADR 0019 ("fund income is category Dividends", organisation = the printed name) and rules README items 12 and 15 (edited in place, status still unverified). A recording choice only: no tax or SBK rule is implemented or decided.

## Context
The same security can appear at both brokers, and money-market fund income is interest-like. The owner edited stored payments by hand (organisation prefixed with the broker; fund income recategorised as Interest). The duplicate rule in `imports.py` compares (payment date, lower-cased organisation, currency, gross), so an importer that kept the old names would not recognise those payments on a re-upload and would double the income.

## Decision
- **One helper** in `core/services/organisations.py`: `broker_organisation(broker, tidied_name)` and `broker_category(is_fund)`, with the constants `ETRADE = 'E*Trade'`, `FIDELITY = 'Fidelity'`, `FIDELITY_ABBREVIATION = 'FID'`. Only the two broker readers call it; `tidy_security_name` is unchanged for every reader.
- **Names:** `E*Trade <name>` / `Fidelity <name>`, single spaces. A first word equal to the broker (any case) is not doubled and takes the owner's spelling; for Fidelity a first word `FID` is replaced by `Fidelity`; `FID` inside a word or later in the name is untouched.
- **Categories:** core money-market fund (E*TRADE `Dividend`, Fidelity `is_fund`) is `Interest`; company stock stays `Dividends`. Frequency, comments and withholding unchanged. The category exists in the seed; no migration.
- **Fund change:** two core funds in one upload give two names and two rows, never merged.
- **Settlement (Fidelity)** matches tax postings by the normalised printed security name, not by the final organisation string, so the prefix does not affect it.
- **Income summary (Fidelity):** the total is also found when the heading shares a printed line with other text (two statements of a fund change); a disagreeing total still refuses, a statement with no summary still gives the notice.
- **Stored payments** are never touched by code. The owner's expected-results files hold dates and amounts only, so they need no change.

## Consequences
Existing tests changed only in names and categories (see the Phase 32 report). Reports use the new category through the existing configuration; the SBK treatment and tax income type of the category `Interest` apply to this income from now on, which the owner should check (open, unverified). A payment still stored under an old name will not be flagged as a duplicate of a re-import.
