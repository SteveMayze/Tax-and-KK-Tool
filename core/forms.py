from django import forms
from django.conf import settings

from .currencies import BASE_CURRENCY, SUPPORTED_CURRENCIES
from .models import AnnualInput, AssessmentSettings, IncomeCategory, Organisation, Payment, ReportingYear
from .services import lookups

DATE = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')


class YearForm(forms.ModelForm):
    class Meta:
        model = ReportingYear
        fields = ['year', 'notes']
        widgets = {'notes': forms.Textarea(attrs={'rows': 3})}


class YearNotesForm(forms.ModelForm):
    class Meta:
        model = ReportingYear
        fields = ['notes']
        widgets = {'notes': forms.Textarea(attrs={'rows': 3})}


class UniqueNameMixin:
    """Reject duplicate spellings (case- and whitespace-insensitive) with a friendly message,
    before the database constraint is hit."""

    def clean_name(self):
        name = ' '.join(self.cleaned_data['name'].split())
        clash = self._meta.model.objects.filter(name__iexact=name).exclude(pk=self.instance.pk)
        if not name:
            raise forms.ValidationError('This field is required.')
        if clash.exists():
            raise forms.ValidationError(f'"{clash.first().name}" already exists.')
        return name


class OrganisationForm(UniqueNameMixin, forms.ModelForm):
    class Meta:
        model = Organisation
        fields = ['name', 'country', 'active']


class CategoryForm(UniqueNameMixin, forms.ModelForm):
    class Meta:
        model = IncomeCategory
        fields = ['name', 'active', 'sbk_treatment', 'tax_income_type']
        help_texts = {
            'sbk_treatment': 'How SBK treats this income (docs/rules). Leave blank if unsure: it is then left out of the SBK estimate and flagged.',
            'tax_income_type': 'Einkunftsart for the tax information summary. Leave blank if unsure.',
        }


class PaymentForm(forms.ModelForm):
    """Original transaction plus optional manual-rate fields. Organisation and category are
    combo-style: type or pick a name; a new name is created only when the payment is saved."""
    organisation_name = forms.CharField(label='Organisation', max_length=200)
    category_name = forms.CharField(label='Category', max_length=100)
    currency = forms.ChoiceField(choices=[(c, c) for c in SUPPORTED_CURRENCIES])

    manual_rate = forms.CharField(
        label='Manual rate (EUR per 1 unit)', required=False,
        help_text='Only needed if no automatic rate is available. EUR = original amount x rate.')
    manual_rate_date = forms.DateField(label='Rate date', required=False, widget=DATE,
                                       help_text='Defaults to the payment date.')
    manual_note = forms.CharField(label='Rate source / note', required=False, max_length=300)

    field_order = ['payment_date', 'organisation_name', 'category_name', 'currency', 'gross_amount',
                   'net_amount', 'frequency', 'income_period_start', 'income_period_end', 'comment',
                   'manual_rate', 'manual_rate_date', 'manual_note']

    class Meta:
        model = Payment
        fields = ['payment_date', 'currency', 'gross_amount', 'net_amount', 'frequency',
                  'income_period_start', 'income_period_end', 'comment']
        widgets = {
            'payment_date': DATE, 'income_period_start': DATE, 'income_period_end': DATE,
            'comment': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['organisation_name'].widget.attrs['list'] = 'organisation-options'
        self.fields['category_name'].widget.attrs['list'] = 'category-options'
        if self.instance.pk:
            self.fields['organisation_name'].initial = self.instance.organisation.name
            self.fields['category_name'].initial = self.instance.category.name

    def _post_clean(self):
        # Validate the user's input only. The stored conversion is stale until it is recomputed
        # in the view; Payment.save() re-checks full consistency afterwards.
        self.instance._skip_conversion_checks = True
        try:
            super()._post_clean()
        finally:
            self.instance._skip_conversion_checks = False

    def _check_name(self, model, field):
        name = self.cleaned_data[field]
        if not ' '.join(name.split()):
            raise forms.ValidationError('This field is required.')
        try:
            lookups.check_usable(model, name)
        except lookups.InactiveLookup as e:
            raise forms.ValidationError(str(e))
        return name

    def clean_organisation_name(self):
        return self._check_name(Organisation, 'organisation_name')

    def clean_category_name(self):
        return self._check_name(IncomeCategory, 'category_name')

    def clean(self):
        cleaned = super().clean()
        # The reporting month is derived from the payment date when saving (see views_payments),
        # so don't validate the old month against a possibly changed date here.
        self.instance.month = None
        if cleaned.get('currency') == BASE_CURRENCY and (cleaned.get('manual_rate') or '').strip():
            self.add_error('manual_rate', 'EUR payments always use rate 1; leave the manual rate empty.')
        return cleaned

    @property
    def manual_rate_value(self):
        return (self.cleaned_data.get('manual_rate') or '').strip() or None

    def has_manual_input(self):
        return bool((self.data.get('manual_rate') or '').strip())


class ManualCorrectionForm(forms.Form):
    rate = forms.CharField(label='Rate (EUR per 1 unit of the payment currency)')
    rate_date = forms.DateField(label='Rate date', required=False, widget=DATE,
                                help_text='Date the rate applies to; defaults to the payment date.')
    reason = forms.CharField(label='Reason / source', max_length=300,
                             help_text='Required; kept in the payment history (e.g. "rate on bank statement").')

    def clean_reason(self):
        reason = ' '.join(self.cleaned_data['reason'].split())
        if not reason:
            raise forms.ValidationError('A reason is required.')
        return reason


class ImportUploadForm(forms.Form):
    file = forms.FileField(label='CSV file', help_text='UTF-8 CSV with a header row; see the format description below.')

    def clean_file(self):
        f = self.cleaned_data['file']
        if f.size > settings.IMPORT_MAX_BYTES:
            raise forms.ValidationError(f'File is larger than {settings.IMPORT_MAX_BYTES // 1024 // 1024} MB.')
        return f


class ImportRowForm(forms.Form):
    """One text field per CSV column; values are re-validated by the import service."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .services.imports import COLUMNS, REQUIRED
        for name in COLUMNS:
            self.fields[name] = forms.CharField(
                required=False, label=name + (' *' if name in REQUIRED else ''), max_length=1000,
                widget=forms.Textarea(attrs={'rows': 2}) if name == 'comment' else forms.TextInput())


class AssessmentSettingsForm(forms.ModelForm):
    class Meta:
        model = AssessmentSettings
        fields = ['kv_rate', 'kv_rate_confirmed', 'pflege', 'joint_assessment']
        labels = {'kv_rate': 'Health-insurance rate', 'kv_rate_confirmed': 'Rate confirmed with SBK',
                  'pflege': 'Care-insurance rate', 'joint_assessment': 'Joint income-tax assessment'}


class AnnualInputForm(forms.ModelForm):
    class Meta:
        model = AnnualInput
        fields = ['treatment', 'costs_eur', 'first_month', 'last_month', 'note']
        labels = {'costs_eur': 'Annual costs EUR (Werbungskosten / Betriebsausgaben)',
                  'first_month': 'First month earned (1-12)', 'last_month': 'Last month earned (1-12)'}

    ALLOWED = ('self_employed', 'rental', 'capital')

    def __init__(self, *args, year=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.year = year
        # Only these income types use costs and months earned; others are rejected as invalid choices.
        self.fields['treatment'].choices = [
            (v, l) for v, l in AnnualInput._meta.get_field('treatment').choices if v in self.ALLOWED]

    def _post_clean(self):
        self.instance.year = self.year        # needed for clean(); uniqueness is handled by upsert in the view
        super()._post_clean()

    def validate_unique(self):
        pass
