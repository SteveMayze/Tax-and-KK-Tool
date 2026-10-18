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


class IncomeCategory(models.Model):
    """Configurable. Deactivate rather than delete (PROTECT prevents deleting referenced rows).

    No tax or SBK meaning is attached here; legal rules come in Phase 7.
    """
    name = models.CharField(max_length=100)
    active = models.BooleanField(default=True)

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
    """Minimal placeholder; fleshed out in Phase 5 (imports)."""
    description = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.description or f'Document {self.pk}'


class ImportBatch(models.Model):
    """Minimal placeholder; fleshed out in Phase 5 (imports)."""
    description = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.description or f'Import batch {self.pk}'


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
    conversion_notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

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
            if self.kind == self.Kind.NORMAL and g <= 0:
                errors['gross_amount'] = 'Gross amount must be positive (use a reversal or correction to adjust).'
            elif self.kind == self.Kind.REVERSAL and g >= 0:
                errors['gross_amount'] = 'A reversal must have a negative gross amount.'
            elif self.kind == self.Kind.CORRECTION and g == 0:
                errors['gross_amount'] = 'A correction must be non-zero.'
            if n is not None and n != 0 and (n > 0) != (g > 0):
                errors['net_amount'] = 'Net amount must have the same sign as gross.'

        if self.kind == self.Kind.NORMAL:
            if self.corrects_id:
                errors['corrects'] = 'Only corrections and reversals may reference another payment.'
        else:
            if not self.corrects_id:
                errors['corrects'] = 'Corrections and reversals must reference the original payment.'
            elif self.corrects.currency != self.currency:
                errors['currency'] = 'Must use the same currency as the payment it corrects.'

        # Stored conversion must be internally consistent.
        if self.conversion_status == self.ConversionStatus.CONVERTED:
            if self.rate is None or self.rate <= 0 or self.rate_date is None or self.gross_eur is None:
                errors['conversion_status'] = 'Converted payments need a positive rate, rate date and gross EUR.'
            elif self.currency == BASE_CURRENCY and self.rate != 1:
                errors['rate'] = 'EUR payments always use rate 1.'
            elif self.net_amount is not None and self.net_eur is None:
                errors['net_eur'] = 'Net EUR is required when a net amount is present.'
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
