"""Backup and restore of the SQLite database and uploaded files (docs/deployment.md).

A backup is one tar.gz: db.sqlite3 (a consistent copy made with SQLite's online backup API, so it is safe
while the app is running), uploads/..., and MANIFEST.json (SHA-256 of every file, integrity-check result,
row counts per table, app version). Restores verify everything first and never overwrite silently.
Row counts and file names are the only data reported; no payment contents are printed or logged.
"""
import datetime
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tarfile
import tempfile
from pathlib import Path

MANIFEST = 'MANIFEST.json'
DB_NAME = 'db.sqlite3'
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
    allowed = {DB_NAME, MANIFEST}
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
    if not isinstance(files, dict) or DB_NAME not in files:
        raise BackupError('Manifest does not list the database.')
    on_disk = {p.relative_to(out).as_posix() for p in out.rglob('*') if p.is_file()} - {MANIFEST}
    if on_disk != set(files):
        raise BackupError('Archive contents do not match the manifest.')
    for rel, expected in files.items():
        if _sha256(out / rel) != expected:
            raise BackupError(f'Checksum mismatch for {rel}.')
    info = inspect_db(out / DB_NAME)
    if info['integrity_check'] != 'ok':
        raise BackupError(f'Database integrity check failed: {info["integrity_check"]}')
    if info['row_counts'] != manifest.get('row_counts'):
        raise BackupError('Row counts differ from the manifest.')
    return manifest, out


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
