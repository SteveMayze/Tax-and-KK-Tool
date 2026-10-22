"""Reports built from the rule policies (SBK estimate, tax information and checks)."""
from django.utils import timezone
from django.utils.translation import gettext as _, gettext_lazy

from core.models import Payment, SbkTreatment

from .policies import sbk, tax
from .i18n import month_name, number, plain_decimal
from .reports import NO_MATCH, REPORTS, Column, Report, ReportSpec, _basis, _payments

TREATMENTS = [SbkTreatment.EMPLOYMENT, SbkTreatment.PENSION, SbkTreatment.SELF_EMPLOYED, SbkTreatment.RENTAL,
              SbkTreatment.CAPITAL, SbkTreatment.ONE_OFF]
# Full column headings (glossary section A: the German text is the glossary label plus " EUR").
SHORT = {SbkTreatment.EMPLOYMENT: gettext_lazy('Employment EUR'), SbkTreatment.PENSION: gettext_lazy('Pension EUR'),
         SbkTreatment.SELF_EMPLOYED: gettext_lazy('Self-employed EUR'), SbkTreatment.RENTAL: gettext_lazy('Rental EUR'),
         SbkTreatment.CAPITAL: gettext_lazy('Capital EUR'), SbkTreatment.ONE_OFF: gettext_lazy('One-off (1/12) EUR')}
NOT_AN_ASSESSMENT = gettext_lazy('Planning estimate only. It is NOT an SBK assessment and not a tax calculation. SBK decides the '
                       'contribution from your proofs and tax assessment.')


def sbk_estimate(year):
    a = sbk.assess_year(year)
    rows = []
    for m in a.months:
        row = {'month': f'{year}-{m.month:02d} {month_name(m.month)}', 'base': m.base, 'assessed': m.assessed,
               'limit': {'minimum': _('minimum'), 'maximum': _('maximum')}.get(m.limit, m.limit), 'kv_general': m.kv_general, 'kv_zusatz': m.kv_zusatz, 'kv': m.kv,
               'pflege': m.pflege, 'total': m.total}
        row.update({t: m.components[t] for t in TREATMENTS})
        rows.append(row)
    totals = {'month': _('Year total'), 'kv_general': sum(r['kv_general'] for r in rows), 'kv_zusatz': sum(r['kv_zusatz'] for r in rows),
              'kv': a.total_kv, 'pflege': a.total_pflege, 'total': a.total}
    for t in TREATMENTS:
        totals[t] = sum(r[t] for r in rows)
    cols = [Column('month', _('Month'))] + [Column(t, str(SHORT[t]), 'money') for t in TREATMENTS] + [
        Column('base', _('Base before limits EUR'), 'money'), Column('assessed', _('Assessed base EUR'), 'money'),
        Column('limit', _('Limit applied')), Column('kv_general', _('Health: general part EUR'), 'money'),
        Column('kv_zusatz', _('Health: additional contribution EUR'), 'money'), Column('kv', _('Health total EUR'), 'money'),
        Column('pflege', _('Care insurance EUR'), 'money'), Column('total', _('Total contribution EUR'), 'money')]

    p = a.params
    payments = list(_payments(year))
    basis = [
        (_('Period'), _('Calendar year %(year)s (estimate for each of its 12 months)') % {'year': year}),
        (_('Policy'), _('%(version)s. Sources: %(sources)s. Rules: docs/rules/sbk-contribution-rules.md') % {
            'version': p.policy_version, 'sources': '; '.join(p.sources)}),
        (_('Status'), NOT_AN_ASSESSMENT),
        (_('Parameters'), _('Ceiling %(ceiling)s EUR/month; minimum base %(minimum)s EUR/month (1/90 of Bezugsgroesse '
                            '%(bezug)s EUR per day, 30-day month); health %(kv)s%% + additional %(zusatz)s%% '
                            '= %(sum)s%%; care insurance %(pflege)s%%.') % {
            'ceiling': number(p.bbg_monthly), 'minimum': number(p.min_monthly), 'bezug': number(p.bezugsgroesse_monthly, 0),
            'kv': plain_decimal(a.kv_pct), 'zusatz': plain_decimal(a.zusatz_pct),
            'sum': plain_decimal(a.kv_pct + a.zusatz_pct), 'pflege': plain_decimal(a.pflege_pct)}),
        (_('Rate basis'), a.rate_label),
        (_('Currency'), _('EUR, gross amounts at the rate stored on each payment.')),
        (_('Basis'), _('Estimated monthly contribution base from your income by SBK income type (not simply annual / 12).')),
        (_('Gross/net'), _('Gross amounts, after the costs entered for self-employed/rental income and the capital-income flat amount.')),
    ]
    basis += [(_('Assumption'), t) for t in sbk.ASSUMPTIONS]
    excl = []
    if a.unmapped:
        excl.append(_('Categories not mapped to an SBK treatment, EXCLUDED: ') + '; '.join(
            _('%(name)s (%(n)s payment(s), %(eur)s EUR converted)') % {'name': n, 'n': c, 'eur': number(g)}
            for n, c, g in a.unmapped) + '.')
    if a.unconverted_mapped:
        excl.append(_('%(n)s unconverted payment(s) in mapped categories excluded, so the base may be understated.') % {'n': a.unconverted_mapped})
    if a.excluded_by_mapping:
        excl.append(_('%(n)s payment(s) in categories mapped as "not contribution-relevant" excluded.') % {'n': a.excluded_by_mapping})
    excl += a.notes
    basis.append((_('Excluded / missing'), ' '.join(excl) if excl else _('None.')))
    notes = [_('Average total contribution per month: %(eur)s EUR.') % {'eur': number(a.total / 12)},
             _('Limit applied: "minimum" means the legal minimum base replaced a lower income.')]
    return Report('sbk', _('SBK contribution estimate'), _('Calendar year %(year)s') % {'year': year}, _('SBK-style estimate'), cols, rows, basis, totals, notes, timezone.now())


def tax_info_summary(year=None, flt=None):
    rows, qs = tax.tax_summary_rows(year, flt)
    cols = [Column('income_type', _('Income type')), Column('country', _('Organisation country')), Column('payments', _('Payments'), 'int'),
            Column('gross_eur', _('Gross EUR (converted, signed sum)'), 'money'),
            Column('losses_eur', _('of which losses EUR (shown separately, not netted across categories)'), 'money'),
            Column('original', _('Original gross by currency')),
            Column('withholding_eur', _('Withholding tax EUR (information, not credited)'), 'money'),
            Column('unconverted', _('Unconverted payments'), 'int'), Column('manual_rates', _('Manual-rate payments'), 'int'),
            Column('flags', _('Flags'))]
    payments = list(qs)
    basis = _basis(payments, year, _('Actual payments received, grouped by tax income type and country'),
                   _('Gross amounts as recorded; net amounts and costs are not used.'), flt=flt)
    basis.insert(1, (_('Policy'), _('%(version)s. Rules: docs/rules/income-tax-rules.md') % {'version': tax.POLICY_VERSION}))
    basis += [(_('Not applied'), t) for t in tax.NOT_APPLIED]
    notes = [_('Information for you or your adviser; not a tax calculation.')]
    no_match = bool(flt is not None and flt.is_active and not payments)
    if no_match:
        notes.append(NO_MATCH)
    return Report('tax_summary', _('Tax information summary'),
                  _('Calendar year %(year)s') % {'year': year} if year else _('All years'), _('Information only'),
                  cols, rows, basis, None, notes, timezone.now(), no_match)


def tax_check_report(year):
    results = tax.tax_checks(year)
    rows = [{'check': r.check, 'amount': r.amount, 'limit': r.limit, 'result': r.result, 'note': r.note} for r in results]
    cols = [Column('check', _('Check')), Column('amount', _('Amount EUR'), 'money'), Column('limit', _('Rule')),
            Column('result', _('Result')), Column('note', _('Note'))]
    payments = list(_payments(year))
    basis = _basis(payments, year, _('Verified statutory checks only'), _('Gross EUR amounts of the mapped categories.'))
    basis.insert(1, (_('Policy'), _('%(version)s. Rules: docs/rules/income-tax-rules.md') % {'version': tax.POLICY_VERSION}))
    basis += [(_('Not applied'), t) for t in tax.NOT_APPLIED]
    return Report('tax_checks', _('Tax checks (verified rules)'), _('Calendar year %(year)s') % {'year': year},
                  _('Rule checks, no tax amount'),
                  cols, rows, basis, None, [_('Categories must be mapped to a tax income type (Categories page) to be included.')], timezone.now())


SPECS = {s.key: s for s in [
    ReportSpec('sbk', gettext_lazy('SBK contribution estimate'), gettext_lazy('Estimated monthly SBK contributions by income type (planning estimate, not an assessment).'), sbk_estimate, True, supports_filter=False),
    ReportSpec('tax_summary', gettext_lazy('Tax information summary'), gettext_lazy('Income by tax income type and country, with flags (no tax calculation).'), tax_info_summary),
    ReportSpec('tax_checks', gettext_lazy('Tax checks (verified rules)'), gettext_lazy('Sparer-Pauschbetrag usage and private-sale Freigrenze; no tax amount.'), tax_check_report, True, supports_filter=False),
]}
REPORTS.update(SPECS)
