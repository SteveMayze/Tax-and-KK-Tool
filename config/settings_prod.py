"""Production settings (container). Everything comes from the environment and nothing falls back to an
insecure default: a missing or weak value stops the process at start-up. Development uses config.settings."""
import os

from django.core.exceptions import ImproperlyConfigured

from .settings import *  # noqa: F401,F403
from .settings import BASE_DIR  # noqa: F401


def _required(name):
    value = os.environ.get(name, '').strip()
    if not value:
        raise ImproperlyConfigured(f'{name} must be set in production.')
    return value


def _required_list(name):
    return [item.strip() for item in _required(name).split(',') if item.strip()]


def _absolute_path(name):
    value = _required(name)
    if not os.path.isabs(value):
        raise ImproperlyConfigured(f'{name} must be an absolute path in production (got a relative path).')
    return value


DEBUG = False

SECRET_KEY = _required('DJANGO_SECRET_KEY')
if len(SECRET_KEY) < 50 or SECRET_KEY.startswith('insecure'):
    raise ImproperlyConfigured('DJANGO_SECRET_KEY is too short or is the development placeholder.')

ALLOWED_HOSTS = _required_list('DJANGO_ALLOWED_HOSTS')
if '*' in ALLOWED_HOSTS:
    raise ImproperlyConfigured('DJANGO_ALLOWED_HOSTS must list explicit hosts, not "*".')

CSRF_TRUSTED_ORIGINS = _required_list('DJANGO_CSRF_TRUSTED_ORIGINS')
if not all(o.startswith('https://') for o in CSRF_TRUSTED_ORIGINS):
    raise ImproperlyConfigured('DJANGO_CSRF_TRUSTED_ORIGINS entries must start with https://.')

# Data lives outside the code tree, on dedicated paths (never repo-relative).
DATABASES['default']['NAME'] = _absolute_path('DJANGO_DB_PATH')  # noqa: F405
UPLOAD_DIR = _absolute_path('DJANGO_UPLOAD_DIR')
BACKUP_DIR = _absolute_path('DJANGO_BACKUP_DIR')

ENABLE_ADMIN = os.environ.get('DJANGO_ENABLE_ADMIN', '0') == '1'

# TLS ends at Caddy, which forwards X-Forwarded-Proto. The container port is published on 127.0.0.1 only,
# so only the local reverse proxy can set that header.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = False        # the health check and Caddy talk plain HTTP on the loopback interface
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'
# HSTS is off unless explicitly enabled: the site uses a locally issued certificate, and HSTS would lock a
# browser out if that certificate stops being trusted.
SECURE_HSTS_SECONDS = int(os.environ.get('DJANGO_HSTS_SECONDS', '0'))

# Console logging only, warnings and above. Request paths are logged by gunicorn; payment details, form
# contents and SQL are never logged.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {'plain': {'format': '%(asctime)s %(levelname)s %(name)s: %(message)s'}},
    'handlers': {'console': {'class': 'logging.StreamHandler', 'formatter': 'plain'}},
    'root': {'handlers': ['console'], 'level': 'WARNING'},
    'loggers': {'django.db.backends': {'level': 'WARNING', 'propagate': True}},
}
