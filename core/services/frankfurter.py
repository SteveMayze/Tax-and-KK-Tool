"""Frankfurter / ECB reference-rate provider. Verified behaviour: docs/exchange-rates.md.

Endpoint: GET {base}/v2/providers/ECB/rate/{CCY}/EUR?date=YYYY-MM-DD
Chosen deliberately: the provider-scoped path returns genuine ECB reference rates and the
date the rate really applies to. (The unscoped /v2 endpoints blend several central banks and
echo the requested date even on weekends, which would mislabel the rate date.)
"""
import datetime
import json
import re
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation

from django.conf import settings

from .rates import ProviderError, RateProvider, RateQuote, RateUnavailable

PROVIDER_NAME = 'frankfurter-ecb'
MAX_BODY = 65536


def _http_get(url, timeout):
    """Return (status, body). Raises on transport failure. Isolated so tests can mock it."""
    req = urllib.request.Request(url, headers={
        'Accept': 'application/json', 'User-Agent': 'tax-healthcare-tool (personal use)'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - https enforced below
            return resp.status, resp.read(MAX_BODY).decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read(MAX_BODY).decode('utf-8', 'replace')


def _message(body):
    try:
        return str(json.loads(body).get('message', ''))[:200]
    except (ValueError, AttributeError):
        return ''


class FrankfurterProvider(RateProvider):
    name = PROVIDER_NAME

    def __init__(self, base_url=None, timeout=None, max_lookback_days=None):
        self.base_url = (base_url or settings.FRANKFURTER_BASE_URL).rstrip('/')
        self.timeout = timeout or settings.FRANKFURTER_TIMEOUT
        self.max_lookback_days = (
            settings.RATE_MAX_LOOKBACK_DAYS if max_lookback_days is None else max_lookback_days)
        if not (self.base_url.startswith('https://') or self.base_url.startswith('http://localhost')):
            raise ProviderError('Frankfurter base URL must use https.')

    def get_rate(self, currency, on_date):
        if not re.fullmatch(r'[A-Z]{3}', currency or ''):
            raise RateUnavailable(f'Invalid currency code {currency!r}.')
        if currency == 'EUR':
            raise RateUnavailable('EUR needs no exchange rate.')
        # Always an explicit date: the API's default (no date) means "latest", which we never want.
        url = f'{self.base_url}/v2/providers/ECB/rate/{currency}/EUR?date={on_date.isoformat()}'
        try:
            status, body = _http_get(url, self.timeout)
        except (OSError, ValueError) as e:  # URLError, timeouts, connection errors
            raise ProviderError(f'Could not reach the exchange-rate service: {e}') from e

        if status == 404:
            raise RateUnavailable(f'The ECB has no {currency} rate for {on_date} (or earlier).')
        if status == 422:
            raise RateUnavailable(f'The exchange-rate service rejected the request: {_message(body)}')
        if status != 200:
            raise ProviderError(f'Exchange-rate service returned HTTP {status}.')
        return self._parse(currency, on_date, url, body)

    def _parse(self, currency, on_date, url, body):
        try:
            # parse_float=Decimal keeps the exact decimal text (no binary float rounding).
            data = json.loads(body, parse_float=Decimal)
            rate = data['rate']
            rate = rate if isinstance(rate, Decimal) else Decimal(str(rate))
            rate_date = datetime.date.fromisoformat(data['date'])
            base, quote = data['base'], data['quote']
        except (ValueError, KeyError, TypeError, InvalidOperation) as e:
            raise ProviderError('Unexpected response from the exchange-rate service.') from e
        if base != currency or quote != 'EUR':
            raise ProviderError(f'Response is for {base}/{quote}, expected {currency}/EUR.')
        if not rate.is_finite() or rate <= 0:
            raise ProviderError(f'Exchange-rate service returned an invalid rate ({rate}).')
        if rate_date > on_date:
            raise ProviderError(f'Rate date {rate_date} is after the requested date {on_date}.')
        gap = (on_date - rate_date).days
        if gap > self.max_lookback_days:
            raise RateUnavailable(
                f'Nearest ECB {currency} rate is from {rate_date}, {gap} days before {on_date}; '
                f'not used (limit {self.max_lookback_days} days).')
        return RateQuote(currency, on_date, rate_date, rate, self.name, source_url=url, raw_response=body[:2000])
