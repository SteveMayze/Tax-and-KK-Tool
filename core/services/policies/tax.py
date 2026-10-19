"""Income-tax information and the three verified checks (policy `tax-information`).

Rules: docs/rules/income-tax-rules.md. Implemented: TAX-02 Sparer-Pauschbetrag (section 20(9) EStG),
TAX-04 Freigrenze for private sale gains (section 23(3) EStG), TAX-03 flat-tax rate as a reference only.
No tax amount is computed. Treaty rules, foreign-tax credit, progression reservation, currency-conversion
rules and Anlage mapping are NOT implemented (unverified).
"""
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from django.utils.translation import gettext as _, gettext_lazy

from core.currencies import CURRENCY_COUNTRY
from core.services.i18n import number
from core.models import AssessmentSettings, IncomeCategory, Payment, TaxIncomeType

POLICY_NAME = 'tax-information'
POLICY_VERSION = f'{POLICY_NAME} 1.0 (verified 2026-10-18; statute text read, no treaty rules)'
ZERO = Decimal(0)
SPARER_PAUSCHBETRAG = Decimal('1000')          # section 20(9) EStG; 2,000 for joint assessment
FREIGRENZE_PRIVATE_SALES = Decimal('1000')     # section 23(3) EStG, from 2024
FLAT_TAX_PCT = Decimal('25')                   # section 32d(1) EStG, reference only
NOT_APPLIED = [
    gettext_lazy('Double-taxation treaties (UK, Australia, USA), foreign-tax credit and progression reservation are not applied.'),
    gettext_lazy('Currency conversion: the app uses the ECB rate of the payment date; whether the tax authorities require another rate is not verified.'),
    gettext_lazy('Withholding tax already deducted at source is shown for information only and is NOT credited: treaty and foreign-tax-credit rules are not implemented. Recorded expenses are not deducted either.'),
    gettext_lazy('Losses (negative payments) are shown separately and are not netted across categories; loss-offset rules (loss pots, carry-forward, relation to SBK) are unverified and not implemented.'),
    gettext_lazy('No tax amount is calculated. Expenses, Anlage mapping and church tax/solidarity surcharge are not handled.'),
]


@dataclass
class CheckResult:
    check: str
    amount: Decimal | None
    limit: str
    result: str
    note: str


def _typed_payments(year, types):
    cats = {c.pk: c.tax_income_type for c in IncomeCategory.objects.all()}
    qs = Payment.objects.filter(month__year__year=year).select_related('organisation')
    return [p for p in qs if cats[p.category_id] in types]


def _converted(payments):
    return [p for p in payments if p.conversion_status == Payment.ConversionStatus.CONVERTED]


def tax_checks(year: int, settings: AssessmentSettings | None = None):
    settings = settings or AssessmentSettings.load()
    results = []

    capital = _typed_payments(year, {TaxIncomeType.CAPITAL})
    by_category = defaultdict(lambda: ZERO)
    for p in _converted(capital):
        by_category[p.category_id] += p.gross_eur
    # A category whose total is a loss counts as 0: losses are NOT netted against other categories (offset rules unverified).
    income = sum((max(total, ZERO) for total in by_category.values()), ZERO)
    capital_losses = sum((total for total in by_category.values() if total < 0), ZERO)
    allowance = SPARER_PAUSCHBETRAG * (2 if settings.joint_assessment else 1)
    used = min(allowance, max(income, ZERO))
    results.append(CheckResult(
        _('Sparer-Pauschbetrag (section 20(9) EStG)'), income,
        _('Allowance %(allowance)s EUR (%(kind)s assessment)') % {
            'allowance': number(allowance, 0), 'kind': _('joint') if settings.joint_assessment else _('single')},
        _('Allowance used %(used)s EUR, remaining %(rest)s EUR; capital income above the allowance %(above)s EUR') % {
            'used': number(used), 'rest': number(allowance - used), 'above': number(max(income - allowance, ZERO))},
        _('Gross EUR capital income of all mapped capital categories, including foreign. Tax already withheld and foreign tax are not modelled. '
          'Actual costs cannot be deducted for capital income.') +
        (_(' A loss of %(eur)s EUR in a capital category is NOT offset against other categories (loss-offset rules unverified).') % {
            'eur': number(-capital_losses)} if capital_losses else '')))

    sales = _typed_payments(year, {TaxIncomeType.PRIVATE_SALE})
    total = sum((p.gross_eur for p in _converted(sales)), ZERO)
    if total < FREIGRENZE_PRIVATE_SALES:
        outcome = (_('Net loss for the year: it can only offset private sale gains of the same year.') if total < 0 else
                   _('Below the Freigrenze: no tax under section 23 on these gains.'))
    else:
        outcome = _('At or above the Freigrenze: the WHOLE gain is taxable under section 23 (holding-period conditions not checked).')
    results.append(CheckResult(
        _('Private sale gains Freigrenze (section 23(3) EStG)'), total,
        _('Freigrenze %(limit)s EUR per person (all-or-nothing)') % {'limit': number(FREIGRENZE_PRIVATE_SALES, 0)},
        outcome, _('Enter the GAIN (proceeds minus cost) as the payment amount, and losses as negative payments in a category marked "may be negative". Holding periods (1 year / 10 years) are not checked.')))

    results.append(CheckResult(
        _('Flat tax on capital income (section 32d(1) EStG)'), None, _('Rate %(pct)s %% (reference)') % {'pct': FLAT_TAX_PCT},
        _('No amount calculated'), _('Reduced by creditable foreign tax per section 32d(5); surcharges and exceptions not applied.')))
    return results


def effective_country(payment):
    """(country, inferred). The organisation's own country wins; a blank one falls back to the
    payment currency's country (AUD -> AU, GBP -> GB, USD -> US). EUR is never inferred."""
    if payment.organisation.country:
        return payment.organisation.country, False
    inferred = CURRENCY_COUNTRY.get(payment.currency, '')
    return inferred, bool(inferred)


def tax_summary_rows(year=None):
    """One row per income type and country (information only)."""
    cats = {c.pk: c.tax_income_type for c in IncomeCategory.objects.all()}
    qs = Payment.objects.select_related('organisation')
    if year:
        qs = qs.filter(month__year__year=year)
    groups = defaultdict(list)
    inferred_in = defaultdict(int)
    for p in qs:
        country, inferred = effective_country(p)
        groups[(cats[p.category_id], country)].append(p)
        inferred_in[(cats[p.category_id], country)] += inferred
    labels = dict(TaxIncomeType.choices)
    rows = []
    for (itype, country), group in groups.items():
        converted = _converted(group)
        by_ccy = defaultdict(lambda: ZERO)
        for p in group:
            by_ccy[p.currency] += p.gross_amount
        flags = []
        if not itype:
            flags.append(_('Category not mapped to an income type: left out of the checks.'))
        if not country:
            flags.append(_('Organisation country not set (EUR payments need it set on the organisation).'))
        else:
            if inferred_in[(itype, country)]:
                flags.append(_('Country taken from the payment currency for %(n)s payment(s); set it on the organisation to override.') % {
                    'n': inferred_in[(itype, country)]})
        if country and country != 'DE':
            flags.append(_('Foreign source: treaty treatment and foreign-tax credit not applied.'))
        rows.append({
            'income_type': str(labels.get(itype, _('Not mapped'))), 'country': country or _('(not set)'), 'payments': len(group),
            'gross_eur': sum((p.gross_eur for p in converted), ZERO),
            'withholding_eur': sum((p.withholding_tax_eur or ZERO for p in converted), ZERO),
            'losses_eur': sum((p.gross_eur for p in converted if p.kind == Payment.Kind.NORMAL and p.gross_eur < 0), ZERO),
            'original': '; '.join(f'{c} {number(a)}' for c, a in sorted(by_ccy.items())),
            'unconverted': len(group) - len(converted),
            'manual_rates': sum(1 for p in converted if p.rate_source == 'manual'),
            'flags': ' '.join(flags)})
    not_mapped = _('Not mapped')
    rows.sort(key=lambda r: (r['income_type'] == not_mapped, r['income_type'], r['country']))
    return rows, qs
