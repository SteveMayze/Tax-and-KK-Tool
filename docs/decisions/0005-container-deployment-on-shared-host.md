# ADR 0005: Container deployment next to an existing app

Status: accepted (Phase 8). Partly superseded by ADR 0006 on one point: static files are now served (WhiteNoise) and the app can run under a URL prefix.

## Context
The target host already runs "Parts DB" (rootful Podman + Quadlet, plain-text secret in a world-readable unit file, port published on all interfaces). Caddy is installed but is a leftover from earlier research work. CLAUDE.md requires a separate image, container, data directory, database, port/route, health check, WSGI server, backups with a tested restore, a rollback plan, and no changes to shared infrastructure without approval.

## Decisions (owner approved the secret and backup choices on 2026-10-18; routing and TLS were revised the same day, see below)
- **Same mechanism, stricter settings:** rootful Podman + Quadlet like the existing app, but a non-root container user, read-only root file system, dropped capabilities, resource limits, health-check restarts and a loopback-only port.
- **Plain HTTP on the app's own port (8889), no Caddy, no TLS** (owner decision after the first deploy attempt: the Caddy setup is legacy and TLS is not needed, as for Parts DB). This supersedes the initial plan (HTTPS on port 8443 via a Caddy import snippet), which was implemented and then removed before it ever ran. Consequence: credentials and data are unencrypted on the LAN; `listen_address` narrows the exposure and `use_https` plus a proxy can restore TLS later. The production settings therefore have a `DJANGO_HTTPS` switch (secure cookies off when plain HTTP, otherwise login would be impossible).
- **Health check as a script** (`healthcheck.py`): Quadlet re-quotes inline commands and broke a `python -c "..."` check.
- **Secret generated on the server** into a root-only file and passed with `EnvironmentFile`; it never exists in the repository or on the Mac.
- **Deploy exactly the committed revision** (`git archive`), never the working directory, so private files (`local/`, databases, uploads) cannot be shipped by accident.
- **Backups:** online SQLite backup + uploads in one verified archive, daily timer, 14 daily / 12 monthly retention, a backup before every deploy, an off-server copy on demand, a non-destructive restore drill, and restores that move existing data aside instead of deleting it.
- **No shared package changes:** the playbooks do not install or upgrade packages on the host.
- **No admin site and no static files in production:** the app uses inline styles and does not use the Django admin, so neither a static file server nor `collectstatic` is needed.

## Consequences
- Deploying needs the sudo password (`-K`), as with the existing app.
- The data and its backups share a disk; the off-server copy is a manual step (`make fetch-backup`).
- Plain HTTP on the LAN (see above).
