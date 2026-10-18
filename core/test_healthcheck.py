"""The container health check script (healthcheck.py), against a throw-away local HTTP server."""
import http.server
import importlib.util
import subprocess
import sys
import threading
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

ROOT = Path(settings.BASE_DIR)
spec = importlib.util.spec_from_file_location('healthcheck', ROOT / 'healthcheck.py')
healthcheck = importlib.util.module_from_spec(spec)
spec.loader.exec_module(healthcheck)


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        status = {'/health/': 200, '/broken/': 500, '/missing/': 404}.get(self.path, 404)
        if self.path == '/slow/':
            import time
            time.sleep(2)
            status = 200
        self.send_response(status)
        self.end_headers()
        self.wfile.write(b'{}')

    def log_message(self, *args):
        pass


class HealthcheckTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        super().tearDownClass()

    def url(self, path):
        return f'http://127.0.0.1:{self.port}{path}'

    def test_healthy_only_on_http_200(self):
        self.assertTrue(healthcheck.check(self.url('/health/')))
        self.assertFalse(healthcheck.check(self.url('/broken/')))
        self.assertFalse(healthcheck.check(self.url('/missing/')))

    def test_connection_refused_and_timeout_are_unhealthy(self):
        self.assertFalse(healthcheck.check('http://127.0.0.1:1/health/'))
        self.assertFalse(healthcheck.check(self.url('/slow/'), timeout=0.5))

    def test_garbage_url_is_unhealthy_not_a_crash(self):
        self.assertFalse(healthcheck.check('not a url'))

    def test_proxy_environment_is_ignored(self):
        import os
        old = os.environ.get('http_proxy')
        os.environ['http_proxy'] = 'http://127.0.0.1:9'          # would fail if it were used
        try:
            self.assertTrue(healthcheck.check(self.url('/health/')))
        finally:
            if old is None:
                os.environ.pop('http_proxy')
            else:
                os.environ['http_proxy'] = old

    def test_exit_status_as_run_by_podman(self):
        def run(path):
            return subprocess.run([sys.executable, str(ROOT / 'healthcheck.py'), self.url(path)], capture_output=True).returncode
        self.assertEqual(run('/health/'), 0)
        self.assertEqual(run('/broken/'), 1)

    def test_default_url_is_the_in_container_port(self):
        self.assertEqual(healthcheck.DEFAULT_URL, 'http://127.0.0.1:8000/health/')
