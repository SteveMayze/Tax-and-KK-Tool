"""Load a dump written by `dump_exact` into a freshly migrated, otherwise EMPTY database (ADR 0035, Phase 39).

`migrate` on an empty database seeds the seven default income categories (migration 0002); they would collide with
the loaded categories (same names, other ids). This command therefore refuses unless the target holds nothing but
what `migrate` itself created (content types, permissions, those seed categories), then, in ONE transaction, removes
the seed categories, loads the dump with `loaddata` and resets the id sequences. On any error nothing is kept.
Prints counts only. Never used on a database that holds the owner's data: the emptiness check refuses that.
"""
from django.apps import apps
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.services import sequences

MIGRATE_OWNED = {'contenttypes.contenttype', 'auth.permission'}
SEED = ['Salary', 'Pension', 'Rental', 'Interest', 'Dividends', 'Capital gains', 'Other']


def _not_empty():
    """Models (labels) that hold rows `migrate` did not create."""
    from core.models import IncomeCategory
    busy = []
    for model in apps.get_models(include_auto_created=True):
        label = model._meta.label_lower
        if label in MIGRATE_OWNED:
            continue
        qs = model._base_manager.all()
        if label == 'core.incomecategory':
            qs = IncomeCategory._base_manager.exclude(name__in=SEED)        # only the migration's seeds may be there
        if qs.exists():
            busy.append(label)
    return busy


class Command(BaseCommand):
    help = 'Load a dump_exact file into a freshly migrated, empty database, then reset the sequences (counts only).'

    def add_arguments(self, parser):
        parser.add_argument('dump', help='the JSON file written by dump_exact')

    def handle(self, *args, **opts):
        from core.models import IncomeCategory
        busy = _not_empty()
        if busy:
            raise CommandError(f'The target database is not empty ({len(busy)} model(s) hold rows); nothing was loaded.')
        with transaction.atomic():
            removed, _ = IncomeCategory._base_manager.filter(name__in=SEED).delete()
            call_command('loaddata', opts['dump'], verbosity=0)
            statements = sequences.reset()
        state = sequences.check()
        self.stdout.write(f'LOADED seed_categories_removed={removed} sequence_statements={statements} '
                          f'sequences={state["sequences"]} behind={state["behind"]}')
        if state['behind']:
            raise CommandError('Some sequences are still behind their table; do not use this database.')
