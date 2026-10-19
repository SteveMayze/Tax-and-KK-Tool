# ADR 0011: Capital loss without any loss-offset rule

Status: accepted (Phase 11, 2026-10-19; owner confirmed the defaults: the capital-income categories and the private-sale category may hold a loss; there is no SBK or tax-office statement on loss treatment, so it stays unverified).

## Decisions
1. **Category flag `may_be_negative`** (default off). A *normal* payment may have a negative gross only in a flagged category (never 0). Checked in the model on every save, and earlier, with a message naming the category, in the payment form and the importer (a category that does not exist yet is not flagged). Reversals and corrections keep their own sign rules.
2. **Migration 0007** sets the flag from the owner's own mapping (SBK treatment capital, or tax income type capital / private sale); names are never guessed. Reversible. The owner can change the flag on the Categories page.
3. **Reports** show losses signed. Gross EUR is the signed sum = gains + losses + corrections/reversals; the annual summary and the category/organisation reports show the three parts. A reversal is not a loss.
4. **SBK estimate:** calculation unchanged. A negative annual surplus of an income type is still floored at 0, so the estimate equals the one with that income at 0. A run-specific note states that a loss was recorded and is not netted against other income types or carried over.
5. **Tax:** the summary has a separate losses column and nets nothing across categories. The Sparer-Pauschbetrag check no longer lets a loss in one capital category reduce another (a category total below 0 counts as 0, with a note). The private-sale Freigrenze check is unchanged (its same-type, same-year rule is verified, TAX-04).
6. **Rules:** TAX-11 "Loss-offset rules" is registered as UNVERIFIED with its open questions (loss pots, carry-forward, relation to SBK); nothing is implemented from memory.

## Consequence to know
Within one income type the SBK annual figure is a signed sum, so a loss payment reduces the gains of the same income type (as corrections always did). Whether that matches SBK's practice is part of the unverified question.
