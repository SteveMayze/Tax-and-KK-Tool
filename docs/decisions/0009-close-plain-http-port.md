# ADR 0009: Close the plain-HTTP port (gateway track G3)

Status: accepted (2026-10-19). Supersedes ADR 0008 decision 1 ("`PublishPort` stays") and the plain-HTTP part of ADR 0005.

## Context
The app is reachable through the gateway at `https://<server>/tax-healthcare/`, which reaches the container by name on the `gateway` network. The published host port was still bound on all interfaces, so anyone on the home network could use plain HTTP and bypass the gateway.

## Decisions
1. `listen_address: 127.0.0.1`: the port is published on the server's own loopback only. It is kept (rather than removed) because the deploy, rollback and status health probes call `http://127.0.0.1:<app_port>/health/`. `Network=gateway.network` stays; that is how Caddy reaches the app.
2. `csrf_trusted_origins` is now only `https://<public_host>` (plus `extra_csrf_origins`); the plain-HTTP origin is gone. `DJANGO_BEHIND_TLS_PROXY=1` stays.
3. A test checks that the unit publishes only `{{ listen_address }}` and that the default is loopback.
4. **Open question for the owner:** with the plain port closed, `use_https: true` (Secure cookies) would now work for all real users. It is not part of this request, so it stays `false` until the owner says so (the health probe is plain HTTP on loopback and is unaffected).

## Consequences
Direct LAN access to the app on its port is refused. Troubleshooting without the gateway: `ssh -L` to the loopback port, or `podman exec`. The old rootful copy (if still running) is a separate decision of the owner and is untouched.
