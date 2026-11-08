# ADR 0044: HUB24 pension credits on the MECU statements

Status: accepted (branch `fix/mecu-hub24-pension`, 2026-11-08). Amends ADR 0022 (MECU yielded interest only). Prompt: `docs/prompts/FIX_MECU_HUB24_PENSION.md`.

## Context
The owner's Australian superannuation pension is paid by direct credit into the MECU everyday account (`Direct Credit Hub24 Custodial - <reference>`). The reader balance-proved every Direct Credit and then skipped it silently, so no pension was ever staged and no notice told the owner. The outgoing `BPAY Payment To Hub24 ...` debits (contributions) are not income. The bank line shows only the net amount credited: no gross, no tax, no period, no frequency.

## Decision
- **Recognition by words** (constant `PENSION_PAYERS` in `mecu_account.py`): the description starts with "Direct Credit" and contains "Hub24" (case-insensitive, spaces normalised). No reference or account number is in code, tests or logs. All other Direct Credits are skipped as before; `BPAY Payment` stays in `NOT_INCOME`.
- **Shape (option A):** one row per credit, organisation `HUB24`, category `Pension`, AUD, payment date = Effective date, gross = net = the credit, withholding 0, expenses 0. The fund's costs and tax belong to the fund and are not attributed to a payment, so nothing is estimated or split. The comment says so. The owner can correct gross/withholding in the review step.
- **Frequency: all rows are staged `monthly`.** The reader sees one statement at a time and cannot know whether a credit is the earliest ever seen; "earliest is one-off" would need hidden state. The owner changes the June 2026 back payment to `one-off` in the review.
- **Direction:** the running-balance proof is unchanged; a HUB24 line that is a debit refuses the statement, naming its first words.
- **Annual summary (M6)** still compares interest only: Pension rows are excluded from its sums.
- **Rules register:** open item 24 (unverified, nothing implemented).

## Consequences
No schema change. Existing payments are never modified; re-uploading an already imported statement is allowed (a committed batch of the same file only adds a warning) and row-level duplicate detection skips the interest rows already held. `tools/collision_report.py` reports the staged Pension rows against the database (counts only).
