"""Organisation and category filter for reports (Phase 30, ADR 0031). Read only; nothing is stored.

Within a group the ticked ids are combined with OR, the two groups with AND; an empty group is no restriction.
The filter is always by primary key (never by name) and is applied in one place, `ReportFilter.apply`, which
`reports._payments`, `reconciliation.build_report` and `tax.tax_summary_rows` call on the payment set they use.
"""
import re
from dataclasses import dataclass
from urllib.parse import urlencode

from django.db.models import Count, Q
from django.utils.translation import gettext as _

from core.models import IncomeCategory, Organisation

ORGANISATION, CATEGORY = 'organisation', 'category'
ID_PATTERN = re.compile(r'[0-9]{1,9}')


@dataclass(frozen=True)
class ReportFilter:
    organisation_ids: tuple = ()
    category_ids: tuple = ()

    @property
    def is_active(self):
        return bool(self.organisation_ids or self.category_ids)

    def apply(self, qs):
        if self.organisation_ids:
            qs = qs.filter(organisation_id__in=self.organisation_ids)
        if self.category_ids:
            qs = qs.filter(category_id__in=self.category_ids)
        return qs

    def describe(self):
        """The text of the `Filter` basis row: ticked names as stored, and the combination rule."""
        def names(model, ids):
            by_id = dict(model.objects.filter(pk__in=ids).values_list('pk', 'name'))
            return ', '.join(by_id[i] for i in ids if i in by_id)
        none = _('no restriction')
        return _('Organisations: %(orgs)s. Categories: %(cats)s. Combined as: any of the ticked organisations AND any '
                 'of the ticked categories (a group with nothing ticked does not restrict).') % {
            'orgs': names(Organisation, self.organisation_ids) or none,
            'cats': names(IncomeCategory, self.category_ids) or none}

    def params(self, year=None, with_year=True):
        items = [('year', year if year else 'all')] if with_year else []
        items += [(ORGANISATION, i) for i in self.organisation_ids] + [(CATEGORY, i) for i in self.category_ids]
        return items

    def querystring(self, year=None, with_year=True):
        return urlencode(self.params(year, with_year))


NO_FILTER = ReportFilter()


def parse(get):
    """(ReportFilter, error text or None) from a QueryDict. Non-numeric or unknown ids are an error (at most 10
    characters of the input are echoed); repeated ids collapse; ids are sorted so equal selections give equal URLs."""
    for key in get:
        if key.lower() in (ORGANISATION, CATEGORY) and key not in (ORGANISATION, CATEGORY):
            return NO_FILTER, _('Unknown filter parameter "%(name)s".') % {'name': key[:10]}
    chosen = {}
    for key, model, label in ((ORGANISATION, Organisation, _('organisation')), (CATEGORY, IncomeCategory, _('category'))):
        ids = set()
        for raw in get.getlist(key):
            raw = raw.strip()
            if not raw:
                continue
            if not ID_PATTERN.fullmatch(raw):
                return NO_FILTER, _('Unknown %(kind)s "%(value)s".') % {'kind': label, 'value': raw[:10]}
            ids.add(int(raw))
        if ids:
            found = set(model.objects.filter(pk__in=ids).values_list('pk', flat=True))
            if ids - found:
                return NO_FILTER, _('Unknown %(kind)s "%(value)s".') % {'kind': label, 'value': str(min(ids - found))[:10]}
        chosen[key] = tuple(sorted(ids))
    return ReportFilter(chosen[ORGANISATION], chosen[CATEGORY]), None


def options(year=None, flt=NO_FILTER):
    """Check-box options: every organisation and category with at least one payment in any year (active or not),
    each with its payment count for the selected period. One query per list."""
    in_period = Q(payments__month__year__year=year) if year else Q()
    result = {}
    for key, model, ticked in ((ORGANISATION, Organisation, flt.organisation_ids), (CATEGORY, IncomeCategory, flt.category_ids)):
        rows = (model.objects.annotate(total=Count('payments'), n=Count('payments', filter=in_period))
                .filter(total__gt=0).order_by('name').values_list('pk', 'name', 'active', 'n'))
        result[key] = [{'id': pk, 'name': name, 'active': active, 'count': n, 'checked': pk in ticked}
                       for pk, name, active, n in rows]
    return result
