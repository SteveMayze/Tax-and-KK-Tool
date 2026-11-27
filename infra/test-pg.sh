#!/bin/sh
# make test-pg: the whole test suite against a THROW-AWAY PostgreSQL 17 on this Mac (ADR 0035).
# It uses the PostgreSQL 17 programs of Postgres.app (or PG_BIN=<folder with initdb, pg_ctl, pg_dump, pg_restore>):
# a new cluster in a temporary folder, listening on 127.0.0.1 only on a free port, with scram-sha-256 and a random
# password that exists only for this run. The cluster and its folder are removed when the run ends (also on Ctrl-C or
# failure). Postgres.app itself does not need to be running and none of its own databases is touched. Nothing else is
# installed or kept, and nothing reaches the server.
set -eu
PG_BIN="${PG_BIN:-/Applications/Postgres.app/Contents/Versions/17/bin}"
PYTHON="${PYTHON:-.venv/bin/python}"
for tool in initdb pg_ctl pg_dump pg_restore; do
  [ -x "$PG_BIN/$tool" ] || { echo "PostgreSQL 17 not found in $PG_BIN (install Postgres.app, or set PG_BIN)." >&2; exit 2; }
done
MAJOR="$("$PG_BIN/pg_dump" --version | sed -E 's/[^0-9]*([0-9]+).*/\1/')"
[ "$MAJOR" -ge 17 ] || { echo "pg_dump in $PG_BIN is version $MAJOR; 17 or newer is needed." >&2; exit 2; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/taxtool-test-pg.XXXXXX")"
PASSWORD="$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')"
PORT="$("$PYTHON" -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')"
cleanup() {
  "$PG_BIN/pg_ctl" -D "$WORK/data" -m immediate stop >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT INT TERM

printf '%s\n' "$PASSWORD" > "$WORK/pw"
# The same locale as the platform's cluster (en_US.utf8), so text comparison behaves as on the server.
"$PG_BIN/initdb" -D "$WORK/data" -U taxtool --pwfile="$WORK/pw" --auth=scram-sha-256 -E UTF8 --locale=en_US.UTF-8 >/dev/null
rm -f "$WORK/pw"
"$PG_BIN/pg_ctl" -D "$WORK/data" -l "$WORK/server.log" -w \
  -o "-c listen_addresses=127.0.0.1 -p $PORT -k $WORK -c fsync=off" start >/dev/null
echo "Throw-away PostgreSQL $MAJOR on 127.0.0.1:$PORT (removed after the run)."

# The role is the cluster's owner here (it may create the test database); on the server it is NOT (no CREATEDB).
PGPASSWORD="$PASSWORD" "$PG_BIN/psql" -h 127.0.0.1 -p "$PORT" -U taxtool -d postgres -qc 'CREATE DATABASE taxtool' >/dev/null

DJANGO_DB_HOST=127.0.0.1 DJANGO_DB_PORT="$PORT" DJANGO_DB_NAME=taxtool DJANGO_DB_USER=taxtool DJANGO_DB_PASSWORD="$PASSWORD" \
DJANGO_PG_BIN_DIR="$PG_BIN" "$PYTHON" manage.py test "$@"
