"""SBK letter of 2026-11-06: arithmetic of the letter and the read-only reconciliation (synthetic data only)."""
import datetime
from decimal import Decimal as D
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from core.models import IncomeCategory
from core.services import sbk_letter as sl
from core.services.conversion import convert_payment

from .test_helpers import make_payment


class LetterArithmeticTests(TestCase):
    def test_components_add_up(self):
        for p in sl.LETTER['periods']:
            self.assertEqual(p['capital'] + p['other'] + p['rental'], p['base'])
            self.assertEqual(p['kv'] + p['zusatz'] + p['pv'], p['total'])

    def test_back_payment_reproduces_the_letter(self):
        self.assertEqual(sl.back_payment(), D('6295.66'))
        self.assertEqual(sl.back_payment(), sl.LETTER['back_payment'])

    def test_document_holds_the_same_figures_and_no_identifiers(self):
        text = (Path(__file__).resolve().parent.parent / 'docs' / 'sbk-letters' / '2026-11-06.md').read_text()
        for p in sl.LETTER['periods']:
            for key in ('capital', 'other', 'rental', 'base', 'kv', 'zusatz', 'pv', 'total'):
                self.assertIn(f'{p[key]:,.2f}', text)
        self.assertIn('6,295.66', text)
        self.assertNotIn('IBAN DE', text)


class ReconciliationTests(TestCase):
    def setUp(self):
        IncomeCategory.objects.filter(name='Rental').update(sbk_treatment='rental')
        IncomeCategory.objects.filter(name='Interest').update(sbk_treatment='capital')

    def add(self, gross, category, date=datetime.date(2025, 5, 10), **kw):
        p = make_payment(gross=gross, category=category, date=date, **kw)
        p.save()
        convert_payment(p)
        return p

    def test_groups_and_a_cent_exact_match(self):
        # 1950.68 x 12 = 23,408.16 ; 23,408.14 / 12 rounds to 1950.68 (the letter shows the monthly figure rounded)
        for i in range(12):
            self.add('1950.6783', 'Rental', datetime.date(2025, i + 1, 5), org='Joint')
        r = sl.build(2025)
        self.assertEqual(r.treatments['rental']['expenses'], D(0))
        self.assertTrue(any('Rental' in s[0] and s[1] == 'gross' for s in r.searches))
        self.assertTrue(sl._month_matches(D('23408.14'), D('1950.68')))
        self.assertFalse(sl._month_matches(D('23408.14'), D('1950.69')))

    def test_pending_rows_are_listed_not_counted(self):
        p = make_payment(gross='100', currency='AUD', category='Interest', date=datetime.date(2025, 3, 1))
        p.save()
        r = sl.build(2025)
        self.assertEqual(len(r.pending_rows), 1)
        self.assertEqual(r.treatments['capital']['gross'], D(0))
        self.assertEqual(r.treatments['capital']['pending'], 1)

    def test_command_runs_and_changes_nothing(self):
        self.add('100', 'Interest')
        out = StringIO()
        call_command('sbk_letter_reconciliation', year=2025, stdout=out)
        self.assertIn('6295.66', out.getvalue())
