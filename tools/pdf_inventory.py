#!/usr/bin/env python
"""Inventory of a folder of PDF statements (Phase 15). Usage: tools/pdf_inventory.py <folder> [--recursive]

Prints one line per PDF: masked file name, reader id or "unrecognised", statement period, number of income rows, number
of notices, outcome, and flags (same content as another file, period gap or overlap, file name period differs from the
period read). No amounts and no names from the documents are printed. The database is not touched. See docs/imports.md."""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main(argv=None, out=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('folder')
    parser.add_argument('--recursive', action='store_true', help='include subfolders')
    args = parser.parse_args(argv)
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from core.services import pdf_inventory
    if not Path(args.folder).is_dir():
        parser.error('not a folder')
    print(pdf_inventory.render(pdf_inventory.inventory(args.folder, args.recursive)), file=out or sys.stdout)


if __name__ == '__main__':
    main()
