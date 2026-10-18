"""Find payments with missing or questionable conversion data. Read-only."""
from dataclasses import dataclass, field

from core.models import ExchangeRateRecord, Payment

from .conversion import eur_amount, for_storage


@dataclass
class Report:
    pending: list = field(default_factory=list)         # not converted: excluded from all totals
    manual_rates: list = field(default_factory=list)    # converted using a manually entered rate
    date_differs: list = field(default_factory=list)    # rate date != payment date
    missing_net: list = field(default_factory=list)     # no net amount: excluded from net totals
    inconsistent: list = field(default_factory=list)    # stored EUR/rate disagree with their inputs

    @property
    def issue_count(self):
        return sum(len(x) for x in (self.pending, self.manual_rates, self.date_differs,
                                    self.missing_net, self.inconsistent))


def build_report(year=None) -> Report:
    qs = Payment.objects.select_related('organisation', 'category', 'month__year', 'rate_record')
    if year is not None:
        qs = qs.filter(month__year__year=year)
    r = Report()
    for p in qs:
        if p.net_amount is None:
            r.missing_net.append(p)
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
            or p.net_eur != for_storage(eur_amount(p.net_amount, p.rate)))
