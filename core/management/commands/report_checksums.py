"""One SHA-256 per CSV report and year, so "the reports are identical before and after" can be proven without showing
a single value (ADR 0035). Read only. Every report of the reports page is rendered exactly as its CSV download
(English, default parameters, no filter), with the generation time fixed, because that line differs on every run.
"""
import datetime
import hashlib

from django.core.management.base import BaseCommand
from django.utils import translation

from core.services import report_csv
from core.services.policies.sbk import PolicyUnavailable
from core.services.reports import REPORTS, available_years

FIXED_TIME = datetime.datetime(2000, 1, 1, tzinfo=datetime.timezone.utc)


def checksums():
    """[(report key, year or 'all', sha256 or a reason)] for every report and every reporting year."""
    years = sorted(available_years())
    out = []
    with translation.override('en'):
        for key in sorted(REPORTS):
            spec = REPORTS[key]
            for year in ([] if spec.needs_year else [None]) + years:
                try:
                    report = spec.build(year)
                except PolicyUnavailable:
                    out.append((key, year or 'all', 'unavailable'))
                    continue
                report.generated_at = FIXED_TIME
                text = report_csv.render(report)
                out.append((key, year or 'all', hashlib.sha256(text.encode('utf-8')).hexdigest()))
    return out


class Command(BaseCommand):
    help = 'Print "report year sha256" for every CSV report and reporting year (no values). Compare two runs with diff.'

    def handle(self, *args, **opts):
        rows = checksums()
        for key, year, digest in rows:
            self.stdout.write(f'{key} {year} {digest}')
        total = hashlib.sha256('\n'.join(f'{k} {y} {d}' for k, y, d in rows).encode()).hexdigest()
        self.stdout.write(f'TOTAL reports={len(rows)} sha256={total}')
