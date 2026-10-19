"""CSV import: parse, validate, flag duplicates, propose conversions, then commit atomically.

Nothing is written to Payment until commit_batch(). The file format is documented in docs/imports.md.
Cell contents and amounts are never logged.
"""
import csv
import datetime
import hashlib
import io
import os
import re
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext

from core.currencies import BASE_CURRENCY
from core.models import (
    ImportBatch, ImportRow, IncomeCategory, Organisation, Payment, ReportingMonth, SourceDocument)

from . import lookups
from .conversion import ConversionError, convert_payment, quote_notes, stored_quote
from .i18n import number
from .money import MoneyError, normalise_currency, to_decimal
from .rates import RateError, RateProvider, RateQuote

REQUIRED = ['payment_date', 'organisation', 'category', 'currency', 'gross_amount', 'frequency']
OPTIONAL = ['net_amount', 'withholding_tax', 'expenses', 'income_period_start', 'income_period_end', 'comment', 'exchange_rate', 'rate_date']
COLUMNS = REQUIRED + OPTIONAL
FREQUENCIES = {'monthly', 'quarterly', 'half_yearly', 'yearly', 'one_off'}
DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
NUMBER_RE = re.compile(r'^-?\d+(\.\d+)?$')

TEMPLATE_CSV = (
    'payment_date,organisation,category,currency,gross_amount,net_amount,withholding_tax,expenses,frequency,'
    'income_period_start,income_period_end,comment,exchange_rate,rate_date\n'
    '2024-03-15,Example Employer GmbH,Salary,EUR,3000.00,2100.00,800.00,100.00,monthly,2024-03-01,2024-03-31,Synthetic example row,,\n'
    '2024-03-28,Example Pension Ltd,Pension,GBP,450.00,,,,monthly,,,Rate looked up automatically,,\n'
    '2024-06-30,Example Bank AU,Interest,AUD,120.50,102.43,18.07,0,one_off,,,Net after 18.07 withholding tax; rate typed in the file,0.6100,2024-06-28\n')


class ImportFileError(Exception):
    """The file cannot be staged at all (shown to the user; no batch is created)."""


class ImportStateError(Exception):
    """The batch is not in a state that allows the action."""


# ---------------------------------------------------------------- parsing

def parse_csv(raw: bytes):
    """Return (rows, warnings). rows = [(line_number, {column: text})]."""
    if len(raw) > settings.IMPORT_MAX_BYTES:
        raise ImportFileError(gettext('File is larger than %(mb)s MB.') % {'mb': settings.IMPORT_MAX_BYTES // 1024 // 1024})
    if b'\x00' in raw:
        raise ImportFileError(gettext('File contains binary data; expected a UTF-8 CSV text file.'))
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ImportFileError(gettext('File is not valid UTF-8. Save it as "CSV UTF-8" and try again.'))
    reader = csv.reader(io.StringIO(text, newline=''))
    try:
        header = next((r for r in reader if any(c.strip() for c in r)), None)
        if header is None:
            raise ImportFileError(gettext('File is empty.'))
        names = [h.strip().lower() for h in header]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            raise ImportFileError(gettext('Duplicate column(s) in header: %(names)s.') % {'names': ', '.join(dupes)})
        missing = [c for c in REQUIRED if c not in names]
        if missing:
            raise ImportFileError(gettext('Missing required column(s): %(names)s. See the format description.') % {'names': ', '.join(missing)})
        warnings = []
        unknown = [h.strip() for h, n in zip(header, names) if n not in COLUMNS]
        if unknown:
            warnings.append(gettext('Ignored unknown column(s): %(names)s.') % {'names': ', '.join(unknown)})
        rows = []
        legacy_format = not ({'withholding_tax', 'expenses'} & set(names))   # file written before Phase 10
        for cells in reader:
            if not any(c.strip() for c in cells):
                continue
            if len(rows) >= settings.IMPORT_MAX_ROWS:
                raise ImportFileError(gettext('More than %(n)s data rows.') % {'n': settings.IMPORT_MAX_ROWS})
            errors = []
            if len(cells) > len(names):
                errors.append(gettext('Row has %(cells)s cells but the header has %(names)s.') % {'cells': len(cells), 'names': len(names)})
            data = {c: '' for c in COLUMNS}
            for name, value in zip(names, cells):
                if name in COLUMNS:
                    data[name] = value.strip()
            if legacy_format:
                data['_legacy_no_breakdown'] = True   # dropped when the row is edited
            if errors:
                data['_structural'] = errors  # dropped when the row is edited
            rows.append((reader.line_num, data))
    except csv.Error as e:
        raise ImportFileError(gettext('Could not read the CSV: %(error)s') % {'error': e})
    if not rows:
        raise ImportFileError(gettext('File has a header but no data rows.'))
    return rows, warnings


# ---------------------------------------------------------------- validation

def _date(value, label, errors, required=False):
    if not value:
        if required:
            errors.append(gettext('%(label)s: required.') % {'label': label})
        return None
    if not DATE_RE.match(value):
        errors.append(gettext('%(label)s: use YYYY-MM-DD (got "%(value)s").') % {'label': label, 'value': value[:20]})
        return None
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        errors.append(gettext('%(label)s: not a real date ("%(value)s").') % {'label': label, 'value': value})
        return None


def _amount(value, label, errors, required=False):
    if not value:
        if required:
            errors.append(gettext('%(label)s: required.') % {'label': label})
        return None
    if not NUMBER_RE.match(value):
        errors.append(gettext('%(label)s: use a plain number like 1234.56, without thousands separators or symbols.') % {'label': label})
        return None
    return to_decimal(value)


def errors_for(errors, label):
    return any(e.startswith(label + ':') for e in errors)


def validate_row(data: dict):
    """Return (errors, notes, cleaned|None). Applies the same model rules as the payment form."""
    errors, notes = list(data.get('_structural', [])), []
    d = _date(data.get('payment_date', ''), 'payment_date', errors, required=True)
    org = ' '.join(data.get('organisation', '').split())
    cat = ' '.join(data.get('category', '').split())
    if not org:
        errors.append(gettext('organisation: required.'))
    elif len(org) > 200:
        errors.append(gettext('organisation: longer than 200 characters.'))
    if not cat:
        errors.append(gettext('category: required.'))
    elif len(cat) > 100:
        errors.append(gettext('category: longer than 100 characters.'))
    for model, name, label in ((Organisation, org, 'organisation'), (IncomeCategory, cat, 'category')):
        if name and len(name) <= 200:
            existing = lookups.find(model, name)
            if existing is not None and not existing.active:
                errors.append(gettext('%(label)s: "%(name)s" is inactive. Reactivate it or use another name.') % {'label': label, 'name': existing.name})
            elif existing is None:
                notes.append(gettext('New %(label)s "%(name)s" will be created.') % {'label': label, 'name': name})
    try:
        currency = normalise_currency(data.get('currency', ''))
    except MoneyError as e:
        errors.append(f'currency: {e}')
        currency = None
    gross = _amount(data.get('gross_amount', ''), 'gross_amount', errors, required=True)
    net = _amount(data.get('net_amount', ''), 'net_amount', errors)
    withholding = _amount(data.get('withholding_tax', ''), 'withholding_tax', errors)
    expenses = _amount(data.get('expenses', ''), 'expenses', errors)
    withholding = Decimal(0) if withholding is None and not errors_for(errors, 'withholding_tax') else withholding
    expenses = Decimal(0) if expenses is None and not errors_for(errors, 'expenses') else expenses
    freq = data.get('frequency', '').strip().lower().replace('-', '_').replace(' ', '_')
    if freq not in FREQUENCIES:
        errors.append(gettext('frequency: must be one of %(values)s.') % {'values': ', '.join(sorted(FREQUENCIES))})
        freq = None
    p_start = _date(data.get('income_period_start', ''), 'income_period_start', errors)
    p_end = _date(data.get('income_period_end', ''), 'income_period_end', errors)
    rate = _amount(data.get('exchange_rate', ''), 'exchange_rate', errors)
    rate_date = _date(data.get('rate_date', ''), 'rate_date', errors)
    if rate is not None and rate <= 0:
        errors.append(gettext('exchange_rate: must be positive.'))
    if rate is not None and currency == BASE_CURRENCY:
        errors.append(gettext('exchange_rate: EUR rows always use rate 1; leave it empty.'))
    if rate_date and rate is None and data.get('exchange_rate', '') == '':
        errors.append(gettext('rate_date: only meaningful together with exchange_rate.'))

    if not errors:
        candidate = Payment(
            payment_date=d, currency=currency, gross_amount=gross, net_amount=net, frequency=freq,
            withholding_tax=withholding, expenses=expenses, income_period_start=p_start, income_period_end=p_end, comment=data.get('comment', ''))
        loss_message = lookups.loss_error(cat, gross)
        if loss_message:
            errors.append('gross_amount: ' + loss_message)
    if not errors:
        try:
            candidate.full_clean(exclude=['month', 'organisation', 'category'], validate_unique=False)
        except ValidationError as e:
            for field, messages in e.message_dict.items():
                errors.extend(f'{field}: {m}' for m in messages)
        if not errors and candidate.breakdown_error():
            if data.get('_legacy_no_breakdown'):
                notes.append(gettext('This file has no withholding_tax / expenses columns: the difference between gross and net '
                                     '(%(gap)s %(ccy)s) is imported as unallocated. Edit the row to allocate it.') % {
                    'gap': number(candidate.unallocated), 'ccy': currency})
            else:
                errors.append('breakdown: ' + candidate.breakdown_error())
    if errors:
        return errors, notes, None
    return errors, notes, {
        'payment_date': d, 'organisation': org, 'category': cat, 'currency': currency, 'gross_amount': gross,
        'net_amount': net, 'withholding_tax': withholding, 'expenses': expenses, 'frequency': freq, 'income_period_start': p_start, 'income_period_end': p_end,
        'comment': data.get('comment', ''), 'exchange_rate': rate, 'rate_date': rate_date}


def _dup_key(c):
    return (c['payment_date'], c['organisation'].lower(), c['currency'], c['gross_amount'].quantize(Decimal('0.0001')))


# ---------------------------------------------------------------- rates

class StoredQuoteProvider(RateProvider):
    """Replays the quote that was shown in the preview, so commit saves exactly what was approved."""
    name = 'import-stored'

    def __init__(self, row: ImportRow):
        self.row = row

    def get_rate(self, currency, on_date):
        r = self.row
        return RateQuote(currency, on_date, r.rate_date, r.rate, r.rate_provider, r.rate_source_url, r.rate_raw_response)


def _clear_rate(row):
    row.rate_key = row.rate_provider = row.rate_notes = row.rate_source_url = row.rate_raw_response = ''
    row.rate = row.rate_date = None
    row.rate_is_manual = False
    row.rate_error = ''


def _propose_rates(rows, cleaned, provider, force):
    """Fill the proposed conversion on each importable row. One lookup per distinct currency/date."""
    cache = {}
    if not force:
        for r in rows:
            if r.rate_key and r.rate is not None and not r.rate_is_manual and r.rate_provider != 'identity':
                cache[r.rate_key] = RateQuote(
                    r.rate_key.split('|')[0], datetime.date.fromisoformat(r.rate_key.split('|')[1]),
                    r.rate_date, r.rate, r.rate_provider, r.rate_source_url, r.rate_raw_response)
    for r in rows:
        c = cleaned.get(r.pk)
        if c is None or r.excluded:
            _clear_rate(r)
            continue
        key = f"{c['currency']}|{c['payment_date'].isoformat()}"
        if c['currency'] == BASE_CURRENCY:
            _clear_rate(r)
            r.rate_key, r.rate, r.rate_date, r.rate_provider = key, Decimal(1), c['payment_date'], 'identity'
        elif c['exchange_rate'] is not None:
            _clear_rate(r)
            r.rate_key, r.rate, r.rate_is_manual = key, c['exchange_rate'], True
            r.rate_date = c['rate_date'] or c['payment_date']
            r.rate_provider = 'manual'
            r.rate_notes = f'Rate supplied in import file (batch #{r.batch_id}, line {r.line_number}).'
        else:
            quote = cache.get(key)
            error = ''
            if quote is None:
                quote = stored_quote(provider, c['currency'], c['payment_date'])
            if quote is None:
                try:
                    quote = provider.get_rate(c['currency'], c['payment_date'])
                except RateError as e:
                    error = f'No rate: {e}'
            _clear_rate(r)
            r.rate_key = key
            if quote is None:
                r.rate_error = error
            else:
                cache[key] = quote
                r.rate, r.rate_date, r.rate_provider = quote.rate, quote.rate_date, quote.provider
                r.rate_source_url, r.rate_raw_response, r.rate_notes = quote.source_url, quote.raw_response, quote_notes(quote)


# ---------------------------------------------------------------- staging / review

RATE_FIELDS = ['rate_key', 'rate', 'rate_date', 'rate_provider', 'rate_is_manual', 'rate_notes',
               'rate_source_url', 'rate_raw_response', 'rate_error']
STATE_FIELDS = ['status', 'errors', 'notes', 'duplicate_of_payment', 'duplicate_of_line', 'data']


def revalidate_batch(batch: ImportBatch, provider: RateProvider, force_rates=False):
    """Re-run validation, duplicate detection and rate proposals for the whole batch."""
    rows = list(batch.rows.all())
    cleaned = {}
    for r in rows:
        errors, notes, c = validate_row(r.data)
        r.errors, r.notes = errors, notes
        r.status = ImportRow.Status.INVALID if errors else ImportRow.Status.VALID
        r.duplicate_of_payment = r.duplicate_of_line = None
        if c is not None:
            cleaned[r.pk] = c

    dates = {c['payment_date'] for c in cleaned.values()}
    existing = defaultdict(list)
    for p in Payment.objects.filter(payment_date__in=dates).select_related('organisation'):
        existing[(p.payment_date, p.organisation.name.lower(), p.currency, p.gross_amount.quantize(Decimal('0.0001')))].append(p)
    seen = {}
    for r in rows:
        c = cleaned.get(r.pk)
        if c is None or r.excluded:
            continue
        key = _dup_key(c)
        if key in existing:
            r.status, r.duplicate_of_payment = ImportRow.Status.DUPLICATE, existing[key][0]
        elif key in seen:
            r.status, r.duplicate_of_line = ImportRow.Status.DUPLICATE, seen[key]
        else:
            seen[key] = r.line_number

    _propose_rates(rows, cleaned, provider, force_rates)
    ImportRow.objects.bulk_update(rows, STATE_FIELDS[:-1] + RATE_FIELDS)
    return rows


def store_upload(raw: bytes, batch: ImportBatch, suffix: str = '.csv') -> str:
    """Save the original file under UPLOAD_DIR with a name that never comes from the user."""
    rel = Path('imports') / f'{batch.pk}-{batch.sha256[:12]}{suffix}'
    full = Path(settings.UPLOAD_DIR) / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(full, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(raw)
    return str(rel)


def upload_path(batch: ImportBatch) -> Path | None:
    """Resolved path of the stored file, or None if missing or outside UPLOAD_DIR."""
    if not batch.stored_path:
        return None
    root = Path(settings.UPLOAD_DIR).resolve()
    full = (root / batch.stored_path).resolve()
    return full if full.is_file() and root in full.parents else None


def stage_batch(raw: bytes, file_name: str, provider: RateProvider) -> ImportBatch:
    """Parse and stage an upload. Raises ImportFileError (nothing created) if unusable."""
    rows, warnings = parse_csv(raw)
    sha = hashlib.sha256(raw).hexdigest()
    previous = ImportBatch.objects.filter(sha256=sha, status=ImportBatch.Status.COMMITTED).first()
    if previous:
        warnings.append(f'This exact file was already imported as batch #{previous.pk}. '
                        'Importing it again will flag every row as a duplicate.')
    stored = None
    try:
        with transaction.atomic():
            batch = ImportBatch.objects.create(
                file_name=' '.join(os.path.basename(file_name or 'upload.csv').split())[:255],
                sha256=sha, warnings=warnings)
            batch.description = f'CSV import #{batch.pk}'
            stored = batch.stored_path = store_upload(raw, batch)
            batch.save()
            ImportRow.objects.bulk_create([
                ImportRow(batch=batch, line_number=line, data=data, original=dict(data))
                for line, data in rows])
            revalidate_batch(batch, provider)
    except Exception:
        if stored:
            (Path(settings.UPLOAD_DIR) / stored).unlink(missing_ok=True)
        raise
    return batch


def _require_preview(batch):
    if batch.status != ImportBatch.Status.PREVIEW:
        raise ImportStateError(gettext('This import is %(status)s and can no longer be changed.') % {'status': str(batch.get_status_display()).lower()})


def update_row(row: ImportRow, data: dict, provider: RateProvider):
    _require_preview(row.batch)
    row.data = {c: (data.get(c, '') or '').strip() for c in COLUMNS}
    row.save(update_fields=['data'])
    revalidate_batch(row.batch, provider)


def set_excluded(row: ImportRow, excluded: bool, provider: RateProvider):
    _require_preview(row.batch)
    row.excluded = excluded
    row.save(update_fields=['excluded'])
    revalidate_batch(row.batch, provider)


def set_keep_duplicate(row: ImportRow, keep: bool):
    _require_preview(row.batch)
    row.keep_duplicate = keep
    row.save(update_fields=['keep_duplicate'])


def refresh_rates(batch: ImportBatch, provider: RateProvider):
    _require_preview(batch)
    revalidate_batch(batch, provider, force_rates=True)


def summary(batch: ImportBatch) -> dict:
    rows = list(batch.rows.all())
    live = [r for r in rows if not r.excluded]
    importing = [r for r in rows if r.will_import]
    new_orgs, new_cats = {}, {}
    for r in importing:
        for n in r.notes:
            m = re.match(r'New (organisation|category) "(.*)" will be created\.', n)
            if m:
                (new_orgs if m.group(1) == 'organisation' else new_cats).setdefault(m.group(2).lower(), m.group(2))
    return {
        'total': len(rows),
        'excluded': sum(1 for r in rows if r.excluded),
        'invalid': sum(1 for r in live if r.status == ImportRow.Status.INVALID),
        'duplicates_skipped': sum(1 for r in live if r.status == ImportRow.Status.DUPLICATE and not r.keep_duplicate),
        'duplicates_kept': sum(1 for r in live if r.status == ImportRow.Status.DUPLICATE and r.keep_duplicate),
        'importing': len(importing),
        'converted': sum(1 for r in importing if r.rate is not None),
        'unconverted': sum(1 for r in importing if r.rate is None),
        'new_organisations': sorted(new_orgs.values()),
        'new_categories': sorted(new_cats.values()),
    }


# ---------------------------------------------------------------- commit / discard

@transaction.atomic
def commit_batch(batch: ImportBatch) -> ImportBatch:
    """Create all payments for the batch in one transaction, or none. Safe to call twice: the
    second call fails with ImportStateError instead of importing again."""
    claimed = ImportBatch.objects.filter(pk=batch.pk, status=ImportBatch.Status.PREVIEW).update(
        status=ImportBatch.Status.COMMITTED)
    if not claimed:
        raise ImportStateError(gettext('This import has already been imported or discarded.'))
    batch.refresh_from_db()
    rows = list(batch.rows.all())
    problems = [r.line_number for r in rows if not r.excluded and r.status == ImportRow.Status.INVALID]
    if problems:
        raise ImportStateError(gettext('Rows still invalid (fix or exclude them): lines %(lines)s.') % {'lines': ', '.join(map(str, problems[:10]))})

    doc = SourceDocument.objects.create(
        description=f'{batch.kind.upper()} import #{batch.pk}',
        file_name=batch.file_name, sha256=batch.sha256)
    imported = unconverted = 0
    for r in rows:
        if not r.will_import:
            continue
        _, _, c = validate_row(r.data)
        if c is None:
            raise ImportStateError(gettext('Line %(n)s is no longer valid.') % {'n': r.line_number})
        payment = Payment(
            month=ReportingMonth.for_date(c['payment_date']),
            organisation=lookups.resolve_organisation(c['organisation']),
            category=lookups.resolve_category(c['category']),
            payment_date=c['payment_date'], currency=c['currency'], gross_amount=c['gross_amount'],
            net_amount=c['net_amount'], withholding_tax=c['withholding_tax'], expenses=c['expenses'],
            frequency=c['frequency'], income_period_start=c['income_period_start'],
            income_period_end=c['income_period_end'], comment=c['comment'],
            source_document=doc, import_batch=batch)
        reason = f'Import batch #{batch.pk}, line {r.line_number}'
        if r.rate is None:
            payment.save()
            unconverted += 1
        elif r.rate_is_manual:
            convert_payment(payment, manual_rate=r.rate, manual_rate_date=r.rate_date,
                            manual_note=r.rate_notes, reason=reason)
        else:
            convert_payment(payment, StoredQuoteProvider(r), reason=reason)
        r.created_payment = payment
        r.save(update_fields=['created_payment'])
        imported += 1

    batch.source_document = doc
    batch.imported_count = imported
    batch.skipped_count = len(rows) - imported
    batch.unconverted_count = unconverted
    batch.committed_at = timezone.now()
    batch.save()
    return batch


@transaction.atomic
def discard_batch(batch: ImportBatch):
    """Drop a not-yet-imported batch: staged rows and the stored file are removed."""
    _require_preview(batch)
    path = upload_path(batch)
    batch.rows.all().delete()
    batch.status = ImportBatch.Status.DISCARDED
    batch.stored_path = ''
    batch.save()
    if path:
        path.unlink(missing_ok=True)
