"""Synthetic test data only."""
import datetime
from decimal import Decimal

from core.models import IncomeCategory, Organisation, Payment, ReportingMonth


def make_payment(gross='1000', net=None, currency='EUR', date=datetime.date(2024, 3, 15),
                 frequency='monthly', org='Acme Test GmbH', category='Salary', **kw):
    organisation, _ = Organisation.objects.get_or_create(name=org)
    cat, _ = IncomeCategory.objects.get_or_create(name=category)
    return Payment(
        month=ReportingMonth.for_date(date), organisation=organisation, category=cat, payment_date=date,
        currency=currency, gross_amount=Decimal(gross), net_amount=None if net is None else Decimal(net),
        frequency=frequency, **kw)
