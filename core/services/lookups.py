"""Combo-style organisation/category lookup: pick an existing name or add a new one."""
from core.models import IncomeCategory, Organisation


class InactiveLookup(Exception):
    pass


def _clean(name):
    return ' '.join((name or '').split())


def find(model, name):
    return model.objects.filter(name__iexact=_clean(name)).first()


def check_usable(model, name):
    """Raise InactiveLookup if the name matches a deactivated row. Creates nothing."""
    obj = find(model, name)
    if obj is not None and not obj.active:
        raise InactiveLookup(f'"{obj.name}" is inactive. Reactivate it first or choose another name.')


def resolve(model, name):
    """Return the existing row (case-insensitive) or create a new one."""
    check_usable(model, name)
    obj = find(model, name)
    return obj or model.objects.create(name=_clean(name))


def resolve_organisation(name):
    return resolve(Organisation, name)


def resolve_category(name):
    return resolve(IncomeCategory, name)
