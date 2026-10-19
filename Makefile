# Development and deployment shortcuts. Routine deployment commands connect as the rootless service user and need NO
# sudo password. Only two targets use sudo (-K): bootstrap-rootless (once) and migrate-copy (the move from the old
# rootful setup). Every target is explained in docs/podman-explained.md.
PYTHON := .venv/bin/python
INFRA_PY := .venv-infra/bin
ANSIBLE := ANSIBLE_CONFIG=infra/ansible.cfg $(INFRA_PY)/ansible-playbook -i infra/inventory.ini
HOST := $(shell awk 'NR==2 {h=$$1; for (i=2;i<=NF;i++) if ($$i ~ /^ansible_host=/) {h=$$i; sub("ansible_host=","",h)}; print h}' infra/inventory.ini 2>/dev/null)
USER_AT := $(shell awk 'NR==2 {for (i=2;i<=NF;i++) if ($$i ~ /^ansible_user=/) {sub("ansible_user=","",$$i); print $$i "@"}}' infra/inventory.ini 2>/dev/null)
BACKUP_ARG := $(if $(BACKUP),-e backup_file=$(BACKUP),)
PORT_ARG := $(if $(PORT),-e app_port=$(PORT),)
# The key to authorise for the service user: KEY=path if given, else the identity file your SSH config uses for this host.
SSH_KEY_GUESS := $(shell ssh -G $(HOST) 2>/dev/null | awk '/^identityfile /{print $$2; exit}' | sed "s|^~|$$HOME|").pub
KEY_ARG := $(if $(KEY),-e key=$(KEY),$(if $(wildcard $(SSH_KEY_GUESS)),-e key=$(SSH_KEY_GUESS),))
MANAGE := bin/tax-healthcare-tool-manage

.PHONY: setup test check ansible-setup syntax bootstrap-rootless deploy status backup-now \
        fetch-backup restore-drill restore rollback createsuperuser changepassword \
        migrate-copy verify-migration

setup:
	$(PYTHON) -m pip install -r requirements.txt

test:
	$(PYTHON) manage.py test

check:
	$(PYTHON) manage.py check

# --- Deployment -------------------------------------------------------------------------------------------
ansible-setup:
	python3 -m venv .venv-infra
	$(INFRA_PY)/pip install -r requirements-infra.txt

syntax:
	@for p in bootstrap-rootless.yml deploy.yaml rollback.yaml restore.yaml restore-drill.yaml fetch-backup.yaml status.yaml migrate-from-rootful.yaml verify-migration.yaml; do \
	  ANSIBLE_CONFIG=infra/ansible.cfg $(INFRA_PY)/ansible-playbook -i infra/inventory.ini --syntax-check infra/$$p >/dev/null && echo "ok  $$p" || exit 1; done

bootstrap-rootless:    ## ONCE: create the service user (asks for your sudo password); KEY=path to your public key
	$(ANSIBLE) infra/bootstrap-rootless.yml -K $(KEY_ARG)

deploy:                ## build and deploy the committed revision (trial: PORT=8890)
	$(ANSIBLE) infra/deploy.yaml $(PORT_ARG)

status:                ## read-only overview
	$(ANSIBLE) infra/status.yaml $(PORT_ARG)

backup-now:            ## backup on the server right now
	ssh $(USER_AT)$(HOST) $(MANAGE) backup_db --label manual

fetch-backup:          ## copy the newest (or BACKUP=name) backup to local/backups and verify it
	$(ANSIBLE) infra/fetch-backup.yaml $(BACKUP_ARG)

restore-drill:         ## prove a backup restores, without touching live data
	$(ANSIBLE) infra/restore-drill.yaml $(BACKUP_ARG) $(PORT_ARG)

restore:               ## restore live data from BACKUP=backup-....tar.gz (asks for confirmation)
	@test -n "$(BACKUP)" || { echo "usage: make restore BACKUP=backup-YYYYMMDD-HHMMSS.tar.gz"; exit 2; }
	$(ANSIBLE) infra/restore.yaml $(BACKUP_ARG) $(PORT_ARG)

rollback:              ## previous image (add BACKUP=pre-deploy backup to restore the data too)
	$(ANSIBLE) infra/rollback.yaml $(BACKUP_ARG) $(PORT_ARG)

createsuperuser:       ## create your login on the server
	ssh -t $(USER_AT)$(HOST) $(MANAGE) createsuperuser

changepassword:        ## USERNAME=... set a new password
	@test -n "$(USERNAME)" || { echo "usage: make changepassword USERNAME=name"; exit 2; }
	ssh -t $(USER_AT)$(HOST) $(MANAGE) changepassword $(USERNAME)

# --- Move from the old rootful setup (Phase 9A) ----------------------------------------------------------
migrate-copy:          ## sudo: take a fresh backup of the OLD rootful instance and copy it to the rootless one
	$(ANSIBLE) infra/migrate-from-rootful.yaml -K

verify-migration:      ## BACKUP=name: prove the rootless data equals that backup (row counts and content hash)
	@test -n "$(BACKUP)" || { echo "usage: make verify-migration BACKUP=backup-....tar.gz"; exit 2; }
	$(ANSIBLE) infra/verify-migration.yaml $(BACKUP_ARG) $(PORT_ARG)
