#!/usr/bin/env python
"""Local report (Phase 32): the stored payments of one broker in one year, per organisation and category, in the original
currency, for comparing with a tax form such as the Form 1042-S. READ ONLY: nothing is changed; it reads the database the
settings point to and prints no file contents.

Usage: .venv/bin/python tools/broker_summary.py --year 2025 --prefix Fidelity
       .venv/bin/python tools/broker_summary.py --year 2025 --prefix "E*Trade"

`--prefix` matches the start of the organisation name (case-insensitive). Per organisation and category it prints the count and
the gross, withholding tax and net sums of each currency; amounts are never added across currencies.
"""
import argparse
import os
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def summary(year, prefix):
    """[(organisation, category, currency, count, gross, withholding, net)] for payments of the year whose organisation starts with prefix."""
    from core.models import Payment
    rows = {}
    qs = (Payment.objects.filter(month__year__year=year, organisation__name__istartswith=prefix)
          .select_related('organisation', 'category').order_by('organisation__name', 'category__name', 'currency'))
    for p in qs:
        key = (p.organisation.name, p.category.name, p.currency)
        count, gross, wh, net = rows.get(key, (0, Decimal(0), Decimal(0), Decimal(0)))
        rows[key] = (count + 1, gross + p.gross_amount, wh + p.withholding_tax, net + (p.net_amount if p.net_amount is not None else p.gross_amount - p.withholding_tax))
    return [(*k, *v) for k, v in rows.items()]


def main(argv=None, out=None):
    out = out or sys.stdout
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--year', type=int, required=True)
    parser.add_argument('--prefix', required=True)
    args = parser.parse_args(argv)
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    rows = summary(args.year, args.prefix)
    print(f'Payments of {args.year} whose organisation starts with "{args.prefix}" (original currency, never added across currencies):', file=out)
    print(f'{"organisation":40} {"category":12} {"ccy":3} {"n":>3} {"gross":>12} {"withholding":>12} {"net":>12}', file=out)
    for org, cat, ccy, n, gross, wh, net in rows:
        print(f'{org[:40]:40} {cat[:12]:12} {ccy:3} {n:>3} {gross:>12,.2f} {wh:>12,.2f} {net:>12,.2f}', file=out)
    if not rows:
        print('(no payments)', file=out)


if __name__ == '__main__':
    main()
