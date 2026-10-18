"""Supported currencies. Adding a currency is a one-line change; no schema change is needed."""
import re

SUPPORTED_CURRENCIES = ('EUR', 'GBP', 'AUD', 'USD')
BASE_CURRENCY = 'EUR'
CURRENCY_CODE_RE = re.compile(r'^[A-Z]{3}$')

# Used only as a fallback for an organisation whose country is blank (tax information summary).
# EUR is deliberately absent: it is shared by many countries, so the organisation's country must be set.
CURRENCY_COUNTRY = {'AUD': 'AU', 'GBP': 'GB', 'USD': 'US'}
