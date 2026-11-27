"""Sequences after a bulk load (ADR 0035). `loaddata` inserts rows with their ids, which does not move PostgreSQL's
id sequences; the next new row would then collide. `reset` sets every sequence of every model to its table's maximum
id; `check` counts sequences that are behind. SQLite needs neither (it takes the next id from the table itself)."""
from django.apps import apps
from django.core.management.color import no_style
from django.db import connections


def _models():
    return [m for m in apps.get_models(include_auto_created=True) if m._meta.pk and m._meta.pk.get_internal_type() in (
        'AutoField', 'BigAutoField', 'SmallAutoField')]


def reset(using='default') -> int:
    connection = connections[using]
    statements = connection.ops.sequence_reset_sql(no_style(), _models())
    with connection.cursor() as cursor:
        for sql in statements:
            cursor.execute(sql)
    return len(statements)


def check(using='default') -> dict:
    """{'sequences': n, 'behind': n} where behind = next value would not be above the table's maximum id."""
    connection = connections[using]
    if connection.vendor != 'postgresql':
        return {'sequences': 0, 'behind': 0}
    result = {'sequences': 0, 'behind': 0}
    with connection.cursor() as cursor:
        for model in _models():
            table, column = model._meta.db_table, model._meta.pk.column
            cursor.execute('SELECT pg_get_serial_sequence(%s, %s)', [connection.ops.quote_name(table), column])
            seq = cursor.fetchone()[0]
            if not seq:
                continue
            result['sequences'] += 1
            cursor.execute(f'SELECT last_value, is_called FROM {seq}')
            last, called = cursor.fetchone()
            cursor.execute(f'SELECT COALESCE(MAX({connection.ops.quote_name(column)}), 0) FROM {connection.ops.quote_name(table)}')
            top = cursor.fetchone()[0]
            next_value = last + 1 if called else last
            if next_value <= top:
                result['behind'] += 1
    return result
