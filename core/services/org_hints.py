"""Enter a missing organisation once for every statement of the same company (ADR 0041).

Rows made from a statement that prints no ASX code carry `ImportRow.org_hint`, the company name as printed. It only groups
rows; it is never data and never matched in code. The owner types the organisation once and applies it to the rows of the
group that are still empty. Review-page convenience only: nothing is imported here.
"""
from django.db import transaction
from django.utils.translation import gettext

from core.models import ImportRow, Organisation

from . import imports, lookups


class HintError(ValueError):
    pass


def _open_rows(batch):
    return [r for r in batch.rows.exclude(org_hint='') if not (r.data.get('organisation') or '').strip()]


def groups(batch):
    """[{'hint', 'count', 'proposal'}]: one per printed name with rows whose organisation is still empty. The proposal is
    the single existing organisation starting with the name, else ''."""
    counts = {}
    for r in _open_rows(batch):
        counts[r.org_hint] = counts.get(r.org_hint, 0) + 1
    result = []
    for hint, count in sorted(counts.items()):
        matches = list(Organisation.objects.filter(name__istartswith=hint)[:2])
        result.append({'hint': hint, 'count': count, 'proposal': matches[0].name if len(matches) == 1 else ''})
    return result


def clean_organisation(value):
    name = ' '.join((value or '').split())
    if not name:
        raise HintError(gettext('organisation: required.'))
    if len(name) > 200:
        raise HintError(gettext('organisation: longer than 200 characters.'))
    existing = lookups.find(Organisation, name)
    if existing is not None and not existing.active:
        raise HintError(gettext('organisation: "%(name)s" is inactive. Reactivate it or use another name.') % {'name': existing.name})
    return name


@transaction.atomic
def apply(batch, hint, value, provider):
    """Set the organisation of this batch's rows with `hint` whose organisation is still empty; returns how many. A row the
    owner already edited is left alone. `original` is untouched. Rows are re-checked once."""
    imports._require_preview(batch)
    name = clean_organisation(value)
    changed = 0
    for r in batch.rows.filter(org_hint=hint):
        if (r.data.get('organisation') or '').strip():
            continue
        r.data = {**{k: v for k, v in r.data.items() if k != '_structural'}, 'organisation': name}
        r.save(update_fields=['data'])
        changed += 1
    if changed:
        imports.revalidate_batch(batch, provider)
    return changed
