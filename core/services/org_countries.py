"""Country of organisations at import (ADR 0040).

A NEW organisation gets a country only from the owner's confirmed choice. The choice starts as a visible proposal: the
reader's own country first, else the country of a non-EUR currency (core.currencies.CURRENCY_COUNTRY), else blank. EUR is
never inferred. An existing organisation keeps its country; one with a blank country can be filled only through an opt-in
tick (default off). Currency is a hint, not proof of the country.
"""
from collections import defaultdict

from django.utils.translation import gettext

from core.countries import ISO_COUNTRIES
from core.currencies import BASE_CURRENCY, CURRENCY_COUNTRY
from core.models import Organisation

from . import lookups


class CountryError(ValueError):
    pass


def clean_code(value):
    """'' (unknown) or an uppercase ISO 3166-1 alpha-2 code from the fixed list; CountryError otherwise."""
    code = (value or '').strip().upper()
    if code and code not in ISO_COUNTRIES:
        raise CountryError(gettext('"%(code)s" is not an ISO 3166-1 alpha-2 country code.') % {'code': (value or '')[:10]})
    return code


def currency_country(currency):
    return CURRENCY_COUNTRY.get((currency or '').upper(), '') if (currency or '').upper() != BASE_CURRENCY else ''


def _groups(batch):
    """lower name -> {'name', 'rows'} for the organisations of the rows that will be imported."""
    groups = {}
    for r in batch.rows.all():
        if not r.will_import:
            continue
        name = ' '.join((r.data.get('organisation') or '').split())
        if name:
            groups.setdefault(name.lower(), {'name': name, 'rows': []})['rows'].append(r)
    return groups


def _proposal(rows):
    """(country, source) from the reader of the first row that knows one, else from a non-EUR currency shared by all rows."""
    for r in rows:
        if r.reader_country:
            return r.reader_country, 'reader'
    codes = {currency_country(r.data.get('currency')) for r in rows}
    if len(codes) == 1 and codes != {''}:
        return codes.pop(), 'currency'
    return '', ''


def review(batch):
    """(new, existing_blank): what the preview page shows. new: one entry per organisation that does not exist yet, with
    the proposed country and the country that will be used (the owner's choice when made). existing_blank: existing
    organisations without a country, with the proposal and whether the opt-in tick is set."""
    saved = batch.organisation_countries or {}
    chosen, fill = saved.get('new', {}), saved.get('fill_existing', {})
    new, existing_blank = [], []
    for key, g in sorted(_groups(batch).items()):
        proposed, source = _proposal(g['rows'])
        org = lookups.find(Organisation, g['name'])
        if org is None:
            new.append({'key': key, 'name': g['name'], 'proposed': proposed, 'source': source,
                        'country': chosen.get(key, proposed), 'chosen': key in chosen, 'payments': len(g['rows'])})
        elif not org.country:
            existing_blank.append({'key': key, 'name': org.name, 'proposed': proposed, 'source': source,
                                   'fill': key in fill, 'payments': len(g['rows'])})
    return new, existing_blank


def save_choices(batch, new_choices, fill_keys):
    """new_choices: {lower name: country text}; fill_keys: lower names whose blank country may be filled. Validates the
    codes (CountryError, nothing saved) and touches nothing else of the batch."""
    new, existing_blank = review(batch)
    known_new = {n['key'] for n in new}
    saved_new = {k: clean_code(v) for k, v in new_choices.items() if k in known_new}
    proposals = {e['key']: e['proposed'] for e in existing_blank}
    saved_fill = {k: proposals[k] for k in fill_keys if k in proposals and proposals[k]}
    batch.organisation_countries = {'new': saved_new, 'fill_existing': saved_fill}
    batch.save(update_fields=['organisation_countries'])


def countries_for_new(batch):
    """lower name -> country that each NEW organisation is created with at commit: the owner's choice if made, else the
    proposal that the preview showed."""
    return {n['key']: n['country'] for n in review(batch)[0]}


def fill_existing_countries(batch):
    """At commit: set the country of the opted-in existing organisations that are still blank. Never overwrites."""
    for key, code in ((batch.organisation_countries or {}).get('fill_existing', {})).items():
        org = Organisation.objects.filter(name__iexact=key).first()
        if org is not None and not org.country and code:
            org.country = code
            org.save()


def organisation_proposals():
    """Existing organisations without a country whose payments all have the same non-EUR currency with a known country:
    [(organisation, proposed country, currency, number of payments)]. Read only."""
    from core.models import Payment
    currencies = defaultdict(set)
    counts = defaultdict(int)
    for org_id, currency in Payment.objects.filter(organisation__country='').values_list('organisation_id', 'currency'):
        currencies[org_id].add(currency)
        counts[org_id] += 1
    result = []
    for org in Organisation.objects.filter(country='').order_by('name'):
        ccys = currencies.get(org.pk)
        if ccys and len(ccys) == 1:
            ccy = next(iter(ccys))
            code = currency_country(ccy)
            if code:
                result.append((org, code, ccy, counts[org.pk]))
    return result
