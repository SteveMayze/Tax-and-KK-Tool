"""Read-only check that every stored decimal survives the exact export unchanged (ADR 0035). For every DecimalField
of every model it counts values that (a) change in a JSON round trip through dump_exact's encoder, (b) have 15 or more
significant digits (SQLite keeps only 15 in its REAL storage, so such a value may already be rounded), or (c) do not
fit the field's max_digits / decimal_places. Prints counts only; all three must be 0 before the move.
"""
import decimal
import json

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import models

from core.management.commands.dump_exact import ExactJSONEncoder


def _significant(value):
    digits = value.normalize().as_tuple().digits
    return 0 if value == 0 else len(digits)


def _fits(value, field):
    sign, digits, exp = value.as_tuple()
    places = max(0, -exp)
    whole = len(digits) - places if len(digits) > places else 0
    return places <= field.decimal_places and whole <= field.max_digits - field.decimal_places


def check():
    totals = {'values': 0, 'roundtrip_changed': 0, 'sig15_or_more': 0, 'does_not_fit': 0}
    fields = 0
    for model in apps.get_models():
        decimal_fields = [f for f in model._meta.concrete_fields if isinstance(f, models.DecimalField)]
        if not decimal_fields:
            continue
        fields += len(decimal_fields)
        for row in model._base_manager.values_list(*[f.attname for f in decimal_fields]).iterator(chunk_size=500):
            for f, value in zip(decimal_fields, row):
                if value is None:
                    continue
                totals['values'] += 1
                back = decimal.Decimal(json.loads(json.dumps(value, cls=ExactJSONEncoder)))
                if back != value or str(back) != str(value):
                    totals['roundtrip_changed'] += 1
                if _significant(value) >= 15:
                    totals['sig15_or_more'] += 1
                if not _fits(value, f):
                    totals['does_not_fit'] += 1
    return fields, totals


class Command(BaseCommand):
    help = 'Count decimals that would not survive the exact export (counts only; read only).'

    def handle(self, *args, **opts):
        fields, t = check()
        self.stdout.write(f'DECIMALS fields={fields} ' + ' '.join(f'{k}={v}' for k, v in t.items()))
