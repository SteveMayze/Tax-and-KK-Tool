"""Reports over saved data. Pure functions: same data in, same report out (nothing is cached or stored).

Every report carries a basis block (period, currency, gross/net, actual/normalised, rate basis,
exclusions). All sums are Python Decimals over stored EUR amounts; rounding happens once, at
presentation/export (see report_csv). Unconverted payments are excluded from EUR figures and
reported as exclusions; payments without a net amount are excluded from net figures only.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from django.utils import timezone
from django.utils.translation import gettext as _, gettext_lazy, ngettext

from core.models import Payment, ReportingYear

from .aggregation import actual_totals, average_of_actuals, normalised_monthly_totals, unallocated_eur
from .i18n import month_name, number
from .normalisation import is_recurring, monthly_equivalent
from .reconciliation import build_report
from .report_filter import NO_FILTER

ZERO = Decimal(0)
CURRENCY_NOTE = gettext_lazy('EUR. Each payment is converted at the rate stored on it '
                   '(no conversion beyond the stored EUR amounts).')
ROUNDING_NOTE = gettext_lazy('Amounts are rounded to 2 decimals only when shown or exported; totals are rounded '
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
    no_match: bool = False         # a filter is active and matched no payment (Phase 30)


# ---------------------------------------------------------------- shared helpers

def _payments(year=None, flt=None):
    """The one place where the payment set of a report is chosen: year, then the organisation/category filter."""
    qs = Payment.objects.select_related('organisation', 'category', 'month__year', 'import_batch')
    qs = qs.filter(month__year__year=year) if year else qs
    return (flt or NO_FILTER).apply(qs)


def _period(year):
    return _('Calendar year %(year)s') % {'year': year} if year else _('All years')


def _rate_basis(payments):
    converted = [p for p in payments if p.conversion_status == Payment.ConversionStatus.CONVERTED]
    if not converted:
        return _('No converted payments.')
    labels = {'identity': _('EUR (rate 1)'), 'manual': _('manually entered rate')}
    counts = Counter(labels.get(p.rate_source, p.rate_source) for p in converted)
    text = '; '.join(f'{n} x {name}' for name, n in sorted(counts.items(), key=lambda kv: str(kv[0])))
    differs = sum(1 for p in converted if p.rate_date != p.payment_date and p.rate_source != 'manual')
    if differs:
        text += '; ' + _('%(n)s used the nearest earlier ECB rate (weekend/holiday)') % {'n': differs}
    return _('Stored rate per payment (EUR per 1 unit of original currency): %(text)s.') % {'text': text}


def _exclusions(payments):
    pending = [p for p in payments if p.conversion_status != Payment.ConversionStatus.CONVERTED]
    items = []
    if pending:
        by_ccy = defaultdict(lambda: ZERO)
        for p in pending:
            by_ccy[p.currency] += p.gross_amount
        amounts = ', '.join(f'{c} {number(a)}' for c, a in sorted(by_ccy.items()))
        items.append(_('%(n)s unconverted payment(s) excluded from every EUR figure (original gross: %(amounts)s).') % {
            'n': len(pending), 'amounts': amounts})
    converted = [p for p in payments if p.conversion_status == Payment.ConversionStatus.CONVERTED]
    no_net = [p for p in converted if p.net_eur is None]
    if no_net:
        items.append(_('%(n)s converted payment(s) have no net amount and are excluded from net figures only.') % {'n': len(no_net)})
    adjustments = sum(1 for p in payments if p.kind != Payment.Kind.NORMAL)
    if adjustments:
        items.append(ngettext('%(n)s correction/reversal entry included as signed amounts.',
                              '%(n)s correction/reversal entries included as signed amounts.', adjustments) % {'n': adjustments})
    return ' '.join(items) if items else _('None.')


def _basis(payments, year, mode, gross_net, extra=(), flt=None):
    filter_row = [(_('Filter'), flt.describe())] if flt is not None and flt.is_active else []
    return [(_('Period'), _period(year)), *filter_row, (_('Currency'), CURRENCY_NOTE), (_('Basis'), mode), (_('Gross/net'), gross_net),
            (_('Exchange-rate basis'), _rate_basis(payments)), (_('Excluded / missing'), _exclusions(payments)),
            (_('Rounding'), ROUNDING_NOTE), *extra]


GROSS_NET_SEPARATE = gettext_lazy('Gross and net are separate columns and are never mixed. Net totals include only '
                        'payments that have a net amount. Identity: gross = net + withholding tax + expenses + unallocated; '
                        'it is enforced when a payment is saved, so "unallocated" is 0 except for older payments (shown, not guessed). '
                        'Unallocated is computed only for payments that have a net amount.')

BREAKDOWN_COLS = [('withholding_eur', gettext_lazy('Withholding tax EUR')), ('expenses_eur', gettext_lazy('Expenses EUR')),
                  ('unallocated_eur', gettext_lazy('Unallocated EUR'))]


def _breakdown_cols():
    return [Column(k, label, 'money') for k, label in BREAKDOWN_COLS]


GAIN_LOSS_COLS = [('gains_eur', gettext_lazy('Gains EUR')), ('losses_eur', gettext_lazy('Losses EUR (signed)')),
                  ('adjustments_eur', gettext_lazy('Corrections / reversals EUR (signed)'))]
GAIN_LOSS_NOTE = gettext_lazy('Gross EUR is the signed sum: gains (normal payments above 0) + losses (normal payments below 0, shown negative) + '
                    'corrections/reversals. Losses are not offset against anything else; loss-offset rules are not implemented (unverified, docs/rules/).')


def _gain_loss_cols():
    return [Column(k, label, 'money') for k, label in GAIN_LOSS_COLS]


def _gain_loss(t):
    return {'gains_eur': t.gains_eur, 'losses_eur': t.losses_eur, 'adjustments_eur': t.adjustments_eur}


def _breakdown(t):
    return {'withholding_eur': t.withholding_eur, 'expenses_eur': t.expenses_eur, 'unallocated_eur': t.unallocated_eur}


def _make(key, title, year, mode, columns, rows, payments, totals=None, notes=(), extra=(), gross_net=GROSS_NET_SEPARATE,
          flt=None):
    notes = list(notes)
    no_match = bool(flt is not None and flt.is_active and not payments)
    if no_match:
        notes.append(NO_MATCH)
    return Report(key, title, _period(year), mode, columns, rows, _basis(payments, year, mode, gross_net, extra, flt),
                  totals, notes, timezone.now(), no_match)


def _group(payments, keyfunc):
    groups = defaultdict(list)
    for p in payments:
        groups[keyfunc(p)].append(p)
    return groups


# ---------------------------------------------------------------- reports

NO_MATCH = gettext_lazy('No payments match this filter')
ACTUAL = gettext_lazy('Actual payments received (not normalised)')


def annual_summary(year=None, flt=None):
    """One row per reporting year: EUR gross and net totals and annual total / 12."""
    payments = list(_payments(year, flt))
    rows = []
    for key, group in sorted(_group(payments, lambda p: p.month.year.year).items()):
        t = actual_totals(group)
        avg = average_of_actuals(t)
        rows.append({
            'year': str(key), 'payments': t.payment_count, 'months': len({p.month_id for p in group}),
            'gross_eur': t.gross_eur, 'net_eur': t.net_eur, 'gross_12': avg['gross_eur'], 'net_12': avg['net_eur'],
            'net_missing': t.net_missing_count, 'unconverted': t.unconverted_count, **_breakdown(t), **_gain_loss(t)})
    cols = [Column('year', _('Year')), Column('payments', _('Payments'), 'int'), Column('months', _('Months with payments'), 'int'),
            *_gain_loss_cols(), Column('gross_eur', _('Gross EUR (signed sum)'), 'money'), Column('net_eur', _('Net EUR'), 'money'), *_breakdown_cols(),
            Column('gross_12', _('Gross EUR / 12'), 'money'), Column('net_12', _('Net EUR / 12'), 'money'),
            Column('net_missing', _('Payments without net'), 'int'), Column('unconverted', _('Unconverted payments'), 'int')]
    return _make('annual', _('Annual summary'), year, ACTUAL, cols, rows, payments,
                 notes=[GAIN_LOSS_NOTE,
                        _('"/ 12" is the annual actual total divided by 12 (always 12, even for a partial year). '
                          'It is an average of actuals, not a recurring monthly figure, and not an official SBK or tax calculation.')], flt=flt)


def monthly_breakdown(year, flt=None):
    """All 12 months of a year, including empty ones: actual gross and net EUR."""
    payments = list(_payments(year, flt))
    by_month = _group(payments, lambda p: p.month.month)
    rows, all_totals = [], actual_totals(payments)
    for m in range(1, 13):
        t = actual_totals(by_month[m])
        rows.append({'month': f'{year}-{m:02d} {month_name(m)}', 'payments': t.payment_count,
                     'gross_eur': t.gross_eur, 'net_eur': t.net_eur, 'net_missing': t.net_missing_count,
                     'unconverted': t.unconverted_count, **_breakdown(t)})
    cols = [Column('month', _('Month')), Column('payments', _('Payments'), 'int'), Column('gross_eur', _('Gross EUR'), 'money'),
            Column('net_eur', _('Net EUR'), 'money'), *_breakdown_cols(), Column('net_missing', _('Payments without net'), 'int'),
            Column('unconverted', _('Unconverted payments'), 'int')]
    totals = {'month': _('Year total'), 'payments': all_totals.payment_count, 'gross_eur': all_totals.gross_eur,
              'net_eur': all_totals.net_eur, 'net_missing': all_totals.net_missing_count,
              'unconverted': all_totals.unconverted_count, **_breakdown(all_totals)}
    return _make('monthly', _('Monthly breakdown'), year, ACTUAL, cols, rows, payments, totals, flt=flt)


def _group_report(key, title, year, label, keyfunc, name_label, flt=None):
    payments = list(_payments(year, flt))
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
    cols = [Column('name', name_label), Column('payments', _('Payments'), 'int'), *_gain_loss_cols(),
            Column('gross_eur', _('Gross EUR (signed sum)'), 'money'),
            Column('net_eur', _('Net EUR'), 'money'), *_breakdown_cols(), Column('share', _('Share of gross'), 'pct'),
            Column('net_missing', _('Payments without net'), 'int'), Column('unconverted', _('Unconverted payments'), 'int')]
    totals = {'name': _('Total'), 'payments': total.payment_count, 'gross_eur': total.gross_eur, 'net_eur': total.net_eur,
              'share': Decimal(1) if total.gross_eur else None, 'net_missing': total.net_missing_count,
              'unconverted': total.unconverted_count, **_breakdown(total), **_gain_loss(total)}
    return _make(key, title, year, ACTUAL, cols, rows, payments, totals,
                 notes=[_('Share of gross = group gross EUR / total gross EUR (converted payments only).'), GAIN_LOSS_NOTE,
                        *([_('A filter is active: shares are relative to the filtered total, so they add up to 100 % within the filter.')]
                          if flt is not None and flt.is_active else [])], flt=flt)


def by_organisation(year=None, flt=None):
    return _group_report('organisation', _('By organisation'), year, 'organisation', lambda p: p.organisation.name, _('Organisation'), flt)


def by_category(year=None, flt=None):
    return _group_report('category', _('By category'), year, 'category', lambda p: p.category.name, _('Category'), flt)


def original_currency_summary(year=None, flt=None):
    """Totals in each original currency (no conversion), next to their EUR equivalents."""
    payments = list(_payments(year, flt))
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
    cols = [Column('currency', _('Original currency')), Column('payments', _('Payments'), 'int'),
            Column('gross_original', _('Gross (original currency)'), 'money'),
            Column('net_original', _('Net (original currency)'), 'money'),
            Column('net_original_missing', _('Payments without net'), 'int'),
            Column('withholding_original', _('Withholding tax (original currency)'), 'money'),
            Column('expenses_original', _('Expenses (original currency)'), 'money'),
            Column('unallocated_original', _('Unallocated (original currency)'), 'money'),
            Column('converted', _('Converted payments'), 'int'), Column('gross_eur', _('Gross EUR (converted only)'), 'money'),
            Column('net_eur', _('Net EUR (converted only)'), 'money'), *_breakdown_cols(),
            Column('unconverted', _('Unconverted payments'), 'int')]
    return _make('currency', _('Original-currency summary'), year,
                 _('Actual payments received; original-currency columns include every payment'), cols, rows, payments,
                 notes=[_('Original-currency columns are as reported and include unconverted payments; '
                          'EUR columns include converted payments only. Different currencies are never added together.')], flt=flt)


def normalised_monthly(year, flt=None):
    """Per month: sum of monthly equivalents of recurring payments. One-off items are excluded."""
    payments = list(_payments(year, flt))
    by_month = _group(payments, lambda p: p.month.month)
    rows = []
    for m in range(1, 13):
        n = normalised_monthly_totals(by_month[m])
        rows.append({'month': f'{year}-{m:02d} {month_name(m)}', 'gross_monthly': n.gross_monthly_eur,
                     'net_monthly': n.net_monthly_eur, 'recurring': n.recurring_count,
                     'one_off': n.one_off_excluded_count, 'net_missing': n.net_missing_count,
                     'unconverted': n.unconverted_count})
    cols = [Column('month', _('Month')), Column('gross_monthly', _('Gross monthly equivalent EUR'), 'money'),
            Column('net_monthly', _('Net monthly equivalent EUR'), 'money'), Column('recurring', _('Recurring payments'), 'int'),
            Column('one_off', _('One-off items excluded'), 'int'), Column('net_missing', _('Recurring without net'), 'int'),
            Column('unconverted', _('Unconverted payments'), 'int')]
    return _make('normalised', _('Normalised monthly recurring income'), year,
                 _('Normalised: monthly equivalents of recurring payments (monthly /1, quarterly /3, half-yearly /6, yearly /12)'),
                 cols, rows, payments,
                 notes=[_('One-off/irregular items are never treated as recurring and are excluded here (counted per month).'),
                        _('No year total is given: adding months of equivalents would count some payments repeatedly. '
                          'For an annual figure use the annual summary (actual total / 12).')], flt=flt)


def payment_level(year=None, flt=None):
    payments = list(_payments(year, flt).order_by('payment_date', 'id'))
    rows = []
    for p in payments:
        conv = p.conversion_status == Payment.ConversionStatus.CONVERTED
        rows.append({
            'id': p.pk, 'date': p.payment_date, 'month': f'{p.month.year.year}-{p.month.month:02d}',
            'organisation': p.organisation.name, 'category': p.category.name, 'kind': p.get_kind_display(),
            'frequency': p.get_frequency_display(), 'currency': p.currency, 'gross_original': p.gross_amount,
            'net_original': p.net_amount, 'status': _('converted') if conv else _('NOT CONVERTED'),
            'rate': p.rate, 'rate_date': p.rate_date, 'rate_source': p.rate_source,
            'gross_eur': p.gross_eur, 'net_eur': p.net_eur,
            'withholding_original': p.withholding_tax, 'expenses_original': p.expenses,
            'unallocated_original': p.unallocated,
            'withholding_eur': p.withholding_tax_eur, 'expenses_eur': p.expenses_eur,
            'unallocated_eur': unallocated_eur(p) if conv and p.net_eur is not None else None,
            'monthly_equiv': monthly_equivalent(p.gross_eur, p.frequency) if conv and is_recurring(p.frequency) else None,
            'period_start': p.income_period_start, 'period_end': p.income_period_end,
            'import_batch': p.import_batch_id, 'comment': p.comment})
    cols = [Column('id', _('ID'), 'int'), Column('date', _('Payment date'), 'date'), Column('month', _('Reporting month')),
            Column('organisation', _('Organisation')), Column('category', _('Category')), Column('kind', _('Type')),
            Column('frequency', _('Frequency')), Column('currency', _('Currency')),
            Column('gross_original', _('Gross (original)'), 'money'), Column('net_original', _('Net (original)'), 'money'),
            Column('status', _('Conversion')), Column('rate', _('Rate (EUR per 1 unit)'), 'rate'),
            Column('rate_date', _('Rate date'), 'date'), Column('rate_source', _('Rate source')),
            Column('withholding_original', _('Withholding tax (original)'), 'money'),
            Column('expenses_original', _('Expenses (original)'), 'money'),
            Column('unallocated_original', _('Unallocated (original)'), 'money'),
            Column('gross_eur', _('Gross EUR'), 'money'), Column('net_eur', _('Net EUR'), 'money'), *_breakdown_cols(),
            Column('monthly_equiv', _('Monthly equivalent gross EUR (recurring only)'), 'money'),
            Column('period_start', _('Income period start'), 'date'), Column('period_end', _('Income period end'), 'date'),
            Column('import_batch', _('Import batch'), 'int'), Column('comment', _('Comment'))]
    total = actual_totals(payments)
    totals = {'organisation': _('Total (converted payments)'), 'gross_eur': total.gross_eur, 'net_eur': total.net_eur,
              **_breakdown(total)}
    return _make('payments', _('Payment-level detail'), year, ACTUAL, cols, rows, payments, totals,
                 notes=[_('Unconverted payments are listed (original amounts only) but contribute nothing to EUR columns or totals.')], flt=flt)


def cross_table(year=None, flt=None):
    """Organisation x category: signed gross EUR of the converted payments per pairing (blank = no payment)."""
    payments = list(_payments(year, flt))
    cats = sorted({(p.category_id, p.category.name) for p in payments}, key=lambda c: (c[1].lower(), c[0]))
    orgs = sorted({(p.organisation_id, p.organisation.name) for p in payments}, key=lambda o: (o[1].lower(), o[0]))
    cells = _group(payments, lambda p: (p.organisation_id, p.category_id))
    rows = []
    for oid, oname in orgs:
        row = {'organisation': oname}
        for cid, _cname in cats:
            group = cells.get((oid, cid))
            row[f'cat_{cid}'] = actual_totals(group).gross_eur if group else None
        t = actual_totals([p for p in payments if p.organisation_id == oid])
        row.update({'payments': t.payment_count, 'gross_eur': t.gross_eur})
        rows.append(row)
    total = actual_totals(payments)
    totals = {'organisation': _('Total'), 'payments': total.payment_count, 'gross_eur': total.gross_eur}
    for cid, _cname in cats:
        totals[f'cat_{cid}'] = actual_totals([p for p in payments if p.category_id == cid]).gross_eur
    cols = [Column('organisation', _('Organisation')), *[Column(f'cat_{cid}', cname, 'money') for cid, cname in cats],
            Column('payments', _('Payments'), 'int'), Column('gross_eur', _('Gross EUR (signed sum)'), 'money')]
    return _make('cross', _('Organisation by category'), year, ACTUAL, cols, rows, payments, totals,
                 notes=[_('Each cell is the signed gross EUR of the converted payments of that organisation in that category; '
                          'a blank cell means no payment (a zero means payments that add up to zero). Row and column totals '
                          'are over the same payments, so every pairing adds up to the total.')], flt=flt)


def reconciliation(year=None, flt=None):
    r = build_report(year, flt)
    payments = list(_payments(year, flt))
    sections = [(_('Not converted'), r.pending), (_('Manually entered rate'), r.manual_rates),
                (_('Rate date differs from payment date'), r.date_differs), (_('No net amount'), r.missing_net),
                (_('Inconsistent stored values'), r.inconsistent),
                (_('Gross differs from net + withholding tax + expenses (unallocated)'), r.unallocated)]
    rows = []
    for label, items in sections:
        for p in items:
            rows.append({'issue': label, 'id': p.pk, 'date': p.payment_date, 'organisation': p.organisation.name,
                         'currency': p.currency, 'gross_original': p.gross_amount,
                         'rate': p.rate, 'rate_date': p.rate_date, 'rate_source': p.rate_source})
    cols = [Column('issue', _('Issue')), Column('id', _('Payment ID'), 'int'), Column('date', _('Payment date'), 'date'),
            Column('organisation', _('Organisation')), Column('currency', _('Currency')),
            Column('gross_original', _('Gross (original)'), 'money'), Column('rate', _('Rate'), 'rate'),
            Column('rate_date', _('Rate date'), 'date'), Column('rate_source', _('Rate source'))]
    summary = {label: len(items) for label, items in sections}
    return _make('reconciliation', _('Missing data and reconciliation'), year,
                 _('Data-quality checks over stored data (no financial totals)'), cols, rows, payments,
                 notes=[_('A payment can appear under several issues. Counts: ') +
                        '; '.join(f'{k}: {v}' for k, v in summary.items()) + '.'],
                 gross_net=_('Not applicable.'), flt=flt)


# ---------------------------------------------------------------- registry

@dataclass(frozen=True)
class ReportSpec:
    key: str
    title: str
    description: str
    build: object
    needs_year: bool = False
    supports_filter: bool = True        # False: a whole-person assessment that cannot be computed over part of the income


REPORTS = {s.key: s for s in [
    ReportSpec('annual', gettext_lazy('Annual summary'), gettext_lazy('EUR gross and net per year, with annual total / 12.'), annual_summary),
    ReportSpec('monthly', gettext_lazy('Monthly breakdown'), gettext_lazy('All 12 months of a year: payments, gross and net EUR.'), monthly_breakdown, True),
    ReportSpec('payments', gettext_lazy('Payment-level detail'), gettext_lazy('Every payment with original amount, rate and EUR amounts.'), payment_level),
    ReportSpec('organisation', gettext_lazy('By organisation'), gettext_lazy('Gross and net EUR per organisation.'), by_organisation),
    ReportSpec('category', gettext_lazy('By category'), gettext_lazy('Gross and net EUR per income category.'), by_category),
    ReportSpec('cross', gettext_lazy('Organisation by category'), gettext_lazy('Gross EUR for every organisation and category pairing at once.'), cross_table),
    ReportSpec('currency', gettext_lazy('Original-currency summary'), gettext_lazy('Totals in each original currency beside their EUR equivalents.'), original_currency_summary),
    ReportSpec('normalised', gettext_lazy('Normalised monthly recurring income'), gettext_lazy('Monthly equivalents of recurring payments (one-offs excluded).'), normalised_monthly, True),
    ReportSpec('reconciliation', gettext_lazy('Missing data and reconciliation'), gettext_lazy('Unconverted, manual-rate, date-differs, no-net and inconsistent payments.'), reconciliation),
]}


def available_years():
    return list(ReportingYear.objects.values_list('year', flat=True))

from . import policy_reports  # noqa: E402,F401  registers the policy-based reports in REPORTS
