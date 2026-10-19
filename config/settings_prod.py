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

# Whether the site is served over HTTPS. Default on (safe). The home-server deployment sets DJANGO_HTTPS=0 because
# it is served as plain HTTP on the LAN, like the other app on that host. Plain HTTP means passwords and financial
# data cross the network unencrypted; see docs/deployment.md.
USE_HTTPS = os.environ.get('DJANGO_HTTPS', '1') == '1'

CSRF_TRUSTED_ORIGINS = _required_list('DJANGO_CSRF_TRUSTED_ORIGINS')
_schemes = ('https://',) if USE_HTTPS else ('https://', 'http://')
if not all(o.startswith(_schemes) for o in CSRF_TRUSTED_ORIGINS):
    raise ImproperlyConfigured(
        'DJANGO_CSRF_TRUSTED_ORIGINS entries must start with ' + ' or '.join(_schemes) + '.')

# Data lives outside the code tree, on dedicated paths (never repo-relative).
DATABASES['default']['NAME'] = _absolute_path('DJANGO_DB_PATH')  # noqa: F405
UPLOAD_DIR = _absolute_path('DJANGO_UPLOAD_DIR')
BACKUP_DIR = _absolute_path('DJANGO_BACKUP_DIR')

ENABLE_ADMIN = os.environ.get('DJANGO_ENABLE_ADMIN', '0') == '1'

if USE_HTTPS:
    # TLS ends at a reverse proxy that forwards X-Forwarded-Proto (it must be the only way to reach the container).
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
else:
    # Secure cookies would never be sent back over plain HTTP, which would make login impossible. During the move
    # behind a proxy the app is also reached directly over plain HTTP: DJANGO_BEHIND_TLS_PROXY=1 (read in
    # config.settings) then still makes proxied HTTPS requests count as secure, without Secure cookies.
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False        # the health check talks plain HTTP on the loopback interface
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'
# HSTS is off unless explicitly enabled (only meaningful when served over HTTPS). Keep it 0 until the local CA is
# installed on every device: a browser that has seen HSTS refuses the site outright if the certificate is not trusted.
SECURE_HSTS_SECONDS = int(os.environ.get('DJANGO_HSTS_SECONDS', '0'))

# Static files (the stylesheet) are served by WhiteNoise from STATIC_ROOT, which `collectstatic` fills when the image
# is built. WhiteNoise sits right after SecurityMiddleware. The admin stays off (ENABLE_ADMIN).
MIDDLEWARE.insert(MIDDLEWARE.index('django.middleware.security.SecurityMiddleware') + 1,  # noqa: F405
                  'whitenoise.middleware.WhiteNoiseMiddleware')
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage'},
}

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
