import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class SetupTests(TestCase):
    def test_app_installed(self):
        self.assertIn('core', settings.INSTALLED_APPS)

    def _db_name(self, **env):
        # Settings are evaluated in a fresh interpreter (the test runner swaps in an in-memory DB).
        clean = {k: v for k, v in os.environ.items() if k != 'DJANGO_DB_PATH'}
        clean.update(env)
        code = "from config import settings; print(settings.DATABASES['default']['NAME'])"
        out = subprocess.run(
            [sys.executable, '-c', code], cwd=settings.BASE_DIR, env=clean,
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()

    def test_db_path_defaults_to_local(self):
        self.assertEqual(self._db_name(), str(Path(settings.BASE_DIR) / 'local' / 'db.sqlite3'))

    def test_db_path_from_environment(self):
        self.assertEqual(self._db_name(DJANGO_DB_PATH='/tmp/x/db.sqlite3'), '/tmp/x/db.sqlite3')


class LoginTests(TestCase):
    def test_home_redirects_anonymous_to_login(self):
        response = self.client.get(reverse('home'))
        self.assertRedirects(response, f"{reverse('login')}?next=/")

    def test_login_page_renders(self):
        self.assertEqual(self.client.get(reverse('login')).status_code, 200)

    def test_home_after_login(self):
        user = get_user_model().objects.create_user('tester', password='pw-for-tests-123')
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('home')).status_code, 200)

    def test_login_flow(self):
        get_user_model().objects.create_user('tester', password='pw-for-tests-123')
        response = self.client.post(
            reverse('login'), {'username': 'tester', 'password': 'pw-for-tests-123'}
        )
        self.assertRedirects(response, reverse('home'))


class HealthTests(TestCase):
    def test_health_is_unauthenticated(self):
        response = self.client.get(reverse('health'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok'})

    def test_health_rejects_post(self):
        self.assertEqual(self.client.post(reverse('health')).status_code, 405)
