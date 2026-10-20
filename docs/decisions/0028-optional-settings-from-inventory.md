# ADR 0028: Optional app settings from the inventory into the env file

Status: accepted (2026-10-20, owner request: manage the joint-account settings with Ansible, as automatically as possible; this supersedes rule 13 of PHASES_5.md for this one change).

## Decision
`infra/deploy.yaml` ensures lines in the service user's 0600 env file from `app_env_extra` (group_vars), whose values come from variables in the git-ignored `infra/inventory.ini`: `joint_rental_account`, `joint_rental_category`, `rental_organisation`, `enable_admin`. Empty means the line is removed. The env file is used by the Quadlet unit and by every one-off `podman run`, so one place configures all of them.

## Why
The account number is personal and must not be in tracked files, so it cannot live in group_vars; the unit file is world-readable and the account number must not be shown, so it cannot be an `Environment=` line either. The env file is already the place for secrets (SECRET_KEY, 0600, created only if missing, never overwritten). The inventory is already git-ignored and already holds the server name.

## Consequences
A deploy needs the variables in the owner's local inventory, nothing on the server by hand. Verified locally with Ansible against a temporary env file (written once, idempotent, mode 0600, removed when unset, no values in the output); not yet run against the real server. A guard test keeps the account out of group_vars and the unit file.
