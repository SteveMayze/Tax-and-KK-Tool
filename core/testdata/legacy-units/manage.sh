#!/bin/sh
# Managed by Ansible (infra/deploy.yaml). Runs one Django management command in a throw-away container
# with the production settings and the real data directories. Run as the service user (no sudo needed):
#   tax-healthcare-tool-manage createsuperuser
#   tax-healthcare-tool-manage changepassword <user>
#   tax-healthcare-tool-manage backup_db --label manual
set -eu
TTY=""
[ -t 0 ] && [ -t 1 ] && TTY="-it"
exec /usr/bin/podman run $TTY --rm --read-only --tmpfs /tmp --cap-drop=ALL --security-opt=no-new-privileges --userns=keep-id:uid=10001,gid=10001 --user 10001:10001 --env-file /home/homeapps/tax-healthcare-tool/config/env -e DJANGO_SETTINGS_MODULE=config.settings_prod -e DJANGO_DB_PATH=/data/db.sqlite3 -e DJANGO_UPLOAD_DIR=/uploads -e DJANGO_BACKUP_DIR=/backups -e DJANGO_ALLOWED_HOSTS=host.example.invalid,localhost,127.0.0.1 -e DJANGO_CSRF_TRUSTED_ORIGINS=https://host.example.invalid -e DJANGO_HTTPS=1 -e DJANGO_URL_PREFIX=/tax-healthcare -e DJANGO_BEHIND_TLS_PROXY=1 -e DJANGO_HSTS_SECONDS=0 -v /home/homeapps/tax-healthcare-tool/data:/data -v /home/homeapps/tax-healthcare-tool/uploads:/uploads -v /home/homeapps/tax-healthcare-tool/backups:/backups localhost/tax-healthcare-tool:current python manage.py "$@"
