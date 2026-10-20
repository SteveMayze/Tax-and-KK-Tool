# ADR 0027: Joint account close-out

Status: accepted (Phase 27, 2026-10-20; owner answer by the stated default: collisions with rows of the earlier project are reported only, any deletion is the owner's decision).

## Decisions
1. **Collision report.** `tools/collision_report.py` gets a joint-account section (folder `RVB-joint`, EUR). It reads the statements through the registry (so it needs the rules and the rent category in the database, and uses the account printed on the first statement when `DJANGO_JOINT_RENTAL_ACCOUNT` is not set) and reports counts only: exact collisions (the review's duplicate rule), near collisions (same gross within 3 days under another organisation among EUR rental payments, or same date and organisation with another gross), staged rows with no counterpart, and database payments of the same organisations within the staged date range with no exact staged counterpart. `--no-file` skips writing `local/exports/collision_report.txt`. Nothing is changed or deleted. Tested with synthetic data (`core/test_collision_report.py`): the output contains no name, amount, category or account number.
2. **Inventory.** `tools/pdf_inventory.py` over the joint folder is the acceptance check: no refused file, no balance or period gap, no file-name/period mismatch. A refusal because the rent category does not exist yet is expected until the owner creates it.
3. **No change to earlier readers.** The Phase 14 to 24 tests and the sample regression test pass unchanged.
4. **Open rules items** are consolidated in `docs/rules/README.md` items 22 and 23 (joint rental income: tax and SBK treatment of the shared rent; rental costs deferred; the category mapping and the share are the owner's).

## Consequences
Run on the owner's statements (counts only): 21 statements read, none refused, a gapless chain, 23 rent rows staged, 1 credit left out with a notice for the owner to handle, no collisions with payments already in the database. Whether the owner's two rules are complete is for the owner to check against the staged rows.
