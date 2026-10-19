"""SBK contribution estimate for a voluntary member (policy `sbk-contribution-estimate`).

Rules: docs/rules/sbk-contribution-rules.md (SBK-01..SBK-17). Sources: section 240 SGB V,
GKV-Spitzenverband Beitragsverfahrensgrundsaetze Selbstzahler (BVSz, 11th amendment, in force
2024-04-01), Katalog von Einnahmen, SBK's published 2026 rates.

This is a planning estimate, NOT an SBK assessment. Parameters exist only for years whose figures
were verified (currently 2026); other years are refused rather than guessed.
"""
import calendar
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from core.models import AnnualInput, AssessmentSettings, IncomeCategory, Payment, SbkTreatment

POLICY_NAME = 'sbk-contribution-estimate'
CENT = Decimal('0.01')
ZERO = Decimal(0)
HUNDRED = Decimal(100)


class PolicyUnavailable(Exception):
    """No verified parameters for this year, or required settings are missing."""


@dataclass(frozen=True)
class SbkParameters:
    year: int
    version: str
    bbg_monthly: Decimal              # contribution assessment ceiling, per month (SBK-08)
    bezugsgroesse_monthly: Decimal    # minimum base = 1/3 of this per month (SBK-09, 1/90 per day)
    kv_general_pct: Decimal           # section 241 SGB V (SBK-10)
    kv_reduced_pct: Decimal           # section 243 SGB V as shown on SBK's page (SBK-10)
    zusatz_pct: Decimal               # SBK additional contribution (SBK-10)
    pflege_base_pct: Decimal          # SBK page (SBK-11; legal-basis CONFLICT recorded)
    pflege_childless_surcharge_pct: Decimal
    capital_costs_flat: Decimal       # Werbungskosten flat amount for capital income (SBK-03)
    sources: tuple = ()

    @property
    def min_monthly(self) -> Decimal:
        return self.bezugsgroesse_monthly / 3   # 1/90 per day x 30 days, kept unrounded

    @property
    def policy_version(self) -> str:
        return f'{POLICY_NAME} {self.version}'


PARAMETERS = {
    2026: SbkParameters(
        year=2026, version='1.0 (2026 parameters, verified 2026-10-18)',
        bbg_monthly=Decimal('5812.50'), bezugsgroesse_monthly=Decimal('3955'),
        kv_general_pct=Decimal('14.6'), kv_reduced_pct=Decimal('14.0'), zusatz_pct=Decimal('3.8'),
        pflege_base_pct=Decimal('3.6'), pflege_childless_surcharge_pct=Decimal('0.6'),
        capital_costs_flat=Decimal('51'),
        sources=('section 240 SGB V', 'BVSz sections 3, 5, 9 (version 2024-04-01)', 'SBK website 2026 figures',
                 'SV-Rechengrossenverordnung 2026')),
}

ASSUMPTIONS = [
    'Membership for all 12 months of the year, each month counted as 30 days.',
    'The base is derived from the selected year\'s data. SBK itself uses the last proven year and the tax assessment, and its '
    'contributions stay provisional until then.',
    'Employment and pension income is allocated to the month of the payment date (income-period dates are not used).',
    'Self-employed, rental and capital income: annual surplus divided by the months from "first month" to "last month" you '
    'entered (default January to December) and applied to those months. This reading of BVSz section 5(2) is not confirmed with SBK.',
    'A negative annual surplus is treated as 0; loss netting (including section 20(6) EStG) is not applied. Losses are recorded '
    'as negative payments in categories marked "may be negative" and are listed in a run-specific note when present.',
    'One-off income is spread at 1/12 per month for 12 months starting with the month of receipt (BVSz section 5(3)), '
    'including one-offs received in the previous year.',
    'Gross EUR amounts at the rate stored on each payment; unconverted payments are excluded. Net amounts are not used.',
    'The category-to-treatment mapping is yours; unmapped categories are excluded.',
    'Not modelled: spouse or partner income, child deductions, ranking of several income types, sick-pay or other '
    'contribution-free periods, special rules for foreign pensions, minimum-base exceptions.',
    'Contributions are rounded to 2 decimals half-up per component; the additional contribution is calculated on the '
    'total base and rounded separately (BVSz section 9).',
]


def round_cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class MonthResult:
    month: int
    components: dict            # treatment -> unrounded amount
    base: Decimal               # sum of components (before limits)
    assessed: Decimal           # after minimum/maximum
    limit: str                  # '', 'minimum', 'maximum'
    kv_general: Decimal
    kv_zusatz: Decimal
    kv: Decimal
    pflege: Decimal

    @property
    def total(self):
        return self.kv + self.pflege


@dataclass
class Assessment:
    params: SbkParameters
    settings: AssessmentSettings
    months: list
    kv_pct: Decimal
    zusatz_pct: Decimal
    pflege_pct: Decimal
    rate_label: str
    unmapped: list = field(default_factory=list)       # [(category name, count, gross_eur)]
    excluded_by_mapping: int = 0
    unconverted: int = 0
    unconverted_mapped: int = 0
    notes: list = field(default_factory=list)          # run-specific warnings

    @property
    def total_kv(self):
        return sum((m.kv for m in self.months), ZERO)

    @property
    def total_pflege(self):
        return sum((m.pflege for m in self.months), ZERO)

    @property
    def total(self):
        return self.total_kv + self.total_pflege


def parameters_for(year: int) -> SbkParameters:
    try:
        return PARAMETERS[year]
    except KeyError:
        raise PolicyUnavailable(
            f'No verified SBK parameters for {year}; only {", ".join(map(str, sorted(PARAMETERS)))} '
            f'{"is" if len(PARAMETERS) == 1 else "are"} available. Add them to the register first (docs/rules/).')


def rates_for(params: SbkParameters, settings: AssessmentSettings):
    kv = params.kv_general_pct if settings.kv_rate == AssessmentSettings.KvRate.GENERAL else params.kv_reduced_pct
    pflege = params.pflege_base_pct + (
        params.pflege_childless_surcharge_pct if settings.pflege == AssessmentSettings.Pflege.CHILDLESS else ZERO)
    if settings.kv_rate_confirmed:
        label = f'{settings.get_kv_rate_display()}, confirmed with SBK'
    else:
        label = (f'{settings.get_kv_rate_display()}: NOT confirmed with SBK; shown as an upper-bound "affordability" '
                 f'figure, the amount you could expect to pay at most' if settings.kv_rate == settings.KvRate.GENERAL
                 else f'{settings.get_kv_rate_display()}: NOT confirmed with SBK')
    return kv, params.zusatz_pct, pflege, label


def contributions(assessed: Decimal, kv_pct, zusatz_pct, pflege_pct):
    """BVSz section 9: each component rounded half-up to cents; health insurance = general part + additional contribution."""
    kv_general = round_cents(assessed * kv_pct / HUNDRED)
    zusatz = round_cents(assessed * zusatz_pct / HUNDRED)
    return kv_general, zusatz, kv_general + zusatz, round_cents(assessed * pflege_pct / HUNDRED)


def _month_range(first, last):
    return range(first, last + 1)


def assess_year(year: int, settings: AssessmentSettings | None = None) -> Assessment:
    params = parameters_for(year)
    settings = settings or AssessmentSettings.load()
    kv_pct, zusatz_pct, pflege_pct, label = rates_for(params, settings)

    categories = {c.pk: c for c in IncomeCategory.objects.all()}
    payments = list(Payment.objects.filter(month__year__year__in=[year - 1, year]).select_related('month__year', 'category'))
    inputs = {i.treatment: i for i in AnnualInput.objects.filter(year__year=year)}

    comps = {m: {t: ZERO for t in SbkTreatment.values} for m in range(1, 13)}
    gross_year = {t: ZERO for t in (SbkTreatment.SELF_EMPLOYED, SbkTreatment.RENTAL, SbkTreatment.CAPITAL)}
    unmapped, notes = {}, []
    losses = {}                      # treatment -> [count, EUR sum] of normal payments below 0 received in the year
    excluded_by_mapping = unconverted = unconverted_mapped = 0

    for p in payments:
        cat = categories[p.category_id]
        treatment = cat.sbk_treatment
        in_year = p.month.year.year == year
        if not treatment:
            if in_year:
                row = unmapped.setdefault(cat.name, [0, ZERO])
                row[0] += 1
                if p.conversion_status == Payment.ConversionStatus.CONVERTED:
                    row[1] += p.gross_eur
            continue
        if treatment == SbkTreatment.EXCLUDED:
            excluded_by_mapping += in_year
            continue
        if p.conversion_status != Payment.ConversionStatus.CONVERTED:
            unconverted += in_year
            unconverted_mapped += in_year
            continue
        gross = p.gross_eur
        if in_year and p.kind == Payment.Kind.NORMAL and gross < 0:
            row = losses.setdefault(treatment, [0, ZERO])
            row[0] += 1
            row[1] += gross
        if treatment in (SbkTreatment.EMPLOYMENT, SbkTreatment.PENSION):
            if in_year:
                comps[p.month.month][treatment] += gross
        elif treatment == SbkTreatment.ONE_OFF:
            start = p.month.year.year * 12 + p.month.month - 1          # month index of receipt
            for idx in range(start, start + 12):
                if idx // 12 == year:
                    comps[idx % 12 + 1][treatment] += gross / 12
        elif in_year:
            gross_year[treatment] += gross

    for treatment, gross in gross_year.items():
        inp = inputs.get(treatment)
        first, last = (inp.first_month, inp.last_month) if inp else (1, 12)
        costs = inp.costs_eur if inp else ZERO
        if gross == 0:
            continue
        if treatment == SbkTreatment.CAPITAL:
            costs = max(costs, params.capital_costs_flat)        # SBK-03: 51 EUR unless higher costs proven
        surplus = gross - costs
        if surplus < 0:
            notes.append(f'{SbkTreatment(treatment).label.split(":")[0]}: costs exceed income; treated as 0 (no loss netting).')
            surplus = ZERO
        per_month = surplus / (last - first + 1)
        for m in _month_range(first, last):
            comps[m][treatment] += per_month
        if inp is None:
            notes.append(f'{SbkTreatment(treatment).label.split(":")[0]}: no months/costs entered for {year}; '
                         f'assumed January to December and no costs' +
                         (f' (capital: flat {params.capital_costs_flat} EUR)' if treatment == SbkTreatment.CAPITAL else '') + '.')

    for treatment, (count, total) in sorted(losses.items()):
        notes.append(f'Loss recorded in {SbkTreatment(treatment).label.split(":")[0]} ({count} payment(s), {total:,.2f} EUR): it only '
                     f'reduces that income type\'s own signed sum; a negative annual surplus counts as 0, and the loss is not netted '
                     f'against other income types or carried over (loss-offset rules are unverified, docs/rules/).')

    months = []
    for m in range(1, 13):
        base = sum(comps[m].values(), ZERO)
        if base < params.min_monthly:
            assessed, limit = params.min_monthly, 'minimum'
        elif base > params.bbg_monthly:
            assessed, limit = params.bbg_monthly, 'maximum'
        else:
            assessed, limit = base, ''
        kv_g, kv_z, kv, pf = contributions(assessed, kv_pct, zusatz_pct, pflege_pct)
        months.append(MonthResult(m, comps[m], base, assessed, limit, kv_g, kv_z, kv, pf))

    return Assessment(
        params, settings, months, kv_pct, zusatz_pct, pflege_pct, label,
        unmapped=sorted((n, c, g) for n, (c, g) in unmapped.items()),
        excluded_by_mapping=excluded_by_mapping, unconverted=unconverted, unconverted_mapped=unconverted_mapped, notes=notes)
