"""Phase 38 (ADR 0035): PostgreSQL support. These tests run on BOTH engines: `make test` (SQLite) and `make test-pg`
(a throw-away PostgreSQL 17). Tests that need one engine say so and are skipped on the other. All data is invented.

The golden hashes below were computed once and must be the SAME on SQLite and PostgreSQL: that equality is the proof
that the fingerprint and the reports do not depend on the engine. If a deliberate change to a model or a report
changes them, recompute them on SQLite, then confirm the PostgreSQL run gives the same values.
"""
import datetime
import io
import json
import os
import subprocess
import sys
import tempfile
from decimal import Decimal as D
from pathlib import Path

from django.conf import settings
from django.contrib.admin.models import ADDITION, LogEntry
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.db import connection
from django.test import SimpleTestCase, TestCase, TransactionTestCase

from core import ordering
from core.models import (ConversionEvent, ExchangeRateRecord, ImportBatch, ImportRow, IncomeCategory, Organisation,
                         Payment, ReportingMonth, ReportingYear)
from core.services import fingerprint as fp
from core.services import sequences

UTC = datetime.timezone.utc
ON_PG = connection.vendor == 'postgresql'
NAMES = ['Zeta Bank', 'alpha Fonds', 'Äpfel AG', 'Bank 10', 'Bank 2', 'ändern GmbH', 'Ölwerk', 'beta Ltd', 'Émile SA']


def ts(n):
    """A fixed timestamp with microseconds (never 'now', so hashes are reproducible)."""
    return datetime.datetime(2025, 3, 1, 12, 0, 0, tzinfo=UTC) + datetime.timedelta(seconds=n, microseconds=123457 + n)


def build_dataset():
    """A synthetic data set through the ORM with explicit primary keys (sequences differ between engines and runs)
    and fixed timestamps. Decimals stay within 15 significant digits: SQLite stores decimals as REAL and Django reads
    them back with 15 digits (see the PostgreSQL-only precision test for the full field sizes)."""
    IncomeCategory.objects.all().delete()                                  # the migration's seed rows: not ours
    year = ReportingYear.objects.create(pk=901, year=2025, notes='Jahr mit Ümlauten')
    months = {m: ReportingMonth.objects.create(pk=910 + m, year=year, month=m) for m in (1, 3, 7)}
    orgs = [Organisation.objects.create(pk=920 + i, name=n, country=('DE' if i % 2 else '')) for i, n in enumerate(NAMES)]
    interest = IncomeCategory.objects.create(pk=950, name='Interest test')
    gains = IncomeCategory.objects.create(pk=951, name='Capital gains test', may_be_negative=True)
    rental = IncomeCategory.objects.create(pk=952, name='Mieteinnahmen')
    batch = ImportBatch.objects.create(
        pk=960, file_name='synthetic.pdf', sha256='0' * 64, kind=ImportBatch.Kind.PDF, status=ImportBatch.Status.COMMITTED,
        warnings=['Hinweis: ä', {'z': 1, 'a': [3, {'y': 'ü', 'b': None}]}],
        organisation_countries={'zeta bank': 'DE', 'alpha fonds': '', 'nested': {'k2': [1, 2], 'k1': {'x': True}}})
    ImportRow.objects.create(
        pk=970, batch=batch, line_number=1, data={'organisation': 'Zeta Bank', 'gross_amount': '12.5'},
        original={'b': '2', 'a': '1'}, errors=[], notes=['new organisation'],
        provenance={'payment_date': {'page': 2, 'text': 'Datum 01.03.'}, 'gross_amount': {'page': 1, 'text': 'Brutto'}})
    rate_rows = [('GBP', '1.1712345678'), ('AUD', '0.6123456789'), ('USD', '0.9234567891')]
    records = {ccy: ExchangeRateRecord.objects.create(pk=980 + i, currency=ccy, rate_date=datetime.date(2025, 3, 3),
                                                      requested_date=datetime.date(2025, 3, 2), rate=D(r), provider='manual')
               for i, (ccy, r) in enumerate(rate_rows)}
    specs = [  # (org index, category, month, day, currency, gross, net, withholding, expenses)
        (0, interest, 1, 15, 'EUR', '1234.5678', '1000.0000', '234.5678', '0'),
        (1, interest, 3, 2, 'GBP', '99.9999', '84.9999', '15.0000', '0'),
        (2, rental, 3, 2, 'AUD', '2500.0000', '2100.0000', '0', '400.0000'),
        (3, gains, 3, 2, 'USD', '-1500.2500', '-1500.2500', '0', '0'),           # a loss, in a may_be_negative category
        (4, interest, 7, 31, 'EUR', '0.0001', '0.0001', '0', '0'),
        (5, rental, 7, 1, 'GBP', '12345678.1234', '12345678.1234', '0', '0'),
        (6, gains, 1, 3, 'EUR', '-0.5000', None, '0', '0'),
        (7, interest, 3, 2, 'EUR', '10.0000', '10.0000', '0', '0'),
        (8, interest, 3, 2, 'AUD', '777.7700', '700.0000', '77.7700', '0'),
    ]
    for i, (o, cat, m, day, ccy, gross, net, wh, ex) in enumerate(specs):
        rate = D('1') if ccy == 'EUR' else records[ccy].rate
        g, n, w, e = D(gross), (D(net) if net is not None else None), D(wh), D(ex)
        q = D('0.000001')
        Payment.objects.create(
            pk=1000 + i, month=months[m], organisation=orgs[o], category=cat, payment_date=datetime.date(2025, m, day),
            currency=ccy, gross_amount=g, net_amount=n, withholding_tax=w, expenses=e, frequency='monthly',
            comment=f'Notiz {i}: Größe ä/ö/ü', conversion_status=Payment.ConversionStatus.CONVERTED,
            rate=rate, rate_date=datetime.date(2025, 3, 3), rate_source='manual',
            rate_record=None if ccy == 'EUR' else records[ccy], import_batch=batch if i == 0 else None,
            gross_eur=(g * rate).quantize(q), net_eur=None if n is None else (n * rate).quantize(q),
            withholding_tax_eur=(w * rate).quantize(q), expenses_eur=(e * rate).quantize(q))
    ConversionEvent.objects.create(pk=990, payment_id=1001, kind=ConversionEvent.Kind.INITIAL, rate_record=records['GBP'],
                                   rate=D('1.1712345678'), rate_date=datetime.date(2025, 3, 3), gross_eur=D('117.122168'),
                                   previous_rate=D('1.1'), previous_gross_eur=D('109.99989'))
    user = User.objects.create(pk=5001, username='synthetic-owner', password='pbkdf2_sha256$1$invented$invented=',
                               is_superuser=True, is_staff=True, date_joined=ts(1))
    LogEntry.objects.create(pk=6001, user=user, content_type=ContentType.objects.get_for_model(Organisation),
                            object_id='920', object_repr='Zeta Bank', action_flag=ADDITION, change_message='[]',
                            action_time=ts(2))
    # Fixed timestamps for every auto_now / auto_now_add field (update() bypasses them).
    from django.apps import apps
    from django.db.models import DateTimeField
    n = 10
    for model in sorted(apps.get_models(), key=lambda m: m._meta.label_lower):
        auto = [f.name for f in model._meta.concrete_fields if isinstance(f, DateTimeField) and (f.auto_now or f.auto_now_add)]
        if not auto:
            continue
        for pk in model._base_manager.order_by('pk').values_list('pk', flat=True):     # pk order: the same on both engines
            n += 1
            model._base_manager.filter(pk=pk).update(**{f: ts(n) for f in auto})
    ImportBatch.objects.filter(pk=960).update(committed_at=ts(99))


# Golden values: identical on SQLite and PostgreSQL (see the module docstring).
GOLDEN_CONTENT = 'f2141189c07c45fdbf0fd3e7166beb71dd3e530c89c1684cbff51b13dbc68efd'
GOLDEN_REPORTS = '93eaeb4ab9c16f0c23e6d100e96c0f0b4eb712cdea7cdaa69cd89e93633d5fe4'


class OrderingTests(TestCase):
    def test_names_sort_by_code_point_on_both_engines(self):
        for i, name in enumerate(NAMES):
            Organisation.objects.create(name=name)
        shown = [o.name for o in ordering.by_text(Organisation.objects.all())]
        self.assertEqual(shown, sorted(NAMES))                      # code-point order: what SQLite gave before
        self.assertEqual(shown[:3], ['Bank 10', 'Bank 2', 'Zeta Bank'])
        self.assertEqual(shown[-1], 'ändern GmbH')

    def test_the_organisations_page_and_the_datalist_use_it(self):
        from core.templatetags.lookups import active_names
        for name in NAMES:
            Organisation.objects.create(name=name)
        self.assertEqual(active_names('organisation'), sorted(NAMES))
        user = User.objects.create_user('o', password='pw-for-test-only')
        self.client.force_login(user)
        page = self.client.get('/organisations/').content.decode()
        positions = [page.index(n.replace('&', '&amp;')) for n in sorted(NAMES)]
        self.assertEqual(positions, sorted(positions))

    def test_provenance_is_shown_in_the_fixed_column_order_not_the_stored_key_order(self):
        batch = ImportBatch.objects.create(file_name='x.pdf')
        row = ImportRow.objects.create(batch=batch, line_number=1, data={}, original={},
                                       provenance={'withholding_tax': {}, 'payment_date': {}, 'zzz_extra': {}, 'gross_amount': {}})
        row.refresh_from_db()
        self.assertEqual([k for k, _v in row.provenance_items], ['payment_date', 'gross_amount', 'withholding_tax', 'zzz_extra'])


class NormalFormTests(SimpleTestCase):
    def test_values_are_written_engine_independently(self):
        self.assertEqual(fp.normal(D('100.0000')), 'd100')
        self.assertEqual(fp.normal(D('-0.0000')), 'd0')
        self.assertEqual(fp.normal(D('1.1712345670')), 'd1.171234567')
        self.assertEqual(fp.normal(datetime.datetime(2025, 1, 1, 13, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=1)))),
                         't2025-01-01T12:00:00.000000')
        self.assertEqual(fp.normal({'b': 1, 'a': [{'d': 2, 'c': 'ü'}]}), 'j{"a":[{"c":"ü","d":2}],"b":1}')
        self.assertEqual(fp.normal({'a': 1, 'b': 2}), fp.normal({'b': 2, 'a': 1}))


class FingerprintGoldenTests(TestCase):
    def test_the_same_data_gives_the_same_hash_on_both_engines(self):
        build_dataset()
        info = fp.fingerprint()
        counts = {label: n for label, n, _h in info['models'] if n}
        self.assertEqual(counts['core.payment'], 9)
        self.assertEqual(counts['admin.logentry'], 1)
        self.assertEqual(info['content_sha256'], GOLDEN_CONTENT, 'engine-dependent fingerprint (see the module docstring)')

    def test_report_checksums_are_the_same_on_both_engines(self):
        from core.management.commands.report_checksums import checksums
        build_dataset()
        rows = checksums()
        self.assertGreater(len(rows), 9)
        joined = '\n'.join(f'{k} {y} {d}' for k, y, d in rows)
        import hashlib
        self.assertEqual(hashlib.sha256(joined.encode()).hexdigest(), GOLDEN_REPORTS, joined)

    def test_any_change_changes_the_hash(self):
        build_dataset()
        before = fp.fingerprint()['content_sha256']
        Payment.objects.filter(pk=1000).update(comment='changed')
        self.assertNotEqual(before, fp.fingerprint()['content_sha256'])

    def test_command_prints_counts_and_hashes_only(self):
        build_dataset()
        out = io.StringIO()
        call_command('data_fingerprint', '--per-model', stdout=out)
        text = out.getvalue()
        self.assertTrue(text.startswith('FINGERPRINT rows='))
        for value in ('Zeta', '1234.5678', 'Notiz', 'synthetic-owner'):
            self.assertNotIn(value, text)


class ExactExportRoundTripTests(TransactionTestCase):
    """dump_exact -> empty database -> load_exact gives the same fingerprint, byte for byte (on each engine)."""

    def test_round_trip(self):
        build_dataset()
        if ON_PG:   # the full field sizes: exact only where the engine stores decimals exactly
            Payment.objects.filter(pk=1000).update(gross_amount=D('999999999999.9999'), net_amount=D('-999999999999.9999'),
                                                   rate=D('9999999999.9999999999'), gross_eur=D('99999999999999.999999'))
        before = fp.fingerprint()
        with tempfile.TemporaryDirectory() as tmp:
            dump = Path(tmp) / 'dump.json'
            call_command('dump_exact', output=str(dump))
            self.assertEqual(dump.stat().st_mode & 0o777, 0o600)
            text = dump.read_text()
            import re
            self.assertRegex(text, r'"created_at": "2025-03-01T12:\d\d:\d\d\.\d{6}Z"')   # microseconds kept (dumpdata cuts them)
            call_command('flush', interactive=False, verbosity=0)
            out = io.StringIO()
            call_command('load_exact', str(dump), stdout=out)
        self.assertIn('behind=0', out.getvalue())
        after = fp.fingerprint()
        self.assertEqual(before['models'], after['models'])
        self.assertEqual(before['content_sha256'], after['content_sha256'])
        new = Payment.objects.create(month_id=911, organisation_id=920, category_id=950, payment_date=datetime.date(2025, 1, 2),
                                     currency='EUR', gross_amount=D('1'), frequency='monthly')
        self.assertGreater(new.pk, 1008)                       # the sequence is above the loaded ids
        if ON_PG:
            p = Payment.objects.get(pk=1000)
            self.assertEqual((str(p.gross_amount), str(p.rate), str(p.gross_eur)),
                             ('999999999999.9999', '9999999999.9999999999', '99999999999999.999999'))

    def test_load_refuses_a_database_with_data(self):
        build_dataset()
        with tempfile.TemporaryDirectory() as tmp:
            dump = Path(tmp) / 'dump.json'
            call_command('dump_exact', output=str(dump))
            from django.core.management.base import CommandError
            with self.assertRaisesMessage(CommandError, 'not empty'):
                call_command('load_exact', str(dump))
        self.assertEqual(Payment.objects.count(), 9)


class CheckCommandTests(TestCase):
    def run_cmd(self, name):
        out = io.StringIO()
        call_command(name, stdout=out)
        return out.getvalue()

    def test_decimal_check_counts_only(self):
        build_dataset()
        text = self.run_cmd('decimal_check')
        self.assertIn('roundtrip_changed=0 sig15_or_more=0 does_not_fit=0', text)
        self.assertNotIn('1234.5678', text)

    def test_stored_files_check_counts_states(self):
        with tempfile.TemporaryDirectory() as tmp, self.settings(UPLOAD_DIR=tmp):
            import hashlib
            (Path(tmp) / 'imports').mkdir()
            good = Path(tmp) / 'imports' / '1-a.pdf'
            good.write_bytes(b'%PDF-synthetic')
            ImportBatch.objects.create(stored_path='imports/1-a.pdf', sha256=hashlib.sha256(b'%PDF-synthetic').hexdigest())
            ImportBatch.objects.create(stored_path='imports/1-a.pdf', sha256='f' * 64)
            ImportBatch.objects.create(stored_path='imports/gone.pdf', sha256='0' * 64)
            ImportBatch.objects.create(stored_path='../outside.pdf')
            ImportBatch.objects.create()
            text = self.run_cmd('stored_files_check')
        self.assertIn('ok=1 none=1 missing=1 outside=1 hash_mismatch=1 zip_unreadable=0', text)

    def test_sequences_check(self):
        text = self.run_cmd('pg_sequences')
        self.assertIn('behind=0', text)
        if ON_PG:
            self.assertGreater(sequences.check()['sequences'], 10)


def _settings_probe(env):
    """Load the settings in a subprocess, as the container does, and return the database part (never the password)."""
    base = {k: v for k, v in os.environ.items() if not k.startswith('DJANGO_')}
    base.update(env)
    code = ("import json, django; django.setup(); from django.conf import settings as s; d = s.DATABASES['default']; "
            "print(json.dumps({'engine': d['ENGINE'], 'host': d.get('HOST'), 'port': d.get('PORT'), 'name': str(d['NAME']), "
            "'user': d.get('USER'), 'max_age': d.get('CONN_MAX_AGE'), 'health': d.get('CONN_HEALTH_CHECKS'), "
            "'options': d.get('OPTIONS'), 'pg': s.USING_POSTGRES}))")
    return subprocess.run([sys.executable, '-c', code], cwd=settings.BASE_DIR, env=base, capture_output=True, text=True)


PROD = {'DJANGO_SETTINGS_MODULE': 'config.settings_prod',
        'DJANGO_SECRET_KEY': 'Zq3x9LmT7vB2nR8wYc5Hd1KfPaJe6GsUo4NiXtV0bMyQ-AlEzWrCgDhSjFkO_9p',
        'DJANGO_ALLOWED_HOSTS': 'app.example.test', 'DJANGO_CSRF_TRUSTED_ORIGINS': 'https://app.example.test',
        'DJANGO_UPLOAD_DIR': '/uploads', 'DJANGO_BACKUP_DIR': '/backups'}
PG = {'DJANGO_DB_HOST': 'postgres', 'DJANGO_DB_PORT': '5432', 'DJANGO_DB_NAME': 'taxtool', 'DJANGO_DB_USER': 'taxtool',
      'DJANGO_DB_PASSWORD': 'invented-test-password-value'}


class SettingsContractTests(SimpleTestCase):
    def test_sqlite_unchanged_without_a_host(self):
        r = _settings_probe({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_DB_PATH': '/tmp/x/db.sqlite3'})
        self.assertEqual(r.returncode, 0, r.stderr[-400:])
        d = json.loads(r.stdout)
        self.assertEqual((d['engine'], d['name'], d['pg']), ('django.db.backends.sqlite3', '/tmp/x/db.sqlite3', False))

    def test_postgres_from_the_five_variables(self):
        r = _settings_probe({'DJANGO_SETTINGS_MODULE': 'config.settings', **PG, 'DJANGO_DB_PORT': ''})
        d = json.loads(r.stdout)
        self.assertEqual((d['engine'], d['host'], d['port'], d['name'], d['user']),
                         ('django.db.backends.postgresql', 'postgres', '5432', 'taxtool', 'taxtool'))
        self.assertEqual((d['max_age'], d['health'], d['options']), (60, True, {'connect_timeout': 5}))
        self.assertTrue(d['pg'])

    def test_production_requires_all_five_and_no_sqlite_path(self):
        r = _settings_probe({**PROD, **PG})
        self.assertEqual(r.returncode, 0, r.stderr[-400:])
        for name in PG:
            env = {**PROD, **PG}
            env.pop(name)
            r = _settings_probe(env)
            if name == 'DJANGO_DB_HOST':
                self.assertIn('DJANGO_DB_PATH must be set', r.stderr)         # no host: SQLite, which needs its path
            else:
                self.assertNotEqual(r.returncode, 0, name)
                self.assertIn(f'{name} must be set in production', r.stderr)
            self.assertNotIn('invented-test-password-value', r.stdout + r.stderr)

    def test_password_never_in_output(self):
        r = _settings_probe({'DJANGO_SETTINGS_MODULE': 'config.settings', **PG})
        self.assertNotIn('invented-test-password-value', r.stdout + r.stderr)


class PostgresBackupTests(TransactionTestCase):
    """Only with PostgreSQL and its client tools (make test-pg)."""

    def setUp(self):
        if not ON_PG:
            self.skipTest('PostgreSQL only (make test-pg)')

    def test_archive_holds_a_verified_dump_uploads_and_orm_counts(self):
        import tarfile
        from core.services import backup
        build_dataset()
        with tempfile.TemporaryDirectory() as tmp:
            up = Path(tmp) / 'up' / 'imports'
            up.mkdir(parents=True)
            (up / '960-x.pdf').write_bytes(b'%PDF-synthetic')
            path = backup.create_pg_backup(settings.DATABASES['default'], Path(tmp) / 'up', Path(tmp) / 'bk',
                                           label='test', version='t')
            with tarfile.open(path) as tar:
                names = sorted(m.name for m in tar.getmembers())
            self.assertEqual(names, ['MANIFEST.json', 'db.dump', 'uploads/imports/960-x.pdf'])
            with tempfile.TemporaryDirectory() as w:
                manifest, _ = backup.verify_archive(path, w)
            self.assertEqual(manifest['engine'], 'postgresql')
            self.assertEqual(manifest['row_counts']['core_payment'], 9)
            out = io.StringIO()
            call_command('restore_backup', str(path), stdout=out)
            self.assertIn('VERIFIED pg_restore=ok', out.getvalue())

    def test_restore_refuses_the_live_database_and_a_swap_without_confirmation(self):
        from django.core.management.base import CommandError
        from core.services import backup
        with self.assertRaisesMessage(backup.BackupError, 'new database'):
            backup.restore_pg_archive('/nonexistent.tar.gz', settings.DATABASES['default'],
                                      settings.DATABASES['default']['NAME'], '/tmp/x')
        with self.assertRaisesMessage(CommandError, 'SWAP'):
            call_command('restore_backup', '/nonexistent.tar.gz', new_db='taxtool_new', target_uploads='/tmp/x', swap=True)


class SqliteArchiveStillReadableTests(SimpleTestCase):
    """Archives from before PostgreSQL carry no `engine` and stay readable: they verify, and `data_fingerprint --archive`
    fingerprints them through the current models, equal to the live data they came from. Run in separate processes
    with a real SQLite file, as on the server (works under make test and make test-pg alike)."""

    def manage(self, tmp, *args, code=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith('DJANGO_')}
        env.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_DB_PATH': f'{tmp}/db.sqlite3',
                    'DJANGO_UPLOAD_DIR': f'{tmp}/up', 'DJANGO_BACKUP_DIR': f'{tmp}/bk'})
        cmd = [sys.executable, 'manage.py', *args] if code is None else [sys.executable, 'manage.py', 'shell', '-c', code]
        r = subprocess.run(cmd, cwd=settings.BASE_DIR, env=env, capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        return r.stdout

    def test_old_archive_verifies_and_fingerprints_like_the_live_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'up' / 'imports').mkdir(parents=True)
            (Path(tmp) / 'up' / 'imports' / '960-x.pdf').write_bytes(b'%PDF-synthetic')
            self.manage(tmp, 'migrate', '--noinput', '-v', '0')
            self.manage(tmp, code='from core.test_postgres import build_dataset; build_dataset()')
            name = self.manage(tmp, 'backup_db').split()[-1]
            verified = self.manage(tmp, 'restore_backup', name)
            self.assertIn('engine=sqlite', verified)
            import tarfile
            with tarfile.open(Path(tmp) / 'bk' / name) as tar:
                manifest = json.load(tar.extractfile('MANIFEST.json'))
            self.assertNotIn('engine', manifest)                     # the SQLite archive format is unchanged
            from_archive = self.manage(tmp, 'data_fingerprint', '--archive', name).splitlines()
            live = self.manage(tmp, 'data_fingerprint').splitlines()
            self.assertEqual(from_archive, live)
            self.assertIn(f'content={GOLDEN_CONTENT} ', live[0] + ' ')   # the same golden value as in this process
            raw = self.manage(tmp, 'data_fingerprint', '--raw-sqlite').splitlines()
            self.assertTrue(raw[1].startswith('TABLES '))             # the Phase 37 format is still available
