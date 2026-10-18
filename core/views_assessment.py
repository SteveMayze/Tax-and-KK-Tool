from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import AnnualInputForm, AssessmentSettingsForm
from .models import AnnualInput, AssessmentSettings, ReportingYear
from .services.policies import sbk


@login_required
def assessment_settings(request):
    settings = AssessmentSettings.load()
    form = AssessmentSettingsForm(request.POST or None, instance=settings)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Assessment settings saved.')
        return redirect('assessment_settings')
    return render(request, 'core/assessment_settings.html', {
        'form': form, 'params': sbk.PARAMETERS, 'years': ReportingYear.objects.all()})


@login_required
def annual_inputs(request, year):
    y = get_object_or_404(ReportingYear, year=year)
    form = AnnualInputForm(request.POST or None, year=y)
    if request.method == 'POST' and form.is_valid():
        cd = form.cleaned_data
        AnnualInput.objects.update_or_create(
            year=y, treatment=cd['treatment'],
            defaults={k: cd[k] for k in ('costs_eur', 'first_month', 'last_month', 'note')})
        messages.success(request, 'Saved.')
        return redirect('annual_inputs', year=year)
    return render(request, 'core/annual_inputs.html', {'year': y, 'form': form, 'inputs': y.annual_inputs.all()})


@login_required
@require_POST
def annual_input_delete(request, year, pk):
    obj = get_object_or_404(AnnualInput, pk=pk, year__year=year)
    obj.delete()
    messages.success(request, 'Removed; defaults (January to December, no costs) apply again.')
    return redirect('annual_inputs', year=year)
