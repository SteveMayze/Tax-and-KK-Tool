# ADR 0015: PDF reader registry and multi-row results

Status: accepted (Phase 15, 2026-10-20; owner answers: organisation = the payer, fixed bank names, one shared name tidier, RVB payment date = booking date, money-market-fund income = Dividends, "nothing to import" as one summary line, no batch when nothing is staged, new upload message).

## Context
Phase 14 read one payment per statement with an `if` chain in `pdf_imports`. The next phases read bank and broker statements that hold from zero to about ten income events, so staging, reader selection and the review needed to change before any new institution is added.

## Decisions
1. **Registry** (`statement_readers.READERS`): ordered `Reader(id, recognises, parse, needs_layout)`. Exactly one reader may claim a file; two claims refuse the file naming both ids (no document text); no claim refuses it as unrecognised. A reader is added by adding one entry. The Phase 14 readers keep their modules and public functions; thin adapters wrap `Dividend` and `FundReturn`. The dividend reader gained `recognises()` (dividend/distribution wording plus Australian-dollar markers, or the two kinds it refuses with advice); `AUD` is matched as a whole capitalised word so that the word "audit" in a US statement does not make it look Australian.
2. **Result type** `StatementResult(rows, notices, fingerprint, period, not_imported)`. No rows and no exception means nothing to import; `not_imported` marks "recognised and not imported".
3. **Staging** stores every row with per-row source name and provenance and batch-unique line numbers. Nothing to import and not-imported outcomes are summary lines with counts in `ImportBatch.warnings`; if nothing is staged and nothing was refused, no batch is created (`NothingToImport`, shown as a success message). Mixed refused/no-income uploads with nothing staged are an error that also states the no-income count.
4. **Fingerprints** (reader id + hash of identity fields) identify the same statement across different bytes. Revolut: currency, period end, earned return, fees. Dividend advices: none, to avoid hiding two real holdings that paid the same amount; the row duplicate rule remains the second defence.
5. **Layout extraction:** `extract_pages(raw, layout=False)`; layout text is extracted lazily, only when a registered reader needs it. Amount parsers for the US, UK and German (H/S) conventions live in `amounts.py` and raise ValueError rather than guess.
6. **Masking:** digit runs of six or more are masked in displayed file names and batch names (stored as masked in staging; the stored original keeps its bytes) and, as before, in source lines.
7. **Organisation strings:** `organisations.tidy_security_name` (the former Phase 14 tidier, moved, behaviour unchanged) is the single function for printed security names; fixed bank names sit in `BANK_ORGANISATIONS`. No company or fund names from the samples are in the code.
8. **Encrypted PDFs:** an empty user password is tried; AES files cannot be opened without the `cryptography` package and are refused with a message saying so. No dependency is added in this phase (see Consequences).
9. **Inventory** (`tools/pdf_inventory.py`, logic in `core/services/pdf_inventory.py`) reports structure only, with no database access.

## Consequences
- Verified on the owner's samples: the 87 supplied Australian-dividend and Revolut files give identical rows (and identical refusals) through the registry as through the Phase 14 code.
- **Open: all 23 RVB statements are AES-encrypted** (open without a password in a viewer). Phase 17 cannot read them until either the `cryptography` package is added to the pinned requirements or the files are re-saved unencrypted. This needs the owner's decision (CLAUDE.md: no unneeded dependency).
- Old Phase 14 behaviour kept: a Revolut fund statement with zero return is still refused (reason: nothing to import) rather than reported as "nothing to import"; changing it would alter a Phase 14 reader.
