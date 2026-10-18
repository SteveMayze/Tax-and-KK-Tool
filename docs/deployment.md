# Deployment (Phase 8)

The app runs as its **own Podman container**, managed by **Quadlet/systemd**, behind the host's existing **Caddy**, with its own data directory and database. It runs next to the existing "Parts DB" app and never touches that app's container, data or database.

Host and user names are not stored in the repository: they live in the git-ignored `infra/inventory.ini` (example: `infra/inventory.ini.example`). In this document `<server>` is the host in that file.

## What was inspected first (2026-10-18, read-only)
| Item | Finding |
|---|---|
| Host | Debian 13, 4 cores, 3.7 GB RAM, 23 GB free; Podman 5.4.2 (crun, overlay), Caddy 2.11, no active firewall |
| Access | SSH key login as an admin user in the `sudo` group; `sudo` needs a password, so privileged Ansible tasks run with `-K` |
| Existing app | "Parts DB": **rootful** Podman container run as a system service from a Quadlet file in `/etc/containers/systemd/`, image built on the server from rsynced source, data under the admin user's home, published on port 8888 |
| Existing Ansible | In the Parts DB project (`infra/`): `deploy-playbook-podman-quadlet.yaml`, `configure-caddy-playbook.yaml`, plain-text secrets in a git-ignored `group_vars/all.yml`, `-K` on the command line via Make |
| Caddy | One shared `/etc/caddy/Caddyfile`, site `<server>` with routes `/parts*`, `/admin*`, `/static*` |
| Ports in use | 22, 80, 443 (Caddy), 8888 (Parts DB), 2019 (Caddy admin, loopback) |

This app follows the same conventions (rootful Podman, Quadlet in `/etc/containers/systemd/`, image built on the server, Ansible with `-K`) and deliberately differs where the existing setup is weaker (see ADR 0005).

### Observations about the shared setup (nothing was changed by this phase)
1. **The Parts DB Caddy playbook overwrites the whole Caddyfile** every time it runs. A route added directly to that file would silently disappear. This app therefore uses an `import` snippet (below), and the Parts DB template needs one extra line to keep it: add `import /etc/caddy/conf.d/*.caddy` at the end of its `infra/templates/Caddyfile.parts-db.j2`. I have not edited that project. Until that line is added, running the Parts DB Caddy playbook removes the import line and this app's HTTPS route (the app itself keeps running; `make caddy` restores the route).
2. **HTTPS on port 443 is currently failing** for `<server>`: Caddy keeps trying to get a public certificate for a private name (the journal shows repeated ACME/NXDOMAIN errors) and a TLS handshake fails. The earlier Caddyfile (backup `Caddyfile.bak-20261007102054`) had a global `local_certs` option and an `/api/*` reverse proxy to another LAN host protected by an API token; the Parts DB playbook replaced it on 2026-10-07. Parts DB is still reachable on port 8888. This app asks Caddy for its own locally issued certificate (`tls internal`), so it does not depend on that state.
3. Parts DB publishes port 8888 on all interfaces and there is no firewall, so it is reachable from the whole LAN. This app is published on the loopback interface only.

## Design
```
browser --HTTPS--> Caddy  <server>:8443 (tls internal) --> 127.0.0.1:8889 --> container (gunicorn, 2 workers)
                                                                                  /data     SQLite database
                                                                                  /uploads  imported CSV originals
                                                                                  /backups  backup archives
```
| Aspect | Choice |
|---|---|
| Image | `localhost/tax-healthcare-tool:<commit>`, tagged `current` and `previous`; built on the server from `git archive HEAD` with `Containerfile`; base `python:3.14.5-slim-trixie`, packages pinned in `requirements.txt` |
| Container | name `tax-healthcare-tool-web`; non-root uid 10001; read-only root file system; all capabilities dropped; no-new-privileges; 512 MB memory and 256 process limits; health check on `/health/` every 30 s with restart on failure |
| Settings | `config.settings_prod`: everything from environment variables, start-up fails on a missing or weak value, `DEBUG` off, admin site off, secure cookies, `ALLOWED_HOSTS` and CSRF origins explicit, console logging at WARNING |
| Secret | `DJANGO_SECRET_KEY` generated **on the server** on first deploy into `/etc/tax-healthcare-tool/env` (root, mode 0600), passed with `EnvironmentFile`; never in the repository, on the Mac, or in the unit file; never overwritten by later deploys |
| Data | `/var/lib/tax-healthcare-tool/{data,uploads,backups}` owned by uid 10001, mode 0700; the database is `/var/lib/tax-healthcare-tool/data/db.sqlite3` |
| Port | container 8000 published on `127.0.0.1:8889` only |
| Proxy | Caddy site `<server>:8443` in `/etc/caddy/conf.d/tax-healthcare-tool.caddy`, imported by one line in the shared Caddyfile |
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
make caddy              # adds the HTTPS site on port 8443 (validated; the Caddyfile is backed up first)
make createsuperuser    # your login (prompted on the server)
make caddy-root-cert    # optional: copies Caddy's local CA certificate to local/ so your Mac trusts the site
```
Open `https://<server>:8443/`. Without trusting the certificate the browser shows a warning. To trust it on macOS: `sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain local/caddy-local-root.crt`.

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
| Situation | Action |
|---|---|
| New release misbehaves, database unaffected | `make rollback` swaps `current` back to `previous` and restarts (after a `pre-rollback` backup) |
| New release ran migrations the old code cannot use | `make rollback BACKUP=backup-<time>-pre-deploy.tar.gz` also restores the data from just before the deploy (changes made since the deploy are lost) |
| Caddy change causes trouble | `make caddy-remove` removes the snippet and the import line, validates and reloads; the other app's routes are never touched. `caddy.yaml` itself restores the Caddyfile if validation fails |
| Remove the app completely | manual and deliberately not automated: stop and disable `tax-healthcare-tool.service` and the backup timer, delete their unit files and `/usr/local/sbin/tax-healthcare-tool-manage`, remove the images, and only then (after fetching a backup) the data and `/etc/tax-healthcare-tool` |

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

## Configuration reference
| Variable | Where | Purpose |
|---|---|---|
| `DJANGO_SETTINGS_MODULE=config.settings_prod` | image and unit | production settings |
| `DJANGO_SECRET_KEY` | `/etc/tax-healthcare-tool/env` | session/CSRF signing key (at least 50 characters) |
| `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` | unit | `<server>` plus loopback names for the health check; `https://<server>:8443` |
| `DJANGO_DB_PATH`, `DJANGO_UPLOAD_DIR`, `DJANGO_BACKUP_DIR` | unit | absolute paths inside the container (`/data/db.sqlite3`, `/uploads`, `/backups`) |
| `DJANGO_RATE_PROVIDER`, `FRANKFURTER_*` | optional | exchange-rate source (default Frankfurter/ECB; the container needs outbound HTTPS to `api.frankfurter.dev`) |
| `DJANGO_HSTS_SECONDS` | optional | HSTS is off by default because the certificate comes from a local CA |
| `DJANGO_ENABLE_ADMIN` | optional | Django admin, off in production |

## What has and has not been verified
Verified on the Mac (all in the test suite or run by hand):
- production settings: each required variable is enforced, weak values are rejected, security headers/cookies/host checking behave, `check --deploy` has no errors (two accepted warnings, see `core/test_settings_prod.py`), a fresh database migrates;
- gunicorn on Python 3.14 serves the app under those settings;
- backup, retention, tamper/corruption detection, path-traversal protection and restore, including a restore into a new location compared with the original;
- all playbooks pass `ansible-playbook --syntax-check`; all templates render correctly with Ansible's own template engine;
- static guard-rail tests for the Containerfile, Quadlet file, playbooks and repository hygiene.

**Not yet verified, because it needs the server and the sudo password:** the image build on the host, Quadlet generation and the systemd units, the Caddy snippet, the health check as Podman runs it, the backup timer, and the restore drill on the real host. The first `make deploy` is therefore the real test; the steps above end with commands that prove each part, and nothing is irreversible (a failed first deploy leaves only the new directories, image and unit files, which the removal steps above describe).

## Troubleshooting
| Symptom | Likely cause / check |
|---|---|
| `make deploy` stops at "Refuse to deploy uncommitted changes" | commit first, or `-e allow_dirty=true` to deploy HEAD anyway |
| Container restarts in a loop | `sudo journalctl -u tax-healthcare-tool -n 50`: a missing/invalid environment value stops start-up with a clear message |
| 400 "Bad Request" from the browser | the host name used in the URL is not in `DJANGO_ALLOWED_HOSTS` |
| 403 on form submit | the origin is not in `DJANGO_CSRF_TRUSTED_ORIGINS` (must be `https://<server>:8443`) |
| Browser certificate warning | expected until `make caddy-root-cert` and trusting that certificate |
| Exchange-rate lookups fail | the container needs outbound HTTPS; manual rates still work |
| `caddy.yaml` fails validation | it restored the Caddyfile and removed the snippet; read the Caddy error shown and fix the snippet template |
