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
        self.assertEqual(names, {'asgiref', 'django', 'gunicorn', 'sqlparse', 'whitenoise'})      # nothing unneeded

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
        self.assertRegex(groups, r'(?m)^listen_address: 127\.0\.0\.1\b')      # G3: loopback only; the gateway uses the network
        self.assertNotRegex(ports[0], r'^(0\.0\.0\.0|:)')                      # never an empty or wildcard host part
        self.assertIn('use_https: false', groups)

    def test_unit_joins_the_gateway_network_and_keeps_its_name_and_port(self):
        self.assertEqual(re.findall(r'^Network=(.+)$', self.text, re.M), ['{{ gateway_network }}'])
        self.assertEqual(re.findall(r'^ContainerName=(.+)$', self.text, re.M), ['{{ container_name }}'])
        groups = read('infra/group_vars/all.yml')
        self.assertIn('gateway_network: gateway.network', groups)
        self.assertIn('container_name: tax-healthcare-tool-web', groups)
        self.assertIn('PublishPort=', self.text)                 # the plain-HTTP port stays open until the gateway track closes it

    def test_gateway_settings_are_on_while_hsts_and_secure_cookies_stay_off(self):
        groups = read('infra/group_vars/all.yml')
        self.assertIn('behind_tls_proxy: true', groups)
        self.assertIn('hsts_seconds: 0', groups)
        self.assertIn('use_https: false', groups)                # plain HTTP on the old port must keep working
        self.assertIn('extra_csrf_origins: ["https://{{ public_host }}"]', groups)
        self.assertIn('csrf_trusted_origins: "{{ extra_csrf_origins | join(\',\') }}"', groups)     # no plain-HTTP origin (G3)
        self.assertNotIn('http://', groups.split('csrf_trusted_origins:')[1].splitlines()[0])

    def test_deploy_checks_that_the_gateway_network_exists(self):
        text = read('infra/deploy.yaml')
        self.assertIn('{{ quadlet_dir }}/{{ gateway_network }}', text)
        self.assertIn('gateway_network_file.stat.exists', text)

    def test_substituted_unit_publishes_no_non_loopback_port(self):
        host = re.search(r'(?m)^listen_address:\s*(\S+)', read('infra/group_vars/all.yml')).group(1)
        rendered = self.text.replace('{{ listen_address }}', host).replace('{{ app_port }}', '8889')
        for spec in re.findall(r'^PublishPort=(.+)$', rendered, re.M):
            self.assertTrue(spec.startswith('127.0.0.1:'), spec)

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
        self.assertIn('DJANGO_CSRF_TRUSTED_ORIGINS={{ csrf_trusted_origins }}', self.text)
        for name in ('DJANGO_ALLOWED_HOSTS={{ allowed_hosts }}', 'DJANGO_URL_PREFIX={{ url_prefix }}',
                     'DJANGO_HSTS_SECONDS={{ hsts_seconds }}', "DJANGO_BEHIND_TLS_PROXY={{ '1' if behind_tls_proxy else '0' }}"):
            self.assertIn('Environment=' + name, self.text)
            self.assertIn('-e ' + name, read('infra/group_vars/all.yml'))     # one-off runs get the same environment

    def test_uses_the_current_tag_and_production_settings(self):
        self.assertIn('Image={{ image_repo }}:current', self.text)
        self.assertIn('Environment=DJANGO_SETTINGS_MODULE=config.settings_prod', self.text)
        self.assertIn('Environment=DJANGO_DB_PATH=/data/db.sqlite3', self.text)


class AnsibleFilesTests(SimpleTestCase):
    def test_group_vars_hold_no_secrets_or_personal_names(self):
        text = read('infra/group_vars/all.yml')
        self.assertNotRegex(text.lower(), r'secret_key\s*:|password|token')
        self.assertIn('public_host: "{{ ansible_host | default(inventory_hostname) }}"', text)

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
        block = text[text.index('Generate the Django SECRET_KEY'):text.index('Make sure the secret file can only be read by the service user')]
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


class RootlessTests(SimpleTestCase):
    """Phase 9A: routine deployment needs no root. Reads the real Makefile and playbooks."""
    SUDO_FILES = {'infra/bootstrap-rootless.yml', 'infra/migrate-from-rootful.yaml'}     # the documented exceptions
    SUDO_TARGETS = {'bootstrap-rootless', 'migrate-copy'}

    def playbooks(self):
        return sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / 'infra').rglob('*') if p.suffix in ('.yml', '.yaml'))

    def makefile_targets(self):
        return re.findall(r'^([a-z][a-z-]*):', read('Makefile'), re.M)

    def test_no_sudo_become_or_password_prompt_outside_the_documented_exceptions(self):
        for rel in self.playbooks() + [p.relative_to(ROOT).as_posix() for p in (ROOT / 'infra' / 'templates').iterdir()]:
            if rel in self.SUDO_FILES:
                continue
            text = '\n'.join(l for l in read(rel).splitlines() if not l.lstrip().startswith('#'))
            self.assertNotRegex(text, r'\bbecome\b|\bsudo\b|ask-become|--ask-become-pass', rel)
            self.assertNotRegex(text, r'(^|\s)-K\b', rel)

    def test_makefile_uses_sudo_only_for_the_two_documented_targets(self):
        current = None
        for line in read('Makefile').splitlines():
            m = re.match(r'^([a-z][a-z-]*):', line)
            if m:
                current = m.group(1)
            if line.startswith('\t') and re.search(r'(^|\s)-K\b|\bsudo\b|\bbecome\b', line):
                self.assertIn(current, self.SUDO_TARGETS, line)
        self.assertTrue(self.SUDO_TARGETS <= set(self.makefile_targets()))
        for name in self.SUDO_FILES:
            self.assertIn('become: true', read(name))

    def test_routine_playbooks_connect_as_the_service_user_and_check_the_session_first(self):
        for name in ('deploy', 'rollback', 'restore', 'restore-drill', 'fetch-backup', 'status', 'verify-migration'):
            text = read(f'infra/{name}.yaml')
            self.assertIn('hosts: taxtool\n', text, name)
            self.assertIn('tasks/service-session.yml', text, name)
            self.assertIn('XDG_RUNTIME_DIR', text, name)
        session = read('infra/tasks/service-session.yml')
        for needle in ('Linger', 'systemctl --user is-system-running', 'service_user'):
            self.assertIn(needle, session)

    def test_systemd_tasks_use_the_user_scope_and_the_user_unit_folders(self):
        for name in ('deploy', 'rollback', 'restore'):
            text = read(f'infra/{name}.yaml')
            self.assertEqual(text.count('ansible.builtin.systemd:'), text.count('scope: user'), name)
        deploy = read('infra/deploy.yaml')
        self.assertIn('quadlet_file: "{{ quadlet_dir }}/{{ app_name }}.container"', deploy)
        self.assertNotIn('/etc/', deploy.replace('/etc/os-release', ''))
        self.assertNotIn('/usr/local/sbin', deploy)
        groups = read('infra/group_vars/all.yml')
        self.assertIn('quadlet_dir: "{{ service_home }}/.config/containers/systemd"', groups)
        self.assertIn('unit_dir: "{{ service_home }}/.config/systemd/user"', groups)

    def test_quadlet_is_a_user_unit_with_the_user_namespace_mapping(self):
        text = read('infra/templates/tax-healthcare-tool.container.j2')
        self.assertIn('UserNS={{ container_userns }}', text)
        self.assertIn('User={{ app_uid }}', text)
        self.assertIn('WantedBy=default.target', text)
        self.assertNotIn('multi-user.target', text)
        self.assertNotIn('RequiresMountsFor', text)
        groups = read('infra/group_vars/all.yml')
        self.assertIn('container_userns: "keep-id:uid={{ app_uid }},gid={{ app_uid }}"', groups)
        self.assertIn('--userns={{ container_userns }} --user {{ app_uid }}:{{ app_uid }}', groups)
        self.assertIn('--userns={{ container_userns }}', read('infra/restore-drill.yaml').replace('"--userns', '--userns').replace('}}"', '}}'))

    def test_hardening_is_kept(self):
        text = read('infra/templates/tax-healthcare-tool.container.j2')
        for line in ('ReadOnly=true', 'NoNewPrivileges=true', 'DropCapability=ALL', 'HealthOnFailure=restart',
                     'Restart=always', '--memory={{ memory_limit }}', '--pids-limit=256'):
            self.assertIn(line, text)

    def test_backup_is_a_user_timer(self):
        deploy = read('infra/deploy.yaml')
        self.assertIn('dest: "{{ unit_dir }}/{{ item }}"', deploy)
        self.assertIn('{{ app_name }}-backup.timer', deploy)
        self.assertIn('Persistent=true', read('infra/templates/tax-healthcare-tool-backup.timer.j2'))

    def test_bootstrap_is_idempotent_commented_and_contains_no_app_secret_or_firewall_change(self):
        text = read('infra/bootstrap-rootless.yml')
        body = '\n'.join(l for l in text.splitlines() if not l.lstrip().startswith('#')).lower()
        for forbidden in ('ufw', 'firewall', 'iptables', 'nft', 'secret_key', 'podman build', 'podman run', 'git archive'):
            self.assertNotIn(forbidden, body)
        for needle in ('password_lock: true', 'enable-linger', 'creates: "/var/lib/systemd/linger', 'passt', 'uidmap',
                       '/etc/subuid', 'state: present'):
            self.assertIn(needle, text)
        tasks = re.findall(r'^    - name: ', text, re.M)
        self.assertGreaterEqual(len(tasks), 10)
        self.assertNotIn('shell: /usr/sbin/nologin', text)        # SSH needs a real shell
        self.assertIn('unprivileged_port_start: null', read('infra/group_vars/all.yml'))    # off unless the owner decides

    def test_every_make_target_is_explained_in_the_plain_language_guide(self):
        guide = read('docs/podman-explained.md')
        for target in self.makefile_targets():
            self.assertRegex(guide, rf'make {re.escape(target)}\b', f'make {target} is not documented in docs/podman-explained.md')

    def test_every_command_block_line_in_the_guide_has_an_explanation(self):
        guide = read('docs/podman-explained.md')
        blocks = re.findall(r'```\n(.*?)```', guide, re.S)
        commands = [l for b in blocks for l in b.splitlines() if re.match(r'(make|systemctl|podman|ssh|sudo|journalctl|loginctl|ls) ', l)]
        self.assertGreater(len(commands), 15)
        for line in commands:
            self.assertIn('#', line, f'command without a one-line explanation: {line}')


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
            if rel.endswith(('.png', '.ico', '.crt')) or rel.startswith('docs/prompts/'):    # owner's own prompt records
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
