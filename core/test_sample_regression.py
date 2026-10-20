"""Phase 24: the Phase 14 samples (Australian dividend advices, Revolut fund statements) must give exactly the rows they gave
before the later readers existed. Reads the owner's real statements when they are present (never committed); prints and asserts
no amounts. The older local tests of core/test_pdf_imports.py look in a folder that no longer exists, so this one covers it."""
from pathlib import Path
from unittest import skipUnless

from django.test import SimpleTestCase

from core.services import dividend_statements as ds
from core.services import interest_statements as it
from core.services import pdf_text
from core.services import statement_readers as sr
from core.services.imports import COLUMNS

SAMPLES = Path(__file__).resolve().parent.parent / 'local' / 'samples'
FOLDERS = [SAMPLES / 'Securities', SAMPLES / 'Revolut']


@skipUnless(any(f.is_dir() for f in FOLDERS), 'owner-supplied Phase 14 samples are not present (they are never committed)')
class Phase14SamplesStayIdenticalTests(SimpleTestCase):
    def test_the_registry_gives_the_same_row_and_provenance_as_the_phase_14_readers_or_refuses_the_same_files(self):
        compared = refused = 0
        for folder in FOLDERS:
            for path in sorted(folder.rglob('*.pdf')):
                raw = path.read_bytes()
                try:
                    pages = pdf_text.extract_pages(raw)
                    statement = it.parse(pages) if it.recognises(pages) else ds.parse(pages)
                    old = (statement.row_data(COLUMNS), {k: tuple(v) for k, v in statement.provenance_items().items()})
                except Exception:
                    old = None
                outcome = sr.read_statement(raw)
                new = None if outcome.result is None else (outcome.result.rows[0].data,
                                                           {k: tuple(v) for k, v in outcome.result.rows[0].provenance.items()})
                self.assertEqual(old, new, path.name[:12])
                compared += 1
                refused += old is None
        print(f'\nPhase 14 samples: {compared} files identical through the registry ({refused} refused as before)')
        self.assertTrue(compared)
