#!/usr/bin/env python
"""Local report (Phase 24): how would the PDF rows of the Australian statements (rental agent, MECU, Ord Minnett) relate to the
payments already in the database? READ ONLY: nothing is changed or deleted. The output has counts only (no amounts, no names, no
account numbers) and is also written to local/exports/collision_report.txt (git-ignored).

Usage: .venv/bin/python tools/collision_report.py [--samples local/samples]

For each folder it reports, per kind of match:
* exact collision: same payment date, organisation, currency and gross (the import's own duplicate rule: the review would flag it);
* near collision: same currency and gross within 3 days under ANOTHER organisation (for example the rental booked under the
  tenant instead of the agent), or the same date and organisation with another gross;
* no counterpart: a staged row with nothing similar in the database (for example term-deposit interest missing from hand-made CSV rows);
and, the other way round, database payments of the same organisation (and category) that no staged row matches exactly.
"""
import argparse
import datetime
import os
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FOLDERS = (('Hodges (rental)', 'Hodges', 'Rental'), ('MECU (interest)', 'MECU', 'Interest'), ('Ord Minnett (interest)', 'Ords', 'Interest'))


def main(argv=None, out=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--samples', default='local/samples')
    args = parser.parse_args(argv)
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from django.conf import settings
    from django.db.models import Count
    from core.models import Payment
    from core.services import statement_readers

    lines = []
    if not settings.RENTAL_ORGANISATION:       # the rental organisation is a setting; for this report use the Rental organisation with most payments
        top = (Payment.objects.filter(category__name='Rental').values('organisation__name').annotate(n=Count('id')).order_by('-n').first())
        settings.RENTAL_ORGANISATION = top['organisation__name'] if top else ''
        lines.append('(setting DJANGO_RENTAL_ORGANISATION is not set: the Rental organisation with the most payments was used)')
    three_days = datetime.timedelta(days=3)
    for label, folder, category in FOLDERS:
        path = Path(args.samples) / folder
        if not path.is_dir():
            lines.append(f'{label}: folder not present')
            continue
        results = []
        for f in sorted(path.glob('*.pdf')):
            outcome = statement_readers.read_statement(f.read_bytes())
            if outcome.result is not None:
                results.append((f.name, outcome.reader_id, outcome.result))
        by_reader = {}
        for name, reader_id, result in results:
            by_reader.setdefault(reader_id, []).append((name, result))
        for reader_id, items in by_reader.items():
            settle = statement_readers.reader_by_id(reader_id).settle
            if settle:
                settle(items)
        rows = [r.data for _n, _i, res in results for r in res.rows]
        organisations = {r['organisation'].lower() for r in rows}
        existing = list(Payment.objects.filter(organisation__name__in=[r['organisation'] for r in rows]).select_related('organisation', 'category'))
        existing_all = list(Payment.objects.filter(category__name=category, currency='AUD').select_related('organisation'))

        def key(d):
            return (datetime.date.fromisoformat(d['payment_date']), d['organisation'].lower(), d['currency'], Decimal(d['gross_amount']).quantize(Decimal('0.0001')))

        exact_keys = {(p.payment_date, p.organisation.name.lower(), p.currency, p.gross_amount.quantize(Decimal('0.0001'))): p for p in existing}
        exact = near_org = near_gross = none = 0
        matched = set()
        for d in rows:
            k = key(d)
            if k in exact_keys:
                exact += 1
                matched.add(exact_keys[k].pk)
                continue
            gross, date = k[3], k[0]
            if any(p.currency == k[2] and abs(p.payment_date - date) <= three_days and p.gross_amount.quantize(Decimal('0.0001')) == gross and p.organisation.name.lower() != k[1]
                   for p in existing_all):
                near_org += 1
            elif any(p.payment_date == date and p.organisation.name.lower() == k[1] and p.currency == k[2] for p in existing):
                near_gross += 1
            else:
                none += 1
        unmatched_existing = [p for p in existing if p.pk not in matched]
        lines.append(f'{label}: {len(results)} statements read, {len(rows)} staged rows; organisations in staged rows: {len(organisations)}')
        lines.append(f'  exact collisions (the review would flag them as duplicates): {exact}')
        lines.append(f'  near collisions, same gross within 3 days under another organisation: {near_org}')
        lines.append(f'  near collisions, same date and organisation but another gross: {near_gross}')
        lines.append(f'  staged rows with no counterpart in the database: {none}')
        lines.append(f'  database payments of the same organisation with no exact staged counterpart: {len(unmatched_existing)} of {len(existing)}')
        if unmatched_existing:
            close = sum(1 for p in unmatched_existing if any(abs(datetime.date.fromisoformat(d['payment_date']) - p.payment_date) <= three_days
                                                              and d['organisation'].lower() == p.organisation.name.lower() for d in rows))
            lines.append(f'    of those, with a staged row of the same organisation within 3 days (another gross or date): {close}')
    text = '\n'.join(lines)
    print(text, file=out or sys.stdout)
    target = Path('local/exports')
    if target.is_dir():
        (target / 'collision_report.txt').write_text(text + '\n')


if __name__ == '__main__':
    main()
