# ADR 0008: Join the gateway network; proxy-aware settings for the https front door

Status: accepted (Phase 9B, 2026-10-19). Builds on ADR 0006 (URL prefix, cookies) and ADR 0007 (rootless Podman; decision 8, "reaching other containers", is now carried out).

## Context
A separate repository owns the reverse proxy (Caddy, a rootless container of the same service user). It already forwards `https://<server>/tax-healthcare/` to this app through the published port, as a stop-gap. It created a rootless Podman network `gateway` (Quadlet file `gateway.network`). Caddy strips `/tax-healthcare` from the path and sends `X-Forwarded-Proto: https`, `X-Forwarded-For`, `X-Forwarded-Host` and the original `Host`. Nothing in this repository configures Caddy.

## Decisions
1. **The unit joins the network:** `Network=gateway.network` in the Quadlet template (variable `gateway_network`). Quadlet then starts the network first. The container keeps its name `tax-healthcare-tool-web`, so the proxy can reach `tax-healthcare-tool-web:8000` (the port inside the container). `PublishPort` stays: the plain-HTTP port is closed later, in the gateway track (G3), after both apps work through the gateway.
2. **Deploy refuses politely when the network file is missing** (a check in `infra/deploy.yaml`), instead of leaving a unit that cannot start. One-off containers (migrate, backup) do not join the network.
3. **Proxy settings as variables:** `behind_tls_proxy: true` (trust `X-Forwarded-Proto`), `extra_csrf_origins: ["https://<public_host>"]` next to the existing plain-HTTP origin, `public_host` already in `ALLOWED_HOSTS`, `url_prefix: /tax-healthcare`, `hsts_seconds: 0`.
4. **Cookies stay not-Secure (`use_https: false`) for now.** Django decides `Secure` once per process, not per request. Making cookies Secure would stop logins on the plain-HTTP port, which must keep working during the transition. Cost: over the old plain port, cookies cross the LAN unencrypted, exactly as today; over https they are protected by TLS regardless. When the plain port closes (G3) set `use_https: true` and drop the plain-HTTP origin. Rejected: separate settings per entry point (two processes for one user).
5. **HSTS stays 0** until the local root certificate is installed on every device.
6. **Trust of the forwarded header:** while the published port is open, a LAN client could send `X-Forwarded-Proto` itself; the only effect is Django treating that request as secure. Closing the port (G3) removes this.

## Consequences
- Tests (real Django test client in a production-settings subprocess): login, redirect target and cookie path carry the prefix; a POST with `Origin: https://<host>` and the proxy header passes CSRF; the plain-HTTP origin still passes; a foreign origin gets 403. Static files under the prefix are covered by the Phase 9 tests.
- Rollback: remove `Network=` (or revert the commit) and redeploy; the published port never stopped working.
- Not done here: the gateway's upstream change (the gateway owner does it after this works), closing 8889/8890, removing the rootful copy.
