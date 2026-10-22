"""Find payments with missing or questionable conversion data. Read-only."""
from dataclasses import dataclass, field

from core.models import ExchangeRateRecord, Payment

from .conversion import breakdown_eur, eur_amount, for_storage


@dataclass
class Report:
    pending: list = field(default_factory=list)         # not converted: excluded from all totals
    manual_rates: list = field(default_factory=list)    # converted using a manually entered rate
    date_differs: list = field(default_factory=list)    # rate date != payment date
    missing_net: list = field(default_factory=list)     # no net amount: excluded from net totals
    inconsistent: list = field(default_factory=list)    # stored EUR/rate disagree with their inputs
    unallocated: list = field(default_factory=list)     # gross != net + withholding tax + expenses (older payments)

    @property
    def issue_count(self):
        return sum(len(x) for x in (self.pending, self.manual_rates, self.date_differs,
                                    self.missing_net, self.inconsistent, self.unallocated))


def build_report(year=None, flt=None) -> Report:
    qs = Payment.objects.select_related('organisation', 'category', 'month__year', 'rate_record')
    if year is not None:
        qs = qs.filter(month__year__year=year)
    if flt is not None:
        qs = flt.apply(qs)
    r = Report()
    for p in qs:
        if p.net_amount is None:
            r.missing_net.append(p)
        elif p.unallocated:
            r.unallocated.append(p)
        if p.conversion_status != Payment.ConversionStatus.CONVERTED:
            r.pending.append(p)
            continue
        if p.rate_source == 'manual':
            r.manual_rates.append(p)
        if p.rate_date != p.payment_date:
            r.date_differs.append(p)
        if _inconsistent(p):
            r.inconsistent.append(p)
    return r


def _inconsistent(p: Payment) -> bool:
    rec: ExchangeRateRecord = p.rate_record
    if rec is None or rec.rate != p.rate or rec.currency != p.currency:
        return True
    return (p.gross_eur != for_storage(eur_amount(p.gross_amount, p.rate))
            or p.net_eur != for_storage(eur_amount(p.net_amount, p.rate))
            or (p.withholding_tax_eur, p.expenses_eur) != breakdown_eur(p, p.rate))
