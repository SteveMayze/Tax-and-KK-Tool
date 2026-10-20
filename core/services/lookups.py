"""Combo-style organisation/category lookup: pick an existing name or add a new one."""
from django.utils.translation import gettext as _

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
        raise InactiveLookup(_('"%(name)s" is inactive. Reactivate it first or choose another name.') % {'name': obj.name})


def loss_error(category_name, gross):
    """Message when a NEGATIVE normal payment is entered for a category not marked "may be negative" (a category
    that does not exist yet is not marked either). None when the amount is fine. Creates nothing."""
    if gross is None or gross >= 0:
        return None
    cat = find(IncomeCategory, category_name)
    if cat is not None and cat.may_be_negative:
        return None
    name = cat.name if cat is not None else _clean(category_name)
    message = _('Gross amount must be positive: a negative amount (loss) is only allowed in categories marked "may be negative"; '
                'category "%(name)s" is not') % {'name': name}
    if cat is None:
        message += _(' (it does not exist yet)')
    return message + _('. Mark it on the Categories page first, or use a reversal/correction.')


def resolve(model, name):
    """Return the existing row (case-insensitive) or create a new one."""
    check_usable(model, name)
    obj = find(model, name)
    return obj or model.objects.create(name=_clean(name))


def resolve_organisation(name):
    """An organisation named by a statement rule (the tenant of the joint-account rent, Phase 26) is created with country
    DE; any other new organisation is created without a country, as before."""
    from core.models import StatementRule
    if find(Organisation, name) is None and StatementRule.objects.filter(organisation__iexact=_clean(name)).exists():
        check_usable(Organisation, name)
        return Organisation.objects.create(name=_clean(name), country='DE')
    return resolve(Organisation, name)


def resolve_category(name):
    return resolve(IncomeCategory, name)
