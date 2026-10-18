"""Supported currencies. Adding a currency is a one-line change; no schema change is needed."""
import re

SUPPORTED_CURRENCIES = ('EUR', 'GBP', 'AUD', 'USD')
BASE_CURRENCY = 'EUR'
CURRENCY_CODE_RE = re.compile(r'^[A-Z]{3}$')
