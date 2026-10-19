"""URL prefix support (Phase 9): generated URLs, cookies and static files under /tax-healthcare. Synthetic data only."""
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.handlers.wsgi import get_script_name
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.test.client import ClientHandler
from django.urls import reverse, set_script_prefix

from core.services.reports import REPORTS
from core.test_helpers import make_payment

PREFIX = '/tax-healthcare'
PREFIXED = dict(FORCE_SCRIPT_NAME=PREFIX, SESSION_COOKIE_PATH=PREFIX, CSRF_COOKIE_PATH=PREFIX,
                STATIC_URL=PREFIX + '/static/')


class PrefixHandler(ClientHandler):
    """Django's test client skips the one step a real WSGI server does first: setting the script prefix for the request
    (django.core.handlers.wsgi.WSGIHandler.__call__). Without it reverse() ignores FORCE_SCRIPT_NAME. The real handler is
    also used directly in RealWsgiHandlerTests."""

    def __call__(self, environ):
        set_script_prefix(get_script_name(environ))
        return super().__call__(environ)


class PrefixClient(Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.handler = PrefixHandler(kwargs.get('enforce_csrf_checks', False))


class Targets(HTMLParser):
    """Collects every link and form action of a page."""

    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ('a', 'link') and a.get('href') is not None:
            self.urls.append(a['href'])
        elif tag == 'form':
            self.urls.append(a.get('action', ''))
        elif tag in ('script', 'img') and a.get('src'):
            self.urls.append(a['src'])


def targets(response):
    t = Targets()
    t.feed(response.content.decode())
    # An empty action posts to the page's own (already prefixed) URL; anchors and external links are not ours.
    return [u for u in t.urls if u and not u.startswith(('#', 'mailto:', 'http://', 'https://'))]


@override_settings(**PREFIXED)
class UnderPrefixTests(TestCase):
    """The proxy strips the prefix (the test client sends /reports/), the app generates /tax-healthcare/... URLs."""
    client_class = PrefixClient

    def tearDown(self):
        set_script_prefix('/')

    def setUp(self):
        get_user_model().objects.create_user('tester', password='pw-for-tests-123')
        p = make_payment(gross='100'); p.save()
        make_payment(gross='50', date=datetime.date(2026, 3, 15)).save()    # SBK parameters exist for 2026 only

    def login(self):
        r = self.client.post('/accounts/login/', {'username': 'tester', 'password': 'pw-for-tests-123'}, follow=True)
        self.assertEqual(r.status_code, 200)
        return r

    def test_login_redirects_and_every_link_and_form_action_carries_the_prefix(self):
        r = self.client.get('/years/2024/')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], f'{PREFIX}/accounts/login/?next={PREFIX}/years/2024/')
        login_page = self.client.get('/accounts/login/')
        self.assertTrue(targets(login_page))

        r = self.client.post(r['Location'].removeprefix(PREFIX), {'username': 'tester', 'password': 'pw-for-tests-123'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], f'{PREFIX}/years/2024/')    # follows ?next=, prefix kept

        pages = ['/', '/years/2024/', '/years/2024/months/3/', '/reports/', '/imports/', '/organisations/',
                 '/categories/', '/assessment/settings/', '/reconciliation/', '/payments/1/', '/payments/1/edit/',
                 f'/reports/{next(iter(REPORTS))}/']
        for path in pages:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            urls = targets(response)
            self.assertTrue(urls, path)
            for url in urls:
                self.assertTrue(url.startswith(PREFIX + '/'), f'{path}: {url!r} lacks the prefix')

    def test_every_report_page_and_csv_link_is_prefixed(self):
        self.login()
        for key in REPORTS:
            response = self.client.get(f'/reports/{key}/?year=2026')    # the SBK parameters exist for 2026 only
            self.assertEqual(response.status_code, 200, key)
            urls = targets(response)
            self.assertTrue(all(u.startswith(PREFIX + '/') for u in urls), (key, urls))
            self.assertTrue(any('.csv' in u for u in urls), key)

    def test_redirect_built_inside_a_view_carries_the_prefix(self):
        self.login()
        r = self.client.post('/reconciliation/convert-pending/', {'year': '2024'})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r['Location'].startswith(PREFIX + '/reconciliation/'), r['Location'])

    def test_the_app_also_answers_when_the_prefix_is_not_stripped(self):
        self.login()
        for path in (PREFIX + '/', PREFIX + '/years/2024/', PREFIX + '/health/'):
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.assertEqual(self.client.get('/health/').status_code, 200)
        r = self.client.get(PREFIX + '/years/2024')            # APPEND_SLASH must not double the prefix
        self.assertEqual(r.status_code, 301)
        self.assertEqual(r['Location'], PREFIX + '/years/2024/')

    def test_logout_returns_to_the_prefixed_login_page(self):
        self.login()
        r = self.client.post('/accounts/logout/')
        self.assertEqual(r['Location'], f'{PREFIX}/accounts/login/')

    def test_session_and_csrf_cookies_use_own_names_and_the_prefix_path(self):
        self.client.get('/accounts/login/')
        csrf = self.client.cookies[settings.CSRF_COOKIE_NAME]
        self.assertEqual((csrf['path'], settings.CSRF_COOKIE_NAME), (PREFIX, 'taxhc_csrftoken'))
        self.login()
        session = self.client.cookies[settings.SESSION_COOKIE_NAME]
        self.assertEqual((session['path'], settings.SESSION_COOKIE_NAME), (PREFIX, 'taxhc_sessionid'))


@override_settings(**PREFIXED)
class RealWsgiHandlerTests(TestCase):
    """The real WSGI handler (what gunicorn calls), with the prefix stripped by the proxy and with SCRIPT_NAME unset."""

    def call(self, path, query=''):
        from django.core.handlers.wsgi import WSGIHandler
        from io import BytesIO
        out = {}
        environ = {'REQUEST_METHOD': 'GET', 'PATH_INFO': path, 'QUERY_STRING': query, 'SERVER_NAME': 'testserver',
                  'SERVER_PORT': '80', 'wsgi.url_scheme': 'http', 'wsgi.input': BytesIO(), 'HTTP_HOST': 'testserver'}
        body = b''.join(WSGIHandler()(environ, lambda status, headers: out.update(status=status, headers=dict(headers))))
        self.addCleanup(set_script_prefix, '/')
        return out['status'], out['headers'], body

    def test_login_redirect_and_login_page_links(self):
        status, headers, _ = self.call('/years/2024/')
        self.assertTrue(status.startswith('302'))
        self.assertEqual(headers['Location'], f'{PREFIX}/accounts/login/?next={PREFIX}/years/2024/')
        status, _, body = self.call('/accounts/login/')
        self.assertTrue(status.startswith('200'))
        t = Targets(); t.feed(body.decode())
        links = [u for u in t.urls if u and not u.startswith('#')]
        self.assertTrue(links and all(u.startswith(PREFIX + '/') for u in links), links)


class WithoutPrefixTests(TestCase):
    def test_default_settings_are_unchanged_for_development(self):
        self.assertEqual(reverse('home'), '/')
        self.assertEqual((settings.URL_PREFIX, settings.FORCE_SCRIPT_NAME), ('', None))
        self.assertEqual((settings.SESSION_COOKIE_PATH, settings.CSRF_COOKIE_PATH), ('/', '/'))
        self.assertEqual(settings.STATIC_URL, '/static/')

    def test_cookie_names_differ_from_the_django_defaults(self):
        self.assertNotEqual(settings.SESSION_COOKIE_NAME, 'sessionid')
        self.assertNotEqual(settings.CSRF_COOKIE_NAME, 'csrftoken')
        get_user_model().objects.create_user('tester', password='pw-for-tests-123')
        self.client.post('/accounts/login/', {'username': 'tester', 'password': 'pw-for-tests-123'})
        self.assertIn('taxhc_sessionid', self.client.cookies)
        self.assertNotIn('sessionid', self.client.cookies)
        self.assertEqual(self.client.cookies['taxhc_sessionid']['path'], '/')

    def test_no_currency_dropdown_on_any_page(self):
        user = get_user_model().objects.create_user('tester2', password='pw-for-tests-123')
        self.client.force_login(user)
        for path in ('/', '/organisations/', '/reports/'):
            html = self.client.get(path).content.decode().lower()
            self.assertNotIn('name="display_currency"', html, path)
            self.assertNotIn('currency', html.split('<main>')[0], path)    # header and navigation


def probe(code, **env_overrides):
    env = {k: v for k, v in os.environ.items() if not k.startswith('DJANGO_')}
    env.update(env_overrides)
    return subprocess.run([sys.executable, '-c', code], cwd=settings.BASE_DIR, env=env, capture_output=True, text=True)


class PrefixFromEnvironmentTests(SimpleTestCase):
    """The real settings module, loaded in a subprocess with the environment variable."""
    CODE = ("import json; from django.conf import settings as s; print(json.dumps({k: getattr(s, k) for k in "
            "['URL_PREFIX','FORCE_SCRIPT_NAME','SESSION_COOKIE_PATH','CSRF_COOKIE_PATH','STATIC_URL',"
            "'SESSION_COOKIE_NAME','CSRF_COOKIE_NAME','SECURE_PROXY_SSL_HEADER','LOGIN_URL']}, default=list))")

    def test_prefix_is_normalised_and_applied_to_settings_and_cookie_paths(self):
        for raw in ('/tax-healthcare', 'tax-healthcare/', '/tax-healthcare/'):
            r = probe(self.CODE, DJANGO_SETTINGS_MODULE='config.settings', DJANGO_URL_PREFIX=raw)
            self.assertEqual(r.returncode, 0, r.stderr[-400:])
            v = json.loads(r.stdout)
            self.assertEqual((v['URL_PREFIX'], v['FORCE_SCRIPT_NAME']), (PREFIX, PREFIX), raw)
            self.assertEqual((v['SESSION_COOKIE_PATH'], v['CSRF_COOKIE_PATH']), (PREFIX, PREFIX))
            self.assertEqual(v['STATIC_URL'], PREFIX + '/static/')
            self.assertEqual((v['SESSION_COOKIE_NAME'], v['CSRF_COOKIE_NAME']), ('taxhc_sessionid', 'taxhc_csrftoken'))

    def test_proxy_ssl_header_is_only_trusted_when_the_switch_is_on(self):
        env = dict(DJANGO_SETTINGS_MODULE='config.settings')
        off = json.loads(probe(self.CODE, **env).stdout)
        on = json.loads(probe(self.CODE, DJANGO_BEHIND_TLS_PROXY='1', **env).stdout)
        self.assertIsNone(off['SECURE_PROXY_SSL_HEADER'])
        self.assertEqual(on['SECURE_PROXY_SSL_HEADER'], ['HTTP_X_FORWARDED_PROTO', 'https'])

    def test_a_bad_prefix_stops_the_process(self):
        r = probe('import django; django.setup()', DJANGO_SETTINGS_MODULE='config.settings', DJANGO_URL_PREFIX='/a b/../x')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('DJANGO_URL_PREFIX', r.stderr)


class StaticFilesInProductionTests(SimpleTestCase):
    """collectstatic and the production settings (WhiteNoise), run as the container does, under the prefix."""

    PROD = {
        'DJANGO_SETTINGS_MODULE': 'config.settings_prod',
        'DJANGO_SECRET_KEY': 'Zq3x9LmT7vB2nR8wYc5Hd1KfPaJe6GsUo4NiXtV0bMyQ-AlEzWrCgDhSjFkO_9p',
        'DJANGO_ALLOWED_HOSTS': 'app.example.test,localhost,127.0.0.1,testserver',
        'DJANGO_CSRF_TRUSTED_ORIGINS': 'https://app.example.test',
        'DJANGO_DB_PATH': '/data/db.sqlite3', 'DJANGO_UPLOAD_DIR': '/uploads', 'DJANGO_BACKUP_DIR': '/backups',
        'DJANGO_URL_PREFIX': PREFIX,
    }

    def test_stylesheet_is_collected_and_served_under_the_prefix(self):
        with tempfile.TemporaryDirectory() as static_root:
            env = dict(self.PROD, DJANGO_STATIC_ROOT=static_root)
            collect = probe('import django; django.setup(); from django.core.management import call_command; '
                            'call_command("collectstatic", interactive=False, verbosity=0)', **env)
            self.assertEqual(collect.returncode, 0, collect.stderr[-500:])
            self.assertTrue((Path(static_root) / 'core' / 'base.css').is_file())

            code = ("import django; django.setup(); from django.test import Client; c = Client(); "
                    f"a = c.get('{PREFIX}/static/core/base.css'); b = c.get('/static/core/base.css'); "
                    "page = c.get('/accounts/login/'); "
                    "print(a.status_code, a['Content-Type'].split(';')[0], b.status_code, "
                    "'" + PREFIX + "/static/core/base.css' in page.content.decode(), b'<style' in page.content)")
            r = probe(code, **env)
            self.assertEqual(r.returncode, 0, r.stderr[-500:])
            self.assertEqual(r.stdout.split(), ['200', 'text/css', '200', 'True', 'False'], r.stdout)

    def test_the_stylesheet_content_is_the_real_one(self):
        self.assertIn('font-family', (Path(settings.BASE_DIR) / 'core' / 'static' / 'core' / 'base.css').read_text())


class HousekeepingTests(SimpleTestCase):
    def read(self, rel):
        return (Path(settings.BASE_DIR) / rel).read_text()

    def test_nothing_in_code_or_templates_refers_to_a_display_currency_setting(self):
        for folder in ('core', 'config', 'templates'):
            for path in (Path(settings.BASE_DIR) / folder).rglob('*'):
                if path.suffix in ('.py', '.html', '.css') and path.name != 'test_prefix.py':
                    text = path.read_text().lower()
                    self.assertNotIn('display_currency', text, path)
                    self.assertNotIn('display currency', text, path)

    def test_claude_md_has_none_of_the_known_inconsistencies(self):
        text = self.read('CLAUDE.md')
        self.assertNotIn('doc/prompts', text.replace('docs/prompts', ''))
        self.assertNotIn('configurable per-institution profiles', text)
        self.assertNotIn('Display-currency dropdown', text)
        self.assertIn('docs/prompts/PHASES_2.md', text)
        self.assertTrue((Path(settings.BASE_DIR) / 'docs/prompts/PHASES_2.md').is_file())
