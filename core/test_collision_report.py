"""Phase 27: the joint-account section of tools/collision_report.py. Synthetic data only; the output must hold counts only."""
import datetime
import io
import tempfile
import importlib.util
from decimal import Decimal as D
from pathlib import Path

from django.test import TestCase, override_settings

from core.models import IncomeCategory, Organisation, Payment, ReportingMonth
from core.services import pdf_imports  # noqa: F401  (loads the readers)
from .test_pdf_support import make_pdf
from .test_rvb_joint import JOINT, rule
from .test_rvb_joint_rows import CATEGORY, rent, stmt


def load_tool():
    path = Path(__file__).resolve().parent.parent / 'tools' / 'collision_report.py'
    spec = importlib.util.spec_from_file_location('collision_report_tool', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def payment(org, category, date, gross):
    month = ReportingMonth.for_date(date)
    return Payment.objects.create(month=month, organisation=org, category=category, payment_date=date, currency='EUR',
                                  gross_amount=D(gross), frequency='monthly')


@override_settings(JOINT_RENTAL_ACCOUNT=JOINT, JOINT_RENTAL_CATEGORY=CATEGORY, RENTAL_ORGANISATION='Agent')
class JointCollisionTests(TestCase):
    def report(self, *statements):
        with tempfile.TemporaryDirectory() as samples:
            folder = Path(samples, 'RVB-joint')
            folder.mkdir()
            for n, pages in enumerate(statements):
                Path(folder, f'{n}.pdf').write_bytes(make_pdf(pages))
            out = io.StringIO()
            load_tool().main(['--samples', samples, '--no-file'], out=out)
        return out.getvalue()

    def test_exact_near_and_missing_rows_are_counted_without_names_or_amounts(self):
        cat = IncomeCategory.objects.create(name=CATEGORY)
        old = IncomeCategory.objects.get(name='Rental')
        rule('tenant', 'tenant_rent', 'example tenant')
        tenant = Organisation.objects.create(name='EXAMPLE TENANT')
        other = Organisation.objects.create(name='EXAMPLE OTHER NAME')
        payment(tenant, old, datetime.date(2025, 3, 3), '800.00')               # exact collision
        payment(tenant, old, datetime.date(2025, 3, 10), '555.00')              # same org, no staged counterpart
        payment(other, old, datetime.date(2025, 3, 27), '810.00')               # same gross within 3 days under another organisation
        payment(tenant, old, datetime.date(2025, 3, 20), '700.00')              # same date and org, another gross than the staged 750.00
        text = self.report(stmt(rent('03', '03', '800.00'), rent('18', '03', '810.00'), rent('20', '03', '750.00'), rent('28', '03', '810.00'),
                                rent('29', '03', '1.00')))
        self.assertIn('5 staged rows', text)
        self.assertIn('exact collisions (the review would flag them as duplicates): 1', text)
        self.assertIn('another organisation (EUR rental payments): 1', text)
        self.assertIn('same date and organisation but another gross: 1', text)
        self.assertIn('no counterpart in the database: 2', text)
        self.assertIn('no exact staged counterpart: 2 of 3', text)
        for forbidden in ('EXAMPLE', '800', '810', JOINT, CATEGORY):
            self.assertNotIn(forbidden, text)
        self.assertEqual(Payment.objects.count(), 4)                             # read only
        del cat

    def test_without_rules_nothing_is_staged_and_the_report_says_so(self):
        text = self.report(stmt(rent('03', '03', '800.00')))
        self.assertIn('0 staged rows', text)
