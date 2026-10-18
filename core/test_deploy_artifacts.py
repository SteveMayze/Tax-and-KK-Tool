"""Static guard rails for the deployment files: they must keep their safety properties."""
import re
import subprocess
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

ROOT = Path(settings.BASE_DIR)


def read(rel):
    return (ROOT / rel).read_text()


class ContainerfileTests(SimpleTestCase):
    def setUp(self):
        self.text = read('Containerfile')
        self.lines = [l.strip() for l in self.text.splitlines() if l.strip() and not l.strip().startswith('#')]

    def test_base_image_is_pinned_to_an_exact_python_release(self):
        base = [l for l in self.lines if l.startswith('FROM ')]
        self.assertEqual(len(base), 1)
        self.assertRegex(base[0], r'python:\d+\.\d+\.\d+-slim-[a-z]+$')
        self.assertNotIn('latest', base[0])

    def test_matches_development_python(self):
        self.assertEqual(read('.python-version').strip(), '3.14')
        self.assertIn('python:3.14.', self.text)

    def test_runs_as_unprivileged_user_with_matching_uid(self):
        users = [l for l in self.lines if l.startswith('USER ')]
        self.assertEqual(users, ['USER 10001:10001'])
        self.assertIn('--uid 10001', self.text)
        self.assertIn('app_uid: 10001', read('infra/group_vars/all.yml'))

    def test_only_application_code_is_copied(self):
        copies = [l for l in self.lines if l.startswith('COPY ')]
        sources = {c.split()[1] for c in copies}
        self.assertEqual(sources, {'requirements.txt', 'manage.py', 'config', 'core', 'templates'})
        self.assertFalse(any(re.search(r'COPY\s+(\.|local|docs|infra)\b', c) for c in copies))

    def test_uses_gunicorn_not_the_development_server(self):
        cmd = ' '.join(l for l in self.text.splitlines() if 'gunicorn' in l or 'runserver' in l)
        self.assertIn('gunicorn', cmd)
        self.assertNotIn('runserver', self.text)

    def test_production_settings_and_no_secrets_baked_in(self):
        self.assertIn('DJANGO_SETTINGS_MODULE=config.settings_prod', self.text)
        for forbidden in ('SECRET_KEY', 'PASSWORD', 'TOKEN'):
            self.assertNotIn(forbidden, self.text)

    def test_requirements_are_fully_pinned(self):
        lines = [l for l in read('requirements.txt').splitlines() if l.strip()]
        self.assertTrue(lines)
        self.assertTrue(all('==' in l for l in lines), lines)
        names = {l.split('==')[0].lower() for l in lines}
        self.assertEqual(names, {'asgiref', 'django', 'gunicorn', 'sqlparse'})      # nothing unneeded

    def test_ignore_files_keep_private_data_out_of_the_build_context(self):
        for name in ('.containerignore', '.dockerignore'):
            entries = set(read(name).split())
            for must in ('.git', '.venv', 'local', '*.sqlite3', '.env', 'infra', 'docs'):
                self.assertIn(must, entries, f'{name} lacks {must}')


class QuadletTests(SimpleTestCase):
    def setUp(self):
        self.text = read('infra/templates/tax-healthcare-tool.container.j2')

    def test_secret_is_never_in_the_unit_file(self):
        self.assertIn('EnvironmentFile={{ etc_dir }}/env', self.text)
        self.assertNotIn('DJANGO_SECRET_KEY', self.text)

    def test_port_is_loopback_only(self):
        ports = re.findall(r'^PublishPort=(.+)$', self.text, re.M)
        self.assertEqual(ports, ['127.0.0.1:{{ app_port }}:8000'])

    def test_hardening(self):
        for line in ('ReadOnly=true', 'NoNewPrivileges=true', 'DropCapability=ALL', 'Tmpfs=/tmp', 'Restart=always'):
            self.assertIn(line, self.text)
        self.assertIn('--memory=', self.text)

    def test_health_check_and_data_volumes(self):
        self.assertIn('HealthCmd=', self.text)
        self.assertIn('/health/', self.text)
        self.assertIn('HealthOnFailure=restart', self.text)
        mounts = re.findall(r'^Volume=(.+)$', self.text, re.M)
        self.assertEqual([m.split(':')[1] for m in mounts], ['/data', '/uploads', '/backups'])
        self.assertTrue(all('{{ data_root }}' in m for m in mounts))

    def test_uses_the_current_tag_and_production_settings(self):
        self.assertIn('Image={{ image_repo }}:current', self.text)
        self.assertIn('Environment=DJANGO_SETTINGS_MODULE=config.settings_prod', self.text)
        self.assertIn('Environment=DJANGO_DB_PATH=/data/db.sqlite3', self.text)


class AnsibleFilesTests(SimpleTestCase):
    def test_group_vars_hold_no_secrets_or_personal_names(self):
        text = read('infra/group_vars/all.yml')
        self.assertNotRegex(text.lower(), r'secret_key\s*:|password|token')
        self.assertIn('public_host: "{{ inventory_hostname }}"', text)

    def test_one_off_container_runs_share_the_service_hardening(self):
        flags = read('infra/group_vars/all.yml')
        for needle in ('--rm', '--read-only', '--cap-drop=ALL', 'no-new-privileges', '--env-file {{ etc_dir }}/env',
                       'DJANGO_SETTINGS_MODULE=config.settings_prod'):
            self.assertIn(needle, flags)

    def test_deploy_ships_only_the_committed_revision(self):
        text = read('infra/deploy.yaml')
        self.assertIn('git -C {{ playbook_dir }} archive', text)
        self.assertNotIn('synchronize', text)
        self.assertNotIn('rsync', text)
        self.assertIn('dirty_tree', text)

    def test_deploy_secret_handling(self):
        text = read('infra/deploy.yaml')
        block = text[text.index('Generate the Django SECRET_KEY'):text.index('Make sure the secret file is root-only')]
        self.assertIn('creates: "{{ etc_dir }}/env"', block)
        self.assertIn('no_log: true', block)
        self.assertIn('umask 077', block)
        self.assertIn('mode: "0600"', text)

    def test_deploy_backs_up_before_migrating_and_checks_health(self):
        text = read('infra/deploy.yaml')
        self.assertLess(text.index('--label pre-deploy'), text.index('migrate --noinput'))
        self.assertLess(text.index('migrate --noinput'), text.index('state: restarted'))
        self.assertIn('healthy', text)
        self.assertIn('/health/', text)

    def test_nothing_is_installed_or_upgraded_on_the_shared_host(self):
        for name in ('deploy', 'caddy', 'rollback', 'restore'):
            text = read(f'infra/{name}.yaml')
            self.assertNotIn('ansible.builtin.apt', text, name)
            self.assertNotIn('update_cache', text, name)

    def test_caddy_change_is_scoped_validated_and_reversible(self):
        text = read('infra/caddy.yaml')
        self.assertIn('backup: true', text)
        self.assertIn('caddy validate', text)
        self.assertIn('rescue:', text)
        self.assertIn('state: reloaded', text)
        self.assertNotIn('state: restarted', text)                       # never restart the shared Caddy
        self.assertNotIn('Caddyfile.parts', text)
        snippet = read('infra/templates/caddy-site.caddy.j2')
        self.assertIn('tls internal', snippet)
        self.assertIn('{{ public_host }}:{{ public_port }}', snippet)
        self.assertIn('reverse_proxy 127.0.0.1:{{ app_port }}', snippet)
        self.assertTrue((ROOT / 'infra/caddy-remove.yaml').exists())

    def test_restore_is_confirmed_and_never_deletes(self):
        text = read('infra/restore.yaml')
        self.assertIn("confirm == 'RESTORE'", text)
        self.assertIn('--force', text)
        self.assertIn('pre-restore', text)
        self.assertNotIn('state: absent', text)

    def test_restore_drill_is_non_destructive(self):
        text = read('infra/restore-drill.yaml')
        self.assertIn('/backups:ro', text)
        self.assertIn('/tmp/drill', text)
        self.assertIn('migrate', text)
        self.assertIn('DRILL_OK', text)
        self.assertNotIn('/data/db.sqlite3 ', text.replace('DJANGO_DB_PATH=/data/db.sqlite3', ''))

    def test_backup_timer_runs_daily_and_prunes(self):
        self.assertIn('backup_db --prune', read('infra/templates/tax-healthcare-tool-backup.service.j2'))
        timer = read('infra/templates/tax-healthcare-tool-backup.timer.j2')
        self.assertIn('Persistent=true', timer)
        self.assertIn('OnCalendar=*-*-* {{ backup_time }}', timer)


class RepositoryHygieneTests(SimpleTestCase):
    def tracked_and_new(self):
        try:
            files = subprocess.run(['git', 'ls-files', '--cached', '--others', '--exclude-standard'], cwd=ROOT,
                                   capture_output=True, text=True, check=True).stdout.split('\n')
        except (OSError, subprocess.CalledProcessError):
            self.skipTest('git not available')
        return [f for f in files if f and (ROOT / f).is_file()]

    def test_no_host_or_user_names_in_files_that_would_be_committed(self):
        offenders = []
        for rel in self.tracked_and_new():
            if rel.endswith(('.png', '.ico', '.crt')):
                continue
            text = (ROOT / rel).read_text(errors='ignore')
            if re.search(r'fritz\.box|\bcornil\b|\bsteve\b', text, re.I):
                offenders.append(rel)
        self.assertEqual(offenders, [])

    def test_private_paths_are_ignored(self):
        for path in ('infra/inventory.ini', 'local/backups/backup-20260101-000000.tar.gz', 'local/caddy-local-root.crt',
                     '.venv-infra/bin/ansible', 'local/db.sqlite3'):
            r = subprocess.run(['git', 'check-ignore', '-q', path], cwd=ROOT)
            self.assertEqual(r.returncode, 0, f'{path} is not git-ignored')

    def test_no_database_backup_or_secret_file_would_be_committed(self):
        bad = [f for f in self.tracked_and_new() if re.search(r'\.sqlite3|\.tar\.gz$|\.env$|inventory\.ini$|\.pem$|\.key$', f)]
        self.assertEqual(bad, [])
