# Development and deployment shortcuts. Deployment commands ask for the sudo password on the server (-K).
PYTHON := .venv/bin/python
INFRA_PY := .venv-infra/bin
ANSIBLE := ANSIBLE_CONFIG=infra/ansible.cfg $(INFRA_PY)/ansible-playbook -i infra/inventory.ini
HOST := $(shell awk 'NR==2 {print $$1}' infra/inventory.ini 2>/dev/null)
USER_AT := $(shell awk 'NR==2 {for (i=2;i<=NF;i++) if ($$i ~ /^ansible_user=/) {sub("ansible_user=","",$$i); print $$i "@"}}' infra/inventory.ini 2>/dev/null)
BACKUP_ARG := $(if $(BACKUP),-e backup_file=$(BACKUP),)

.PHONY: setup test check ansible-setup syntax deploy caddy caddy-remove caddy-root-cert status backup-now \
        fetch-backup restore-drill restore rollback createsuperuser changepassword

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
	@for p in deploy caddy caddy-remove caddy-root-cert rollback restore restore-drill fetch-backup status; do \
	  ANSIBLE_CONFIG=infra/ansible.cfg $(INFRA_PY)/ansible-playbook -i infra/inventory.ini --syntax-check infra/$$p.yaml >/dev/null && echo "ok  $$p" || exit 1; done

deploy:                ## build and deploy the committed revision
	$(ANSIBLE) infra/deploy.yaml -K

caddy:                 ## add the site (own port) to Caddy via an import snippet
	$(ANSIBLE) infra/caddy.yaml -K

caddy-remove:          ## remove the snippet and the import line again
	$(ANSIBLE) infra/caddy-remove.yaml -K

caddy-root-cert:       ## copy Caddy's local root certificate to local/ so you can trust it
	$(ANSIBLE) infra/caddy-root-cert.yaml -K

status:                ## read-only overview
	$(ANSIBLE) infra/status.yaml -K

backup-now:            ## backup on the server right now
	ssh -t $(USER_AT)$(HOST) sudo /usr/local/sbin/tax-healthcare-tool-manage backup_db --label manual

fetch-backup:          ## copy the newest (or BACKUP=name) backup to local/backups and verify it
	$(ANSIBLE) infra/fetch-backup.yaml -K $(BACKUP_ARG)

restore-drill:         ## prove a backup restores, without touching live data
	$(ANSIBLE) infra/restore-drill.yaml -K $(BACKUP_ARG)

restore:               ## restore live data from BACKUP=backup-....tar.gz (asks for confirmation)
	@test -n "$(BACKUP)" || { echo "usage: make restore BACKUP=backup-YYYYMMDD-HHMMSS.tar.gz"; exit 2; }
	$(ANSIBLE) infra/restore.yaml -K $(BACKUP_ARG)

rollback:              ## previous image (add BACKUP=pre-deploy backup to restore the data too)
	$(ANSIBLE) infra/rollback.yaml -K $(BACKUP_ARG)

createsuperuser:       ## create your login on the server
	ssh -t $(USER_AT)$(HOST) sudo /usr/local/sbin/tax-healthcare-tool-manage createsuperuser

changepassword:        ## USERNAME=... set a new password
	@test -n "$(USERNAME)" || { echo "usage: make changepassword USERNAME=name"; exit 2; }
	ssh -t $(USER_AT)$(HOST) sudo /usr/local/sbin/tax-healthcare-tool-manage changepassword $(USERNAME)
