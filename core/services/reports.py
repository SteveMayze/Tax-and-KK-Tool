"""Reports over saved data. Pure functions: same data in, same report out (nothing is cached or stored).

Every report carries a basis block (period, currency, gross/net, actual/normalised, rate basis,
exclusions). All sums are Python Decimals over stored EUR amounts; rounding happens once, at
presentation/export (see report_csv). Unconverted payments are excluded from EUR figures and
reported as exclusions; payments without a net amount are excluded from net figures only.
"""
import calendar
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from django.utils import timezone

from core.models import Payment, ReportingYear

from .aggregation import actual_totals, average_of_actuals, normalised_monthly_totals, unallocated_eur
from .normalisation import is_recurring, monthly_equivalent
from .reconciliation import build_report

ZERO = Decimal(0)
CURRENCY_NOTE = ('EUR. Each payment is converted at the rate stored on it '
                 '(no conversion beyond the stored EUR amounts).')
ROUNDING_NOTE = ('Amounts are rounded to 2 decimals only when shown or exported; totals are rounded '
                 'once from unrounded sums, so they can differ by a cent from the sum of rounded rows.')


@dataclass
class Column:
    key: str
    label: str
    kind: str = 'text'   # text | int | money | rate | date | pct


@dataclass
class Report:
    key: str
    title: str
    period: str
    mode: str                      # "Actual payments received" / "Normalised recurring monthly" / ...
    columns: list
    rows: list
    basis: list = field(default_factory=list)       # [(label, text)]
    totals: dict | None = None
    notes: list = field(default_factory=list)
    generated_at: object = None


# ---------------------------------------------------------------- shared helpers

def _payments(year=None):
    qs = Payment.objects.select_related('organisation', 'category', 'month__year', 'import_batch')
    return qs.filter(month__year__year=year) if year else qs


def _period(year):
    return f'Calendar year {year}' if year else 'All years'


def _rate_basis(payments):
    converted = [p for p in payments if p.conversion_status == Payment.ConversionStatus.CONVERTED]
    if not converted:
        return 'No converted payments.'
    labels = {'identity': 'EUR (rate 1)', 'manual': 'manually entered rate'}
    counts = Counter(labels.get(p.rate_source, p.rate_source) for p in converted)
    text = '; '.join(f'{n} x {name}' for name, n in sorted(counts.items()))
    differs = sum(1 for p in converted if p.rate_date != p.payment_date and p.rate_source != 'manual')
    if differs:
        text += f'; {differs} used the nearest earlier ECB rate (weekend/holiday)'
    return f'Stored rate per payment (EUR per 1 unit of original currency): {text}.'


def _exclusions(payments):
    pending = [p for p in payments if p.conversion_status != Payment.ConversionStatus.CONVERTED]
    items = []
    if pending:
        by_ccy = defaultdict(lambda: ZERO)
        for p in pending:
            by_ccy[p.currency] += p.gross_amount
        amounts = ', '.join(f'{c} {a:,.2f}' for c, a in sorted(by_ccy.items()))
        items.append(f'{len(pending)} unconverted payment(s) excluded from every EUR figure (original gross: {amounts}).')
    converted = [p for p in payments if p.conversion_status == Payment.ConversionStatus.CONVERTED]
    no_net = [p for p in converted if p.net_eur is None]
    if no_net:
        items.append(f'{len(no_net)} converted payment(s) have no net amount and are excluded from net figures only.')
    adjustments = sum(1 for p in payments if p.kind != Payment.Kind.NORMAL)
    if adjustments:
        items.append(f'{adjustments} correction/reversal entr{"y" if adjustments == 1 else "ies"} included as signed amounts.')
    return ' '.join(items) if items else 'None.'


def _basis(payments, year, mode, gross_net, extra=()):
    return [('Period', _period(year)), ('Currency', CURRENCY_NOTE), ('Basis', mode), ('Gross/net', gross_net),
            ('Exchange-rate basis', _rate_basis(payments)), ('Excluded / missing', _exclusions(payments)),
            ('Rounding', ROUNDING_NOTE), *extra]


GROSS_NET_SEPARATE = ('Gross and net are separate columns and are never mixed. Net totals include only '
                      'payments that have a net amount. Identity: gross = net + withholding tax + expenses + unallocated; '
                      'it is enforced when a payment is saved, so "unallocated" is 0 except for older payments (shown, not guessed). '
                      'Unallocated is computed only for payments that have a net amount.')

BREAKDOWN_COLS = [('withholding_eur', 'Withholding tax EUR'), ('expenses_eur', 'Expenses EUR'),
                  ('unallocated_eur', 'Unallocated EUR')]


def _breakdown_cols():
    return [Column(k, label, 'money') for k, label in BREAKDOWN_COLS]


GAIN_LOSS_COLS = [('gains_eur', 'Gains EUR'), ('losses_eur', 'Losses EUR (signed)'), ('adjustments_eur', 'Corrections / reversals EUR (signed)')]
GAIN_LOSS_NOTE = ('Gross EUR is the signed sum: gains (normal payments above 0) + losses (normal payments below 0, shown negative) + '
                  'corrections/reversals. Losses are not offset against anything else; loss-offset rules are not implemented (unverified, docs/rules/).')


def _gain_loss_cols():
    return [Column(k, label, 'money') for k, label in GAIN_LOSS_COLS]


def _gain_loss(t):
    return {'gains_eur': t.gains_eur, 'losses_eur': t.losses_eur, 'adjustments_eur': t.adjustments_eur}


def _breakdown(t):
    return {'withholding_eur': t.withholding_eur, 'expenses_eur': t.expenses_eur, 'unallocated_eur': t.unallocated_eur}


def _make(key, title, year, mode, columns, rows, payments, totals=None, notes=(), extra=(), gross_net=GROSS_NET_SEPARATE):
    return Report(key, title, _period(year), mode, columns, rows, _basis(payments, year, mode, gross_net, extra),
                  totals, list(notes), timezone.now())


def _group(payments, keyfunc):
    groups = defaultdict(list)
    for p in payments:
        groups[keyfunc(p)].append(p)
    return groups


# ---------------------------------------------------------------- reports

ACTUAL = 'Actual payments received (not normalised)'


def annual_summary(year=None):
    """One row per reporting year: EUR gross and net totals and annual total / 12."""
    payments = list(_payments(year))
    rows = []
    for key, group in sorted(_group(payments, lambda p: p.month.year.year).items()):
        t = actual_totals(group)
        avg = average_of_actuals(t)
        rows.append({
            'year': str(key), 'payments': t.payment_count, 'months': len({p.month_id for p in group}),
            'gross_eur': t.gross_eur, 'net_eur': t.net_eur, 'gross_12': avg['gross_eur'], 'net_12': avg['net_eur'],
            'net_missing': t.net_missing_count, 'unconverted': t.unconverted_count, **_breakdown(t), **_gain_loss(t)})
    cols = [Column('year', 'Year'), Column('payments', 'Payments', 'int'), Column('months', 'Months with payments', 'int'),
            *_gain_loss_cols(), Column('gross_eur', 'Gross EUR (signed sum)', 'money'), Column('net_eur', 'Net EUR', 'money'), *_breakdown_cols(),
            Column('gross_12', 'Gross EUR / 12', 'money'), Column('net_12', 'Net EUR / 12', 'money'),
            Column('net_missing', 'Payments without net', 'int'), Column('unconverted', 'Unconverted payments', 'int')]
    return _make('annual', 'Annual summary', year, ACTUAL, cols, rows, payments,
                 notes=[GAIN_LOSS_NOTE,
                        '"/ 12" is the annual actual total divided by 12 (always 12, even for a partial year). '
                        'It is an average of actuals, not a recurring monthly figure, and not an official SBK or tax calculation.'])


def monthly_breakdown(year):
    """All 12 months of a year, including empty ones: actual gross and net EUR."""
    payments = list(_payments(year))
    by_month = _group(payments, lambda p: p.month.month)
    rows, all_totals = [], actual_totals(payments)
    for m in range(1, 13):
        t = actual_totals(by_month[m])
        rows.append({'month': f'{year}-{m:02d} {calendar.month_name[m]}', 'payments': t.payment_count,
                     'gross_eur': t.gross_eur, 'net_eur': t.net_eur, 'net_missing': t.net_missing_count,
                     'unconverted': t.unconverted_count, **_breakdown(t)})
    cols = [Column('month', 'Month'), Column('payments', 'Payments', 'int'), Column('gross_eur', 'Gross EUR', 'money'),
            Column('net_eur', 'Net EUR', 'money'), *_breakdown_cols(), Column('net_missing', 'Payments without net', 'int'),
            Column('unconverted', 'Unconverted payments', 'int')]
    totals = {'month': 'Year total', 'payments': all_totals.payment_count, 'gross_eur': all_totals.gross_eur,
              'net_eur': all_totals.net_eur, 'net_missing': all_totals.net_missing_count,
              'unconverted': all_totals.unconverted_count, **_breakdown(all_totals)}
    return _make('monthly', 'Monthly breakdown', year, ACTUAL, cols, rows, payments, totals)


def _group_report(key, title, year, label, keyfunc, name_label):
    payments = list(_payments(year))
    groups = _group(payments, keyfunc)
    total = actual_totals(payments)
    rows = []
    for name, group in groups.items():
        t = actual_totals(group)
        share = (t.gross_eur / total.gross_eur) if total.gross_eur else None
        rows.append({'name': name, 'payments': t.payment_count, 'gross_eur': t.gross_eur, 'net_eur': t.net_eur,
                     'share': share, 'net_missing': t.net_missing_count, 'unconverted': t.unconverted_count,
                     **_breakdown(t), **_gain_loss(t)})
    rows.sort(key=lambda r: (-r['gross_eur'], r['name'].lower()))
    cols = [Column('name', name_label), Column('payments', 'Payments', 'int'), *_gain_loss_cols(),
            Column('gross_eur', 'Gross EUR (signed sum)', 'money'),
            Column('net_eur', 'Net EUR', 'money'), *_breakdown_cols(), Column('share', 'Share of gross', 'pct'),
            Column('net_missing', 'Payments without net', 'int'), Column('unconverted', 'Unconverted payments', 'int')]
    totals = {'name': 'Total', 'payments': total.payment_count, 'gross_eur': total.gross_eur, 'net_eur': total.net_eur,
              'share': Decimal(1) if total.gross_eur else None, 'net_missing': total.net_missing_count,
              'unconverted': total.unconverted_count, **_breakdown(total), **_gain_loss(total)}
    return _make(key, title, year, ACTUAL, cols, rows, payments, totals,
                 notes=['Share of gross = group gross EUR / total gross EUR (converted payments only).', GAIN_LOSS_NOTE])


def by_organisation(year=None):
    return _group_report('organisation', 'By organisation', year, 'organisation', lambda p: p.organisation.name, 'Organisation')


def by_category(year=None):
    return _group_report('category', 'By category', year, 'category', lambda p: p.category.name, 'Category')


def original_currency_summary(year=None):
    """Totals in each original currency (no conversion), next to their EUR equivalents."""
    payments = list(_payments(year))
    rows = []
    for ccy, group in sorted(_group(payments, lambda p: p.currency).items()):
        t = actual_totals(group)
        rows.append({
            'currency': ccy, 'payments': len(group),
            'gross_original': sum((p.gross_amount for p in group), ZERO),
            'net_original': sum((p.net_amount for p in group if p.net_amount is not None), ZERO),
            'net_original_missing': sum(1 for p in group if p.net_amount is None),
            'converted': len(group) - t.unconverted_count, 'gross_eur': t.gross_eur, 'net_eur': t.net_eur,
            'unconverted': t.unconverted_count,
            'withholding_original': sum((p.withholding_tax for p in group), ZERO),
            'expenses_original': sum((p.expenses for p in group), ZERO),
            'unallocated_original': sum((p.unallocated for p in group if p.unallocated is not None), ZERO),
            **_breakdown(t)})
    cols = [Column('currency', 'Original currency'), Column('payments', 'Payments', 'int'),
            Column('gross_original', 'Gross (original currency)', 'money'),
            Column('net_original', 'Net (original currency)', 'money'),
            Column('net_original_missing', 'Payments without net', 'int'),
            Column('withholding_original', 'Withholding tax (original currency)', 'money'),
            Column('expenses_original', 'Expenses (original currency)', 'money'),
            Column('unallocated_original', 'Unallocated (original currency)', 'money'),
            Column('converted', 'Converted payments', 'int'), Column('gross_eur', 'Gross EUR (converted only)', 'money'),
            Column('net_eur', 'Net EUR (converted only)', 'money'), *_breakdown_cols(),
            Column('unconverted', 'Unconverted payments', 'int')]
    return _make('currency', 'Original-currency summary', year,
                 'Actual payments received; original-currency columns include every payment', cols, rows, payments,
                 notes=['Original-currency columns are as reported and include unconverted payments; '
                        'EUR columns include converted payments only. Different currencies are never added together.'])


def normalised_monthly(year):
    """Per month: sum of monthly equivalents of recurring payments. One-off items are excluded."""
    payments = list(_payments(year))
    by_month = _group(payments, lambda p: p.month.month)
    rows = []
    for m in range(1, 13):
        n = normalised_monthly_totals(by_month[m])
        rows.append({'month': f'{year}-{m:02d} {calendar.month_name[m]}', 'gross_monthly': n.gross_monthly_eur,
                     'net_monthly': n.net_monthly_eur, 'recurring': n.recurring_count,
                     'one_off': n.one_off_excluded_count, 'net_missing': n.net_missing_count,
                     'unconverted': n.unconverted_count})
    cols = [Column('month', 'Month'), Column('gross_monthly', 'Gross monthly equivalent EUR', 'money'),
            Column('net_monthly', 'Net monthly equivalent EUR', 'money'), Column('recurring', 'Recurring payments', 'int'),
            Column('one_off', 'One-off items excluded', 'int'), Column('net_missing', 'Recurring without net', 'int'),
            Column('unconverted', 'Unconverted payments', 'int')]
    return _make('normalised', 'Normalised monthly recurring income', year,
                 'Normalised: monthly equivalents of recurring payments (monthly /1, quarterly /3, half-yearly /6, yearly /12)',
                 cols, rows, payments,
                 notes=['One-off/irregular items are never treated as recurring and are excluded here (counted per month).',
                        'No year total is given: adding months of equivalents would count some payments repeatedly. '
                        'For an annual figure use the annual summary (actual total / 12).'])


def payment_level(year=None):
    payments = list(_payments(year).order_by('payment_date', 'id'))
    rows = []
    for p in payments:
        conv = p.conversion_status == Payment.ConversionStatus.CONVERTED
        rows.append({
            'id': p.pk, 'date': p.payment_date, 'month': f'{p.month.year.year}-{p.month.month:02d}',
            'organisation': p.organisation.name, 'category': p.category.name, 'kind': p.get_kind_display(),
            'frequency': p.get_frequency_display(), 'currency': p.currency, 'gross_original': p.gross_amount,
            'net_original': p.net_amount, 'status': 'converted' if conv else 'NOT CONVERTED',
            'rate': p.rate, 'rate_date': p.rate_date, 'rate_source': p.rate_source,
            'gross_eur': p.gross_eur, 'net_eur': p.net_eur,
            'withholding_original': p.withholding_tax, 'expenses_original': p.expenses,
            'unallocated_original': p.unallocated,
            'withholding_eur': p.withholding_tax_eur, 'expenses_eur': p.expenses_eur,
            'unallocated_eur': unallocated_eur(p) if conv and p.net_eur is not None else None,
            'monthly_equiv': monthly_equivalent(p.gross_eur, p.frequency) if conv and is_recurring(p.frequency) else None,
            'period_start': p.income_period_start, 'period_end': p.income_period_end,
            'import_batch': p.import_batch_id, 'comment': p.comment})
    cols = [Column('id', 'ID', 'int'), Column('date', 'Payment date', 'date'), Column('month', 'Reporting month'),
            Column('organisation', 'Organisation'), Column('category', 'Category'), Column('kind', 'Type'),
            Column('frequency', 'Frequency'), Column('currency', 'Currency'),
            Column('gross_original', 'Gross (original)', 'money'), Column('net_original', 'Net (original)', 'money'),
            Column('status', 'Conversion'), Column('rate', 'Rate (EUR per 1 unit)', 'rate'),
            Column('rate_date', 'Rate date', 'date'), Column('rate_source', 'Rate source'),
            Column('withholding_original', 'Withholding tax (original)', 'money'),
            Column('expenses_original', 'Expenses (original)', 'money'),
            Column('unallocated_original', 'Unallocated (original)', 'money'),
            Column('gross_eur', 'Gross EUR', 'money'), Column('net_eur', 'Net EUR', 'money'), *_breakdown_cols(),
            Column('monthly_equiv', 'Monthly equivalent gross EUR (recurring only)', 'money'),
            Column('period_start', 'Income period start', 'date'), Column('period_end', 'Income period end', 'date'),
            Column('import_batch', 'Import batch', 'int'), Column('comment', 'Comment')]
    total = actual_totals(payments)
    totals = {'organisation': 'Total (converted payments)', 'gross_eur': total.gross_eur, 'net_eur': total.net_eur,
              **_breakdown(total)}
    return _make('payments', 'Payment-level detail', year, ACTUAL, cols, rows, payments, totals,
                 notes=['Unconverted payments are listed (original amounts only) but contribute nothing to EUR columns or totals.'])


def reconciliation(year=None):
    r = build_report(year)
    payments = list(_payments(year))
    sections = [('Not converted', r.pending), ('Manually entered rate', r.manual_rates),
                ('Rate date differs from payment date', r.date_differs), ('No net amount', r.missing_net),
                ('Inconsistent stored values', r.inconsistent),
                ('Gross differs from net + withholding tax + expenses (unallocated)', r.unallocated)]
    rows = []
    for label, items in sections:
        for p in items:
            rows.append({'issue': label, 'id': p.pk, 'date': p.payment_date, 'organisation': p.organisation.name,
                         'currency': p.currency, 'gross_original': p.gross_amount,
                         'rate': p.rate, 'rate_date': p.rate_date, 'rate_source': p.rate_source})
    cols = [Column('issue', 'Issue'), Column('id', 'Payment ID', 'int'), Column('date', 'Payment date', 'date'),
            Column('organisation', 'Organisation'), Column('currency', 'Currency'),
            Column('gross_original', 'Gross (original)', 'money'), Column('rate', 'Rate', 'rate'),
            Column('rate_date', 'Rate date', 'date'), Column('rate_source', 'Rate source')]
    summary = {label: len(items) for label, items in sections}
    return _make('reconciliation', 'Missing data and reconciliation', year,
                 'Data-quality checks over stored data (no financial totals)', cols, rows, payments,
                 notes=['A payment can appear under several issues. Counts: ' +
                        '; '.join(f'{k}: {v}' for k, v in summary.items()) + '.'],
                 gross_net='Not applicable.')


# ---------------------------------------------------------------- registry

@dataclass(frozen=True)
class ReportSpec:
    key: str
    title: str
    description: str
    build: object
    needs_year: bool = False


REPORTS = {s.key: s for s in [
    ReportSpec('annual', 'Annual summary', 'EUR gross and net per year, with annual total / 12.', annual_summary),
    ReportSpec('monthly', 'Monthly breakdown', 'All 12 months of a year: payments, gross and net EUR.', monthly_breakdown, True),
    ReportSpec('payments', 'Payment-level detail', 'Every payment with original amount, rate and EUR amounts.', payment_level),
    ReportSpec('organisation', 'By organisation', 'Gross and net EUR per organisation.', by_organisation),
    ReportSpec('category', 'By category', 'Gross and net EUR per income category.', by_category),
    ReportSpec('currency', 'Original-currency summary', 'Totals in each original currency beside their EUR equivalents.', original_currency_summary),
    ReportSpec('normalised', 'Normalised monthly recurring income', 'Monthly equivalents of recurring payments (one-offs excluded).', normalised_monthly, True),
    ReportSpec('reconciliation', 'Missing data and reconciliation', 'Unconverted, manual-rate, date-differs, no-net and inconsistent payments.', reconciliation),
]}


def available_years():
    return list(ReportingYear.objects.values_list('year', flat=True))

from . import policy_reports  # noqa: E402,F401  registers the policy-based reports in REPORTS
