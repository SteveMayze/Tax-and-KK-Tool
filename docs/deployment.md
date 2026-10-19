# Deployment (Phase 8)

The app runs as its **own Podman container**, managed by **Quadlet/systemd**, with its own data directory and database. It is reached **directly over plain HTTP on its own port**, like the existing "Parts DB" app next to which it runs; it never touches that app's container, data or database, and it does not use or change Caddy.

Host and user names are not stored in the repository: they live in the git-ignored `infra/inventory.ini` (example: `infra/inventory.ini.example`). In this document `<server>` is the host in that file.

## What was inspected first (2026-10-18, read-only)
| Item | Finding |
|---|---|
| Host | Debian 13, 4 cores, 3.7 GB RAM, 23 GB free; Podman 5.4.2 (crun, overlay), Caddy 2.11, no active firewall |
| Access | SSH key login as an admin user in the `sudo` group; `sudo` needs a password, so privileged Ansible tasks run with `-K` |
| Existing app | "Parts DB": **rootful** Podman container run as a system service from a Quadlet file in `/etc/containers/systemd/`, image built on the server from rsynced source, data under the admin user's home, published on port 8888 |
| Existing Ansible | In the Parts DB project (`infra/`): `deploy-playbook-podman-quadlet.yaml`, `configure-caddy-playbook.yaml`, plain-text secrets in a git-ignored `group_vars/all.yml`, `-K` on the command line via Make |
| Caddy | Installed, but a leftover from earlier research work; **not used by this app** and not modified by it |
| Ports in use | 22, 80, 443 (Caddy), 8888 (Parts DB), 2019 (Caddy admin, loopback); this app uses **8889** |

This app follows the same conventions (rootful Podman, Quadlet in `/etc/containers/systemd/`, image built on the server, Ansible with `-K`) and deliberately differs where the existing setup is weaker (see ADR 0005).

### Plain HTTP (owner decision, 2026-10-18)
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
| Container | name `tax-healthcare-tool-web`; non-root uid 10001; read-only root file system; all capabilities dropped; no-new-privileges; 512 MB memory and 256 process limits; health check (`python /app/healthcheck.py`, a script because Quadlet mangles inline commands) every 30 s with restart on failure |
| Settings | `config.settings_prod`: everything from environment variables, start-up fails on a missing or weak value, `DEBUG` off, admin site off, `ALLOWED_HOSTS` and CSRF origins explicit, console logging at WARNING; `DJANGO_HTTPS=0` here (plain HTTP: cookies cannot be "secure"), default is HTTPS-hardened |
| Secret | `DJANGO_SECRET_KEY` generated **on the server** on first deploy into `/etc/tax-healthcare-tool/env` (root, mode 0600), passed with `EnvironmentFile`; never in the repository, on the Mac, or in the unit file; never overwritten by later deploys |
| Data | `/var/lib/tax-healthcare-tool/{data,uploads,backups}` owned by uid 10001, mode 0700; the database is `/var/lib/tax-healthcare-tool/data/db.sqlite3` |
| Port | container 8000 published on `<listen_address>:8889` (default all interfaces) |
| Service names | `tax-healthcare-tool.service` (from the Quadlet file), `tax-healthcare-tool-backup.service` and `.timer` |
| Wrapper | `/usr/local/sbin/tax-healthcare-tool-manage` runs a Django management command in a throw-away container with the real data (used for `createsuperuser`, `changepassword`, manual backups) |

## First deployment
Prerequisites on your Mac: this repository with the Phase 8 changes **committed** (the deployment is exactly the committed revision), `infra/inventory.ini` (copy of the example, already present), and the Ansible environment:
```
make ansible-setup      # creates .venv-infra with the pinned ansible-core
make syntax             # offline check of all playbooks
make test
```
Then, in order (each asks for the sudo password of the server user):
```
make deploy             # directories, secret, pre-deploy backup (if any), build, migrate, service, backup timer
make createsuperuser    # your login (prompted on the server)
```
Open `http://<server>:8889/`.

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
| Schedule | daily 03:15 (+ up to 10 min random delay, `Persistent=true` so a missed run happens at next boot), plus `pre-deploy`, `pre-rollback`, `pre-restore` and `manual` backups |
| Retention | the newest backup of each of the last 14 days and of each of the last 12 months, and every labelled backup younger than 30 days; only files matching `backup-YYYYMMDD-HHMMSS[-label].tar.gz` are ever deleted |
| Location | `/var/lib/tax-healthcare-tool/backups/` (mode 0700). **Same disk as the data**, so also run `make fetch-backup` regularly: it copies the newest backup to `local/backups/` on your Mac (git-ignored; keep that folder out of synced or shared locations) |
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
| Remove the app completely | manual and deliberately not automated: stop and disable `tax-healthcare-tool.service` and the backup timer, delete their unit files (`/etc/containers/systemd/tax-healthcare-tool.container`, `/etc/systemd/system/tax-healthcare-tool-backup.*`) and `/usr/local/sbin/tax-healthcare-tool-manage`, remove the images, and only then (after fetching a backup) the data and `/etc/tax-healthcare-tool` |

## Operations
| Task | Command |
|---|---|
| Overview | `make status` |
| Logs | `sudo journalctl -u tax-healthcare-tool -n 100` (gunicorn request lines and warnings; no payment contents) |
| Restart | `sudo systemctl restart tax-healthcare-tool` |
| New password | `make changepassword USERNAME=<name>` |
| Base image / package updates | change the pin in `Containerfile` or `requirements.txt`, run `make test`, commit, `make deploy` |
| Rotate the secret key | delete `/etc/tax-healthcare-tool/env` on the server and deploy again (all sessions end) |
| Backup timer | `systemctl list-timers tax-healthcare-tool-backup.timer`; a failed run shows in `make status` |

## URL prefix, reverse proxy, cookies and static files (Phase 9)
Prepares the app for the gateway (a separate repository) that serves it over HTTPS at `/tax-healthcare`. Nothing here configures Caddy, and **the deployed port stays 8889**.

- **Prefix.** `url_prefix` in `infra/group_vars/all.yml` (`DJANGO_URL_PREFIX`) is `/tax-healthcare`. Every generated URL (links, form actions, redirects, login redirect, static files) then starts with it (`FORCE_SCRIPT_NAME`). The app answers **both** when the proxy strips the prefix before forwarding (`handle_path`) and when a request still carries it, so the same container works behind the gateway and directly on its own port. Direct use therefore becomes `http://<server>:8889/tax-healthcare/` (the old `http://<server>:8889/` also still answers, and its pages link to the prefixed URLs). Set `url_prefix: ""` to go back to root-only URLs. Health checks use `/health/` and need no prefix.
- **TLS proxy.** `behind_tls_proxy: true` (`DJANGO_BEHIND_TLS_PROXY=1`) makes Django trust `X-Forwarded-Proto: https`, so HTTPS requests count as secure. Only set it when the proxy is in place; while port 8889 is still open, a LAN client could send that header itself (the effect is limited to Django treating its own request as secure; closing 8889 is a later step in the gateway track). Secure cookies stay governed by `use_https`, which must stay `false` while the app is also used over plain HTTP on 8889, otherwise those logins break.
- **Hosts and origins.** `extra_allowed_hosts` and `extra_csrf_origins` (full origin with scheme, e.g. `https://tax.example.test`) add the gateway's host name and browser origin to `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`. A form post from an origin that is not listed is refused with 403.
- **HSTS** (`hsts_seconds`, `DJANGO_HSTS_SECONDS`) stays **0**. HSTS tells a browser to refuse the site whenever its certificate is not trusted; with a local CA that cannot be undone quickly, so enable it only after the CA is installed on every device, and start with a small value.
- **Cookies.** Session `taxhc_sessionid`, CSRF `taxhc_csrftoken` (Django's defaults would collide with the other app on the same host: browsers share cookies across ports and paths). Their path is the prefix when one is set. A login made on a direct `:8889/` URL is therefore sent on to the prefixed pages. After this update everyone is logged out once.
- **Static files.** The stylesheet (`core/static/core/base.css`, moved out of the page) is collected into `/app/staticfiles` while the image is built and served by WhiteNoise (pinned in `requirements.txt`) at `<prefix>/static/`. The admin site stays off.
- **`listen_address`** (default `0.0.0.0`) is the interface the container port is published on; set it to the server's LAN address to narrow it, or `127.0.0.1` when only the gateway on the same host should reach the app. It is rendered into `PublishPort=` in the Quadlet unit.
- The deployment stays rootful here. Phase 9A converts it to rootless; the new settings are plain variables and environment lines in the same two places (`group_vars/all.yml` and the Quadlet template), so they move unchanged.

### Rehearsal run for this phase
`make syntax` passes for all six playbooks. The Quadlet template and `podman_run_flags` were rendered with Ansible's own template engine (default values and with a proxy host, origin and `behind_tls_proxy: true`). `ansible-playbook --check` against the server and a container build were **not** run (see the Phase 9 report: `--check` needs the sudo password, and there is no container runtime on the development Mac).

## Configuration reference
| Variable | Where | Purpose |
|---|---|---|
| `DJANGO_SETTINGS_MODULE=config.settings_prod` | image and unit | production settings |
| `DJANGO_SECRET_KEY` | `/etc/tax-healthcare-tool/env` | session/CSRF signing key (at least 50 characters) |
| `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` | unit | `<server>` plus loopback names for the health check; `http://<server>:8889` |
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
| 403 on form submit | the origin is not in `DJANGO_CSRF_TRUSTED_ORIGINS` (must be `http://<server>:8889`) |
| Login page loads but login does nothing | secure cookies with plain HTTP: `DJANGO_HTTPS` must be `0` when served over HTTP |
| `make deploy` waits then fails on "healthy" | `sudo journalctl -u tax-healthcare-tool -n 80` and `curl http://127.0.0.1:8889/health/` on the server; the second tells whether the app or only the check is failing |
| Exchange-rate lookups fail | the container needs outbound HTTPS; manual rates still work |
