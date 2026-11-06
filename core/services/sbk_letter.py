"""The figures of SBK's Beitragsmitteilung of 2026-11-06 and a read-only comparison with the recorded data.

Letter figures: docs/sbk-letters/2026-11-06.md (owner's input; no insurance number or IBAN). Nothing here changes data
and nothing here is a rule: the comparison only lists which groupings of the recorded payments reproduce a figure.
"""
from dataclasses import dataclass, field
from decimal import Decimal
from itertools import combinations

from core.models import AnnualInput, IncomeCategory, Payment

D = Decimal
ZERO = D(0)
CENT = D('0.01')

LETTER = {
    'date': '2026-11-06',
    'back_payment': D('6295.66'),
    'periods': [
        {'label': '2025-11-01 to 2025-12-31', 'months': 2, 'capital': D('975.52'), 'other': D('1045.62'), 'rental': D('1950.68'),
         'base': D('3971.82'), 'kv': D('556.05'), 'zusatz': D('150.93'), 'pv': D('166.82'), 'total': D('873.80')},
        {'label': 'from 2026-01-01', 'months': 9, 'capital': D('970.24'), 'other': D('561.52'), 'rental': D('765.22'),
         'base': D('2296.98'), 'kv': D('321.58'), 'zusatz': D('87.29'), 'pv': D('96.47'), 'total': D('505.34')},
    ],
}   # 'months' of the second period = 2026-01 to 2026-09, the months the back payment covers


def back_payment(periods=None):
    """Sum of monthly totals x covered months (the check of task D)."""
    return sum(((p['total'] * p['months']) for p in (periods or LETTER['periods'])), ZERO)


def targets():
    """(label, monthly figure, annual figure = monthly x 12) for each letter income figure."""
    out = []
    for p in LETTER['periods']:
        for key, name in (('capital', 'Capital'), ('other', 'Sonstige'), ('rental', 'Rental')):
            out.append((f'{name} {p["label"]}', p[key], p[key] * 12))
    return out


def _month_matches(total, monthly):
    """The letter shows annual / 12 rounded to cents, so a candidate matches when its monthly figure rounds to the letter's."""
    return (total / 12).quantize(CENT) == monthly


@dataclass
class Group:
    treatment: str
    category: str
    country: str
    currency: str
    count: int = 0
    gross: Decimal = ZERO
    withholding: Decimal = ZERO
    expenses: Decimal = ZERO
    pending: int = 0

    @property
    def key(self):
        return f'{self.category} / {self.country or "no country"} / {self.currency}'


@dataclass
class Reconciliation:
    year: int
    groups: list = field(default_factory=list)
    treatments: dict = field(default_factory=dict)     # treatment -> dict(gross, expenses, costs, base, pending)
    organisations: list = field(default_factory=list)  # (treatment, organisation, category, count, gross, withholding, expenses)
    pending_rows: list = field(default_factory=list)   # (date, organisation, treatment, currency, original gross)
    hypotheses: list = field(default_factory=list)     # (target label, description, monthly figure, matches)
    searches: list = field(default_factory=list)       # (target label, mode, description, sum) matching subsets


def build(year: int) -> Reconciliation:
    cats = {c.pk: c for c in IncomeCategory.objects.all()}
    inputs = {i.treatment: i for i in AnnualInput.objects.filter(year__year=year)}
    payments = Payment.objects.filter(month__year__year=year).select_related('organisation', 'category', 'month')
    r = Reconciliation(year)
    groups, orgs = {}, {}
    for p in payments:
        treatment = cats[p.category_id].sbk_treatment or '(not mapped)'
        g = groups.setdefault((treatment, p.category.name, p.organisation.country, p.currency),
                              Group(treatment, p.category.name, p.organisation.country, p.currency))
        o = orgs.setdefault((treatment, p.organisation.name, p.category.name), [0, ZERO, ZERO, ZERO])
        if p.conversion_status != Payment.ConversionStatus.CONVERTED:
            g.pending += 1
            r.pending_rows.append((p.payment_date, p.organisation.name, treatment, p.currency, p.gross_amount))
            continue
        for tgt in (g,):
            tgt.count += 1
            tgt.gross += p.gross_eur
            tgt.withholding += p.withholding_tax_eur or ZERO
            tgt.expenses += p.expenses_eur or ZERO
        o[0] += 1
        o[1] += p.gross_eur
        o[2] += p.withholding_tax_eur or ZERO
        o[3] += p.expenses_eur or ZERO
    r.groups = sorted(groups.values(), key=lambda g: (g.treatment, g.category, g.country, g.currency))
    r.organisations = sorted((t, n, c, *v) for (t, n, c), v in orgs.items())
    for g in r.groups:
        t = r.treatments.setdefault(g.treatment, {'gross': ZERO, 'withholding': ZERO, 'expenses': ZERO, 'pending': 0})
        t['gross'] += g.gross
        t['withholding'] += g.withholding
        t['expenses'] += g.expenses
        t['pending'] += g.pending
    for treatment, t in r.treatments.items():
        inp = inputs.get(treatment)
        t['costs'] = inp.costs_eur if inp else ZERO
        t['has_input'] = inp is not None
        t['monthly'] = t['gross'] / 12
    _hypotheses(r)
    _searches(r)
    return r


def _sel(r, treatments=None, categories=None, countries=None, exclude_categories=None, exclude_countries=None):
    out = []
    for g in r.groups:
        if treatments and g.treatment not in treatments:
            continue
        if categories and g.category not in categories:
            continue
        if exclude_categories and g.category in exclude_categories:
            continue
        if countries is not None and g.country not in countries:
            continue
        if exclude_countries is not None and g.country in exclude_countries:
            continue
        out.append(g)
    return out


def _hypotheses(r):
    """Named, obvious readings. Every one is shown with its monthly figure; matches are marked, none is chosen."""
    cap = ('capital',)
    hyps = [
        ('capital gross (all mapped capital categories)', _sel(r, cap), 'gross'),
        ('capital gross less the 51 EUR flat', _sel(r, cap), 'gross-51'),
        ('capital net of withholding tax', _sel(r, cap), 'net'),
        ('capital net of withholding tax less the 51 EUR flat', _sel(r, cap), 'net-51'),
        ('interest only (gross)', _sel(r, cap, ['Interest']), 'gross'),
        ('dividends only (gross)', _sel(r, cap, ['Dividends']), 'gross'),
        ('dividends only, net of withholding tax', _sel(r, cap, ['Dividends']), 'net'),
        ('foreign-source dividends (organisation country not DE, gross)', _sel(r, cap, ['Dividends'], exclude_countries={'DE'}), 'gross'),
        ('foreign-source dividends, net of withholding tax', _sel(r, cap, ['Dividends'], exclude_countries={'DE'}), 'net'),
        ('rental, all categories (gross)', _sel(r, ('rental',)), 'gross'),
        ('rental, all categories (gross less recorded expenses)', _sel(r, ('rental',)), 'gross-exp'),
        ('rental without the joint account (gross)', _sel(r, ('rental',), exclude_categories={'Rental (joint)'}), 'gross'),
        ('rental, joint account only (gross)', _sel(r, ('rental',), ['Rental (joint)']), 'gross'),
        ('rental, joint account only, 50 % share', _sel(r, ('rental',), ['Rental (joint)']), 'half'),
        ('rental, all with the joint account at 50 %', None, 'rental-half-joint'),
        ('all mapped income except rental (gross)', [g for g in r.groups if g.treatment not in ('rental', '(not mapped)')], 'gross'),
    ]
    for desc, groups, mode in hyps:
        r.hypotheses.append((desc, _value(r, groups, mode)))


def _value(r, groups, mode):
    if mode == 'rental-half-joint':
        return sum((g.gross / 2 if g.category == 'Rental (joint)' else g.gross for g in r.groups if g.treatment == 'rental'), ZERO)
    gross = sum((g.gross for g in groups), ZERO)
    wh = sum((g.withholding for g in groups), ZERO)
    ex = sum((g.expenses for g in groups), ZERO)
    return {'gross': gross, 'gross-51': gross - 51, 'net': gross - wh, 'net-51': gross - wh - 51,
            'gross-exp': gross - ex, 'half': gross / 2}[mode]


def _searches(r):
    """Every combination of the (treatment, category, country, currency) groups whose gross, or gross net of withholding,
    reproduces a letter figure. Brute force over the small number of groups; lists all matches, picks none.
    Deliberately NOT done per organisation: with ~17 payers there are over 100,000 subsets and one matches any figure to the cent
    by chance, which would prove nothing."""
    groups = [g for g in r.groups if g.gross != 0 and g.treatment != '(not mapped)']
    if len(groups) > 18:
        return
    for label, monthly, _annual in targets():
        for mode in ('gross', 'net'):
            for n in range(1, len(groups) + 1):
                for combo in combinations(groups, n):
                    total = sum((g.gross - (g.withholding if mode == 'net' else ZERO) for g in combo), ZERO)
                    if _month_matches(total, monthly):
                        r.searches.append((label, mode, ' + '.join(g.key for g in combo), total))

