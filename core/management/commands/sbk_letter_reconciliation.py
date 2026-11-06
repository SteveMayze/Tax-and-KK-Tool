from django.core.management.base import BaseCommand

from core.services import sbk_letter as sl


class Command(BaseCommand):
    help = ('Read-only: compare the recorded data of a year with the figures of SBK\'s letter of 2026-11-06 '
            '(docs/sbk-letters/2026-11-06.md). Lists which readings reproduce each letter figure; chooses none.')

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int, required=True)
        parser.add_argument('--organisations', action='store_true', help='also list the per-organisation breakdown (names of payers)')

    def handle(self, *args, **opts):
        w = self.stdout.write
        r = sl.build(opts['year'])
        w(f'SBK letter {sl.LETTER["date"]} against recorded data of {r.year} (EUR at stored rates; unconverted rows excluded)')
        w('Back payment check: ' + ' + '.join(f'{p["months"]} x {p["total"]}' for p in sl.LETTER['periods'])
          + f' = {sl.back_payment()} (letter: {sl.LETTER["back_payment"]})')
        w('')
        w('Targets (letter monthly x 12 = annual):')
        for label, monthly, annual in sl.targets():
            w(f'  {label:42} {monthly:>10} x 12 = {annual:>10}')
        w('')
        w('Per treatment (annual): gross | withholding | recorded expenses | AnnualInput costs | gross/12 | unconverted rows')
        for t, v in sorted(r.treatments.items()):
            note = '' if v['has_input'] or not v['expenses'] else '   <-- expenses recorded but NO AnnualInput costs entered'
            w(f'  {t:12} {v["gross"]:>12.2f} {v["withholding"]:>10.2f} {v["expenses"]:>10.2f} {v["costs"]:>10.2f} '
              f'{v["monthly"]:>10.2f} {v["pending"]:>3}{note}')
        w('')
        w('Groups (category / organisation country / currency):')
        for g in r.groups:
            w(f'  {g.treatment:10} {g.key:42} n={g.count:<3} gross={g.gross:>11.2f} withholding={g.withholding:>9.2f} '
              f'expenses={g.expenses:>9.2f} unconverted={g.pending}')
        w('')
        w('Unconverted (pending) rows, excluded above:')
        for d, org, t, cur, amt in r.pending_rows:
            w(f'  {d} {t:10} {cur} {amt}' + (f'  {org}' if opts['organisations'] else ''))
        if not r.pending_rows:
            w('  none')
        w('')
        w('Named readings (monthly = annual / 12); [=] marks a match with a letter figure:')
        for desc, total in r.hypotheses:
            monthly = (total / 12).quantize(sl.CENT)
            hits = [label for label, m, _a in sl.targets() if sl._month_matches(total, m)]
            w(f'  {desc:70} annual {total:>11.2f} monthly {monthly:>9}' + (f'  [=] {"; ".join(hits)}' if hits else ''))
        w('')
        w('Every combination of groups (gross, or gross net of withholding) that reproduces a letter figure:')
        for label, mode, desc, total in r.searches:
            w(f'  {label}: {mode}: {desc}  (annual {total:.2f})')
        if not r.searches:
            w('  none')
        if opts['organisations']:
            w('')
            w('Per organisation (treatment, organisation, category, n, gross, withholding, expenses):')
            for row in r.organisations:
                if row[0] in ('capital', 'rental'):
                    w('  ' + ' | '.join(f'{x:.2f}' if hasattr(x, 'quantize') else str(x) for x in row))
