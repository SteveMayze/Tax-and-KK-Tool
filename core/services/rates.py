"""Exchange-rate provider interface.

Convention: rate = EUR per 1 unit of the original currency, so EUR = original x rate.
Providers must never silently substitute another date: they return the date the rate
actually applies to, and callers label any difference from the requested date.
"""
import datetime
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal


class RateError(Exception):
    """Base class for rate lookup failures."""


class RateUnavailable(RateError):
    """The provider has no rate for this currency/date."""


class ProviderError(RateError):
    """The provider failed (network, bad response, ...)."""


@dataclass(frozen=True)
class RateQuote:
    currency: str
    requested_date: datetime.date
    rate_date: datetime.date  # date the rate applies to; may differ from requested_date
    rate: Decimal             # EUR per 1 unit of currency
    provider: str

    @property
    def date_differs(self) -> bool:
        return self.rate_date != self.requested_date


class RateProvider(ABC):
    name = 'abstract'

    @abstractmethod
    def get_rate(self, currency: str, on_date: datetime.date) -> RateQuote:
        """Return the EUR-per-unit rate or raise RateUnavailable / ProviderError."""


class FakeRateProvider(RateProvider):
    """Deterministic in-memory provider for tests and development. Not real data."""
    name = 'fake'

    def __init__(self, rates=None, fail=False, date_overrides=None):
        # rates: {(currency, date): Decimal}; date_overrides: {(currency, date): date actually applied}
        self.rates = dict(rates or {})
        self.fail = fail
        self.date_overrides = dict(date_overrides or {})
        self.calls = []

    def get_rate(self, currency, on_date):
        self.calls.append((currency, on_date))
        if self.fail:
            raise ProviderError('Fake provider failure.')
        key = (currency, on_date)
        if key not in self.rates:
            raise RateUnavailable(f'No fake rate for {currency} on {on_date}.')
        return RateQuote(currency, on_date, self.date_overrides.get(key, on_date), self.rates[key], self.name)
