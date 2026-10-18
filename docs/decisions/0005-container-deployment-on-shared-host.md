# ADR 0005: Container deployment next to an existing app

Status: accepted (Phase 8)

## Context
The target host already runs "Parts DB" (rootful Podman + Quadlet, one shared Caddyfile that its playbook overwrites, plain-text secret in a world-readable unit file, port published on all interfaces). CLAUDE.md requires a separate image, container, data directory, database, port/route, health check, WSGI server, backups with a tested restore, a rollback plan, and no changes to shared infrastructure without approval.

## Decisions (owner approved the routing, Caddy, secret and backup choices on 2026-10-18)
- **Same mechanism, stricter settings:** rootful Podman + Quadlet like the existing app, but a non-root container user, read-only root file system, dropped capabilities, resource limits, health-check restarts and a loopback-only port.
- **Own HTTPS port (8443) on the same host name** rather than a path prefix or a new host name: no clash with `/parts`, `/admin`, `/static`, no Django prefix handling, no DNS change.
- **Caddy via an import snippet:** one `import` line added once to the shared Caddyfile (backed up, validated, restored on failure) and a self-contained snippet file. The other app's playbook must keep that line (one-line change proposed, not applied). The snippet requests a local certificate (`tls internal`) because the shared Caddy currently has no working certificate source.
- **Secret generated on the server** into a root-only file and passed with `EnvironmentFile`; it never exists in the repository or on the Mac.
- **Deploy exactly the committed revision** (`git archive`), never the working directory, so private files (`local/`, databases, uploads) cannot be shipped by accident.
- **Backups:** online SQLite backup + uploads in one verified archive, daily timer, 14 daily / 12 monthly retention, a backup before every deploy, an off-server copy on demand, a non-destructive restore drill, and restores that move existing data aside instead of deleting it.
- **No shared package changes:** the playbooks do not install or upgrade packages on the host.
- **No admin site and no static files in production:** the app uses inline styles and does not use the Django admin, so neither a static file server nor `collectstatic` is needed.

## Consequences
- Deploying needs the sudo password (`-K`), as with the existing app.
- The data and its backups share a disk; the off-server copy is a manual step (`make fetch-backup`).
- Caddy snippet persistence depends on the other app's Caddy playbook keeping the import line.
