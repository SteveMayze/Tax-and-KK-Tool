# Deployment (Phase 8; rootless since Phase 9A)

> **Rootless since Phase 9A.** The app is run by an ordinary Linux user (`homeapps`) with **rootless** Podman, and routine deploys need **no sudo**. New to Podman? Read `docs/podman-explained.md` first: it explains every term and command. The decision is ADR 0007. The Phase 8 rootful layout is described under "Legacy rootful setup" at the end and is kept only until you remove it.
> **Status:** written and rehearsed, not yet run on the server (see "What has and has not been verified").

The app runs as its **own Podman container**, managed by **Quadlet/systemd**, with its own data directory and database. It is reached **directly over plain HTTP on its own port**, like the existing "Parts DB" app next to which it runs; it never touches that app's container, data or database, and it does not use or change Caddy.

Host and user names are not stored in the repository: they live in the git-ignored `infra/inventory.ini` (example: `infra/inventory.ini.example`). In this document `<server>` is the host in that file.

## What was inspected first (2026-10-18, read-only)
| Item | Finding |
|---|---|
| Host | Debian 13, 4 cores, 3.7 GB RAM, 23 GB free; Podman 5.4.2 (crun, overlay), Caddy 2.11, no active firewall |
| Access | SSH key login as an admin user in the `sudo` group; `sudo` needs a password (this was why every Phase 8 task used `-K`) |
| Existing app | "Parts DB": **rootful** Podman container run as a system service from a Quadlet file in `/etc/containers/systemd/`, image built on the server from rsynced source, data under the admin user's home, published on port 8888 |
| Existing Ansible | In the Parts DB project (`infra/`): `deploy-playbook-podman-quadlet.yaml`, `configure-caddy-playbook.yaml`, plain-text secrets in a git-ignored `group_vars/all.yml`, `-K` on the command line via Make |
| Caddy | Installed, but a leftover from earlier research work; **not used by this app** and not modified by it |
| Ports in use | 22, 80, 443 (Caddy), 8888 (Parts DB), 2019 (Caddy admin, loopback); this app: loopback only since G3 (the old rootful copy may still hold 8889) |

Phase 8 followed the same conventions (rootful Podman, Quadlet in `/etc/containers/systemd/`, image built on the server, Ansible with `-K`). Phase 9A moves this app to rootless (ADR 0007); Parts DB is not touched and stays rootful.

### Server inspection for Phase 9A (2026-10-19, read-only)
| Item | Finding |
|---|---|
| Podman / systemd | Podman 5.4.2 (crun 1.21, netavark, aardvark-dns, `passt`/`pasta` and `slirp4netns` installed), `uidmap` installed; systemd 257; Debian 13, kernel 6.12 |
| Current container | **rootful**: Quadlet files `parts-db.container` and `tax-healthcare-tool.container` in `/etc/containers/systemd/` (root-owned), run by the server's own systemd; the Ansible connection uses an admin login in the `sudo` group and every privileged task needed `become` (sudo asks for a password) |
| Data and volumes | `/var/lib/tax-healthcare-tool/{data,uploads,backups}` owned by numeric uid/gid 10001 (mode 0700); `build/` and `DEPLOYED` owned by root; secret in `/etc/tax-healthcare-tool/env` (root, 0600) |
| Sub-id ranges | the admin login has `100000:65536` in `/etc/subuid` and `/etc/subgid`; no range exists yet for a service user (the bootstrap adds one, or `useradd` does) |
| Linger | off for the admin login; none for a service user yet |
| `net.ipv4.ip_unprivileged_port_start` | **1024**: a non-root user can bind 8889/8890 but not 80/443. The gateway track needs 443, so a later decision (the bootstrap has an optional variable, off by default) |
| cgroup v2 | unified hierarchy (`cgroup2fs`); controllers `cpu memory pids` are enabled for the user slice, so memory and process limits are expected to work in a user session; this can only be confirmed once the service user's manager runs (`make status` prints it) |
| SELinux | not present (no `getenforce`), so no `:Z` volume labels are needed |
| Backups today | a root-owned systemd timer (`tax-healthcare-tool-backup.timer`, daily about 03:15, last run on schedule) running the backup in a container |
| Ports | 22, 80, 443, 8888 (Parts DB), 8889 (this app) |

### Plain HTTP (owner decision, 2026-10-18; **superseded by ADR 0009**: the port is now loopback-only and the app is used through the gateway over https; the text below is the original reasoning)
No TLS and no reverse proxy: the app is served as plain HTTP on port 8889 of the server, like Parts DB on 8888. Consequences to be aware of: the login password, the session cookie and all financial data cross the home network **unencrypted**, and anyone on the LAN can reach the login page (there is no firewall on the host). Mitigations in place: login is required for every financial page, passwords are hashed, the container is hardened, and the port can be narrowed by setting `listen_address` in `infra/group_vars/all.yml` to the server's LAN address. If TLS is wanted later, set `use_https: true` and put a TLS-terminating proxy in front (the settings then switch to secure cookies).

## Design
```
browser --HTTP--> <server>:8889 --> container (gunicorn, 2 workers)
                                      /data     SQLite database
                                      /uploads  imported CSV originals
                                      /backups  backup archives
```
| Aspect | Choice |
|---|---|
| Image | `localhost/tax-healthcare-tool:<commit>`, tagged `current` and `previous`; built on the server from `git archive HEAD` with `Containerfile`; base `python:3.14.5-slim-trixie`, packages pinned in `requirements.txt` |
| Container | name `tax-healthcare-tool-web`; non-root uid 10001 inside, which is the service user `homeapps` on the host (`UserNS=keep-id:uid=10001,gid=10001`); read-only root file system; all capabilities dropped; no-new-privileges; 512 MB memory and 256 process limits; health check (`python /app/healthcheck.py`, a script because Quadlet mangles inline commands) every 30 s with restart on failure |
| Settings | `config.settings_prod`: everything from environment variables, start-up fails on a missing or weak value, `DEBUG` off, admin site off, `ALLOWED_HOSTS` and CSRF origins explicit, console logging at WARNING; `DJANGO_HTTPS=0` here (plain HTTP: cookies cannot be "secure"), default is HTTPS-hardened |
| Secret | `DJANGO_SECRET_KEY` generated **on the server** on first deploy into `~homeapps/tax-healthcare-tool/config/env` (owned by the service user, mode 0600), passed with `EnvironmentFile`; never in the repository, on the Mac, or in the unit file; never overwritten by later deploys |
| Data | `/home/homeapps/tax-healthcare-tool/{data,uploads,backups}` owned by `homeapps`, mode 0700 (inside the container that user is 10001); the database is `.../data/db.sqlite3` |
| Port | container 8000 published on `127.0.0.1:<app_port>` only (health probes; the LAN cannot reach it). The gateway reaches the app by name on the `gateway` network |
| Service names | user services `tax-healthcare-tool.service` (from the Quadlet file `~/.config/containers/systemd/tax-healthcare-tool.container`), `tax-healthcare-tool-backup.service` and `.timer` (in `~/.config/systemd/user/`); manage with `systemctl --user` |
| Wrapper | `~/bin/tax-healthcare-tool-manage` (as the service user, no sudo) runs a Django management command in a throw-away container with the real data (used for `createsuperuser`, `changepassword`, manual backups) |

## First deployment
Prerequisites on your Mac: this repository with your changes **committed** (the deployment is exactly the committed revision), `infra/inventory.ini` (copy of the example: the service-user login under `[taxtool]`, your admin login under `[taxtool_bootstrap]`), and the Ansible environment:
```
make ansible-setup      # creates .venv-infra with the pinned ansible-core
make syntax             # offline check of all playbooks
make test
```
Then, in order (only the first command asks for the sudo password, once):
```
make bootstrap-rootless # ONCE: service user, linger, sub-ids, folders (see docs/podman-explained.md)
make deploy             # directories, secret, pre-deploy backup (if any), build, migrate, service, backup timer
make createsuperuser    # your login (prompted on the server)
```
Open `https://<server>/tax-healthcare/` (through the gateway).

Then prove the safety net works before relying on it:
```
make backup-now         # a backup right now
make restore-drill      # restores it into a temporary directory and checks it; live data untouched
make fetch-backup       # copies it to local/backups/ on your Mac and verifies it there
make status             # read-only overview
```

## Updating
Commit, then `make deploy`. The playbook backs up first (`pre-deploy`), builds the new image, keeps the old one as `previous`, runs `check --deploy` and migrations, restarts, waits for a healthy container and checks `/health/`. Old images beyond the newest five builds are removed.

## Backups
| Item | Detail |
|---|---|
| Content | one `tar.gz` per backup: a consistent SQLite copy (online backup API, safe while the app runs), all uploaded files, and `MANIFEST.json` with SHA-256 of every file, the integrity-check result, row counts per table and the app version |
| Verification | at creation (integrity check of the copy) and at every restore/drill (checksums, no unexpected archive members, integrity check, row counts equal to the manifest) |
| Schedule | a systemd **user** timer, daily 03:15 (+ up to 10 min random delay, `Persistent=true` so a missed run happens at next boot; it fires with nobody logged in because linger is on), plus `pre-deploy`, `pre-rollback`, `pre-restore` and `manual` backups |
| Retention | the newest backup of each of the last 14 days and of each of the last 12 months, and every labelled backup younger than 30 days; only files matching `backup-YYYYMMDD-HHMMSS[-label].tar.gz` are ever deleted |
| Location | `/home/homeapps/tax-healthcare-tool/backups/` (mode 0700). **Same disk as the data**, so also run `make fetch-backup` regularly: it copies the newest backup to `local/backups/` on your Mac (git-ignored; keep that folder out of synced or shared locations) |
| Data loss window | up to 24 hours (since the last daily backup), or nothing since the last `make backup-now` |
| Privacy | backups contain all financial data and the original uploads; treat them like the database. Commands print only file names and row counts, never payment contents |

### Restore
1. Pick the backup (`ls` on the server, or `make status`).
2. Optional rehearsal: `make restore-drill BACKUP=<name>`.
3. `make restore BACKUP=<name>`: asks you to type `RESTORE`, verifies the archive, stops the app, takes a `pre-restore` safety backup, restores, starts the app and waits for it to be healthy.
Existing data is **moved aside** (`db.sqlite3.before-restore-<time>`, `uploads.before-restore-<time>` in the data directory), never deleted. Remove those by hand once you are sure.

To inspect a backup on your Mac without any server: `make fetch-backup`, then `.venv/bin/python manage.py restore_backup <name> --backup-dir local/backups` (verification only), or add `--target-db /tmp/x/db.sqlite3 --target-uploads /tmp/x/up` to extract it.

## Rollback plan
Rule that keeps rollback possible: configuration changes (new environment variables or settings) must stay compatible with the previous release. If a release breaks that, `make rollback` refuses to proceed; roll back by checking out the older commit and running `make deploy` instead.

| Situation | Action |
|---|---|
| New release misbehaves, database unaffected | `make rollback` first proves that the previous image starts with the current configuration (and stops if not), then swaps `current` back to `previous` and restarts (after a `pre-rollback` backup) |
| New release ran migrations the old code cannot use | `make rollback BACKUP=backup-<time>-pre-deploy.tar.gz` also restores the data from just before the deploy (changes made since the deploy are lost) |
| Remove the app completely | manual and deliberately not automated: as the service user stop and disable `tax-healthcare-tool.service` and the backup timer (`systemctl --user`), delete their unit files under `~/.config/`, remove the images (`podman rmi`), and only then (after fetching a backup) the data folder `~/tax-healthcare-tool` |
| Go back to the old rootful setup | possible until you remove it: `docs/podman-explained.md` section 7 |

## Operations
| Task | Command |
|---|---|
| Overview | `make status` |
| Logs | `ssh homeapps@<server> journalctl --user -u tax-healthcare-tool -n 100` (gunicorn request lines and warnings; no payment contents) |
| Restart | `ssh homeapps@<server> systemctl --user restart tax-healthcare-tool` |
| New password | `make changepassword USERNAME=<name>` |
| Base image / package updates | change the pin in `Containerfile` or `requirements.txt`, run `make test`, commit, `make deploy` |
| Rotate the secret key | delete `~/tax-healthcare-tool/config/env` on the server (as the service user) and deploy again (all sessions end) |
| Backup timer | `systemctl --user list-timers` (as the service user); a failed run shows in `make status` |

## URL prefix, reverse proxy, cookies and static files (Phase 9)
Prepares the app for the gateway (a separate repository) that serves it over HTTPS at `/tax-healthcare`. Nothing here configures Caddy, and **the deployed port stays 8889**.

- **Prefix.** `url_prefix` in `infra/group_vars/all.yml` (`DJANGO_URL_PREFIX`) is `/tax-healthcare`. Every generated URL (links, form actions, redirects, login redirect, static files) then starts with it (`FORCE_SCRIPT_NAME`). The app answers **both** when the proxy strips the prefix before forwarding (`handle_path`) and when a request still carries it, so the same container works behind the gateway and directly on its own port. Direct use therefore becomes `http://<server>:8889/tax-healthcare/` (the old `http://<server>:8889/` also still answers, and its pages link to the prefixed URLs). Set `url_prefix: ""` to go back to root-only URLs. Health checks use `/health/` and need no prefix.
- **TLS proxy.** `behind_tls_proxy: true` (`DJANGO_BEHIND_TLS_PROXY=1`) makes Django trust `X-Forwarded-Proto: https`, so HTTPS requests count as secure. Only set it when the proxy is in place; while port 8889 is still open, a LAN client could send that header itself (the effect is limited to Django treating its own request as secure; closing 8889 is a later step in the gateway track). Secure cookies stay governed by `use_https`, which must stay `false` while the app is also used over plain HTTP on 8889, otherwise those logins break.
- **Hosts and origins.** `extra_allowed_hosts` and `extra_csrf_origins` (full origin with scheme, e.g. `https://tax.example.test`) add the gateway's host name and browser origin to `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`. A form post from an origin that is not listed is refused with 403.
- **HSTS** (`hsts_seconds`, `DJANGO_HSTS_SECONDS`) stays **0**. HSTS tells a browser to refuse the site whenever its certificate is not trusted; with a local CA that cannot be undone quickly, so enable it only after the CA is installed on every device, and start with a small value.
- **Cookies.** Session `taxhc_sessionid`, CSRF `taxhc_csrftoken` (Django's defaults would collide with the other app on the same host: browsers share cookies across ports and paths). Their path is the prefix when one is set. A login made on a direct `:8889/` URL is therefore sent on to the prefixed pages. After this update everyone is logged out once.
- **Static files.** The stylesheet (`core/static/core/base.css`, moved out of the page) is collected into `/app/staticfiles` while the image is built and served by WhiteNoise (pinned in `requirements.txt`) at `<prefix>/static/`. The admin site stays off.
- **`listen_address`** (default `127.0.0.1` since G3; `0.0.0.0` would reopen the plain-HTTP port to the LAN) is the interface the container port is published on; set it to the server's LAN address to narrow it, or `127.0.0.1` when only the gateway on the same host should reach the app. It is rendered into `PublishPort=` in the Quadlet unit.
- The new settings are plain variables and environment lines in `group_vars/all.yml` and the Quadlet template; Phase 9A moved them unchanged to the rootless layout.

## Gateway network (Phase 9B, ADR 0008)
The gateway (a separate repository; Caddy as a rootless container of the same service user) listens on 80/443 and forwards `/tax-healthcare/` to this app. Plain language: a **Podman network** is a private virtual switch between containers; containers on it find each other by name. The gateway made one called `gateway`; this app's unit now also plugs into it (`Network=gateway.network`), so the proxy can call `tax-healthcare-tool-web:8000` without any published port.

- `make deploy` first checks that `~/.config/containers/systemd/gateway.network` exists for the service user and stops with a clear message if not (deploy the gateway first). Nothing changes in that case.
- Defaults in `infra/group_vars/all.yml`: `behind_tls_proxy: true`, `extra_csrf_origins: ["https://{{ public_host }}"]`, `hsts_seconds: 0`, `use_https: true`. Since G3 (ADR 0009) the published port is loopback-only, the plain-HTTP origin is gone, and cookies are Secure (owner approved 2026-10-19).
- Why cookies are not Secure yet: see ADR 0008, decision 4.
- Check it: `ssh homeapps@<server> podman ps --format '{{.Names}} {{.Networks}}'` should list `tax-healthcare-tool-web` with `gateway` (and the default network). `podman network inspect gateway` lists both containers.
- If the proxy shows 502/connection errors: the app container is not on the network (`podman ps` network column), or its health check is failing (`make status`). If a form post gives 403: the browser origin is not in `DJANGO_CSRF_TRUSTED_ORIGINS`.

### Rehearsal run for this phase
`make syntax` passed for the six Phase 8 playbooks. The Quadlet template and `podman_run_flags` were rendered with Ansible's own template engine (default values and with a proxy host, origin and `behind_tls_proxy: true`). `ansible-playbook --check` against the server and a container build were **not** run (see the Phase 9 report: `--check` needs the sudo password, and there is no container runtime on the development Mac).

## Configuration reference
| Variable | Where | Purpose |
|---|---|---|
| `DJANGO_SETTINGS_MODULE=config.settings_prod` | image and unit | production settings |
| `DJANGO_SECRET_KEY` | `~homeapps/tax-healthcare-tool/config/env` | session/CSRF signing key (at least 50 characters) |
| `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` | unit | `<server>` plus loopback names for the health check; `https://<server>` (no plain-HTTP origin since G3) |
| `DJANGO_HTTPS` | unit | `0` for plain HTTP (secure cookies off), default `1` |
| `DJANGO_DB_PATH`, `DJANGO_UPLOAD_DIR`, `DJANGO_BACKUP_DIR` | unit | absolute paths inside the container (`/data/db.sqlite3`, `/uploads`, `/backups`) |
| `DJANGO_RATE_PROVIDER`, `FRANKFURTER_*` | optional | exchange-rate source (default Frankfurter/ECB; the container needs outbound HTTPS to `api.frankfurter.dev`) |
| `DJANGO_HSTS_SECONDS` | unit (`hsts_seconds`) | HSTS, `0` (off) by default, see "URL prefix" below |
| `DJANGO_URL_PREFIX` | unit (`url_prefix`) | `/tax-healthcare`; empty serves at the root |
| `DJANGO_BEHIND_TLS_PROXY` | unit (`behind_tls_proxy`) | `1` makes the app trust `X-Forwarded-Proto` from a TLS proxy |
| `DJANGO_STATIC_ROOT` | image | `/app/staticfiles`, filled by `collectstatic` during the image build |
| `DJANGO_ENABLE_ADMIN` | optional | Django admin, off in production |

## What has and has not been verified
Verified on the Mac (all in the test suite or run by hand): production settings in both HTTPS and plain-HTTP mode (each required variable is enforced, weak values rejected, host checking, a real login over plain HTTP with CSRF checks on, `check --deploy` without errors); gunicorn on Python 3.14; backup, retention, tamper/corruption detection, path-traversal protection and restore; the health-check script; the exact `git archive` the playbook ships; syntax and template rendering of all playbooks; static guard-rail tests for the Containerfile, Quadlet file and repository hygiene.

Found only by running on the real server (each fixed, each with a regression test):
1. `git archive` was run from `infra/`, which archived only that directory and left the build without a `Containerfile`. The playbook now archives the repository root and verifies the unpacked files before building.
2. Quadlet re-quotes inline commands, which dropped the closing quote of an inline `python -c "..."` health check, so the container never became healthy and was restarted in a loop. The check is now a script.
3. The pre-deploy backup ran the previous image with the new environment; the old settings rejected the new values and the deploy stopped before changing anything. The backup now runs with the newly built image (still before migrations).

**Not yet verified on the server:** the backup timer's first run and the restore drill (run `make backup-now` and `make restore-drill` after the first successful deploy).

## Troubleshooting
| Symptom | Likely cause / check |
|---|---|
| `make deploy` stops at "Refuse to deploy uncommitted changes" | commit first, or `-e allow_dirty=true` to deploy HEAD anyway |
| Container restarts in a loop | `sudo journalctl -u tax-healthcare-tool -n 50`: a missing/invalid environment value stops start-up with a clear message |
| 400 "Bad Request" from the browser | the host name used in the URL is not in `DJANGO_ALLOWED_HOSTS` |
| 403 on form submit | the origin is not in `DJANGO_CSRF_TRUSTED_ORIGINS` (must be `https://<server>`, the gateway's address) |
| Login page loads but login does nothing | secure cookies with plain HTTP: `DJANGO_HTTPS` must be `0` when served over HTTP |
| `make deploy` waits then fails on "healthy" | `sudo journalctl -u tax-healthcare-tool -n 80` and `curl http://127.0.0.1:8889/health/` on the server; the second tells whether the app or only the check is failing |
| Exchange-rate lookups fail | the container needs outbound HTTPS; manual rates still work |

## Rootless conversion (Phase 9A)
Files: `infra/bootstrap-rootless.yml` (once, sudo), `infra/deploy.yaml` and the other playbooks (service user, no sudo), `infra/tasks/service-session.yml` (shared pre-check), `infra/migrate-from-rootful.yaml` (sudo, move only), `infra/verify-migration.yaml`, and the Quadlet and backup templates.

| Question | Answer |
|---|---|
| Which user | `homeapps` (`service_user`): password locked, SSH key only, real shell (SSH needs one), linger on |
| User mapping | `UserNS=keep-id:uid=10001,gid=10001` + `User=10001`: the host user appears in the container as the app user, so the data folders owned by `homeapps` are writable by it; other container ids (root) map into the user's sub-id range. `podman_run_flags` and the restore drill use the same flags |
| Hardening kept | read-only root file system, all capabilities dropped, no-new-privileges, non-root user, health check with restart, `--memory=512m --pids-limit=256`. The memory and process limits need cgroup delegation to the user manager; `make status` prints the delegated controllers and the limits Podman recorded (`memory=0` or an unset process limit would mean a limit was **not** applied; that must be reported, not accepted silently) |
| Image | built by the service user from the same `git archive` of the repository root; the unpacked files are checked before the build |
| Backups | systemd user service and timer; fires without a login because of linger |
| Reaching other containers | by published host port (`127.0.0.1:8889`). A future gateway running as the same user can join a user-level Podman network instead |
| What still needs root | the bootstrap (once), `make migrate-copy` (reading the old root-owned data), stopping the old rootful unit and later removing it; optionally lowering `net.ipv4.ip_unprivileged_port_start` for port 443 (gateway track) |
| Migration proof | `data_fingerprint` (row counts and a content hash of every table except sessions, plus a hash of the uploaded files) of the backup archive versus the live rootless data: `make verify-migration` |

## Legacy rootful setup (Phase 8)
Until you remove it, the old container keeps its files: unit `/etc/containers/systemd/tax-healthcare-tool.container`, backup units `/etc/systemd/system/tax-healthcare-tool-backup.{service,timer}`, wrapper `/usr/local/sbin/tax-healthcare-tool-manage`, data `/var/lib/tax-healthcare-tool/`, secret `/etc/tax-healthcare-tool/env`, images in root's Podman storage. The Phase 8 playbooks that managed it (`become`, `-K`) are in git history at commit `b7d8e16` and earlier. Cut-over, going back and removal: `docs/podman-explained.md` sections 7 and 8.
