# ADR 0004: SBK estimate and tax information as versioned policies

Status: accepted (Phase 7)

## Context
CLAUDE.md requires legal rules to be versioned, documented and verified, and forbids assuming categories are taxable or SBK-relevant. Research (docs/rules/) found that SBK builds the monthly base per income type (not simply annual / 12), that parts of the tax picture (treaties, foreign-tax credit, conversion rules) could not be verified, and that two sources disagree on the base care-insurance rate.

## Decision
- Rules live in `core/services/policies/` as separate modules with a name, version and source references. Outputs state the policy version, parameters, assumptions and "not applied" items.
- Parameters exist only for verified years (SBK: 2026). Other years are refused rather than guessed.
- The user maps each category to an SBK treatment and a tax income type; unmapped categories are excluded and listed. Annual costs and months earned are explicit user data, never inferred.
- The health-insurance rate is a setting. Until the user confirms it with SBK, the general rate is shown as an upper-bound "affordability" figure and labelled so.
- Tax support is information plus the verified checks (Sparer-Pauschbetrag, section 23 Freigrenze); no tax amount and no treaty logic.
- Contribution arithmetic follows BVSz section 9 (per-component half-up rounding to cents) and is tested against hand calculations and SBK's published examples (one documented one-cent difference).

## Consequences
The annual / 12 figure stays as a simple average of actuals and is explicitly not the SBK figure. Adding a year or a rule means verifying it, recording it in docs/rules/, adding a policy version and tests. Interpretation points that SBK has not confirmed are listed in every output.
