# Exchange rates: Frankfurter / ECB

Verified against the live API on **2026-10-18** (read-only GETs; no user data sent). Re-verify before relying on this after a long gap; the service is third-party.

## Service facts
- Base URL `https://api.frankfurter.dev`. No API key. Open source (lineofflight/frankfurter). No rate-limit headers were observed; responses are cacheable (`cache-control: public, max-age=86400` for dated rates).
- Versions: **v2 is "current"; v1 is "frozen"** and its data endpoints now carry a `Deprecation` header with a v2 `successor-version` link. v1 still answers. We use v2.
- v1 and unscoped v2 are not suitable (see below), so the app uses only the provider-scoped v2 path.

## Endpoint used
`GET /v2/providers/ECB/rate/{BASE}/EUR?date=YYYY-MM-DD`

Response: `{"date":"2024-03-15","base":"GBP","quote":"EUR","rate":1.1708}`
- `rate` = EUR per 1 unit of `base`, which matches our convention (EUR = original x rate).
- `date` = the date the ECB rate applies to.
- Rates are JSON numbers. We parse with `Decimal` straight from the response text, so no binary-float rounding.
- Source is the **ECB euro foreign exchange reference rates** (provider `ECB`, rate type "reference rate", daily, data from 1999-01-04).
- Supported by ECB data: includes EUR, GBP, AUD, USD (the app's initial currencies); the app can add more with no schema change.

## Behaviour observed
| Case | Result | App handling |
|---|---|---|
| Business day | 200, `date` = requested date | Used as is |
| Weekend (2024-03-16, Sat) | 200, `date` = 2024-03-15 (previous business day) | Used and **labelled**: note on the payment, flagged in Reconciliation |
| Holiday (2024-12-25; 2024-01-01) | 200, previous publication day (2024-12-24; 2023-12-29) | Same |
| Date after latest data (e.g. 2026-10-19) | 200 with latest available date | Accepted only inside the lookback limit, labelled |
| Before 1999-01-04, or unknown pair/provider | 404 `{"status":404,"message":"not found"}` | `RateUnavailable` -> error + manual rate option |
| Invalid date / currency code | 422 with message | `RateUnavailable` with the message |
| Omitted `date` | Returns **latest** rate | Never used; every request carries an explicit date |
| `EUR/EUR` | 200 rate 1 on v2 (422 on v1) | Never requested; EUR uses rate 1 locally |
| Lower-case codes | Accepted | We always send upper case |

Why not the other endpoints: unscoped v2 (`/v2/rate/...` without `providers`) blends many central banks and, on a weekend, **echoes the requested date** for a rate that is not an ECB publication, which would mislabel the rate date. v1 is deprecated.

## How the app uses it (`core/services/frankfurter.py`)
- Provider name `frankfurter-ecb`. Timeout 10 s (`FRANKFURTER_TIMEOUT`). HTTPS only. No retries; the user can retry or enter a rate manually.
- Response checks: JSON shape, `base`/`quote` match the request, rate finite and > 0, rate date not after the requested date.
- **Lookback limit** (`RATE_MAX_LOOKBACK_DAYS`, default 7): if the returned rate date is more than 7 days before the payment date, the rate is treated as unavailable instead of silently accepted.
- A date difference within the limit is stored on the payment (`conversion_notes`) and listed on the Reconciliation page. Nothing is guessed or substituted unlabelled.
- Failures (timeout, connection error, 5xx, 429, malformed body) raise `ProviderError`; 404/422/too-old raise `RateUnavailable`. Both become a `ConversionError`: nothing is saved, form input is kept, the manual-rate section opens.

## Provenance and repeat requests
Each rate is stored as an append-only `ExchangeRateRecord`: provider, currency, requested date, rate date, rate, exact request URL, response body, retrieval time. A payment links to the record it used.
- **Repeat requests:** a rate already retrieved for the same provider, currency and requested date is reused, so a second payment on that date makes no HTTP call. Identical provider records are not duplicated.
- **Recalculation** deliberately bypasses the stored rate and asks the service again; the old record stays.
- Reports use the rate stored on each payment and never re-fetch.

## Privacy
Each request contains only a currency code and a date (no amounts, names or documents). Requests go to a third party and reveal that a payment in that currency occurred on that date. No data is sent to any other service.

## Operations notes
- Needs outbound HTTPS to `api.frankfurter.dev`.
- **macOS python.org builds have no CA certificates until you run** `/Applications/Python 3.14/Install Certificates.command`, or set `SSL_CERT_FILE=/etc/ssl/cert.pem`. Until then every lookup fails with a clear "could not reach" error and the manual-rate option still works. TLS verification is never disabled.
- Work offline: `DJANGO_RATE_PROVIDER=core.services.rates.ManualOnlyProvider`.
- Tests never touch the network: the test runner (`config/testrunner.py`) fails any non-local socket connection, and the HTTP helper is mocked.
