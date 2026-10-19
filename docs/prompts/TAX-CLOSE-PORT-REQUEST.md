# Request for the Tax and Healthcare Tool repo: close the plain-HTTP port

Paste into a new session in the Tax-and-KK-Tool repo. Its `CLAUDE.md` applies. The owner knows little about Podman and Linux administration: plain language, each command explained.

## Context
The app now runs behind the `cornil-gateway` Caddy at `https://cornil.fritz.box/tax-healthcare/`. Caddy reaches it **by container name on the `gateway` network** (`tax-healthcare-tool-web:8000`); this was verified, and the gateway now uses that route, so the app's published host port is no longer needed. It is still published on all interfaces (8890), so anyone on the home network can use plain HTTP and bypass the gateway.

## Do (one phase, then stop and report)
1. Set the app's `listen_address` to `127.0.0.1` (default for the deployment variables), so the published port listens on the server's own loopback only. Do not remove `Network=gateway.network` (that is how Caddy reaches the app). If `listen_address` cannot do this cleanly, remove `PublishPort` instead and keep the health probe working through `podman exec`.
2. Remove the plain-HTTP origin from `DJANGO_CSRF_TRUSTED_ORIGINS`; keep `https://cornil.fritz.box`. Keep `DJANGO_BEHIND_TLS_PROXY=1`.
3. Update tests, docs and the `status`/health checks that assumed the LAN port; add a test that the rendered unit publishes no non-loopback port.
4. Deploy (no sudo), then show me: `podman ps`; from the Mac `curl -m 5 http://cornil.fritz.box:8890/` is refused or times out; `https://cornil.fritz.box/tax-healthcare/` still loads, I can log in and submit a form.
5. Do not touch the gateway repo. Decommissioning the old rootful copy on 8889 is a separate step I decide (do not run any sudo command for it here).

Report as usual (done, commits, checks, deviations, open questions, not verified; each acceptance criterion met / not met / not verifiable), then wait for my "go".
