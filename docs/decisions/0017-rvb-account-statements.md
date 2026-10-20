# ADR 0017: RVB current-account statements

Status: accepted (Phase 17, 2026-10-20; owner answers: payment date = booking date; withholding = Kapitalertragsteuer + Solidaritätszuschlag + Kirchensteuer (if booked) in one field with each tax and its amount named in the comment; prize credits are a notice (the owner believes lottery prizes are not taxed, unverified); fees exist on other RVB and Revolut accounts but not on the downloaded one).

## Context
23 monthly statements (2 pages, AES-encrypted with an empty user password, opened since `cryptography` was added in Phase 16). Seven are quarterly interest closings, two of which book tax. All others hold transfers, standing orders and a monthly savings-lottery credit. Two statement numbers exist twice (same text, different bytes). The default pypdf mode splits the "alter Kontostand" amount onto its own line; layout mode keeps it with its label.

## Decisions
1. **Reader `rvb_giro`, `needs_layout=True`**, recognised by one alter and one neuer Kontostand row with H/S amounts. Header and bank name are not used (G8, R5).
2. **Every statement must close arithmetically** (alter + credits - debits = neuer); otherwise it is refused. Statements without an interest closing then return no rows ("nothing to import") with notices.
3. **Booking classification by text only to exclude non-income:** Gutschrift, Umbuchung, Dauerauftrag, Überweisung variants. A Gutschrift with "Gewinn" or "Los" in its detail lines is a prize notice; other credits get their own notice. Any other text refuses the statement naming it (G12), which also means fee lines are refused until a real example exists.
4. **Closing:** gross = sum of the HABENZINSEN lines = booked "Abschluss lt. Anlage 1" amount = "Summe Abschlussposten"; the tax lines of the block must equal the booked tax lines; the stated base (under the Kapitalertragsteuer booking and in the block) must agree and not exceed the interest. Any other amount line in the block (a possible fee) refuses the statement. The samples show the booked closing amount equal to the gross interest, with tax booked separately, so net = gross - expenses - withholding.
5. **Row:** booking date as payment date (year chosen closest to the statement date; value date in the comment), income period from the block, quarterly, EUR, Interest, fixed organisation. The comment states each tax with its amount and "Tax charged on <base> of the <gross> interest". The app never infers an exemption order.
6. **Fingerprint:** statement number, year, closing balance, closing date. **Continuity** (balances only; statement numbers restart each year) is computed over all recognised statements, not only those with rows, which required moving the staging's continuity input from "staged" to "recognised".
7. **Notices** are grouped: the same text from several statements is one line with a count.

## Consequences
All 23 real files are read (7 closings staged, 16 nothing to import, 0 refused, 2 duplicates by fingerprint); the owner's checked expected rows go in `local/samples/expected/rvb.csv`. Kirchensteuer is covered by a synthetic test only (no real example). German tax treatment of the interest and of the lottery credits is an open question (rules README items 14 and the owner's note).
