"""Backup and restore of the database (SQLite or PostgreSQL) and the uploaded files (docs/deployment.md).

A backup is one tar.gz: db.sqlite3 (a consistent copy made with SQLite's online backup API, so it is safe
while the app is running), uploads/..., and MANIFEST.json (SHA-256 of every file, integrity-check result,
row counts per table, app version). Restores verify everything first and never overwrite silently.
Row counts and file names are the only data reported; no payment contents are printed or logged.

On PostgreSQL (ADR 0035) the database file is db.dump, a `pg_dump -Fc` taken from one exported snapshot inside a
REPEATABLE READ transaction, and the row counts in the manifest are counted through the ORM in that same transaction,
so both describe one moment while the app keeps running. The manifest also records `engine`. Restores go into a NEW,
EMPTY database that the platform created (this app's role cannot create or drop databases); swapping it in renames
the live database aside and never drops it. Archives written before PostgreSQL (no `engine`) are SQLite archives and
stay readable.
"""
import datetime
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
from pathlib import Path

MANIFEST = 'MANIFEST.json'
DB_NAME = 'db.sqlite3'
PG_DUMP = 'db.dump'
SQLITE, POSTGRESQL = 'sqlite', 'postgresql'
DB_FILES = {SQLITE: DB_NAME, POSTGRESQL: PG_DUMP}
DB_NAME_RE = re.compile(r'^[a-z][a-z0-9_]{0,62}$')
PG_MIN_MAJOR = 17
UPLOADS = 'uploads'
NAME_RE = re.compile(r'^backup-(\d{8})-(\d{6})(?:-([a-z0-9-]+))?\.tar\.gz$')
LABEL_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,30}$')


class BackupError(Exception):
    pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _tables(conn):
    return [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def inspect_db(path: Path) -> dict:
    """Integrity check result and row counts per table (opened read-only)."""
    try:
        conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
        try:
            check = conn.execute('PRAGMA integrity_check').fetchall()
            result = 'ok' if check == [('ok',)] else '; '.join(r[0] for r in check)[:300]
            counts = {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in _tables(conn)}
        finally:
            conn.close()
    except sqlite3.Error as e:
        raise BackupError(f'Database cannot be read: {e}') from e
    return {'integrity_check': result, 'row_counts': counts}


def fingerprint(db_path, uploads_dir=None) -> dict:
    """Content fingerprint used to prove that two instances hold the same data (Phase 9A migration).

    Row counts per table, one SHA-256 over every row of every table (ordered by rowid; the session table is left out
    because every login changes it) and one over the uploaded files (relative path + content hash). Only counts and
    hashes are returned, never row contents.
    """
    try:
        conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
        try:
            digest, counts = hashlib.sha256(), {}
            for table in _tables(conn):
                counts[table] = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                if table == 'django_session':
                    continue
                digest.update(f'table {table}\n'.encode())
                for row in conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid'):
                    digest.update(repr(row).encode() + b'\n')
        finally:
            conn.close()
    except sqlite3.Error as e:
        raise BackupError(f'Database cannot be read: {e}') from e
    uploads = hashlib.sha256()
    files = 0
    if uploads_dir and Path(uploads_dir).is_dir():
        root = Path(uploads_dir)
        for src in sorted(p for p in root.rglob('*') if p.is_file() and not p.is_symlink()):
            uploads.update(f'{src.relative_to(root).as_posix()} {_sha256(src)}\n'.encode())
            files += 1
    return {'row_counts': counts, 'rows': sum(c for t, c in counts.items() if t != 'django_session'),
            'content_sha256': digest.hexdigest(), 'upload_files': files, 'uploads_sha256': uploads.hexdigest()}


def _copy_db(source: Path, dest: Path):
    """Consistent online copy (SQLite backup API)."""
    try:
        src = sqlite3.connect(f'file:{source}?mode=ro', uri=True)
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
    except sqlite3.Error as e:
        raise BackupError(f'Database cannot be copied: {e}') from e


def create_backup(db_path, uploads_dir, backup_dir, label='', now=None, version='unknown') -> Path:
    """Write backup-YYYYmmdd-HHMMSS[-label].tar.gz into backup_dir and return its path."""
    db_path, uploads_dir, backup_dir = Path(db_path), Path(uploads_dir), Path(backup_dir)
    if not db_path.is_file():
        raise BackupError('Database file not found.')
    if label and not LABEL_RE.match(label):
        raise BackupError('Label may only contain lower-case letters, digits and hyphens.')
    now = now or datetime.datetime.now(datetime.timezone.utc)
    backup_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(backup_dir, 0o700)
    name = f'backup-{now:%Y%m%d-%H%M%S}{"-" + label if label else ""}.tar.gz'
    final = backup_dir / name
    if final.exists():
        raise BackupError(f'{name} already exists.')

    with tempfile.TemporaryDirectory(dir=backup_dir, prefix='.staging-') as tmp:
        stage = Path(tmp)
        _copy_db(db_path, stage / DB_NAME)
        info = inspect_db(stage / DB_NAME)
        if info['integrity_check'] != 'ok':
            raise BackupError(f'Database integrity check failed: {info["integrity_check"]}')
        files = {DB_NAME: _sha256(stage / DB_NAME)}
        if uploads_dir.is_dir():
            for src in sorted(p for p in uploads_dir.rglob('*') if p.is_file() and not p.is_symlink()):
                rel = Path(UPLOADS) / src.relative_to(uploads_dir)
                (stage / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, stage / rel)
                files[rel.as_posix()] = _sha256(stage / rel)
        manifest = {'format': 1, 'created_utc': now.strftime('%Y-%m-%dT%H:%M:%SZ'), 'label': label,
                    'app_version': version, 'files': files, **info}
        (stage / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True))
        partial = backup_dir / f'.{name}.partial'
        with tarfile.open(partial, 'w:gz') as tar:
            tar.add(stage / MANIFEST, arcname=MANIFEST)
            for rel in files:
                tar.add(stage / rel, arcname=rel)
        os.chmod(partial, 0o600)
        os.replace(partial, final)           # atomic: a half-written file never carries the final name
    return final


def _safe_members(tar):
    allowed = {DB_NAME, PG_DUMP, MANIFEST}
    for m in tar.getmembers():
        parts = Path(m.name).parts
        ok = m.isfile() and not Path(m.name).is_absolute() and '..' not in parts and (
            m.name in allowed or (len(parts) > 1 and parts[0] == UPLOADS))
        if not ok:
            raise BackupError(f'Unexpected entry in archive: {m.name[:80]!r}')
        yield m


def verify_archive(archive, workdir) -> tuple[dict, Path]:
    """Extract into workdir and check manifest, hashes and the database. Returns (manifest, extracted dir)."""
    archive, workdir = Path(archive), Path(workdir)
    if not archive.is_file():
        raise BackupError('Backup archive not found.')
    out = workdir / 'extracted'
    out.mkdir(parents=True)
    try:
        with tarfile.open(archive, 'r:gz') as tar:
            members = list(_safe_members(tar))
            tar.extractall(out, members=members, filter='data')
    except (tarfile.TarError, OSError, EOFError) as e:
        raise BackupError(f'Archive cannot be read: {e}') from e
    try:
        manifest = json.loads((out / MANIFEST).read_text())
    except (OSError, ValueError) as e:
        raise BackupError('Manifest missing or unreadable.') from e
    files = manifest.get('files')
    engine = manifest.get('engine', SQLITE)                 # archives from before ADR 0035 have no engine: SQLite
    if engine not in DB_FILES:
        raise BackupError('Manifest names an unknown database engine.')
    if not isinstance(files, dict) or DB_FILES[engine] not in files:
        raise BackupError('Manifest does not list the database.')
    on_disk = {p.relative_to(out).as_posix() for p in out.rglob('*') if p.is_file()} - {MANIFEST}
    if on_disk != set(files):
        raise BackupError('Archive contents do not match the manifest.')
    for rel, expected in files.items():
        if _sha256(out / rel) != expected:
            raise BackupError(f'Checksum mismatch for {rel}.')
    if engine == POSTGRESQL:
        pg_check_dump(out / PG_DUMP)       # row counts are compared when the dump is restored into a database
        return manifest, out
    info = inspect_db(out / DB_NAME)
    if info['integrity_check'] != 'ok':
        raise BackupError(f'Database integrity check failed: {info["integrity_check"]}')
    if info['row_counts'] != manifest.get('row_counts'):
        raise BackupError('Row counts differ from the manifest.')
    return manifest, out


def archive_engine(manifest) -> str:
    return manifest.get('engine', SQLITE)


def _move_aside(path: Path, stamp: str) -> Path | None:
    if not path.exists():
        return None
    aside = path.with_name(f'{path.name}.before-restore-{stamp}')
    os.replace(path, aside)
    return aside


def restore_archive(archive, target_db, target_uploads, force=False, now=None) -> dict:
    """Verify, then place the database and uploads. Existing targets are refused unless force=True, in
    which case they are moved aside (never deleted)."""
    target_db, target_uploads = Path(target_db), Path(target_uploads)
    now = now or datetime.datetime.now(datetime.timezone.utc)
    stamp = f'{now:%Y%m%d-%H%M%S}'
    uploads_present = target_uploads.exists() and any(target_uploads.iterdir())
    if (target_db.exists() or uploads_present) and not force:
        raise BackupError('Target already contains data; refusing to overwrite (use force to move it aside).')
    target_db.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target_db.parent, prefix='.restore-') as tmp:
        manifest, out = verify_archive(archive, tmp)
        if archive_engine(manifest) != SQLITE:
            raise BackupError('This archive holds a PostgreSQL dump; restore it into a PostgreSQL database instead.')
        aside = []
        for p in (target_db, Path(f'{target_db}-wal'), Path(f'{target_db}-shm')):
            aside.append(_move_aside(p, stamp))
        if uploads_present:
            aside.append(_move_aside(target_uploads, stamp))
        shutil.copy2(out / DB_NAME, target_db)
        os.chmod(target_db, 0o600)
        target_uploads.mkdir(parents=True, exist_ok=True)
        if (out / UPLOADS).is_dir():
            shutil.copytree(out / UPLOADS, target_uploads, dirs_exist_ok=True)
    return {'manifest': manifest, 'moved_aside': [str(a) for a in aside if a]}


def parse_name(name: str):
    """(datetime, label) for a backup file name, or None if it is not one of ours."""
    m = NAME_RE.match(name)
    if not m:
        return None
    when = datetime.datetime.strptime(m.group(1) + m.group(2), '%Y%m%d%H%M%S').replace(tzinfo=datetime.timezone.utc)
    return when, m.group(3) or ''


def prune(backup_dir, now=None, keep_days=14, keep_months=12, keep_labelled_days=30) -> list[Path]:
    """Delete old backups. Kept: the newest backup of each calendar day within the last `keep_days` days, the
    newest of each calendar month within the last `keep_months` months, and every labelled backup (e.g.
    pre-deploy) younger than `keep_labelled_days`. Only files that match the backup naming pattern are ever
    touched."""
    backup_dir = Path(backup_dir)
    now = now or datetime.datetime.now(datetime.timezone.utc)
    found = sorted(((parse_name(p.name), p) for p in backup_dir.iterdir() if p.is_file()),
                   key=lambda t: t[0][0] if t[0] else now, reverse=True) if backup_dir.is_dir() else []
    found = [(meta, p) for meta, p in found if meta]
    keep, days, months = set(), set(), set()
    this_month = now.year * 12 + now.month
    for (when, label), p in found:                       # newest first: the first one seen per day/month wins
        age_days = (now.date() - when.date()).days
        month_age = this_month - (when.year * 12 + when.month)
        if label and age_days < keep_labelled_days:
            keep.add(p)
        if age_days < keep_days and when.date() not in days:
            days.add(when.date())
            keep.add(p)
        if month_age < keep_months and (when.year, when.month) not in months:
            months.add((when.year, when.month))
            keep.add(p)
    removed = []
    for _, p in found:
        if p not in keep:
            p.unlink()
            removed.append(p)
    return removed


def list_backups(backup_dir) -> list[Path]:
    backup_dir = Path(backup_dir)
    items = [(parse_name(p.name), p) for p in backup_dir.iterdir() if p.is_file()] if backup_dir.is_dir() else []
    return [p for meta, p in sorted((i for i in items if i[0]), key=lambda t: t[0][0], reverse=True)]


# --- PostgreSQL (ADR 0035) -----------------------------------------------------------------------------------------
def _pg_tool(name):
    from django.conf import settings
    base = getattr(settings, 'PG_BIN_DIR', '')
    return str(Path(base) / name) if base else name


def pg_env(db):
    """Environment for the client tools. The password travels in the environment, never on a command line."""
    env = {k: v for k, v in os.environ.items() if not k.startswith('PG')}
    env.update({'PGHOST': str(db['HOST']), 'PGPORT': str(db['PORT']), 'PGUSER': str(db['USER']),
                'PGPASSWORD': str(db.get('PASSWORD') or ''), 'PGCONNECT_TIMEOUT': '10'})
    return env


def _run(cmd, env=None, timeout=900):
    try:
        result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise BackupError(f'{Path(cmd[0]).name} could not run: {type(e).__name__}') from e
    if result.returncode != 0:
        # The tools never echo the password; still, only the first lines of their message are shown.
        message = ' '.join(result.stderr.strip().splitlines()[:3])[:300]
        raise BackupError(f'{Path(cmd[0]).name} failed: {message}')
    return result


def pg_tools_version() -> int:
    """Major version of pg_dump (must be at least the server's, 17)."""
    out = _run([_pg_tool('pg_dump'), '--version']).stdout
    m = re.search(r'(\d+)(?:\.\d+)?', out)
    if not m:
        raise BackupError('pg_dump --version gave no version.')
    return int(m.group(1))


def pg_check_dump(path: Path):
    """The dump must be readable and carry table data (pg_restore --list)."""
    result = _run([_pg_tool('pg_restore'), '--list', str(path)])
    if 'TABLE DATA' not in result.stdout:
        raise BackupError('The database dump contains no table data.')


def orm_row_counts() -> dict:
    """Row count per table through the ORM, for every model (many-to-many tables included). Same keys on both engines."""
    from django.apps import apps
    return {m._meta.db_table: m._base_manager.count() for m in sorted(
        apps.get_models(include_auto_created=True), key=lambda m: m._meta.db_table)}


def create_pg_backup(db, uploads_dir, backup_dir, label='', now=None, version='unknown') -> Path:
    """backup-YYYYmmdd-HHMMSS[-label].tar.gz holding db.dump (pg_dump -Fc), uploads/... and MANIFEST.json."""
    from django.db import connection, transaction
    uploads_dir, backup_dir = Path(uploads_dir), Path(backup_dir)
    if label and not LABEL_RE.match(label):
        raise BackupError('Label may only contain lower-case letters, digits and hyphens.')
    now = now or datetime.datetime.now(datetime.timezone.utc)
    backup_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(backup_dir, 0o700)
    name = f'backup-{now:%Y%m%d-%H%M%S}{"-" + label if label else ""}.tar.gz'
    final = backup_dir / name
    if final.exists():
        raise BackupError(f'{name} already exists.')
    if pg_tools_version() < PG_MIN_MAJOR:
        raise BackupError(f'pg_dump is older than {PG_MIN_MAJOR}; it cannot dump the server.')

    with tempfile.TemporaryDirectory(dir=backup_dir, prefix='.staging-') as tmp:
        stage = Path(tmp)
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    # One REPEATABLE READ snapshot, exported: pg_dump reads exactly this state, and so do the counts.
                    cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
                    cursor.execute('SELECT pg_export_snapshot()')
                    snapshot = cursor.fetchone()[0]
                _run([_pg_tool('pg_dump'), '-Fc', '--no-owner', '--no-acl', f'--snapshot={snapshot}',
                      f'--dbname={db["NAME"]}', '-f', str(stage / PG_DUMP)], env=pg_env(db))
                counts = orm_row_counts()
        except BackupError:
            raise
        except Exception as e:                       # driver errors: the type only (a message could carry details)
            raise BackupError(f'Database cannot be read: {type(e).__name__}') from e
        pg_check_dump(stage / PG_DUMP)
        files = {PG_DUMP: _sha256(stage / PG_DUMP)}
        if uploads_dir.is_dir():
            for src in sorted(p for p in uploads_dir.rglob('*') if p.is_file() and not p.is_symlink()):
                rel = Path(UPLOADS) / src.relative_to(uploads_dir)
                (stage / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, stage / rel)
                files[rel.as_posix()] = _sha256(stage / rel)
        manifest = {'format': 1, 'engine': POSTGRESQL, 'created_utc': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
                    'label': label, 'app_version': version, 'files': files, 'integrity_check': 'ok', 'row_counts': counts}
        (stage / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True))
        partial = backup_dir / f'.{name}.partial'
        with tarfile.open(partial, 'w:gz') as tar:
            tar.add(stage / MANIFEST, arcname=MANIFEST)
            for rel in files:
                tar.add(stage / rel, arcname=rel)
        os.chmod(partial, 0o600)
        # Re-verify what was written (checksums, pg_restore --list) before it carries the final name.
        with tempfile.TemporaryDirectory(dir=backup_dir, prefix='.verify-') as vtmp:
            verify_archive(partial, vtmp)
        os.replace(partial, final)
    return final


def _pg_connect(db, dbname):
    import psycopg
    try:
        return psycopg.connect(host=db['HOST'], port=db['PORT'], user=db['USER'], password=db.get('PASSWORD') or '',
                               dbname=dbname, connect_timeout=10, autocommit=True)
    except psycopg.Error as e:
        raise BackupError(f'Cannot connect to database {dbname!r}: {type(e).__name__}') from e


def pg_user_tables(db, dbname) -> dict:
    """Exact row count of every table in the public schema of a database."""
    import psycopg
    with _pg_connect(db, dbname) as conn:
        try:
            names = [r[0].decode() if isinstance(r[0], (bytes, memoryview)) else r[0] for r in conn.execute(
                "SELECT tablename::text FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")]
            return {n: conn.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0] for n in names}
        except psycopg.Error as e:
            raise BackupError(f'Cannot read database {dbname!r}: {type(e).__name__}') from e


def restore_pg_archive(archive, db, new_db, target_uploads, force=False, swap=False, now=None) -> dict:
    """Restore into the NEW, EMPTY database `new_db` (created beforehand on the platform side) and the uploads into
    `target_uploads`. The live database is untouched unless swap=True; then it is renamed aside, never dropped."""
    import psycopg
    target_uploads = Path(target_uploads)
    now = now or datetime.datetime.now(datetime.timezone.utc)
    stamp = f'{now:%Y%m%d_%H%M%S}'
    live = db['NAME']
    if not DB_NAME_RE.match(new_db):
        raise BackupError('Database name may only contain lower-case letters, digits and underscores.')
    if new_db == live:
        raise BackupError('The restore target must be a new database, not the live one (swap replaces the live one).')
    uploads_present = target_uploads.exists() and any(target_uploads.iterdir())
    if uploads_present and not force:
        raise BackupError('Target uploads folder already contains files; refusing to overwrite (use force to move them aside).')
    with tempfile.TemporaryDirectory() as tmp:
        manifest, out = verify_archive(archive, tmp)
        if archive_engine(manifest) != POSTGRESQL:
            raise BackupError('This archive holds a SQLite database; it cannot be restored into PostgreSQL.')
        if pg_user_tables(db, new_db):                 # also fails if it does not exist (this role cannot create it)
            raise BackupError(f'Database {new_db!r} is not empty; refusing to restore into it.')
        _run([_pg_tool('pg_restore'), '--no-owner', '--no-acl', '--exit-on-error', f'--dbname={new_db}',
              str(out / PG_DUMP)], env=pg_env(db))
        restored = pg_user_tables(db, new_db)
        expected = manifest['row_counts']
        if {t: restored.get(t) for t in expected} != expected:
            raise BackupError('Row counts of the restored database differ from the manifest.')
        aside_uploads = None
        if uploads_present:
            aside_uploads = target_uploads.with_name(f'{target_uploads.name}.before-restore-{stamp}')
            os.replace(target_uploads, aside_uploads)
        target_uploads.mkdir(parents=True, exist_ok=True)
        if (out / UPLOADS).is_dir():
            shutil.copytree(out / UPLOADS, target_uploads, dirs_exist_ok=True)
    result = {'manifest': manifest, 'new_db': new_db, 'moved_aside': [str(aside_uploads)] if aside_uploads else [],
              'swapped_aside_db': None}
    if swap:
        aside_db = f'{live}_before_restore_{stamp}'
        with _pg_connect(db, 'postgres') as admin:
            try:
                admin.execute(f'ALTER DATABASE "{live}" RENAME TO "{aside_db}"')
            except psycopg.Error as e:
                raise BackupError(
                    f'Cannot rename the live database ({type(e).__name__}): stop the app first; renaming needs a role '
                    f'with CREATEDB, which this app does not have, so swap with the platform tool (make pg-restore). '
                    f'Nothing was swapped; the restored copy is database {new_db!r}.') from e
            try:
                admin.execute(f'ALTER DATABASE "{new_db}" RENAME TO "{live}"')
            except psycopg.Error as e:
                admin.execute(f'ALTER DATABASE "{aside_db}" RENAME TO "{live}"')          # put the live one back
                raise BackupError(f'Swap failed and was undone ({type(e).__name__}).') from e
        result['swapped_aside_db'] = aside_db
    return result

