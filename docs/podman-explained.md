# Podman, containers and the rootless setup, explained from scratch

This guide assumes you know nothing about containers, Podman, systemd or Quadlet. Every term is explained the first time it appears, and every command has a one-line explanation. Technical detail and the design decision are in `docs/deployment.md` and `docs/decisions/0007-rootless-podman.md`.

**Status:** the rootless setup is written and rehearsed, but at the time of writing it has **not been run on the server yet**. Where this guide says what you "will see", that is what the code is designed to produce, not something observed on the real server. The report for Phase 9A lists what only the real server can prove.

## 1. The ideas

- **Container.** A packaged copy of the app, with everything it needs inside, that runs isolated from the rest of the server. It cannot see the server's other files unless we explicitly share a folder with it. The packaged copy itself is called an **image**; a container is an image that is running.
- **Podman.** The program that builds images and runs containers. (Docker is a well-known alternative; this project uses Podman.)
- **Root and sudo.** `root` is the all-powerful administrator account on a Linux server. `sudo` means "do this one command as root"; it asks for your password. Anything done as root can change or break anything on the server.
- **Rootful Podman** means Podman itself runs as root. Starting, stopping or deploying then needs `sudo`. If something ever escaped the container, it would be root on the server. This is how the app runs **today**.
- **Rootless Podman** means Podman runs as an ordinary Linux user with no special powers. Deploying and restarting need no `sudo`. Inside the container the program still thinks it has its own users, but they are all mapped onto that ordinary user, so an escape would only reach what that one user can reach. This is where the app is **going**.
- **User namespace / subordinate ids.** The trick that makes rootless work: Linux lends each user a private block of numbers ("subordinate ids", listed in `/etc/subuid` and `/etc/subgid`) that the container may use as its own user numbers. The first number in the block is handed to the container as if it were `root`, but outside the container it is just a harmless number nobody can log in as. Our setting (`keep-id`) additionally makes the service user itself appear inside the container as the app's user (number 10001), so the app can write to the data folders that belong to the service user.
- **systemd.** The server's service manager. It starts programs at boot and restarts them when they fail. There is one systemd for the whole server (it needs root to change) and one **per user** (it needs no root).
- **Quadlet.** A small text file (`*.container`) that describes a container; systemd turns it into a service. The old setup keeps that file in `/etc/containers/systemd/` (root only). The new one keeps it in the service user's own folder `~/.config/containers/systemd/`, and you control it with `systemctl --user`.
- **Linger.** A setting that lets a user's services keep running when nobody is logged in and start at boot. Without it, the container would stop when the last SSH session ended. Turning it on needs root, once.
- **SSH key.** A pair of files that replace a password when logging in over the network. The service user has **no password at all**; only your key opens it.
- **Health check.** A tiny test the container runs on itself every 30 seconds (it asks the app's `/health/` page whether it is alive). If it fails three times, the container is restarted.

## 2. Before and after

```
BEFORE (rootful)                                AFTER (rootless)

you ── make deploy ── asks for the sudo password  you ── make deploy ── no password, SSH key only
        │                                                 │
        ▼                                                 ▼
  Ansible logs in as your admin login             Ansible logs in as the service user "homeapps"
  and uses sudo for every step                    and runs every step as that user
        │                                                 │
        ▼                                                 ▼
  root ── Podman ── container                     homeapps ── Podman ── container
  data in /var/lib/... (owned by root-mapped      data in /home/homeapps/... (owned by homeapps)
  numbers), secret in /etc/... (root only)        secret in /home/homeapps/... (homeapps only)
  unit in /etc/containers/systemd/                unit in ~/.config/containers/systemd/
  backup timer in the server's systemd            backup timer in homeapps' own systemd
```

## 3. What needs sudo, and what does not

| Step | Needs sudo? | Why |
|---|---|---|
| `make bootstrap-rootless` (run **once**) | yes | creating a user, turning on linger and installing missing programs change the whole server |
| `make migrate-copy` (during the move only) | yes | the old data belongs to root, so only root can read it |
| Stopping the old rootful container (once, commands in section 7) | yes | it is a root-owned service |
| Removing the old rootful setup (later, commands in section 8) | yes | same |
| Everything else: `make deploy`, `status`, `backup-now`, `restore-drill`, `fetch-backup`, `restore`, `rollback`, `createsuperuser`, `changepassword`, `verify-migration` | **no** | they run as the service user |

A test in the repository fails if a command other than the two sudo ones above ever gains `sudo`, `become` or `-K` (Ansible's "ask for the sudo password" flag).

## 4. The one-time bootstrap

Your inventory file (`infra/inventory.ini`, never committed) has two logins for the same server: the service user for routine work and your own admin login for the two sudo steps. See `infra/inventory.ini.example`.

```
make ansible-setup           # once on your Mac: installs Ansible into a private folder (.venv-infra)
make syntax                  # checks that all playbooks are well-formed; changes nothing
make bootstrap-rootless      # asks for your sudo password once, then creates the service user and its folders
make bootstrap-rootless KEY=~/.ssh/other_key.pub   # same, with a specific public key to authorise
```

What the bootstrap does, in order (each step does nothing if it is already done): installs Podman and its helpers if missing (`passt`/`pasta` is the rootless networking helper; `uidmap` does the id mapping; `dbus-user-session` lets `systemctl --user` work over SSH); creates the user `homeapps` with a locked password; authorises your public key; makes sure it has a subordinate id range; turns on linger; creates its folders. It contains no app, no secret and no firewall change.

What you will see if it works: a list of tasks, then a final line like `ok=… changed=… failed=0`. A second run shows `changed=0`.

## 5. Daily commands

Run all of these on your Mac, from the project folder. None asks for a sudo password.

```
make deploy                  # builds the committed code on the server as homeapps and restarts the app (about a few minutes)
make status                  # read-only overview: who runs the app, its health, data owner, next backup
make backup-now              # takes a verified backup right now, on the server
make fetch-backup            # copies the newest backup to local/backups on your Mac and verifies it there
make restore-drill           # proves the newest backup can be restored, in a throw-away place; live data untouched
make restore BACKUP=backup-YYYYMMDD-HHMMSS.tar.gz   # replaces the live data with that backup (asks you to type RESTORE)
make rollback                # puts the previous version of the app back (add BACKUP=... to restore its data too)
make createsuperuser         # creates your login for the web page (asks for a name and password)
make changepassword USERNAME=name   # sets a new password for that login
```

Development helpers on your Mac only: `make setup` installs the app's Python packages; `make test` runs the test suite; `make check` runs Django's own configuration check.

What normal output looks like:

- `make deploy` ends with a summary: the commit that was deployed, the pre-deploy backup name (or "none (first deploy)"), whether migrations were applied, and the address to open. The wait for "healthy" can take up to a minute or two.
- `make status` shows `rootless=true`, a service state of `active`, the container health `healthy`, the owner of the data files as the service user's number, a next backup time under "backup timer", and `[http=200]` from the health probe.
- `make restore-drill` ends with `DRILL_OK`.
- `make rollback` ends with the health endpoint answering 200.

## 6. Checking that it really is rootless (commands for you)

```
ssh homeapps@<server>                                 # log in as the service user (your key opens it)
podman ps                                             # lists the running container; it must show tax-healthcare-tool-web
podman top tax-healthcare-tool-web huser user pid     # HUSER = the user on the server (must be homeapps, never root); USER = the user inside (10001)
ps -eo user,pid,args | grep gunicorn                  # the app's processes; the first column must be homeapps, not root
ls -ln ~/tax-healthcare-tool/data                     # the data files; owned by homeapps' number, not by a root-mapped number
systemctl --user list-timers                          # the daily backup timer and when it fires next
systemctl --user status tax-healthcare-tool.service   # the app's service: should say active (running)
loginctl show-user homeapps --property=Linger         # must say Linger=yes, so it runs with nobody logged in
curl -s http://127.0.0.1:8889/health/                 # the health page; answers {"status": "ok"}
```

Survives a restart: `systemctl --user restart tax-healthcare-tool.service` (as homeapps) and then `make status`. Survives a reboot (only you can check this): `sudo reboot` on the server, wait a minute or two with **nobody logged in**, then `make status` from your Mac.

## 7. Moving from the old rootful setup (cut-over procedure)

The old rootful container and its data are **never touched** by anything except the explicit steps below. Until you say so, they stay where they are.

**Part A: trial run next to the old app, on port 8890**

```
make bootstrap-rootless                        # once, see section 4
make deploy PORT=8890                          # builds and starts the rootless copy on port 8890 (the old app keeps 8889)
make migrate-copy                              # asks for sudo: takes a fresh backup of the OLD app and copies it to the rootless side; prints its name
make restore BACKUP=backup-<name>-migrate.tar.gz PORT=8890   # loads that backup into the rootless copy (type RESTORE)
make verify-migration BACKUP=backup-<name>-migrate.tar.gz PORT=8890   # compares row counts and a content hash; must print MATCH
```

Then open `http://<server>:8890/tax-healthcare/` and log in with your usual login. Look around. The old app on port 8889 is still the live one.

**Part B: the switch (only when you approve)**

Run on the server with your admin login (you need to type the sudo password). Together these stop the old container, keep it from starting again at boot, and leave all its data in place:

```
sudo systemctl stop tax-healthcare-tool.service                       # stops the old rootful container
sudo systemctl disable --now tax-healthcare-tool-backup.timer         # stops the old daily backup
sudo mv /etc/containers/systemd/tax-healthcare-tool.container /etc/containers/systemd/tax-healthcare-tool.container.rootful-disabled   # so it cannot start again after a reboot
sudo systemctl daemon-reload                                          # tells the server's systemd about the change
```

Then, on your Mac:

```
make migrate-copy                              # asks for sudo: a final backup of the old data (now nobody is writing to it), copied across; prints its name
make deploy                                    # restarts the rootless app on the real port 8889
make restore BACKUP=backup-<name>-migrate.tar.gz   # loads the final backup (type RESTORE)
make verify-migration BACKUP=backup-<name>-migrate.tar.gz   # must print MATCH
make status                                    # health, owner of the files, next backup
```

**Going back to the old rootful setup** (if something is wrong; its data was not touched):

```
ssh homeapps@<server> systemctl --user stop tax-healthcare-tool.service   # stops the rootless app (frees port 8889)
sudo mv /etc/containers/systemd/tax-healthcare-tool.container.rootful-disabled /etc/containers/systemd/tax-healthcare-tool.container   # puts the old unit file back
sudo systemctl daemon-reload                                          # tells systemd about it
sudo systemctl start tax-healthcare-tool.service                      # starts the old container again
sudo systemctl enable --now tax-healthcare-tool-backup.timer          # turns the old daily backup back on
```

Anything entered into the rootless app after the switch is only in the rootless data and its backups; ask for help to copy it back if you need that.

## 8. Removing the old rootful setup (later; not run by anything)

Only when you are sure you will not go back, and after a verified backup is safely copied off the server (`make fetch-backup`). These delete things permanently:

```
sudo rm /etc/containers/systemd/tax-healthcare-tool.container.rootful-disabled   # the old unit file
sudo rm /etc/systemd/system/tax-healthcare-tool-backup.service /etc/systemd/system/tax-healthcare-tool-backup.timer   # the old backup units
sudo rm /usr/local/sbin/tax-healthcare-tool-manage                    # the old management wrapper
sudo systemctl daemon-reload                                          # tells systemd about the removals
sudo podman rmi localhost/tax-healthcare-tool:current localhost/tax-healthcare-tool:previous   # the old rootful images (list others with: sudo podman images)
sudo rm -r /var/lib/tax-healthcare-tool                               # the old data, uploads and backups: PERMANENT
sudo rm -r /etc/tax-healthcare-tool                                   # the old secret file
```

## 9. Glossary

| Term | Meaning |
|---|---|
| Ansible | the tool that runs the playbooks (step lists) on the server from your Mac |
| Playbook | one Ansible step list, e.g. `infra/deploy.yaml` |
| Container / image | a running / packaged copy of the app |
| Health check | the container's self-test every 30 seconds |
| keep-id | the user-namespace setting that shows the service user as the app user inside the container |
| Linger | lets a user's services run without a login session and at boot |
| Podman | the program that runs containers |
| Podman network | a private virtual switch between containers; the `gateway` network lets the proxy reach this app by container name |
| Quadlet | a text file describing a container for systemd |
| Rootful / rootless | Podman run by root / by an ordinary user |
| Service user | the ordinary Linux user `homeapps` that runs the containers |
| Subordinate ids | the private block of user numbers lent to a user for containers (`/etc/subuid`, `/etc/subgid`) |
| systemd, `systemctl --user` | the service manager, and the way to talk to a user's own one |

## 10. Troubleshooting

| What you see | Likely cause and what to do |
|---|---|
| `Permission denied (publickey)` when logging in as `homeapps` | the key your SSH really uses was not authorised: run `make bootstrap-rootless KEY=~/.ssh/<that key>.pub` (safe to repeat; `ssh -G <server> \| grep identityfile` shows which key is used) |
| `make deploy` says it cannot connect or the user does not exist | the bootstrap has not been run: `make bootstrap-rootless` |
| `Linger must be on` | the bootstrap did not finish; run it again (it is safe to repeat) |
| `The user's own systemd must be running` | log in once with `ssh homeapps@<server>` and run `loginctl show-user homeapps`; if linger is on and it still fails, run the bootstrap again and reboot the server |
| `Failed to connect to bus` or `XDG_RUNTIME_DIR` errors | the package `dbus-user-session` is missing or the user has no session yet; the bootstrap installs it, then log out and in again |
| Build fails while pulling the base image | the server has no internet access to the image registry or PyPI; check with `curl -I https://pypi.org` on the server |
| `newuidmap` / `cannot set up namespace` / `no subuid ranges found` | the service user has no subordinate id range; run the bootstrap again (it adds one) and check `/etc/subuid` |
| Container starts but the health check never says `healthy` | `ssh homeapps@<server> journalctl --user -u tax-healthcare-tool -n 80` (the app's own log), then `curl http://127.0.0.1:8889/health/` on the server; the second tells whether the app or only the check is failing |
| `permission denied` writing the database | the data folder is not owned by the service user (`ls -ln ~/tax-healthcare-tool/data`) or the `keep-id` mapping was changed; compare with `make status` |
| `address already in use` on 8889 | the old rootful container still holds the port: use `make deploy PORT=8890` for the trial, or stop the old one (section 7, part B) |
| Cannot use port 80 or 443 | non-root users may not use ports below 1024 until the server setting `net.ipv4.ip_unprivileged_port_start` is lowered; the app does not need it (8889), the future gateway will; it is a decision for the gateway work, not part of this phase |
| 403 when submitting a form | the page's address is not in the allowed origins; the trial port needs `make deploy PORT=8890` so the origin matches |
| `make migrate-copy` fails to find the old wrapper | the old rootful setup is not installed (nothing to migrate), or is already removed |
| A memory or process limit "was not applied" | the user's systemd does not hand the `memory` or `pids` controller to the user; `make status` prints the delegated controllers, and the limits it applied |

## Finding stored files nobody refers to (Phase 28)
After deleting imports, or if a file removal ever failed, `stored_files_report` lists files in the uploads folder that no import refers to. It only counts and prints masked names unless you add `--apply`. Run it as any other one-off command through the `manage` wrapper (`bin/tax-healthcare-tool-manage stored_files_report`, then again with `--apply` once you have read the list). Backups are not changed by it.
