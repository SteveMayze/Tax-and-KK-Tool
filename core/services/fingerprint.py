"""Engine-neutral fingerprint of the data (ADR 0035): row count and content hash per model, through the ORM.

Rows are read in primary-key order and every value is written in one normalised text form, so the same data gives the
same hash on SQLite and on PostgreSQL:
- decimals as exact normalised strings (`Decimal.normalize()`, zero always `0`), never floats;
- datetimes in UTC, ISO format with microseconds; dates and times in ISO format;
- JSON as canonical JSON (sorted keys, fixed separators), because PostgreSQL's jsonb does not keep key order;
- a reference to a content type or a permission by its natural key (`app.model`, `app.model.codename`), because
  `migrate` recreates those rows with different ids on each database.
Content types, permissions and sessions themselves are left out (recreated by `migrate`, or short-lived). The
automatic many-to-many tables are hashed without their own id, ordered by their two references. Only counts and
hashes ever leave this module, never a value.
"""
import datetime
import decimal
import hashlib
import json

SKIP = {'contenttypes.contenttype', 'auth.permission', 'sessions.session'}


def _natural_resolvers(using):
    from django.contrib.auth.models import Permission
    from django.contrib.contenttypes.models import ContentType
    cts = {c.pk: f'{c.app_label}.{c.model}' for c in ContentType.objects.using(using).all()}
    perms = {p.pk: f'{cts.get(p.content_type_id, "?")}.{p.codename}' for p in Permission.objects.using(using).all()}
    return {ContentType: cts, Permission: perms}


def normal(value) -> str:
    """One value in the normalised text form (the same on both engines)."""
    if value is None:
        return 'N'
    if isinstance(value, bool):
        return f'b{int(value)}'
    if isinstance(value, decimal.Decimal):
        return 'd0' if value == 0 else 'd' + format(value.normalize(), 'f')
    if isinstance(value, datetime.datetime):
        if value.tzinfo is not None:
            value = value.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        return 't' + value.isoformat(timespec='microseconds')
    if isinstance(value, (datetime.date, datetime.time)):
        return 't' + value.isoformat()
    if isinstance(value, (dict, list)):
        return 'j' + json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    if isinstance(value, float):
        return 'f' + repr(value)
    if isinstance(value, (bytes, memoryview)):
        return 'x' + bytes(value).hex()
    return 's' + str(value)


def models():
    from django.apps import apps
    return sorted(apps.get_models(include_auto_created=True), key=lambda m: m._meta.label_lower)


def model_fingerprints(using='default'):
    """[(model label, row count, sha256)] for every model except SKIP."""
    resolvers = _natural_resolvers(using)
    out = []
    for model in models():
        label = model._meta.label_lower
        if label in SKIP:
            continue
        through = model._meta.auto_created
        fields = [f for f in model._meta.concrete_fields if not (through and f.primary_key)]
        lookups = {f.attname: resolvers.get(f.related_model) for f in fields if f.is_relation}
        rows = []
        qs = model._base_manager.using(using)
        for row in qs.order_by('pk').values_list(*[f.attname for f in fields]).iterator(chunk_size=500):
            cells = []
            for f, value in zip(fields, row):
                mapping = lookups.get(f.attname)
                if mapping is not None and value is not None:
                    value = mapping.get(value, value)
                cells.append(f'{f.attname}={normal(value)}')
            rows.append('\x1f'.join(cells))
        if through:
            rows.sort()              # a link table's own ids are not data; its rows are ordered by what they link
        digest = hashlib.sha256()
        for line in rows:
            digest.update(line.encode('utf-8') + b'\x1e')
        out.append((label, len(rows), digest.hexdigest()))
    return out


def uploads_fingerprint(uploads_dir):
    """(number of files, sha256 over relative path + content hash), as in the SQLite-era fingerprint."""
    from pathlib import Path
    from .backup import _sha256
    digest, files = hashlib.sha256(), 0
    if uploads_dir and Path(uploads_dir).is_dir():
        root = Path(uploads_dir)
        for src in sorted(p for p in root.rglob('*') if p.is_file() and not p.is_symlink()):
            digest.update(f'{src.relative_to(root).as_posix()} {_sha256(src)}\n'.encode())
            files += 1
    return files, digest.hexdigest()


def fingerprint(uploads_dir=None, using='default') -> dict:
    per_model = model_fingerprints(using)
    total = hashlib.sha256()
    for label, count, h in per_model:
        total.update(f'{label}:{count}:{h}\n'.encode())
    files, uploads = uploads_fingerprint(uploads_dir)
    return {'models': per_model, 'rows': sum(c for _l, c, _h in per_model), 'content_sha256': total.hexdigest(),
            'upload_files': files, 'uploads_sha256': uploads}
