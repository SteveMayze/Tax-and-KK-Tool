"""Reports built from the rule policies (SBK estimate, tax information and checks)."""
from django.utils import timezone

from core.models import Payment, SbkTreatment

from .policies import sbk, tax
from .reports import REPORTS, Column, Report, ReportSpec, _basis, _payments

TREATMENTS = [SbkTreatment.EMPLOYMENT, SbkTreatment.PENSION, SbkTreatment.SELF_EMPLOYED, SbkTreatment.RENTAL,
              SbkTreatment.CAPITAL, SbkTreatment.ONE_OFF]
SHORT = {SbkTreatment.EMPLOYMENT: 'Employment', SbkTreatment.PENSION: 'Pension', SbkTreatment.SELF_EMPLOYED: 'Self-employed',
         SbkTreatment.RENTAL: 'Rental', SbkTreatment.CAPITAL: 'Capital', SbkTreatment.ONE_OFF: 'One-off (1/12)'}
NOT_AN_ASSESSMENT = ('Planning estimate only. It is NOT an SBK assessment and not a tax calculation. SBK decides the '
                     'contribution from your proofs and tax assessment.')


def sbk_estimate(year):
    a = sbk.assess_year(year)
    import calendar
    rows = []
    for m in a.months:
        row = {'month': f'{year}-{m.month:02d} {calendar.month_name[m.month]}', 'base': m.base, 'assessed': m.assessed,
               'limit': m.limit, 'kv_general': m.kv_general, 'kv_zusatz': m.kv_zusatz, 'kv': m.kv,
               'pflege': m.pflege, 'total': m.total}
        row.update({t: m.components[t] for t in TREATMENTS})
        rows.append(row)
    totals = {'month': 'Year total', 'kv_general': sum(r['kv_general'] for r in rows), 'kv_zusatz': sum(r['kv_zusatz'] for r in rows),
              'kv': a.total_kv, 'pflege': a.total_pflege, 'total': a.total}
    for t in TREATMENTS:
        totals[t] = sum(r[t] for r in rows)
    cols = [Column('month', 'Month')] + [Column(t, f'{SHORT[t]} EUR', 'money') for t in TREATMENTS] + [
        Column('base', 'Base before limits EUR', 'money'), Column('assessed', 'Assessed base EUR', 'money'),
        Column('limit', 'Limit applied'), Column('kv_general', 'Health: general part EUR', 'money'),
        Column('kv_zusatz', 'Health: additional contribution EUR', 'money'), Column('kv', 'Health total EUR', 'money'),
        Column('pflege', 'Care insurance EUR', 'money'), Column('total', 'Total contribution EUR', 'money')]

    p = a.params
    payments = list(_payments(year))
    basis = [
        ('Period', f'Calendar year {year} (estimate for each of its 12 months)'),
        ('Policy', f'{p.policy_version}. Sources: {"; ".join(p.sources)}. Rules: docs/rules/sbk-contribution-rules.md'),
        ('Status', NOT_AN_ASSESSMENT),
        ('Parameters', f'Ceiling {p.bbg_monthly:,.2f} EUR/month; minimum base {p.min_monthly:,.2f} EUR/month (1/90 of Bezugsgroesse '
                       f'{p.bezugsgroesse_monthly:,.0f} EUR per day, 30-day month); health {a.kv_pct}% + additional {a.zusatz_pct}% '
                       f'= {a.kv_pct + a.zusatz_pct}%; care insurance {a.pflege_pct}%.'),
        ('Rate basis', a.rate_label),
        ('Currency', 'EUR, gross amounts at the rate stored on each payment.'),
        ('Basis', 'Estimated monthly contribution base from your income by SBK income type (not simply annual / 12).'),
        ('Gross/net', 'Gross amounts, after the costs entered for self-employed/rental income and the capital-income flat amount.'),
    ]
    basis += [('Assumption', t) for t in sbk.ASSUMPTIONS]
    excl = []
    if a.unmapped:
        excl.append('Categories not mapped to an SBK treatment, EXCLUDED: ' + '; '.join(
            f'{n} ({c} payment(s), {g:,.2f} EUR converted)' for n, c, g in a.unmapped) + '.')
    if a.unconverted_mapped:
        excl.append(f'{a.unconverted_mapped} unconverted payment(s) in mapped categories excluded, so the base may be understated.')
    if a.excluded_by_mapping:
        excl.append(f'{a.excluded_by_mapping} payment(s) in categories mapped as "not contribution-relevant" excluded.')
    excl += a.notes
    basis.append(('Excluded / missing', ' '.join(excl) if excl else 'None.'))
    notes = [f'Average total contribution per month: {a.total / 12:,.2f} EUR.',
             'Limit applied: "minimum" means the legal minimum base replaced a lower income.']
    return Report('sbk', 'SBK contribution estimate', f'Calendar year {year}', 'SBK-style estimate', cols, rows, basis, totals, notes, timezone.now())


def tax_info_summary(year=None):
    rows, qs = tax.tax_summary_rows(year)
    cols = [Column('income_type', 'Income type'), Column('country', 'Organisation country'), Column('payments', 'Payments', 'int'),
            Column('gross_eur', 'Gross EUR (converted)', 'money'), Column('original', 'Original gross by currency'),
            Column('withholding_eur', 'Withholding tax EUR (information, not credited)', 'money'),
            Column('unconverted', 'Unconverted payments', 'int'), Column('manual_rates', 'Manual-rate payments', 'int'),
            Column('flags', 'Flags')]
    payments = list(qs)
    basis = _basis(payments, year, 'Actual payments received, grouped by tax income type and country',
                   'Gross amounts as recorded; net amounts and costs are not used.')
    basis.insert(1, ('Policy', f'{tax.POLICY_VERSION}. Rules: docs/rules/income-tax-rules.md'))
    basis += [('Not applied', t) for t in tax.NOT_APPLIED]
    return Report('tax_summary', 'Tax information summary', f'Calendar year {year}' if year else 'All years', 'Information only',
                  cols, rows, basis, None, ['Information for you or your adviser; not a tax calculation.'], timezone.now())


def tax_check_report(year):
    results = tax.tax_checks(year)
    rows = [{'check': r.check, 'amount': r.amount, 'limit': r.limit, 'result': r.result, 'note': r.note} for r in results]
    cols = [Column('check', 'Check'), Column('amount', 'Amount EUR', 'money'), Column('limit', 'Rule'),
            Column('result', 'Result'), Column('note', 'Note')]
    payments = list(_payments(year))
    basis = _basis(payments, year, 'Verified statutory checks only', 'Gross EUR amounts of the mapped categories.')
    basis.insert(1, ('Policy', f'{tax.POLICY_VERSION}. Rules: docs/rules/income-tax-rules.md'))
    basis += [('Not applied', t) for t in tax.NOT_APPLIED]
    return Report('tax_checks', 'Tax checks (verified rules)', f'Calendar year {year}', 'Rule checks, no tax amount',
                  cols, rows, basis, None, ['Categories must be mapped to a tax income type (Categories page) to be included.'], timezone.now())


SPECS = {s.key: s for s in [
    ReportSpec('sbk', 'SBK contribution estimate', 'Estimated monthly SBK contributions by income type (planning estimate, not an assessment).', sbk_estimate, True),
    ReportSpec('tax_summary', 'Tax information summary', 'Income by tax income type and country, with flags (no tax calculation).', tax_info_summary),
    ReportSpec('tax_checks', 'Tax checks (verified rules)', 'Sparer-Pauschbetrag usage and private-sale Freigrenze; no tax amount.', tax_check_report, True),
]}
REPORTS.update(SPECS)
