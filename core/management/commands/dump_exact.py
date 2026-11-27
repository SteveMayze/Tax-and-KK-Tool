"""Dump all data as JSON for the move between database engines, without losing precision (ADR 0035).

Django's own `dumpdata` cuts every timestamp to milliseconds (its JSON encoder drops the last three digits of the
microseconds). This app stores microseconds in all its timestamps, so a plain dumpdata -> loaddata would change every
created_at / updated_at; the parts-db pilot found exactly that. This command is `dumpdata` with an encoder that keeps
all digits. Decimals are written as exact strings (Django's encoder already does that) and JSON fields as JSON.
Load the result with the normal `loaddata`.

Carried: every `core` row with its primary key (report references and stored file names contain ids), the users with
their password hashes and primary keys, groups, and the admin log. Left out, because `migrate` recreates them:
content types, permissions; and sessions (the owner logs in again). References to content types and permissions are
written by natural key. The output holds the owner's data: write it only to a private file, never to a log.
"""
import datetime

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.core.serializers import json as django_json

EXCLUDE = ['contenttypes', 'auth.permission', 'sessions']


class ExactJSONEncoder(django_json.DjangoJSONEncoder):
    def default(self, o):
        if isinstance(o, datetime.datetime):
            r = o.isoformat()                                  # keeps the microseconds
            return r.removesuffix('+00:00') + 'Z' if r.endswith('+00:00') else r
        if isinstance(o, datetime.time):
            return o.isoformat() if o.tzinfo is None else super().default(o)
        return super().default(o)


class Command(BaseCommand):
    help = 'dumpdata as JSON with full timestamp precision and exact decimals (for the SQLite -> PostgreSQL move).'

    def add_arguments(self, parser):
        parser.add_argument('-o', '--output', default=None, help='write to this file (mode 0600) instead of stdout')

    def handle(self, *args, **options):
        original = django_json.DjangoJSONEncoder
        django_json.DjangoJSONEncoder = ExactJSONEncoder        # the serializer looks the name up when it starts
        try:
            if options['output']:
                import os
                fd = os.open(options['output'], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                os.close(fd)
            call_command('dumpdata', use_natural_foreign_keys=True, use_natural_primary_keys=False,
                         exclude=EXCLUDE, format='json', indent=None, output=options['output'],
                         stdout=self.stdout)
        finally:
            django_json.DjangoJSONEncoder = original
