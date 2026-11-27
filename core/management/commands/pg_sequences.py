from django.core.management.base import BaseCommand

from core.services import sequences


class Command(BaseCommand):
    help = ('Check (default) or --reset the id sequences after a bulk load (PostgreSQL; counts only). '
            'behind=0 means every sequence is above its table\'s maximum id.')

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true')

    def handle(self, *args, **opts):
        if opts['reset']:
            self.stdout.write(f'RESET statements={sequences.reset()}')
        state = sequences.check()
        self.stdout.write(f'SEQUENCES checked={state["sequences"]} behind={state["behind"]}')
