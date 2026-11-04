"""Income as recorded, for the tax adviser (Phase 40, ADR 0036).

Groups the saved payments by their STORED category name, STORED organisation name and ORIGINAL currency, and
nothing else. No tax income type, no SBK treatment, no organisation country and no inferred country is read here;
no legal interpretation is made. Original-currency amounts of different currencies are never added together; EUR
figures are the sums of the amounts stored on the payments (unconverted payments are left out and counted).
All sums are Decimals; rounding happens only when shown or exported.
"""
from collections import defaultdict
from decimal import Decimal

from django.utils.translation import gettext as _

from core.models import IncomeCategory, Payment

from . import report_sources
from .reports import ROUNDING_NOTE, Column, Table, _period, _rate_basis

ZERO = Decimal(0)
CONVERTED = Payment.ConversionStatus.CONVERTED


def _converted(group):
    return [p for p in group if p.conversion_status == CONVERTED]


def _sums(group):
    """The amount columns shared by tables 1 to 3 for one group of payments."""
    conv = _converted(group)
    return {
        'payments': len(group),
        'gross': sum((p.gross_amount for p in group), ZERO),
        'negative': sum((p.gross_amount for p in group if p.kind == Payment.Kind.NORMAL and p.gross_amount < 0), ZERO),
        'withholding': sum((p.withholding_tax for p in group), ZERO),
        'gross_eur': sum((p.gross_eur for p in conv), ZERO),
        'withholding_eur': sum((p.withholding_tax_eur or ZERO for p in conv), ZERO),
        'unconverted': len(group) - len(conv),
    }


def _eur_only(group):
    s = _sums(group)
    return {k: s[k] for k in ('payments', 'gross_eur', 'withholding_eur', 'unconverted')}


def _rate_source_text(p):
    if p.conversion_status != CONVERTED:
        return _('not converted')
    return {'identity': _('EUR (rate 1)'), 'manual': _('manual rate')}.get(p.rate_source, p.rate_source)


def _amount_cols():
    return [Column('payments', _('Payments'), 'int'), Column('gross', _('Gross (original currency)'), 'money'),
            Column('negative', _('Of which negative payments (original currency)'), 'money'),
            Column('withholding', _('Withholding tax (original currency)'), 'money'),
            Column('gross_eur', _('Gross EUR'), 'money'), Column('withholding_eur', _('Withholding tax EUR'), 'money'),
            Column('unconverted', _('Unconverted payments'), 'int')]


def _documents(group, sources):
    """References behind a group of payments, and 'none (n)' for payments without a source document."""
    refs = sorted({sources.per_payment[p.pk].ref for p in group if sources.per_payment[p.pk].ref})
    lacking = sum(1 for p in group if not sources.per_payment[p.pk].ref)
    return ', '.join(refs + ([_('none (%(n)s)') % {'n': lacking}] if lacking else []))


def tables(payments, sources=None):
    """The tables for an already filtered, ordered payment list."""
    sources = sources or report_sources.resolve(payments)
    by_cc = defaultdict(list)
    by_cac = defaultdict(list)
    for p in payments:
        by_cc[(p.category.name, p.currency)].append(p)
        by_cac[(p.category.name, p.organisation.name, p.currency)].append(p)

    # Table 1: category x currency, with a EUR-only subtotal line per category.
    rows1 = []
    for category in sorted({k[0] for k in by_cc}):
        in_cat = []
        for (cat, ccy), group in sorted(by_cc.items()):
            if cat == category:
                rows1.append({'category': cat, 'currency': ccy, **_sums(group)})
                in_cat += group
        rows1.append({'category': _('Subtotal %(name)s (EUR only)') % {'name': category}, '_total': True, **_eur_only(in_cat)})
    t1 = Table('category_currency', _('Income by category and currency'),
               [Column('category', _('Category')), Column('currency', _('Currency'))] + _amount_cols(),
               rows1, {'category': _('Total (EUR only)'), **_eur_only(payments)})

    # Table 2: category x organisation x currency.
    rows2 = [{'category': c, 'organisation': o, 'currency': ccy, **_sums(group), 'documents': _documents(group, sources)}
             for (c, o, ccy), group in sorted(by_cac.items())]
    t2 = Table('organisation', _('Income by organisation'),
               [Column('category', _('Category')), Column('organisation', _('Organisation')), Column('currency', _('Currency'))]
               + _amount_cols() + [Column('documents', _('Documents'))], rows2,
               {'category': _('Total (EUR only)'), **_eur_only(payments)})

    # Table 3: only payments with a recorded withholding, same grouping as table 2, a total per currency and in EUR.
    withheld = [p for p in payments if p.withholding_tax != 0]
    groups3 = defaultdict(list)
    for p in withheld:
        groups3[(p.category.name, p.organisation.name, p.currency)].append(p)
    rows3 = []
    for (c, o, ccy), group in sorted(groups3.items()):
        s = _sums(group)
        rows3.append({'category': c, 'organisation': o, 'currency': ccy, 'payments': s['payments'],
                      'withholding': s['withholding'], 'withholding_eur': s['withholding_eur'], 'unconverted': s['unconverted'],
                      'documents': _documents(group, sources)})
    for ccy in sorted({p.currency for p in withheld}):
        group = [p for p in withheld if p.currency == ccy]
        s = _sums(group)
        rows3.append({'category': _('Total %(currency)s') % {'currency': ccy}, '_total': True, 'currency': ccy,
                      'payments': s['payments'], 'withholding': s['withholding'],
                      'withholding_eur': s['withholding_eur'], 'unconverted': s['unconverted'],
                      'documents': _documents(group, sources)})
    s = _sums(withheld)
    t3 = Table('withholding', _('Taxes withheld'),
               [Column('category', _('Category')), Column('organisation', _('Organisation')), Column('currency', _('Currency')),
                Column('payments', _('Payments'), 'int'), Column('withholding', _('Withholding tax (original currency)'), 'money'),
                Column('withholding_eur', _('Withholding tax EUR'), 'money'), Column('unconverted', _('Unconverted payments'), 'int'),
                Column('documents', _('Documents'))],
               rows3, {'category': _('Total EUR'), 'payments': s['payments'], 'withholding_eur': s['withholding_eur'],
                       'unconverted': s['unconverted']},
               _('Withholding tax as recorded from the statement. A zero or a missing row means none is recorded, not that '
                 'none was withheld. Not credited; no treaty or foreign-tax-credit rule is applied.') if rows3 else
               _('No withholding tax is recorded for these payments. A zero or a missing row means none is recorded, not '
                 'that none was withheld.'))

    # Table 4: every payment, as stored.
    kinds = dict(Payment.Kind.choices)
    rows4 = [{'date': p.payment_date, 'category': p.category.name, 'organisation': p.organisation.name, 'currency': p.currency,
              'gross': p.gross_amount, 'withholding': p.withholding_tax,
              'rate': p.rate if p.conversion_status == CONVERTED else None,
              'rate_date': p.rate_date if p.conversion_status == CONVERTED else None,
              'rate_source': _rate_source_text(p),
              'gross_eur': p.gross_eur if p.conversion_status == CONVERTED else None,
              'withholding_eur': (p.withholding_tax_eur or ZERO) if p.conversion_status == CONVERTED else None,
              'kind': str(kinds.get(p.kind, p.kind)), 'comment': p.comment,
              'source': sources.per_payment[p.pk].text()}
             for p in payments]
    s = _sums(payments)
    t4 = Table('payments', _('Payments'),
               [Column('date', _('Date'), 'date'), Column('category', _('Category')), Column('organisation', _('Organisation')),
                Column('currency', _('Currency')), Column('gross', _('Gross'), 'money'),
                Column('withholding', _('Withholding tax'), 'money'), Column('rate', _('Rate'), 'rate'),
                Column('rate_date', _('Rate date'), 'date'), Column('rate_source', _('Rate source')),
                Column('gross_eur', _('Gross EUR'), 'money'), Column('withholding_eur', _('Withholding tax EUR'), 'money'),
                Column('kind', _('Kind')), Column('source', _('Source')), Column('comment', _('Comment'))],
               rows4, {'date': None, 'category': _('Total (EUR only)'), 'gross_eur': s['gross_eur'],
                       'withholding_eur': s['withholding_eur']},
               _('* The withholding of this payment may be settled from another statement of the same upload.')
               if sources.any_settled_elsewhere else '')

    rows5 = [{'ref': d.ref, 'organisations': '; '.join(sorted(d.organisations)),
              'kind': _('PDF statement') if d.kind == 'pdf' else _('CSV file (your own import file)'),
              'name': d.name, 'uploaded': d.uploaded, 'sha256': d.sha256, 'state': d.state, 'payments': d.payments}
             for d in sources.documents]
    t5 = Table('sources', _('Source documents'),
               [Column('ref', _('Reference')), Column('organisations', _('Organisation(s)')), Column('kind', _('Kind')),
                Column('name', _('File name (as shown)')), Column('uploaded', _('First uploaded'), 'date'),
                Column('sha256', _('SHA-256'), 'hash'), Column('state', _('Stored original')),
                Column('payments', _('Payments in this report'), 'int')], rows5, None,
               _('A document is one file, identified by the SHA-256 of its bytes; the same statement uploaded twice is one '
                 'document. File names are shown with long digit runs masked. A CSV file is your own import file and may '
                 'hold more than this report shows.'))
    return [t1, t2, t3, t4, t5]


def ordered(qs):
    """Payment date, then organisation, then id (the order of table 4)."""
    return list(qs.select_related('organisation', 'category').order_by('payment_date', 'organisation__name', 'id'))


def _source_line(payments, sources):
    if not payments:
        return _('None.')
    sources = sources or report_sources.resolve(payments)
    text = _('%(docs)s document(s) referenced; %(n)s of %(total)s payment(s) have no source document') % {
        'docs': len(sources.documents), 'n': sum(sources.without.values()), 'total': len(payments)}
    if sources.without:
        text += ' (' + '; '.join(f'{r}: {n}' for r, n in sorted(sources.without.items())) + ')'
    return text + '.'


def basis_rows(payments, year, flt, sources=None):
    """The basis block above the tables."""
    rows = [(_('Period'), _period(year))]
    if flt is not None and flt.is_active:
        rows.append((_('Filter'), flt.describe()))
    pending = [p for p in payments if p.conversion_status != CONVERTED]
    unconverted = (_('%(n)s unconverted payment(s) are listed but left out of every EUR figure (their original amounts are shown).')
                   % {'n': len(pending)}) if pending else _('None.')
    used = {p.category_id for p in payments}
    empty = [c.name for c in IncomeCategory.objects.filter(active=True).order_by('name') if c.pk not in used]
    rows += [
        (_('Basis'), _('Income as recorded; no tax classification, no country inference, no treaty or credit rules applied.')),
        (_('Gross/net'), _('Gross amounts as recorded and withholding tax as recorded. Net amounts and expenses are not shown.')),
        (_('Currency'), _('Original amounts are in the currency of each payment and are never added across currencies. '
                          'EUR amounts use the rate stored on each payment.')),
        (_('Exchange-rate basis'), _rate_basis(payments)),
        (_('Excluded / missing'), unconverted),
        (_('Categories without payments'), '; '.join(empty) + '.' if empty else _('None.')),
        (_('Source documents'), _source_line(payments, sources)),
        (_('Stored values'), _('Amounts are the stored values. A payment edited after its import may differ from its statement.')),
        (_('Rounding'), ROUNDING_NOTE),
    ]
    return rows


def notes():
    return [
        _('Information for you or your adviser; not a tax calculation.'),
        _('Double-taxation treaties and foreign-tax credit are not applied. Withholding tax is shown as recorded and is not credited.'),
        _('Currency conversion: the stored rate of each payment is used; whether the tax authorities require another rate is not verified.'),
        _('Negative payments are shown as recorded in their own category and are not netted across categories; no loss rule is applied. '
          '"Of which negative" counts normal payments only; corrections and reversals are listed with their kind.'),
        _('No tax amount is calculated.'),
    ]
