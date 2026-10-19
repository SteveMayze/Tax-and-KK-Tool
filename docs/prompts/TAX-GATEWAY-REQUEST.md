# Request for the Tax and Healthcare Tool repo: join the cornil gateway

Paste this into a new session in the Tax-and-KK-Tool repo. Read its `CLAUDE.md` first; all its rules (secrets, privacy, plain language, one phase at a time with a hard stop) apply.

## Context
A new repository, `cornil-gateway`, now owns the Caddy reverse proxy on the home server. It is live: `https://cornil.fritz.box/tax-healthcare/` already reaches this app (through the app's published port 8890, as a stop-gap) and shows the login page. Caddy runs as a **rootless container of the same service user (`homeapps`)** and listens on 80 and 443. Nothing in this repo may contain Caddy configuration.

The gateway repo created a rootless Podman network called `gateway` (Quadlet file `gateway.network`, in the service user's `~/.config/containers/systemd/`). Caddy is on it. This app should join it so Caddy can reach it **by container name** instead of through a published port.

I (the owner) know little about Podman and Linux administration: explain every concept in plain language, give each command with a one-line "what this does", say what normal output looks like and what to do if it fails.

## What to do (one phase, then stop and report)
1. **Join the network.** In the rootless Quadlet unit template, add `Network=gateway.network`. Quadlet then makes the unit depend on the network automatically. Keep `ContainerName=tax-healthcare-tool-web`; Caddy will reach `tax-healthcare-tool-web:8000` (the port **inside** the container). Keep `PublishPort` as it is for now: closing the plain-HTTP port is a later step (G3), after both apps work through the gateway.
2. **Proxy-aware settings for the https front door**, as variables with sensible defaults, replacing the trial values (`DJANGO_BEHIND_TLS_PROXY=0`, CSRF origin `http://cornil.fritz.box:8890`):
   - `DJANGO_BEHIND_TLS_PROXY=1` so `SECURE_PROXY_SSL_HEADER` trusts `X-Forwarded-Proto` from Caddy;
   - `DJANGO_CSRF_TRUSTED_ORIGINS=https://cornil.fritz.box` (keep any plain-HTTP origin only while the old port stays open, so the 8890/8889 access does not break);
   - keep `DJANGO_ALLOWED_HOSTS` including `cornil.fritz.box` (Caddy keeps the Host header) and `DJANGO_URL_PREFIX=/tax-healthcare`;
   - check `DJANGO_HTTPS` / secure-cookie settings and decide, with a test, what must be on when requests arrive over https via the proxy but also over plain HTTP on the old port during the transition. Do not enable HSTS (`DJANGO_HSTS_SECONDS` stays 0): the owner has not finished installing the root certificate on every device.
   - keep the app's own cookie names and cookie path set to `/tax-healthcare`, so it and parts-db cannot log each other out.
3. Caddy sends `X-Forwarded-Proto: https`, `X-Forwarded-For`, `X-Forwarded-Host`, keeps `Host: cornil.fritz.box`, and **strips** `/tax-healthcare` from the path before forwarding (the app already expects this with its script-name prefix). Add or confirm tests with the real Django test client that prove: login, logout, redirects and form actions carry the prefix; CSRF works with `Origin: https://cornil.fritz.box` behind the proxy header; static files load under the prefix.
4. Deploy it to the rootless unit (`make deploy`, no sudo). Then verify from the server and from the Mac, and show me: `podman ps` (network column), that `https://cornil.fritz.box/tax-healthcare/` loads and I can log in and submit a form without a CSRF error, and that `http://cornil.fritz.box:8890` still works.
5. **Do not touch** the gateway repo or its files on the server. When this works, tell me; I will then ask the gateway session to change its `tax_upstream` to `tax-healthcare-tool-web:8000`. (Doing that earlier, before this app is on the network, would make the gateway return errors.)
6. Out of scope here: closing port 8890/8889 (G3), decommissioning the old rootful copy (separate step, mine to approve), any sudo.

## Rules
Secrets and privacy as in this repo's `CLAUDE.md`; no real addresses or usernames in tracked files or in the report. Update `CLAUDE.md` and add an ADR after each decision. End with the end-of-phase report (done, commits, checks, deviations, open questions, what was not verified), each acceptance criterion marked met / not met / not verifiable here, then wait for my "go".

Acceptance: unit has `Network=gateway.network`; `https://cornil.fritz.box/tax-healthcare/` works through the gateway with login and a form post; the old plain port still works; the new tests pass; no Caddy code and no secrets in the repo.
