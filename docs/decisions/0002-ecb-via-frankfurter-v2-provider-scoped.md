# ADR 0002: ECB rates via Frankfurter v2, provider-scoped

Status: accepted (Phase 4)

## Context
CLAUDE.md specifies ECB reference rates via Frankfurter, a swappable provider, historical rates by payment date, and no silent date substitution. Checking the live API (2026-10-18) showed v1 is frozen/deprecated, and that unscoped v2 queries blend multiple central banks and echo the requested date on non-publication days.

## Decision
Use `GET /v2/providers/ECB/rate/{CCY}/EUR?date=...`. Always send an explicit date. Accept the returned earlier date for weekends/holidays only within a 7-day lookback, store and label the difference. Store provenance (URL, body, retrieval time) on append-only rate records. Reuse previously retrieved rates for identical requests; recalculation refreshes explicitly. The provider is chosen by `RATE_PROVIDER` so it can be replaced.

## Consequences
- ECB's own rate date is recorded, so labelling is truthful.
- v2 may change; `docs/exchange-rates.md` records what was verified and when.
- No new Python dependency (standard-library `urllib`).
