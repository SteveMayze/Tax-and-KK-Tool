# ADR 0039: Australian dividend advices: three layout fixes, franking as information only

Status: accepted (fix branch `fix/au-dividend-statements`, 2026-11-05). Supersedes only the sentence "franking details are not read" of the 2026-10-19 decision in `dividend_statements.py`; the decision on gross, net and withholding stands.

## Decision
- **Franking, option B (owner's choice):** franked amount, unfranked amount, franking percentage and franking credit are read when the statement prints them unambiguously, shown in the review's provenance and appended to the comment. They have NO effect on gross, net or withholding (ADR 0010 `gross = net + withholding + expenses` is untouched). Franked + unfranked must equal the total payment, and a franking credit must be 0 when nothing is franked; otherwise the statement is refused. A figure with two different readings, or in a layout not recognised, is left out.
- **Not done (option C):** treating the franking credit as withholding tax or grossing up needs a verified rule from the owner's adviser in `docs/rules/` and an ADR superseding this one. Whether a German resident can use an Australian franking credit is unverified.
- **Layout fixes:** `Net Payment (AUD$) $x` (and `AUD$x` / `AUD $x` amounts), `DATE PAID`, and a "Payment Date" label printed twice (taken as one date only when the statement holds exactly one standalone date; two different dates stay ambiguous).
- **AGL "DRP Residual Cash Balance" payouts are imported as income** (owner's decision), although the statement says the amount was already included in taxable income at allotment.

## Open
Mirvac distribution statements print the security name but no ASX code; they are still refused ("security could not be found") and the code is not guessed. Scheme consideration and bonus share plans remain refused on purpose.
