# ADR 0006: URL prefix, own cookies, static files, no display currency

Status: accepted (Phase 9, 2026-10-19). Supersedes in part ADR 0005 ("no static files in production") and the display-currency item of the Phase 3 scope (kept for audit in `docs/prompts/PHASES.md`).

## Context
A separate gateway repository will serve this app over HTTPS at `/tax-healthcare`. The owner confirmed the prefix and that the app stays reachable on its own port 8889 during the transition. Browsers share cookies across ports and paths on one host, and another app (parts-db) lives on the same host. The display-currency dropdown never converted anything (reports are EUR at each payment's stored rate); the owner no longer wants it.

## Decisions
- **Prefix by environment variable** `DJANGO_URL_PREFIX` (default empty: development unchanged). It sets `FORCE_SCRIPT_NAME`, the static URL and the cookie paths; `reverse()` and `LOGIN_URL`/`LOGIN_REDIRECT_URL` (named URLs) then include it. A view that built a redirect from a literal path was fixed.
- **The app answers with and without the prefix** (`core.middleware.StripUrlPrefixMiddleware`, first in the chain). Reason: during the transition the same container is reached through the proxy (prefix stripped) and directly on 8889 (generated links carry the prefix). Rejected: answering only stripped paths, which would break every link on the direct port.
- **TLS proxy switch** `DJANGO_BEHIND_TLS_PROXY=1` enables `SECURE_PROXY_SSL_HEADER`; secure cookies stay tied to `DJANGO_HTTPS` because 8889 remains plain HTTP. Risk accepted: while 8889 is open a LAN client can forge `X-Forwarded-Proto`; closing the port is a gateway-track step. `CSRF_TRUSTED_ORIGINS` and `ALLOWED_HOSTS` stay configurable (Ansible: `extra_csrf_origins`, `extra_allowed_hosts`).
- **HSTS stays off** (`DJANGO_HSTS_SECONDS=0`) until the local CA is installed on every device.
- **Own cookie names** `taxhc_sessionid` and `taxhc_csrftoken`, path = prefix when set. Consequence: one forced re-login after the change.
- **Static files via WhiteNoise 6.12.0** (pinned), collected into `/app/staticfiles` at image build; the existing inline stylesheet moved to `core/static/core/base.css` so the whole path is exercised. Admin stays off. Phase 13 builds the design stylesheet on this.
- **Display currency removed:** dropdown, session key, context processor, view, URL and tests. Amounts show in their own currency; reports stay EUR.

## Consequences
- Direct use becomes `http://<server>:8889/tax-healthcare/`; the old root URL still answers.
- A bookmark of a page path without the prefix keeps working but its cookie is only sent under the prefix after login; the login redirect leads to the prefixed URL.
