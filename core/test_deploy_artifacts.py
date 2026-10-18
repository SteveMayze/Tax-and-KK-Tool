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
        sources = {src for c in copies for src in c.split()[1:-1]}          # every source between COPY and the destination
        self.assertEqual(sources, {'requirements.txt', 'manage.py', 'healthcheck.py', 'config', 'core', 'templates'})
        self.assertFalse(any(re.search(r'COPY\s+(\.|local|docs|infra)\b', c) for c in copies))

    def test_uses_gunicorn_not_the_development_server(self):
        cmd = ' '.join(l for l in self.text.splitlines() if 'gunicorn' in l or 'runserver' in l)
        self.assertIn('gunicorn', cmd)
        self.assertNotIn('runserver', self.text)

    def test_gunicorn_control_socket_is_disabled(self):
        # gunicorn 26 otherwise tries to create a socket under $HOME, which is read-only in this container
        self.assertIn('--no-control-socket', self.text)

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

    def test_port_is_published_on_the_configured_address(self):
        ports = re.findall(r'^PublishPort=(.+)$', self.text, re.M)
        self.assertEqual(ports, ['{{ listen_address }}:{{ app_port }}:8000'])
        groups = read('infra/group_vars/all.yml')
        self.assertRegex(groups, r'listen_address: 0\.0\.0\.0')            # owner decision: reachable on the LAN, like the other app
        self.assertIn('use_https: false', groups)

    def test_hardening(self):
        for line in ('ReadOnly=true', 'NoNewPrivileges=true', 'DropCapability=ALL', 'Tmpfs=/tmp', 'Restart=always'):
            self.assertIn(line, self.text)
        self.assertIn('--memory=', self.text)

    def test_health_check_is_a_quote_free_script(self):
        # Regression: an inline `python -c "..."` was re-quoted by Quadlet (closing quote lost), so the check always failed.
        cmds = re.findall(r'^HealthCmd=(.+)$', self.text, re.M)
        self.assertEqual(cmds, ['python /app/healthcheck.py'])
        for ch in ('"', "'", ';', '`', '$'):
            self.assertNotIn(ch, cmds[0])
        self.assertIn('HealthOnFailure=restart', self.text)
        self.assertIn('COPY manage.py healthcheck.py', read('Containerfile'))

    def test_data_volumes(self):
        mounts = re.findall(r'^Volume=(.+)$', self.text, re.M)
        self.assertEqual([m.split(':')[1] for m in mounts], ['/data', '/uploads', '/backups'])
        self.assertTrue(all('{{ data_root }}' in m for m in mounts))

    def test_http_mode_is_passed_to_the_app(self):
        self.assertIn("Environment=DJANGO_HTTPS={{ '1' if use_https else '0' }}", self.text)
        self.assertIn('DJANGO_CSRF_TRUSTED_ORIGINS={{ public_scheme }}://{{ public_host }}:{{ app_port }}', self.text)

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
        self.assertIn('git -C {{ repo_root }} archive', text)
        self.assertIn('repo_root: "{{ playbook_dir }}/.."', text)            # playbook_dir is infra/: archiving there ships only infra/
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

    def test_pre_deploy_backup_uses_the_new_image_after_the_build(self):
        # Regression: it used the OLD image with the NEW environment; the old settings rejected the new values and the
        # backup (and so the whole deploy) failed.
        text = read('infra/deploy.yaml')
        task = text[text.index('- name: Back up before changing anything'):text.index("- name: Keep the live image as 'previous'")]
        self.assertIn('{{ image_new }}', task)
        self.assertNotIn(':current', task)
        self.assertIn('--label pre-deploy', task)
        self.assertLess(text.index('- name: Build the image'), text.index('- name: Back up before changing anything'))
        self.assertLess(text.index('- name: Back up before changing anything'), text.index("- name: Point 'current' at the new image"))
        self.assertLess(text.index('- name: Back up before changing anything'), text.index('migrate --noinput'))

    def test_deploy_backs_up_before_migrating_and_checks_health(self):
        text = read('infra/deploy.yaml')
        self.assertLess(text.index('--label pre-deploy'), text.index('migrate --noinput'))
        self.assertLess(text.index('migrate --noinput'), text.index('state: restarted'))
        self.assertIn('healthy', text)
        self.assertIn('/health/', text)

    def test_nothing_is_installed_or_upgraded_on_the_shared_host(self):
        for name in ('deploy', 'rollback', 'restore'):
            text = read(f'infra/{name}.yaml')
            self.assertNotIn('ansible.builtin.apt', text, name)
            self.assertNotIn('update_cache', text, name)

    def test_no_reverse_proxy_configuration_is_managed(self):
        # Owner decision 2026-10-18: Caddy is legacy and not used; the app is served directly over plain HTTP.
        names = {p.name for p in (ROOT / 'infra').rglob('*') if p.is_file()}
        self.assertFalse([n for n in names if 'caddy' in n.lower()])
        for name in ('deploy', 'rollback', 'restore', 'status'):
            self.assertNotIn('/etc/caddy', read(f'infra/{name}.yaml'))
        self.assertNotIn('caddy', read('Makefile').lower())

    def test_rollback_proves_the_previous_image_accepts_the_current_configuration_first(self):
        text = read('infra/rollback.yaml')
        check = text.index('The previous image must start with the current configuration')
        self.assertIn(':previous', text[check:check + 400])
        self.assertIn('manage.py check', text[check:check + 400])
        self.assertLess(check, text.index('--label pre-rollback'))
        self.assertLess(check, text.index("podman tag {{ image_repo }}:previous {{ image_repo }}:current"))

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


class DeployArchiveTests(SimpleTestCase):
    """Runs the exact git archive command the playbook uses and inspects what would be shipped."""

    def archive_names(self):
        import io
        import tarfile
        try:
            data = subprocess.run(['git', '-C', str(ROOT / 'infra' / '..'), 'archive', '--format=tar.gz', '--prefix=src/', 'HEAD'],
                                  capture_output=True, check=True).stdout
        except (OSError, subprocess.CalledProcessError):
            self.skipTest('git repository not available')
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            self.dirs = {m.name for m in tar.getmembers() if m.isdir()}
            return {m.name for m in tar.getmembers() if m.isfile()}

    def test_archive_contains_everything_the_image_build_needs(self):
        names = self.archive_names()
        for needed in ('Containerfile', 'manage.py', 'healthcheck.py', 'requirements.txt', 'config/settings_prod.py', 'config/wsgi.py',
                       'core/models.py', 'templates/base.html'):
            self.assertIn(f'src/{needed}', names, f'{needed} missing from the deployment archive')

    def test_archive_is_the_whole_repository_not_a_subdirectory(self):
        names = self.archive_names()
        top = {n.split('/')[1] for n in names}
        self.assertTrue({'config', 'core', 'infra', 'Containerfile'} <= top, top)

    def test_archive_never_contains_private_data(self):
        bad = [n for n in self.archive_names()
               if re.search(r'\.sqlite3|\.tar\.gz$|\.env$|inventory\.ini$|\.pem$|\.key$|\.crt$', n)
               or (n.startswith('src/local/') and not n.endswith('README.md'))]
        self.assertEqual(bad, [])

    def test_playbook_checks_the_unpacked_files_before_building(self):
        text = read('infra/deploy.yaml')
        self.assertLess(text.index('must contain what the build needs'), text.index('Build the image'))
        self.assertIn('Containerfile', text[text.index('must contain what the build needs'):text.index('Build the image')])


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
        for path in ('infra/inventory.ini', 'local/backups/backup-20260101-000000.tar.gz',
                     '.venv-infra/bin/ansible', 'local/db.sqlite3'):
            r = subprocess.run(['git', 'check-ignore', '-q', path], cwd=ROOT)
            self.assertEqual(r.returncode, 0, f'{path} is not git-ignored')

    def test_no_database_backup_or_secret_file_would_be_committed(self):
        bad = [f for f in self.tracked_and_new() if re.search(r'\.sqlite3|\.tar\.gz$|\.env$|inventory\.ini$|\.pem$|\.key$', f)]
        self.assertEqual(bad, [])
