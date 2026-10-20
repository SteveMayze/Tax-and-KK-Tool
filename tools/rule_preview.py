#!/usr/bin/env python
"""Preview the statement rules over a folder of joint-account statements. Usage: tools/rule_preview.py <folder> [--recursive]

Prints, per active rule (by id and kind only), how many credit lines it matches and in which statements, and how many
lines are matched by more than one rule (conflicts are never staged). No amounts, names, patterns or labels are printed.
Reads the database, changes nothing. Needs DJANGO_JOINT_RENTAL_ACCOUNT. See docs/imports.md."""
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
    from django.conf import settings
    from core.services import rule_preview
    if not Path(args.folder).is_dir():
        parser.error('not a folder')
    if not settings.JOINT_RENTAL_ACCOUNT:
        parser.error('DJANGO_JOINT_RENTAL_ACCOUNT is not set')
    print(rule_preview.render(rule_preview.preview(args.folder, args.recursive)), file=out or sys.stdout)


if __name__ == '__main__':
    main()
