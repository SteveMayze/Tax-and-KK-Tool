# ADR 0007: Rootless Podman for the application

Status: accepted (Phase 9A, 2026-10-19; owner approved proceeding, defaults used for the three design questions, see below). Supersedes in part ADR 0005 ("rootful Podman + Quadlet like the existing app" and "deploying needs the sudo password"). The rest of ADR 0005 (non-root container user, read-only root file system, dropped capabilities, health check, `git archive` deploys, backups, plain HTTP on 8889) stands.

## Context
The Phase 8 report says the app runs as a rootful container managed by system-level Quadlet units, and every deploy needed `-K` (sudo password). The owner expected rootless. Rootful means an escape from the container would be root on a server that also runs another app and, later, a gateway; and every routine step needs the sudo password. Inspection (2026-10-19, read-only): Podman 5.4.2 with `passt`/`pasta` and `uidmap` installed, systemd 257, cgroup v2 with `cpu memory pids` available to user slices, no SELinux, `ip_unprivileged_port_start=1024`, an admin login with sub-id ranges and sudo, linger off.

## Decisions (defaults of PHASES_2.md, unchanged because the owner did not choose otherwise)
1. **A dedicated user `homeapps`**, no password (locked), SSH key only, real shell. Shared later by the gateway and optionally Parts DB. Rejected: the owner's own login (simpler, but mixes admin rights, personal files and the service).
2. **One last sudo, in a labelled bootstrap playbook** (`infra/bootstrap-rootless.yml`): installs missing packages, creates the user, authorises the key, ensures sub-ids, enables linger, creates folders. No app, secret or firewall change. Routine deploys need no sudo; a test enforces it, with two documented exceptions (`bootstrap-rootless`, `migrate-copy`).
3. **Cut-over side by side**: the rootless copy is built on trial port 8890, a fresh backup of the rootful instance is loaded into it, row counts and a content hash are compared (`data_fingerprint`), the owner looks, then the owner stops the rootful unit and the rootless one takes 8889. The rootful container and its data stay untouched until the owner removes them (commands documented, not run).
4. **Where data lives:** `/home/homeapps/tax-healthcare-tool/{data,uploads,backups,build,config}`, mode 0700, owned by `homeapps`. Not under `/var/lib` (that needs root to create); not repo-relative.
5. **User mapping:** `UserNS=keep-id:uid=10001,gid=10001` with `User=10001`. The host user appears as the app user inside the container; other ids map into the sub-id range. Result: data files are owned by `homeapps` on the host, no `chown` or root needed, and a process escaping the container has only `homeapps` rights. Rejected: an explicit `UIDMap` table (more to get wrong), and a root-mapped container (`root` inside = `homeapps` outside would drop the non-root-in-container hardening).
6. **Secret:** generated on the server on first deploy into `config/env` (mode 0600, owned by `homeapps`). The rootless instance gets a **new** key (the old one is root-readable only), so everyone logs in once after the cut-over; the data is unaffected.
7. **Backups:** a systemd **user** timer and service (daily 03:15, `Persistent=true`), working without a login because of linger; same archive format, verification, retention and restore tools as before.
8. **Reaching other containers:** via the published host port (`127.0.0.1:8889`). A future gateway running as the same user may join a user-level Podman network instead. No shared network now.
9. **Hardening retained:** read-only root file system, capabilities dropped, no-new-privileges, health check with restart, memory 512 MB and 256 processes (needs cgroup delegation to the user manager; verified through `make status`, never dropped silently).
10. **What still needs root and why:** the bootstrap (users, linger, packages, system files), `make migrate-copy` and stopping/removing the old rootful setup (the old data and unit are root-owned), and an optional later `net.ipv4.ip_unprivileged_port_start` change if the gateway must bind 443 (affects every user of the server; therefore off by default and a separate decision).

## Consequences
- After the bootstrap, `make deploy`, `status`, `backup-now`, `restore-drill`, `fetch-backup`, `restore`, `rollback` need no password.
- Images live in `homeapps`' own Podman storage; the old rootful images are separate and can be removed later.
- The ports 80/443 stay unavailable to the service user until the sysctl decision is made.
- The rootless setup was rehearsed (syntax check, template rendering, the real Quadlet generator in dry-run, a sudo-free `--check` of the bootstrap) but has not yet run on the server; see the Phase 9A report for what only the server can prove.
