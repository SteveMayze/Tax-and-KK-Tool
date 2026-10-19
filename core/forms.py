from decimal import Decimal

from django import forms
from django.conf import settings
from django.utils.translation import gettext, gettext_lazy as _

from .currencies import BASE_CURRENCY, SUPPORTED_CURRENCIES
from .models import AnnualInput, AssessmentSettings, IncomeCategory, Organisation, Payment, ReportingYear
from .services import lookups

DATE = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')


class YearForm(forms.ModelForm):
    class Meta:
        model = ReportingYear
        fields = ['year', 'notes']
        labels = {'year': _('Year'), 'notes': _('Notes')}
        widgets = {'notes': forms.Textarea(attrs={'rows': 3})}


class YearNotesForm(forms.ModelForm):
    class Meta:
        model = ReportingYear
        fields = ['notes']
        labels = {'notes': _('Notes')}
        widgets = {'notes': forms.Textarea(attrs={'rows': 3})}


class UniqueNameMixin:
    """Reject duplicate spellings (case- and whitespace-insensitive) with a friendly message,
    before the database constraint is hit."""

    def clean_name(self):
        name = ' '.join(self.cleaned_data['name'].split())
        clash = self._meta.model.objects.filter(name__iexact=name).exclude(pk=self.instance.pk)
        if not name:
            raise forms.ValidationError(gettext('This field is required.'))
        if clash.exists():
            raise forms.ValidationError(gettext('"%(name)s" already exists.') % {'name': clash.first().name})
        return name


class OrganisationForm(UniqueNameMixin, forms.ModelForm):
    class Meta:
        model = Organisation
        fields = ['name', 'country', 'active']
        labels = {'name': _('Name'), 'country': _('Country'), 'active': _('Active')}
        help_texts = {'country': _('ISO 3166-1 alpha-2, e.g. DE')}


class CategoryForm(UniqueNameMixin, forms.ModelForm):
    class Meta:
        model = IncomeCategory
        fields = ['name', 'active', 'sbk_treatment', 'tax_income_type', 'may_be_negative']
        labels = {'name': _('Name'), 'active': _('Active'), 'sbk_treatment': _('SBK treatment'),
                  'tax_income_type': _('Tax income type'), 'may_be_negative': _('May be negative')}
        help_texts = {
            'sbk_treatment': _('How SBK treats this income (docs/rules). Leave blank if unsure: it is then left out of the SBK estimate and flagged.'),
            'tax_income_type': _('Einkunftsart for the tax information summary. Leave blank if unsure.'),
            'may_be_negative': _('Allows a loss (negative gross amount) as a normal payment. Reports show losses signed; no loss-offset rule is applied (unverified, see docs/rules/).'),
        }


class PaymentForm(forms.ModelForm):
    """Original transaction plus optional manual-rate fields. Organisation and category are
    combo-style: type or pick a name; a new name is created only when the payment is saved."""
    organisation_name = forms.CharField(label=_('Organisation'), max_length=200)
    category_name = forms.CharField(label=_('Category'), max_length=100)
    currency = forms.ChoiceField(label=_('Currency'), choices=[(c, c) for c in SUPPORTED_CURRENCIES])

    manual_rate = forms.CharField(
        label=_('Manual rate (EUR per 1 unit)'), required=False,
        help_text=_('Only needed if no automatic rate is available. EUR = original amount x rate.'))
    manual_rate_date = forms.DateField(label=_('Rate date'), required=False, widget=DATE,
                                       help_text=_('Defaults to the payment date.'))
    manual_note = forms.CharField(label=_('Rate source / note'), required=False, max_length=300)

    field_order = ['payment_date', 'organisation_name', 'category_name', 'currency', 'gross_amount',
                   'net_amount', 'withholding_tax', 'expenses', 'frequency', 'income_period_start', 'income_period_end', 'comment',
                   'manual_rate', 'manual_rate_date', 'manual_note']

    class Meta:
        model = Payment
        fields = ['payment_date', 'currency', 'gross_amount', 'net_amount', 'withholding_tax', 'expenses', 'frequency',
                  'income_period_start', 'income_period_end', 'comment']
        labels = {
            'payment_date': _('Payment date'), 'gross_amount': _('Gross amount'), 'net_amount': _('Net amount'),
            'withholding_tax': _('Withholding tax'), 'expenses': _('Expenses'), 'frequency': _('Frequency'),
            'income_period_start': _('Income period start'), 'income_period_end': _('Income period end'),
            'comment': _('Comment'),
        }
        widgets = {
            'payment_date': DATE, 'income_period_start': DATE, 'income_period_end': DATE,
            'comment': forms.Textarea(attrs={'rows': 2}),
        }
        help_texts = {
            'net_amount': _('Optional. When given, gross must equal net + withholding tax + expenses.'),
            'withholding_tax': _('Tax withheld at source, in the payment currency. Leave empty for 0.'),
            'expenses': _('Costs deducted before payment, in the payment currency. Leave empty for 0.'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ('withholding_tax', 'expenses'):
            self.fields[name].required = False
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

    def _clean_breakdown_amount(self, name):
        value = self.cleaned_data.get(name)
        return Decimal(0) if value is None else value

    def clean_withholding_tax(self):
        return self._clean_breakdown_amount('withholding_tax')

    def clean_expenses(self):
        return self._clean_breakdown_amount('expenses')

    def _check_name(self, model, field):
        name = self.cleaned_data[field]
        if not ' '.join(name.split()):
            raise forms.ValidationError(gettext('This field is required.'))
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
            self.add_error('manual_rate', gettext('EUR payments always use rate 1; leave the manual rate empty.'))
        if cleaned.get('category_name') and 'gross_amount' not in self.errors and self.instance.kind == Payment.Kind.NORMAL:
            message = lookups.loss_error(cleaned['category_name'], cleaned.get('gross_amount'))
            if message:
                self.add_error('gross_amount', message)
        # gross = net + withholding tax + expenses, exactly (only when a net amount is given). The message names the numbers.
        g, n = cleaned.get('gross_amount'), cleaned.get('net_amount')
        if g is not None and n is not None and not self.errors.keys() & {'gross_amount', 'net_amount', 'withholding_tax', 'expenses'}:
            probe = Payment(gross_amount=g, net_amount=n, withholding_tax=cleaned.get('withholding_tax'),
                            expenses=cleaned.get('expenses'), currency=cleaned.get('currency') or '')
            message = probe.breakdown_error()
            if message:
                self.add_error(None, message)
        return cleaned

    @property
    def manual_rate_value(self):
        return (self.cleaned_data.get('manual_rate') or '').strip() or None

    def has_manual_input(self):
        return bool((self.data.get('manual_rate') or '').strip())


class ManualCorrectionForm(forms.Form):
    rate = forms.CharField(label=_('Rate (EUR per 1 unit of the payment currency)'))
    rate_date = forms.DateField(label=_('Rate date'), required=False, widget=DATE,
                                help_text=_('Date the rate applies to; defaults to the payment date.'))
    reason = forms.CharField(label=_('Reason / source'), max_length=300,
                             help_text=_('Required; kept in the payment history (e.g. "rate on bank statement").'))

    def clean_reason(self):
        reason = ' '.join(self.cleaned_data['reason'].split())
        if not reason:
            raise forms.ValidationError(gettext('A reason is required.'))
        return reason


class ImportUploadForm(forms.Form):
    file = forms.FileField(label=_('CSV file'), help_text=_('UTF-8 CSV with a header row; see the format description below.'))

    def clean_file(self):
        f = self.cleaned_data['file']
        if f.size > settings.IMPORT_MAX_BYTES:
            raise forms.ValidationError(gettext('File is larger than %(mb)s MB.') % {'mb': settings.IMPORT_MAX_BYTES // 1024 // 1024})
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
        labels = {'kv_rate': _('Health-insurance rate'), 'kv_rate_confirmed': _('Rate confirmed with SBK'),
                  'pflege': _('Care-insurance rate'), 'joint_assessment': _('Joint income-tax assessment')}
        help_texts = {'kv_rate_confirmed': _('Tick once SBK has confirmed which rate applies to you.'),
                      'joint_assessment': _('Jointly assessed for income tax (doubles the Sparer-Pauschbetrag).')}


class AnnualInputForm(forms.ModelForm):
    class Meta:
        model = AnnualInput
        fields = ['treatment', 'costs_eur', 'first_month', 'last_month', 'note']
        labels = {'treatment': _('Treatment'), 'costs_eur': _('Annual costs EUR (Werbungskosten / Betriebsausgaben)'),
                  'first_month': _('First month earned (1-12)'), 'last_month': _('Last month earned (1-12)'), 'note': _('Note')}

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
