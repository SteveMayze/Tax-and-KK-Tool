from core.currencies import BASE_CURRENCY, SUPPORTED_CURRENCIES

SESSION_KEY = 'display_currency'


def get_display_currency(request):
    value = request.session.get(SESSION_KEY, BASE_CURRENCY)
    return value if value in SUPPORTED_CURRENCIES else BASE_CURRENCY


def display_currency(request):
    current = get_display_currency(request)
    return {
        'display_currency': current,
        'display_currencies': SUPPORTED_CURRENCIES,
        # No exchange-rate source for display conversion exists before Phase 4: never invent rates.
        'display_unconverted_note': current != BASE_CURRENCY,
    }
