# Production image. Built on the server from the committed revision (git archive), see docs/deployment.md.
# Base image pinned to an exact Python patch release (matches development: Python 3.14, Django 5.2 LTS).
FROM docker.io/library/python:3.14.5-slim-trixie

ARG GIT_COMMIT=unknown
LABEL org.opencontainers.image.title="tax-healthcare-tool" \
      org.opencontainers.image.revision="${GIT_COMMIT}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings_prod \
    APP_VERSION=${GIT_COMMIT}

# Unprivileged user. Data directories on the host are owned by this numeric uid.
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin app

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --no-compile -r requirements.txt

# Application code only: no docs, infra, tests data, local/ or databases. Files stay root-owned and read-only to the app.
COPY manage.py ./
COPY config ./config
COPY core ./core
COPY templates ./templates
RUN echo "${GIT_COMMIT}" > /app/VERSION

USER 10001:10001
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", \
     "--worker-tmp-dir", "/dev/shm", "--timeout", "60", "--access-logfile", "-", "--error-logfile", "-"]
