# GATEWAY.md: one Caddy owner for cornil.fritz.box

Run this in a **new, separate repository** (suggested name `cornil-gateway`), not inside the Tax and Healthcare Tool repo and not inside parts-db. Part B is a short companion change for the parts-db repo and is run in its own session.

Goal: both Django apps reachable over HTTPS at

- `https://cornil.fritz.box/parts-db`
- `https://cornil.fritz.box/tax-healthcare`

with Caddy as the single entry point, owned by exactly one repository, so one app's deploy can never overwrite the proxy configuration of the other (this happened on 2026-10-07: the parts-db Caddy playbook overwrote the whole shared Caddyfile and removed a `local_certs` option and an API route).

## Background

- Host: the home server `cornil` (rootful Podman with Quadlet, deployed with Ansible and a Makefile, `-K` for the sudo password).
- parts-db (https://github.com/SteveMayze/parts-db) currently listens on port 8888 over plain HTTP; the Tax and Healthcare Tool on port 8889.
- The FritzBox is the home router. `.fritz.box` is not a public domain, so no public certificate can be issued. Caddy's internal CA (`tls internal`) is the intended solution; each client must trust Caddy's root certificate once.
- The old Caddy was part of an abandoned ESP32 reverse-proxy experiment. Its old settings are legacy.
- No firewall is configured on the host.
- **Rootless goal (added scope).** The tax app runs today as a rootful Podman container and every deploy needs the sudo password. Phase 9A of `PHASES_2.md` converts it to rootless (an ordinary Linux user runs Podman, no sudo for routine deploys). The gateway must use the same model: Caddy as a rootless container of the same service user. The owner has little Podman experience: explain every concept and every command in plain language (see Phase 9A, "Why this phase exists", for the wording and for `docs/podman-explained.md`, which this repo should link to rather than copy).

## Standing rules

1. Inspect first and change nothing on the host during inspection (read-only commands only). Report what you found.
2. Never overwrite a file on the host that this repo does not own. Before replacing the existing Caddy setup, back up the old Caddyfile and the Caddy data directory to a dated folder and tell the owner where it is.
3. Rehearse before applying: `ansible-playbook --syntax-check`, `--check`, and `caddy validate` on the rendered Caddyfile (in a container if Caddy is not installed locally).
4. Secrets: none are needed. Do not put any password in the repo.
5. One step at a time, with a hard stop and a short report after each. The owner runs anything that needs sudo, with the exact command given.
6. Do not enable HSTS in this task.
7. Routine deploys of the gateway must not need the sudo password. Only a one-time bootstrap step may use sudo, and it must say exactly what it changes and why. Run this track after Phase 9A of the tax app is done, so the service user and the bootstrap pattern already exist; reuse them.

---

## Part A: the gateway repository

### G1: Inspect and design

Questions for the owner:
- Confirm the hostname `cornil.fritz.box` resolves on all the devices you use (Mac, phone, tablet).
- Does anything besides parts-db and the Tax and Healthcare Tool need the proxy? (Default: no; the old ESP32 API route is dropped.)
- Which devices will get Caddy's root certificate installed? (Default: Mac and phone.)
- Should Caddy run as the same rootless service user as the tax app (default `homeapps`, from Phase 9A)? (Default: yes.)
- Should parts-db also move to rootless later? (Default: yes, as a separate step after the gateway works; until then it stays rootful on port 8888.)

Tasks:
1. Read-only inspection of the host: what Caddy runs today (container or package, version), where its Caddyfile and data live, who owns it, which ports 80, 443, 8888 and 8889 are bound and by what, the Podman version, and how parts-db and the tax app are started.
2. Decide how Caddy reaches the apps. A Caddy container cannot use `127.0.0.1` for host services. Preferred design when Caddy and the tax app belong to the same rootless user: put them on one shared Podman network and let Caddy reach the app by container name, so the app publishes no port on the LAN at all. For parts-db (rootful until migrated) and as a fallback, test and choose between `host.containers.internal` and host networking; rootless networking behaves differently from rootful (Podman 5 uses `pasta`), so prove the choice with a real test, do not assume. Say why, and note the effect on the apps' `listen_address`.
3. **Privileged ports.** An ordinary user may not bind ports below 1024, but the wanted URL has no port number, so Caddy needs 80 and 443. The standard fix is one system setting, `net.ipv4.ip_unprivileged_port_start=80`, written to `/etc/sysctl.d/` and applied once by the bootstrap with sudo. Explain it in plain language, including the trade-off (any local user can then bind ports from 80 upward, acceptable on a single-owner home server) and the alternative (run Caddy rootful, which keeps sudo for gateway deploys; not recommended). Ask the owner to approve before it is applied.
4. Write the design in `docs/design.md` and an ADR in `docs/decisions/`.

Acceptance: the design names the network approach, the user that runs Caddy, what needs sudo once and why, the Caddy data directory location and its backup, and the rollback path. **Stop and report.**

### G2: Build the gateway (parallel to the old ports)

Tasks:
1. Repo skeleton: `README.md`, `Makefile`, `ansible/`, `Caddyfile` template, `docs/`, `.gitignore`.
2. The Caddyfile, roughly (adjust after G1):

   ```
   cornil.fritz.box {
       tls internal
       encode zstd gzip

       redir /parts-db /parts-db/ 308
       redir /tax-healthcare /tax-healthcare/ 308

       handle_path /parts-db/* {
           reverse_proxy <upstream for 8888>
       }
       handle_path /tax-healthcare/* {
           reverse_proxy <upstream for 8889>
       }

       handle {
           respond "cornil: parts-db and tax-healthcare" 200
       }
   }
   ```

   `handle_path` strips the prefix; each app generates prefixed URLs itself (see Part B and Phase 9 of the tax app). Caddy sends `X-Forwarded-Proto` and keeps the Host header; verify both.
3. Ansible: render the Caddyfile, run `caddy validate`, install a **rootless Quadlet user unit** for the service user (in `~/.config/containers/systemd/`, managed with `systemctl --user`, with linger already on from Phase 9A), read-only root file system if it works with Caddy, persistent volume for `/data`, reload rather than restart, and a handler that restores the previous Caddyfile if validation fails. The playbook connects as the service user and uses no sudo. The sysctl for ports 80 and 443 goes into a separate, clearly labelled bootstrap step the owner runs once.
4. A `make backup-caddy-data` target (the internal CA lives in the data directory; losing it means reinstalling the root certificate on every device).
5. A `make root-cert` target that fetches Caddy's root certificate (`root.crt`) for installation on clients, and `docs/trust-root-cert.md` with steps for macOS, iOS and Android, written for a non-expert.
6. A smoke-test script `make smoke` that checks, with curl and the root certificate, that `https://cornil.fritz.box/` responds, and that each app path returns its login page or a redirect to it.

Acceptance:
- `caddy validate` passes; `ansible-playbook --check` passes.
- After the one-time bootstrap, `make deploy` for the gateway runs without a sudo password (a test over the Makefile and playbooks finds no `-K`, `become` or `sudo` outside the bootstrap), and `podman ps` as the service user shows Caddy.
- After the owner installs the root certificate, `https://cornil.fritz.box/parts-db/` and `/tax-healthcare/` load without a browser warning and without breaking the old plain-HTTP ports (both still work).
- Re-running the playbook twice changes nothing the second time.
- Deploying or changing either app's repo cannot modify the gateway's Caddyfile (state how this is guaranteed: the apps no longer contain any Caddy playbook; the owner removes the old Caddy tasks from parts-db in Part B).

**Stop and report.** Do not close the old ports yet.

### G3: Close the plain ports

Only after Part B and Phase 9 of the tax app are deployed and both apps work through the gateway.

Tasks:
1. Set both apps to listen only where the gateway reaches them (the shared Podman network by container name, or localhost) so the LAN can no longer reach 8888 and 8889; with the shared network the apps publish no host port at all. Provide the exact variables for each app repo; do not change the other repos yourself.
2. Optionally propose host firewall rules that allow only 80 and 443 (and SSH) from the LAN; present them as a proposal, do not apply them without the owner's approval.
3. Update `docs/` with the final layout and a recovery procedure ("the root certificate expired or the CA was lost").

Acceptance: from another device on the LAN, `http://cornil.fritz.box:8888` and `:8889` are refused, and both https paths work. **Stop and report.**

---

## Part B: companion change in the parts-db repository (separate session)

Goal: parts-db runs under `/parts-db` behind the gateway, with no Caddy code of its own.

Questions for the owner: confirm the prefix `/parts-db`.

Tasks:
1. Verify parts-db's current settings, templates, login redirects, static files, cookies and deployment (how the Caddy playbook came to overwrite the shared file).
2. Prefix support, configurable by environment variable, default empty: `FORCE_SCRIPT_NAME`, prefixed `LOGIN_URL`, `LOGIN_REDIRECT_URL` and static URL, and `SECURE_PROXY_SSL_HEADER` when behind the TLS proxy; configurable `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` (`https://cornil.fritz.box`).
3. Distinct cookie names (for example `partsdb_sessionid`, `partsdb_csrftoken`) with cookie paths set to the prefix, so it and the tax app do not log each other out.
4. **Remove the Caddy playbook and tasks** from parts-db, and document that the proxy is owned by `cornil-gateway`. Keep a copy of the old playbook in git history only.
5. Add `listen_address` control to its deployment variables, defaulting to the current behaviour until G3.
6. **Optional follow-up, only after the gateway works and the owner says go:** move parts-db from rootful to rootless under the same service user, following the pattern of Phase 9A (explain in plain language, migrate beside the old instance, compare data, cut over, leave the old data until the owner approves removal). Treat this as its own step with its own report; do not combine it with the prefix work.
6. Tests with the real test client and `SCRIPT_NAME` set: login, redirects and form actions carry the prefix; static files load under the prefix.

Acceptance:
- All of parts-db's existing tests pass with the prefix empty; the new prefix tests pass.
- After deployment, `https://cornil.fritz.box/parts-db/` works through the gateway, and the old `http://cornil.fritz.box:8888` still works until G3.
- parts-db contains no Caddy configuration.

**Stop and report.**
