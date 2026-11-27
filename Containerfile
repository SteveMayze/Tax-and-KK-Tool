# Production image. Built on the server from the committed revision (git archive), see docs/deployment.md.
# Base image pinned to an exact Python patch release (matches development: Python 3.14, Django 5.2 LTS).
FROM docker.io/library/python:3.14.5-slim-trixie

ARG GIT_COMMIT=unknown
LABEL org.opencontainers.image.title="tax-healthcare-tool" \
      org.opencontainers.image.revision="${GIT_COMMIT}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings_prod \
    DJANGO_STATIC_ROOT=/app/staticfiles \
    APP_VERSION=${GIT_COMMIT}

# Unprivileged user. Data directories on the host are owned by this numeric uid.
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin app

# PostgreSQL client tools for the backups (ADR 0035): pg_dump/pg_restore 17 from Debian 13's own repository. They must
# not be older than the server (PostgreSQL 17), because pg_dump refuses a newer server; the build fails otherwise.
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-17 \
    && rm -rf /var/lib/apt/lists/* \
    && for tool in pg_dump pg_restore; do \
         v="$($tool --version | sed -E 's/[^0-9]*([0-9]+).*/\1/')"; \
         [ -n "$v" ] && [ "$v" -ge 17 ] || { echo "$tool missing or older than 17 (got: $v)" >&2; exit 1; }; \
       done

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --no-compile -r requirements.txt

# Application code only: no docs, infra, tests data, local/ or databases. Files stay root-owned and read-only to the app.
COPY manage.py healthcheck.py ./
COPY config ./config
COPY core ./core
COPY templates ./templates
RUN echo "${GIT_COMMIT}" > /app/VERSION
# Collect the stylesheet for WhiteNoise at build time (the development settings are enough here: nothing secret is read).
RUN DJANGO_SETTINGS_MODULE=config.settings python manage.py collectstatic --noinput

USER 10001:10001
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", \
     "--worker-tmp-dir", "/dev/shm", "--timeout", "180", "--no-control-socket", \
     "--access-logfile", "-", "--error-logfile", "-"]
