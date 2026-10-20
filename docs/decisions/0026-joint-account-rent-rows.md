# ADR 0026: Rent rows from the joint account; rental costs deliberately deferred

Status: accepted (Phase 26, 2026-10-20; owner answers by stated defaults: Q26.1 whole credit recorded, Q26.2 costs out of scope (the owner's decision of 2026-10-20), Q26.3 no period, month named only if the purpose states it, Q26.4 settlements as their own rows, Q26.5 the rule's organisation, created with country DE).

## Context
Phase 25 identified the joint account and defined rules as data. Rent arrives straight from the tenant (sometimes paid by a relative), changes over time, can come twice in a month or not at all, once arrived combined with a deposit, and sits among many household bookings.

## Decisions
1. **One row per matching credit** (`rvb_joint.parse`): payment date = booking date (year from the statement dates, J14), EUR, monthly, category from the setting `DJANGO_JOINT_RENTAL_CATEGORY` (default `Rental (joint)`), organisation = the rule's organisation, gross = net = the credit, withholding and expenses 0, no income period. The comment says "Rent received directly from tenant, joint account, whole amount" (the share is a later decision, J19); if the purpose names exactly one month, the comment adds it (never derived from the date). No amount-based rule: rents change (J7). Two credits in one month, a rest payment and identical credits on one day are separate rows (J6, J21).
2. **Service-charge back-payments** (rule kind `service_charge_settlement`) are their own one-off rows whose comment names the kind (J9). A credit from the property manager for a year's settlement is not matched by any rule and is ignored.
3. **Deposit combined with rent (J8).** If the purpose mentions a Kaution, the purpose must state one Kaution figure and one Miete figure (German number forms, either order) that sum to the credit: the rent figure is staged and the deposit part is a notice (not income, not staged). Otherwise the credit is not staged and a notice says it could not be split; the statement is still staged.
4. **Possible rent not matched (J12).** A credit with the whole word "Miete" in its purpose and no rule is not staged; one notice per credit. Debits are never listed.
5. **Everything else is ignored and counted** ("N bookings ignored (not rent)" in the upload summary): all debits (house fees, property charges, association fees, charges, overdraft interest, car hire), transfers, fund trades, refunds. **Rental costs are deliberately deferred (J10):** no cost rule, cost summary or `tools/rental_costs.py`. A later extension will cover income and expenses for the tax return.
6. **Conflicts.** A credit matching rules of different kinds or tenants is never staged (notice). Because a tenant also pays settlements, a new match mode `combined` searches one text "counterparty | purpose", so a rent rule can say "this payer, but not a settlement" with a negative lookahead (`^(?!.*nebenkosten).*<tenant>`); without that, the same tenant's settlement is a conflict, not a guess.
7. **Category.** The importer never creates it. If rent rows would be staged and the category is missing or inactive, the statement is refused with a message saying what to create; nothing is staged. A statement without rent rows does not need it.
8. **Organisation.** A new organisation that a rule names is created with country DE (`lookups.resolve_organisation`); all other organisations are created as before.
9. **Provenance** cites the page, the booking line and the counterparty/purpose with digit runs of six or more masked; reference lines (EREF, MREF, IBAN, BIC) are never kept.
10. Continuity (Phase 17 check) and the fingerprint (Phase 25) apply unchanged; nothing is deduplicated inside a statement.

## Consequences
How the whole-amount rent is treated for tax and SBK is open (rules README items 22 and 23). With a blank SBK/tax mapping on the new category the SBK estimate lists it as "not mapped, EXCLUDED" with count and gross, and the tax checks leave it out and flag it; the owner chooses the mappings. Existing rows of the owner's earlier project are only reported in Phase 27.
