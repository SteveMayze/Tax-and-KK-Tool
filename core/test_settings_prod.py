"""Production settings are loaded in a subprocess, exactly as the container loads them."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

GOOD = {
    'DJANGO_SETTINGS_MODULE': 'config.settings_prod',
    'DJANGO_SECRET_KEY': 'Zq3x9LmT7vB2nR8wYc5Hd1KfPaJe6GsUo4NiXtV0bMyQ-AlEzWrCgDhSjFkO_9p',
    'DJANGO_ALLOWED_HOSTS': 'app.example.test,localhost,127.0.0.1',
    'DJANGO_CSRF_TRUSTED_ORIGINS': 'https://app.example.test:8443',
    'DJANGO_DB_PATH': '/data/db.sqlite3',
    'DJANGO_UPLOAD_DIR': '/uploads',
    'DJANGO_BACKUP_DIR': '/backups',
}
PROBE = ("import json; from django.conf import settings as s; print(json.dumps({k: getattr(s, k) for k in "
         "['DEBUG','ALLOWED_HOSTS','CSRF_TRUSTED_ORIGINS','SECURE_PROXY_SSL_HEADER','SESSION_COOKIE_SECURE','CSRF_COOKIE_SECURE',"
         "'SECURE_SSL_REDIRECT','SECURE_HSTS_SECONDS','UPLOAD_DIR','BACKUP_DIR','ENABLE_ADMIN','X_FRAME_OPTIONS',"
         "'SECURE_CONTENT_TYPE_NOSNIFF','SECURE_REFERRER_POLICY']} | {'DB': s.DATABASES['default']['NAME']}, default=list))")


def run(code, env_overrides=None, drop=(), extra_args=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith('DJANGO_')}
    env.update(GOOD)
    env.update(env_overrides or {})
    for k in drop:
        env.pop(k, None)
    args = [sys.executable, '-c', code] if code else [sys.executable, 'manage.py'] + list(extra_args)
    return subprocess.run(args, cwd=settings.BASE_DIR, env=env, capture_output=True, text=True)


class ProductionSettingsTests(SimpleTestCase):
    def values(self, **kw):
        r = run('import django; django.setup(); ' + PROBE, **kw)
        self.assertEqual(r.returncode, 0, r.stderr[-600:])
        return json.loads(r.stdout)

    def test_good_environment_yields_hardened_settings(self):
        v = self.values()
        self.assertEqual((v['DEBUG'], v['ENABLE_ADMIN']), (False, False))
        self.assertEqual(v['ALLOWED_HOSTS'], ['app.example.test', 'localhost', '127.0.0.1'])
        self.assertEqual(v['CSRF_TRUSTED_ORIGINS'], ['https://app.example.test:8443'])
        self.assertEqual(v['SECURE_PROXY_SSL_HEADER'], ['HTTP_X_FORWARDED_PROTO', 'https'])
        self.assertTrue(v['SESSION_COOKIE_SECURE'] and v['CSRF_COOKIE_SECURE'])
        self.assertFalse(v['SECURE_SSL_REDIRECT'])
        self.assertEqual(v['SECURE_HSTS_SECONDS'], 0)
        self.assertEqual((v['DB'], v['UPLOAD_DIR'], v['BACKUP_DIR']), ('/data/db.sqlite3', '/uploads', '/backups'))
        self.assertEqual((v['X_FRAME_OPTIONS'], v['SECURE_CONTENT_TYPE_NOSNIFF'], v['SECURE_REFERRER_POLICY']), ('DENY', True, 'same-origin'))

    def test_each_required_variable_is_enforced(self):
        for name in ('DJANGO_SECRET_KEY', 'DJANGO_ALLOWED_HOSTS', 'DJANGO_CSRF_TRUSTED_ORIGINS', 'DJANGO_DB_PATH',
                     'DJANGO_UPLOAD_DIR', 'DJANGO_BACKUP_DIR'):
            r = run('import django; django.setup()', drop=[name])
            self.assertNotEqual(r.returncode, 0, name)
            self.assertIn(f'{name} must be set in production', r.stderr, name)

    def test_weak_or_unsafe_values_are_rejected(self):
        cases = [
            ({'DJANGO_SECRET_KEY': 'short'}, 'too short'),
            ({'DJANGO_SECRET_KEY': 'insecure-dev-key-do-not-use-in-production' + 'x' * 20}, 'too short or is the development placeholder'),
            ({'DJANGO_ALLOWED_HOSTS': '*'}, 'not "*"'),
            ({'DJANGO_ALLOWED_HOSTS': 'a.test,*'}, 'not "*"'),
            ({'DJANGO_CSRF_TRUSTED_ORIGINS': 'http://app.example.test'}, 'https://'),
            ({'DJANGO_DB_PATH': 'db.sqlite3'}, 'absolute path'),
            ({'DJANGO_UPLOAD_DIR': 'uploads'}, 'absolute path'),
            ({'DJANGO_BACKUP_DIR': 'local/backups'}, 'absolute path'),
        ]
        for env, text in cases:
            r = run('import django; django.setup()', env_overrides=env)
            self.assertNotEqual(r.returncode, 0, env)
            self.assertIn(text, r.stderr, env)

    def test_debug_cannot_be_switched_on_by_environment(self):
        self.assertFalse(self.values(env_overrides={'DJANGO_DEBUG': '1'})['DEBUG'])

    def test_admin_only_when_explicitly_enabled(self):
        self.assertFalse(self.values()['ENABLE_ADMIN'])
        self.assertTrue(self.values(env_overrides={'DJANGO_ENABLE_ADMIN': '1'})['ENABLE_ADMIN'])

    def test_plain_http_mode_for_the_lan_deployment(self):
        env = {'DJANGO_HTTPS': '0', 'DJANGO_CSRF_TRUSTED_ORIGINS': 'http://app.example.test:8889'}
        v = self.values(env_overrides=env)
        self.assertEqual(v['CSRF_TRUSTED_ORIGINS'], ['http://app.example.test:8889'])
        self.assertFalse(v['SESSION_COOKIE_SECURE'] or v['CSRF_COOKIE_SECURE'])       # secure cookies would break login over http
        self.assertIsNone(v['SECURE_PROXY_SSL_HEADER'])

    def test_https_is_the_default_and_rejects_http_origins(self):
        r = run('import django; django.setup()', env_overrides={'DJANGO_CSRF_TRUSTED_ORIGINS': 'http://app.example.test:8889'})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('must start with https://', r.stderr)

    def test_http_mode_still_rejects_other_schemes(self):
        r = run('import django; django.setup()', env_overrides={'DJANGO_HTTPS': '0', 'DJANGO_CSRF_TRUSTED_ORIGINS': 'ftp://x.test'})
        self.assertNotEqual(r.returncode, 0)

    def test_hsts_is_opt_in(self):
        self.assertEqual(self.values(env_overrides={'DJANGO_HSTS_SECONDS': '3600'})['SECURE_HSTS_SECONDS'], 3600)

    def test_development_settings_still_work_without_any_of_this(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith('DJANGO_')}
        r = subprocess.run([sys.executable, 'manage.py', 'check'], cwd=settings.BASE_DIR, env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


class DeploymentCheckTests(SimpleTestCase):
    def test_check_deploy_has_no_errors_or_unexpected_warnings(self):
        r = run(None, extra_args=['check', '--deploy', '--fail-level', 'WARNING'])
        # Two warnings are accepted on purpose (see settings_prod): W004 (HSTS is opt-in because the site uses a
        # locally issued certificate) and W008 (TLS ends at Caddy; the container only speaks plain HTTP on 127.0.0.1).
        self.assertIn('security.W004', r.stderr)
        self.assertIn('security.W008', r.stderr)
        for other in ('W012', 'W016', 'W018', 'W009', 'W007', 'W006', 'W021'):
            self.assertNotIn(f'security.{other}', r.stderr, r.stderr)
        errors = [line for line in r.stderr.splitlines() if 'ERRORS:' in line or '(security.E' in line]
        self.assertEqual(errors, [])

    def test_fresh_database_migrates_and_serves_the_health_endpoint_under_production_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {'DJANGO_DB_PATH': f'{tmp}/db.sqlite3', 'DJANGO_UPLOAD_DIR': f'{tmp}/up', 'DJANGO_BACKUP_DIR': f'{tmp}/bk'}
            r = run(None, env_overrides=env, extra_args=['migrate', '--noinput'])
            self.assertEqual(r.returncode, 0, r.stderr[-500:])
            self.assertTrue(Path(f'{tmp}/db.sqlite3').is_file())
            code = (
                "import django; django.setup(); from django.test import Client; "
                "c = Client(HTTP_HOST='localhost'); "
                "h = c.get('/health/'); "
                "a = c.get('/'); "
                "adm = c.get('/admin/'); "
                "print(h.status_code, h.json()['status'], a.status_code, a['Location'], adm.status_code)")
            r = run(code, env_overrides=env)
            self.assertEqual(r.returncode, 0, r.stderr[-500:])
            self.assertEqual(r.stdout.strip(), '200 ok 302 /accounts/login/?next=/ 404')   # admin is off in production

    def test_login_works_over_plain_http(self):
        # The deployed configuration: HTTP, no TLS. A user can log in and reach the app (cookies must not be 'secure').
        with tempfile.TemporaryDirectory() as tmp:
            env = {'DJANGO_DB_PATH': f'{tmp}/db.sqlite3', 'DJANGO_UPLOAD_DIR': f'{tmp}/up', 'DJANGO_BACKUP_DIR': f'{tmp}/bk',
                   'DJANGO_HTTPS': '0', 'DJANGO_CSRF_TRUSTED_ORIGINS': 'http://app.example.test:8889'}
            self.assertEqual(run(None, env_overrides=env, extra_args=['migrate', '--noinput']).returncode, 0)
            code = (
                "import django; django.setup(); "
                "from django.contrib.auth import get_user_model; "
                "get_user_model().objects.create_user('tester', password='pw-for-tests-123'); "
                "from django.test import Client; "
                "c = Client(HTTP_HOST='app.example.test:8889', enforce_csrf_checks=True); "
                "page = c.get('/accounts/login/'); token = c.cookies['taxhc_csrftoken'].value; "
                "secure = bool(c.cookies['taxhc_csrftoken']['secure']); "
                "r = c.post('/accounts/login/', {'username': 'tester', 'password': 'pw-for-tests-123', 'csrfmiddlewaretoken': token}, "
                "HTTP_ORIGIN='http://app.example.test:8889'); "
                "home = c.get('/'); "
                "print(page.status_code, secure, r.status_code, home.status_code)")
            r = run(code, env_overrides=env)
            self.assertEqual(r.returncode, 0, r.stderr[-600:])
            self.assertEqual(r.stdout.strip(), '200 False 302 200')

    def test_check_deploy_in_http_mode_has_only_the_expected_warnings(self):
        env = {'DJANGO_HTTPS': '0', 'DJANGO_CSRF_TRUSTED_ORIGINS': 'http://app.example.test:8889'}
        r = run(None, env_overrides=env, extra_args=['check', '--deploy', '--fail-level', 'WARNING'])
        errors = [line for line in r.stderr.splitlines() if 'ERRORS:' in line or '(security.E' in line]
        self.assertEqual(errors, [])
        for expected in ('W004', 'W008', 'W012', 'W016'):               # HSTS, ssl redirect, secure cookies: all off by design in http mode
            self.assertIn(f'security.{expected}', r.stderr)
        for unexpected in ('W009', 'W018', 'W007', 'W006'):             # secret key strength, DEBUG, content-type, XSS filter
            self.assertNotIn(f'security.{unexpected}', r.stderr)

    def test_secure_cookies_and_host_checking_behind_the_proxy(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {'DJANGO_DB_PATH': f'{tmp}/db.sqlite3', 'DJANGO_UPLOAD_DIR': f'{tmp}/up', 'DJANGO_BACKUP_DIR': f'{tmp}/bk'}
            self.assertEqual(run(None, env_overrides=env, extra_args=['migrate', '--noinput']).returncode, 0)
            code = (
                "import django; django.setup(); from django.test import Client; "
                "bad = Client(HTTP_HOST='evil.example').get('/health/'); "
                "ok = Client(HTTP_HOST='app.example.test', HTTP_X_FORWARDED_PROTO='https').get('/accounts/login/'); "
                "print(bad.status_code, ok.status_code, ok.cookies['taxhc_csrftoken']['secure'], ok.cookies['taxhc_csrftoken']['samesite'])")
            r = run(code, env_overrides=env)
            self.assertEqual(r.returncode, 0, r.stderr[-500:])
            self.assertEqual(r.stdout.strip(), '400 200 True Lax')

    def test_gateway_scenario_login_and_csrf_over_https_proxy_and_plain_http(self):
        """The deployed shape: prefix, proxy header trusted, plain HTTP still allowed (cookies not Secure)."""
        with tempfile.TemporaryDirectory() as tmp:
            env = {'DJANGO_DB_PATH': f'{tmp}/db.sqlite3', 'DJANGO_UPLOAD_DIR': f'{tmp}/up', 'DJANGO_BACKUP_DIR': f'{tmp}/bk',
                   'DJANGO_HTTPS': '0', 'DJANGO_BEHIND_TLS_PROXY': '1', 'DJANGO_URL_PREFIX': '/tax-healthcare',
                   'DJANGO_ALLOWED_HOSTS': 'gw.example.test,localhost',
                   'DJANGO_CSRF_TRUSTED_ORIGINS': 'http://gw.example.test:8890,https://gw.example.test'}
            self.assertEqual(run(None, env_overrides=env, extra_args=['migrate', '--noinput']).returncode, 0)
            code = '''
import re, django
django.setup()
from django.contrib.auth import get_user_model
from django.core.handlers.wsgi import get_script_name
from django.test import Client
from django.test.client import ClientHandler
from django.urls import set_script_prefix
get_user_model().objects.create_user('u', password='pw-for-test-only-1')

class H(ClientHandler):
    def __call__(self, environ):
        set_script_prefix(get_script_name(environ))
        return super().__call__(environ)

def client(**extra):
    c = Client(enforce_csrf_checks=True, HTTP_HOST='gw.example.test', **extra)
    c.handler = H(True)
    return c

def login(c, origin):
    page = c.get('/accounts/login/')
    token = c.cookies['taxhc_csrftoken'].value
    m = re.search(r'<form[^>]*action="([^"]*)"', page.content.decode())
    action = m.group(1) if m else ''   # no action attribute: the browser posts to the page's own (prefixed) URL
    r = c.post('/accounts/login/', {'username': 'u', 'password': 'pw-for-test-only-1', 'csrfmiddlewaretoken': token},
               HTTP_ORIGIN=origin)
    return (bool(page.cookies['taxhc_csrftoken']['secure']), action, r.status_code, r['Location'],
            c.cookies['taxhc_sessionid']['path'])

https = login(client(HTTP_X_FORWARDED_PROTO='https'), 'https://gw.example.test')
plain = login(client(), 'http://gw.example.test:8890')
bad = client(HTTP_X_FORWARDED_PROTO='https')
bad.get('/accounts/login/')
foreign = bad.post('/accounts/login/', {'username': 'u', 'password': 'x',
                   'csrfmiddlewaretoken': bad.cookies['taxhc_csrftoken'].value}, HTTP_ORIGIN='https://evil.example').status_code
print(https, plain, foreign)
'''
            r = run(code, env_overrides=env)
            self.assertEqual(r.returncode, 0, r.stderr[-800:])
            same = "(False, '', 302, '/tax-healthcare/', '/tax-healthcare')"
            self.assertEqual(r.stdout.strip(), f'{same} {same} 403')
