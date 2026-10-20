# ADR 0021: Managing-agent rental statements

Status: accepted (Phase 21, 2026-10-20; owner answers: one row per statement; fees go into expenses; the owner withdrawal is never staged; organisation = the managing agent; category Rental; gross = the Money In amount of the rent entry; income period = the day after "previously paid to" up to "paid to"; payment date = the statement date only; council and water rates are expenses).

## Context
Eleven one-page "Tax Invoice" statements (numbers 76 to 86, December 2024 to January 2026). Each has Money In, Money Out and You Received, one rent entry (two receipts in one statement), a management fee, a sundry fee after the "Total" line, an owner withdrawal, and two to five lines flagged `*` (GST-inclusive). Five carry council or water rates as costs and some carry repairs with free-text descriptions. Every rent line is worded as a part payment ("Rent paid to <date> with part payment of $x (previously paid to <date> + $y)"), so that wording is the normal rent line, not an arrears case. The default and layout text modes give the same lines.

## Decisions
1. **Reader `hodges_rental`** (default text mode), recognised by structure. The reader id follows the sample folder; no agent name is in code.
2. **Closing arithmetic** (G9, A1, A5): In - Out = Received; rent receipts = Money In = second figure of the Total line; cost lines = first figure of the Total line; costs + sundry fees = Money Out. The printed Total excludes the sundry fee. In all 11 samples the owner withdrawal equals You Received and is not part of Money Out, so it is not an expense of the rent.
3. **Costs are recognised by arithmetic, not by a label list:** every amount line between the rent entry and "Total" is an expense (repairs carry free-text descriptions); the sums prove none is missing. Arrears, advance and prepaid wording, a non-rent money-in entry, and unknown lines after "Total" refuse the statement naming the label.
4. **Receipts:** a receipt ends at a standalone amount line or at the amount closing the "(previously paid to ... + $x)" bracket; further "Rent paid to" lines of the same entry are further receipts.
5. **Row:** payment date = statement date; income period from the day after the earliest "previously paid to" to the latest "paid to"; AUD, Rental, monthly; expenses = costs + sundry; comment counts `*` lines (GST-inclusive); no GST split.
6. **Organisation** from the setting `DJANGO_RENTAL_ORGANISATION`; the existing hand-entered rental rows use another organisation name, so the duplicate rule (date + organisation + currency + gross) will not flag collisions with them; Phase 24 reports such near-collisions.
7. **Fingerprint:** statement number, period end, You Received.

## Consequences
All 11 real statements are staged (periods contiguous, one spanning two months, the last a short period ending in mid-January); the owner's checked rows go in the git-ignored `local/samples/expected/hodges.csv`. Rental income treatment and the GST are open (rules README item 17). The setting must be present in the server environment before the first production import (documented, not changed here).
