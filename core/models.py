from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models.functions import Lower

from .currencies import BASE_CURRENCY, CURRENCY_CODE_RE, SUPPORTED_CURRENCIES

# Precision: see docs/decisions/0001-decimal-precision.md
AMOUNT = {'max_digits': 16, 'decimal_places': 4}  # as reported
RATE = {'max_digits': 20, 'decimal_places': 10}   # EUR per 1 unit of original currency
EUR_AMOUNT = {'max_digits': 20, 'decimal_places': 6}  # gross x rate, kept at (near) full precision

currency_code_validator = RegexValidator(CURRENCY_CODE_RE, 'Currency must be a 3-letter upper-case code.')


def validate_supported_currency(value):
    if value not in SUPPORTED_CURRENCIES:
        raise ValidationError(f'Unsupported currency {value!r}; supported: {", ".join(SUPPORTED_CURRENCIES)}.')


class Frequency(models.TextChoices):
    MONTHLY = 'monthly', 'Monthly'
    QUARTERLY = 'quarterly', 'Quarterly'
    HALF_YEARLY = 'half_yearly', 'Half-yearly'
    YEARLY = 'yearly', 'Yearly'
    ONE_OFF = 'one_off', 'One-off / irregular'


class ReportingYear(models.Model):
    year = models.PositiveSmallIntegerField(
        unique=True, validators=[MinValueValidator(1900), MaxValueValidator(2200)])
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-year']

    def __str__(self):
        return str(self.year)


class ReportingMonth(models.Model):
    # Deleting a year deletes its months (and, through them, payments).
    year = models.ForeignKey(ReportingYear, on_delete=models.CASCADE, related_name='months')
    month = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(12)])

    class Meta:
        ordering = ['year__year', 'month']
        constraints = [models.UniqueConstraint(fields=['year', 'month'], name='unique_year_month')]

    def __str__(self):
        return f'{self.year.year}-{self.month:02d}'

    @classmethod
    def for_date(cls, d):
        """Get or create the reporting month (and year) containing date `d`."""
        year, _ = ReportingYear.objects.get_or_create(year=d.year)
        month, _ = cls.objects.get_or_create(year=year, month=d.month)
        return month


class Organisation(models.Model):
    name = models.CharField(max_length=200)
    country = models.CharField(max_length=2, blank=True, help_text='ISO 3166-1 alpha-2, e.g. DE')
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']
        constraints = [models.UniqueConstraint(Lower('name'), name='unique_organisation_name_ci')]

    def save(self, *args, **kwargs):
        self.name = ' '.join(self.name.split())
        self.country = self.country.strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class SbkTreatment(models.TextChoices):
    """How SBK treats an income type (docs/rules/sbk-contribution-rules.md). Blank = not mapped yet."""
    EMPLOYMENT = 'employment', 'Employment income (Arbeitsentgelt): month of receipt'
    PENSION = 'pension', 'Pension / Versorgungsbezug: month of receipt'
    SELF_EMPLOYED = 'self_employed', 'Self-employment profit (Arbeitseinkommen): annual / months earned'
    RENTAL = 'rental', 'Rental income: annual surplus / months earned'
    CAPITAL = 'capital', 'Capital income (interest, dividends): annual surplus / months earned'
    ONE_OFF = 'one_off', 'One-off income: 1/12 per month for 12 months'
    EXCLUDED = 'excluded', 'Not contribution-relevant (excluded)'


class TaxIncomeType(models.TextChoices):
    """Einkunftsart per section 2(1) EStG, plus private sale gains (section 22 no. 2 / 23). Blank = not mapped."""
    EMPLOYMENT = 'employment', 'Non-self-employed work (section 19)'
    SELF_EMPLOYED = 'self_employed', 'Self-employment / business (sections 15, 18)'
    CAPITAL = 'capital', 'Capital assets (section 20)'
    RENTAL = 'rental', 'Rental and leasing (section 21)'
    OTHER = 'other', 'Other income, e.g. pensions (section 22)'
    PRIVATE_SALE = 'private_sale', 'Private sale gains (sections 22 no. 2, 23): enter the gain, not the proceeds'
    NOT_TAXABLE = 'not_taxable', 'Not income for tax (excluded)'


class IncomeCategory(models.Model):
    """Configurable. Deactivate rather than delete (PROTECT prevents deleting referenced rows).

    The SBK and tax mappings are chosen by the user and never guessed; a blank mapping means the
    category is left out of the SBK assessment / tax summary and flagged there.
    """
    name = models.CharField(max_length=100)
    active = models.BooleanField(default=True)
    sbk_treatment = models.CharField(max_length=15, choices=SbkTreatment.choices, blank=True)
    tax_income_type = models.CharField(max_length=15, choices=TaxIncomeType.choices, blank=True)
    may_be_negative = models.BooleanField(
        default=False, help_text='Tick if a normal payment in this category may be a loss (negative gross amount).')

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'income categories'
        constraints = [models.UniqueConstraint(Lower('name'), name='unique_category_name_ci')]

    def save(self, *args, **kwargs):
        self.name = ' '.join(self.name.split())
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class SourceDocument(models.Model):
    """An original file a payment came from (kept under UPLOAD_DIR, never publicly served)."""
    description = models.CharField(max_length=300, blank=True)
    file_name = models.CharField(max_length=255, blank=True, help_text='Name as uploaded; display only.')
    sha256 = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.description or self.file_name or f'Document {self.pk}'


class ImportBatch(models.Model):
    """One CSV upload: staged, reviewed, then committed or discarded (see docs/imports.md)."""
    class Status(models.TextChoices):
        PREVIEW = 'preview', 'Preview (not imported)'
        COMMITTED = 'committed', 'Imported'
        DISCARDED = 'discarded', 'Discarded'

    description = models.CharField(max_length=300, blank=True)
    file_name = models.CharField(max_length=255, blank=True, help_text='Name as uploaded; display only.')
    sha256 = models.CharField(max_length=64, blank=True)
    stored_path = models.CharField(max_length=500, blank=True, help_text='Relative to UPLOAD_DIR.')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PREVIEW)
    warnings = models.JSONField(default=list, blank=True)
    imported_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    unconverted_count = models.PositiveIntegerField(default=0)
    source_document = models.ForeignKey(SourceDocument, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    committed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return self.description or f'Import batch {self.pk}'


class ImportRow(models.Model):
    """A staged CSV row. Nothing here is a payment until the batch is committed."""
    class Status(models.TextChoices):
        VALID = 'valid', 'Valid'
        INVALID = 'invalid', 'Invalid'
        DUPLICATE = 'duplicate', 'Possible duplicate'

    batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE, related_name='rows')
    line_number = models.PositiveIntegerField(help_text='Line in the file (header is line 1).')
    data = models.JSONField(help_text='Cell values as text, editable during review.')
    original = models.JSONField(help_text='Cell values exactly as uploaded.')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.VALID)
    errors = models.JSONField(default=list, blank=True)
    notes = models.JSONField(default=list, blank=True, help_text='Non-blocking flags, e.g. new organisation.')
    excluded = models.BooleanField(default=False)
    keep_duplicate = models.BooleanField(default=False)
    duplicate_of_payment = models.ForeignKey(
        'Payment', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    duplicate_of_line = models.PositiveIntegerField(null=True, blank=True)
    # Proposed conversion shown in the preview and applied unchanged at commit.
    rate_key = models.CharField(max_length=20, blank=True, help_text='currency|payment date the proposal was made for.')
    rate = models.DecimalField(**RATE, null=True, blank=True)
    rate_date = models.DateField(null=True, blank=True)
    rate_provider = models.CharField(max_length=50, blank=True)
    rate_is_manual = models.BooleanField(default=False)
    rate_notes = models.TextField(blank=True)
    rate_source_url = models.CharField(max_length=500, blank=True)
    rate_raw_response = models.TextField(blank=True)
    rate_error = models.TextField(blank=True)
    created_payment = models.ForeignKey('Payment', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        ordering = ['line_number']
        constraints = [models.UniqueConstraint(fields=['batch', 'line_number'], name='unique_batch_line')]

    @property
    def will_import(self):
        if self.excluded or self.status == self.Status.INVALID:
            return False
        return self.status != self.Status.DUPLICATE or self.keep_duplicate


class ExchangeRateRecord(models.Model):
    """Append-only record of a rate that was used. Rows are never edited, so rate changes stay auditable.

    rate = EUR per 1 unit of `currency`.
    """
    currency = models.CharField(max_length=3, validators=[currency_code_validator])
    rate_date = models.DateField(help_text='Date the rate applies to, as stated by the source.')
    requested_date = models.DateField(
        null=True, blank=True, help_text='Date that was asked for (the payment date); may differ from rate_date.')
    rate = models.DecimalField(**RATE, validators=[MinValueValidator(Decimal('0.0000000001'))])
    provider = models.CharField(max_length=50, help_text='e.g. frankfurter, fake, manual, identity')
    is_manual = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    source_url = models.CharField(max_length=500, blank=True, help_text='Exact request URL for provider rates.')
    raw_response = models.TextField(blank=True, help_text='Provider response body, kept as provenance.')
    created_at = models.DateTimeField(auto_now_add=True, help_text='When the rate was retrieved/entered.')

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'{self.currency} {self.rate} @ {self.rate_date} ({self.provider})'


class Payment(models.Model):
    class Kind(models.TextChoices):
        NORMAL = 'normal', 'Normal'
        CORRECTION = 'correction', 'Correction'
        REVERSAL = 'reversal', 'Reversal'

    class ConversionStatus(models.TextChoices):
        PENDING = 'pending', 'Not yet converted'
        CONVERTED = 'converted', 'Converted'

    # Deleting a month deletes its payments. Organisation/category are PROTECTed.
    month = models.ForeignKey(ReportingMonth, on_delete=models.CASCADE, related_name='payments')
    organisation = models.ForeignKey(Organisation, on_delete=models.PROTECT, related_name='payments')
    category = models.ForeignKey(IncomeCategory, on_delete=models.PROTECT, related_name='payments')
    payment_date = models.DateField()
    income_period_start = models.DateField(null=True, blank=True)
    income_period_end = models.DateField(null=True, blank=True)

    # Original transaction, exactly as reported. Never overwritten by conversion.
    currency = models.CharField(max_length=3, validators=[currency_code_validator, validate_supported_currency])
    gross_amount = models.DecimalField(**AMOUNT)
    net_amount = models.DecimalField(**AMOUNT, null=True, blank=True)
    # Breakdown of the difference between gross and net (Phase 10, ADR 0010), in the original currency:
    # gross = net + withholding_tax + expenses. Non-negative for normal payments; signed like gross otherwise.
    withholding_tax = models.DecimalField(**AMOUNT, default=0)
    expenses = models.DecimalField(**AMOUNT, default=0)
    frequency = models.CharField(max_length=12, choices=Frequency.choices)
    comment = models.TextField(blank=True)

    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.NORMAL)
    corrects = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.PROTECT, related_name='corrections',
        help_text='For corrections/reversals: the payment being corrected or reversed.')

    source_document = models.ForeignKey(SourceDocument, null=True, blank=True, on_delete=models.SET_NULL)
    import_batch = models.ForeignKey(ImportBatch, null=True, blank=True, on_delete=models.SET_NULL)

    # Conversion (stored per payment; reports use these unless recalculation is explicitly requested)
    conversion_status = models.CharField(
        max_length=10, choices=ConversionStatus.choices, default=ConversionStatus.PENDING)
    rate = models.DecimalField(**RATE, null=True, blank=True)
    rate_date = models.DateField(null=True, blank=True)
    rate_source = models.CharField(max_length=50, blank=True)
    rate_record = models.ForeignKey(ExchangeRateRecord, null=True, blank=True, on_delete=models.PROTECT)
    gross_eur = models.DecimalField(**EUR_AMOUNT, null=True, blank=True)
    net_eur = models.DecimalField(**EUR_AMOUNT, null=True, blank=True)
    # Converted with the SAME stored rate as gross and net (null until the payment is converted).
    withholding_tax_eur = models.DecimalField(**EUR_AMOUNT, null=True, blank=True)
    expenses_eur = models.DecimalField(**EUR_AMOUNT, null=True, blank=True)
    conversion_notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Set only by PaymentForm while it validates user input: at that point the stored conversion
    # still reflects the OLD amounts/currency and is recomputed afterwards. save() always checks it.
    _skip_conversion_checks = False

    class Meta:
        ordering = ['payment_date', 'id']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(income_period_start__isnull=True) | models.Q(income_period_end__isnull=True)
                | models.Q(income_period_end__gte=models.F('income_period_start')),
                name='income_period_order'),
        ]

    def __str__(self):
        return f'{self.payment_date} {self.organisation} {self.gross_amount} {self.currency}'

    @property
    def unallocated(self):
        """gross - net - withholding tax - expenses, in the original currency. None when no net amount is
        recorded (the gross cannot be broken down without it)."""
        if self.net_amount is None or self.gross_amount is None:
            return None
        return self.gross_amount - self.net_amount - (self.withholding_tax or 0) - (self.expenses or 0)

    def breakdown_error(self):
        """A message naming the three numbers when gross != net + withholding tax + expenses, else None.
        Enforced when a payment is created or edited by the form and the importer, not on every save, so
        older payments with a gap can still be recalculated or have their rate corrected."""
        gap = self.unallocated
        if gap is None or gap == 0:
            return None
        return (f'Gross {self.gross_amount:,.2f} must equal net {self.net_amount:,.2f} + withholding tax '
                f'{(self.withholding_tax or 0):,.2f} + expenses {(self.expenses or 0):,.2f} '
                f'(= {self.net_amount + (self.withholding_tax or 0) + (self.expenses or 0):,.2f}); '
                f'{gap:,.2f} {self.currency} is unallocated.')

    def clean(self):
        errors = {}
        # Month must match payment date (payment date determines the reporting month).
        if self.payment_date and self.month_id:
            m = self.month
            if (m.year.year, m.month) != (self.payment_date.year, self.payment_date.month):
                errors['month'] = f'Reporting month {m} does not match payment date {self.payment_date}.'
        if self.income_period_start and self.income_period_end and self.income_period_end < self.income_period_start:
            errors['income_period_end'] = 'Income period end is before its start.'

        # Amount signs: normal payments are positive; reversals negative; corrections signed but non-zero.
        g, n = self.gross_amount, self.net_amount
        if g is not None:
            if self.kind == self.Kind.NORMAL and g == 0:
                errors['gross_amount'] = 'Gross amount must be positive (it cannot be zero).'
            elif self.kind == self.Kind.NORMAL and g < 0 and self.category_id and not self.category.may_be_negative:
                errors['gross_amount'] = (f'Gross amount must be positive: category "{self.category}" is not marked '
                                          f'"may be negative" (use a reversal or correction to adjust).')
            elif self.kind == self.Kind.NORMAL and g < 0 and not self.category_id:
                pass            # the caller (form, importer) checks the category it resolves; save() checks it again
            elif self.kind == self.Kind.REVERSAL and g >= 0:
                errors['gross_amount'] = 'A reversal must have a negative gross amount.'
            elif self.kind == self.Kind.CORRECTION and g == 0:
                errors['gross_amount'] = 'A correction must be non-zero.'
            if n is not None and n != 0 and (n > 0) != (g > 0):
                errors['net_amount'] = 'Net amount must have the same sign as gross.'
            for name, label in (('withholding_tax', 'Withholding tax'), ('expenses', 'Expenses')):
                v = getattr(self, name)
                if v is not None and v != 0 and (v > 0) != (g > 0):
                    errors[name] = (f'{label} cannot be negative.' if g > 0 else f'{label} must have the same sign as gross.')

        if self.kind == self.Kind.NORMAL:
            if self.corrects_id:
                errors['corrects'] = 'Only corrections and reversals may reference another payment.'
        else:
            if not self.corrects_id:
                errors['corrects'] = 'Corrections and reversals must reference the original payment.'
            elif self.corrects.currency != self.currency:
                errors['currency'] = 'Must use the same currency as the payment it corrects.'

        # Stored conversion must be internally consistent.
        if self.conversion_status == self.ConversionStatus.CONVERTED and not self._skip_conversion_checks:
            if self.rate is None or self.rate <= 0 or self.rate_date is None or self.gross_eur is None:
                errors['conversion_status'] = 'Converted payments need a positive rate, rate date and gross EUR.'
            elif self.currency == BASE_CURRENCY and self.rate != 1:
                errors['rate'] = 'EUR payments always use rate 1.'
            elif self.net_amount is not None and self.net_eur is None:
                errors['net_eur'] = 'Net EUR is required when a net amount is present.'
            elif ((self.withholding_tax and self.withholding_tax_eur is None)
                  or (self.expenses and self.expenses_eur is None)):
                errors['withholding_tax_eur'] = 'Withholding tax / expenses EUR are required when those amounts are present.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        # Enforce invariants on every save, not only in forms.
        self.currency = (self.currency or '').strip().upper()
        self.full_clean()
        super().save(*args, **kwargs)


class ConversionEvent(models.Model):
    """Append-only audit trail of every conversion or rate change on a payment.

    Stores the values that took effect and the values they replaced, so any change
    to a stored rate or EUR amount can be reconstructed.
    """
    class Kind(models.TextChoices):
        INITIAL = 'initial', 'Initial conversion'
        RECALCULATED = 'recalculated', 'Recalculated from provider'
        MANUAL_CORRECTION = 'manual_correction', 'Manual rate correction'
        BASIS_CHANGED = 'basis_changed', 'Currency or date edited'
        AMOUNTS_EDITED = 'amounts_edited', 'Amounts edited (stored rate kept)'

    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name='conversion_events')
    kind = models.CharField(max_length=20, choices=Kind.choices)
    rate_record = models.ForeignKey(ExchangeRateRecord, on_delete=models.PROTECT, related_name='+')
    rate = models.DecimalField(**RATE)
    rate_date = models.DateField()
    gross_eur = models.DecimalField(**EUR_AMOUNT)
    net_eur = models.DecimalField(**EUR_AMOUNT, null=True, blank=True)
    previous_rate = models.DecimalField(**RATE, null=True, blank=True)
    previous_gross_eur = models.DecimalField(**EUR_AMOUNT, null=True, blank=True)
    previous_net_eur = models.DecimalField(**EUR_AMOUNT, null=True, blank=True)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']

    def __str__(self):
        return f'{self.get_kind_display()} {self.rate} ({self.created_at:%Y-%m-%d})'


class AssessmentSettings(models.Model):
    """The user's own circumstances for the SBK estimate (single row). Defaults record the owner's
    decisions of Phase 7: general rate as an unconfirmed upper-bound "affordability" figure; childless."""
    class KvRate(models.TextChoices):
        GENERAL = 'general', 'General rate (with sick-pay entitlement)'
        REDUCED = 'reduced', 'Reduced rate (no sick-pay entitlement)'

    class Pflege(models.TextChoices):
        CHILDLESS = 'childless', 'Age 23 or over, no children (surcharge)'
        BASE = 'base', 'One child, or under 23 (base rate)'

    kv_rate = models.CharField(max_length=10, choices=KvRate.choices, default=KvRate.GENERAL)
    kv_rate_confirmed = models.BooleanField(
        default=False, help_text='Tick once SBK has confirmed which rate applies to you.')
    pflege = models.CharField(max_length=10, choices=Pflege.choices, default=Pflege.CHILDLESS)
    joint_assessment = models.BooleanField(
        default=False, help_text='Jointly assessed for income tax (doubles the Sparer-Pauschbetrag).')

    class Meta:
        verbose_name_plural = 'assessment settings'

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)


class AnnualInput(models.Model):
    """Per year and SBK treatment: annual costs and the months the income was earned.

    Costs are Werbungskosten / Betriebsausgaben in EUR (only used for self-employed, rental and
    capital income). Months earned are explicit user data, never inferred from payment dates.
    """
    year = models.ForeignKey(ReportingYear, on_delete=models.CASCADE, related_name='annual_inputs')
    treatment = models.CharField(max_length=15, choices=SbkTreatment.choices)
    costs_eur = models.DecimalField(max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    first_month = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(12)])
    last_month = models.PositiveSmallIntegerField(default=12, validators=[MinValueValidator(1), MaxValueValidator(12)])
    note = models.CharField(max_length=300, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['year', 'treatment'], name='unique_annual_input')]
        ordering = ['year__year', 'treatment']

    def clean(self):
        if self.first_month and self.last_month and self.last_month < self.first_month:
            raise ValidationError({'last_month': 'Last month is before the first month.'})
        if self.treatment in (SbkTreatment.EMPLOYMENT, SbkTreatment.PENSION, SbkTreatment.ONE_OFF, SbkTreatment.EXCLUDED):
            raise ValidationError({'treatment': 'Costs and months earned apply only to self-employed, rental and capital income.'})

    @property
    def months_earned(self):
        return self.last_month - self.first_month + 1
