from collections import defaultdict

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.conf import settings as django_settings
from django.http import JsonResponse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.urls import reverse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from .forms import YearForm, YearNotesForm
from .models import AssessmentSettings, Payment, ReportingMonth, ReportingYear
from .services.aggregation import (
    actual_totals, average_of_actuals, normalised_monthly_totals, year_payments)
from .services import import_files
from .services.i18n import month_name
from .services.normalisation import is_recurring, monthly_equivalent


@require_GET
def health(request):
    """Unauthenticated liveness check. Returns no data beyond status."""
    return JsonResponse({'status': 'ok'})


@login_required
@require_POST
def set_language(request):
    """Save the app-wide language (one setting) and return to the page the user was on."""
    code = request.POST.get('language', '')
    if code not in dict(django_settings.LANGUAGES):
        messages.error(request, _('Unknown language.'))
    else:
        settings_row = AssessmentSettings.load()
        settings_row.language = code
        settings_row.save(update_fields=['language'])
    target = request.POST.get('next', '')
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        target = reverse('home')
    return redirect(target)


def _year_summary(year):
    payments = list(year_payments(year))
    totals = actual_totals(payments)
    return {
        'year': year, 'totals': totals, 'avg': average_of_actuals(totals),
        'months_with_payments': len({p.month_id for p in payments}),
    }


@login_required
def home(request, form=None):
    summaries = [_year_summary(y) for y in ReportingYear.objects.all()]
    return render(request, 'core/home.html', {'summaries': summaries, 'form': form or YearForm()})


@login_required
@require_POST
def year_add(request):
    form = YearForm(request.POST)
    if form.is_valid():
        year = form.save()
        messages.success(request, _('Year %(year)s added.') % {'year': year.year})
        return redirect('year_detail', year=year.year)
    return home(request, form=form)


@login_required
def year_detail(request, year):
    y = get_object_or_404(ReportingYear, year=year)
    payments = list(year_payments(y).select_related('month'))
    by_month = defaultdict(list)
    for p in payments:
        by_month[p.month.month].append(p)
    existing = {m.month: m for m in y.months.all()}
    rows = [{
        'number': n, 'name': month_name(n), 'obj': existing.get(n),
        'totals': actual_totals(by_month[n]),
    } for n in range(1, 13)]
    return render(request, 'core/year_detail.html', {
        'year': y, 'rows': rows, 'summary': _year_summary(y), 'notes_form': YearNotesForm(instance=y)})


@login_required
@require_POST
def year_notes(request, year):
    y = get_object_or_404(ReportingYear, year=year)
    form = YearNotesForm(request.POST, instance=y)
    if form.is_valid():
        form.save()
        messages.success(request, _('Notes saved.'))
    return redirect('year_detail', year=year)


@login_required
def year_delete(request, year):
    y = get_object_or_404(ReportingYear, year=year)
    if request.method == 'POST':
        removal = import_files.delete_year(y, delete_imports=request.POST.get('delete_imports') == 'on')
        messages.success(request, _('Year %(year)s and all its months and payments were deleted.') % {'year': year})
        if removal.batches:
            messages.success(request, _('%(batches)s import batch(es) used only by this year were deleted: %(removed)s stored file(s) removed, %(gone)s already gone.') % {
                'batches': removal.batches, 'removed': removal.removed, 'gone': removal.already_gone})
        if removal.failed:
            messages.error(request, _('%(n)s stored file(s) could not be removed and are no longer linked to any import. List them with the command stored_files_report and remove them with its --apply option.') % {'n': removal.failed})
        if removal.kept_shared:
            messages.warning(request, _('%(n)s import batch(es) also support other years and were kept.') % {'n': removal.kept_shared})
        if removal.refused_batches:
            messages.error(request, _('%(n)s import batch(es) were kept because their stored path is not inside the storage directory.') % {'n': removal.refused_batches})
        return redirect('home')
    return render(request, 'core/year_delete.html', {
        'year': y, 'months': y.months.count(), 'payments': year_payments(y).count(),
        'batches': import_files.year_batches(y), 'cancel_href': reverse('year_detail', args=[year])})


@login_required
@require_POST
def month_add(request, year, month):
    y = get_object_or_404(ReportingYear, year=year)
    if not 1 <= month <= 12:
        messages.error(request, _('Month must be between 1 and 12.'))
        return redirect('year_detail', year=year)
    _month, created = ReportingMonth.objects.get_or_create(year=y, month=month)
    messages.success(request, _('%(month)s %(year)s added.') % {'month': month_name(month), 'year': year} if created
                     else _('Month already exists.'))
    return redirect('month_detail', year=year, month=month)


@login_required
def month_detail(request, year, month):
    m = get_object_or_404(ReportingMonth.objects.select_related('year'), year__year=year, month=month)
    payments = list(Payment.objects.filter(month=m).select_related('organisation', 'category'))
    rows = []
    for p in payments:
        converted = p.conversion_status == Payment.ConversionStatus.CONVERTED
        rows.append({
            'p': p,
            'normalised': monthly_equivalent(p.gross_eur, p.frequency) if converted else None,
            'recurring': is_recurring(p.frequency),
        })
    return render(request, 'core/month_detail.html', {
        'month': m, 'month_name': month_name(month), 'rows': rows,
        'actual': actual_totals(payments), 'normalised': normalised_monthly_totals(payments)})


@login_required
def month_delete(request, year, month):
    m = get_object_or_404(ReportingMonth, year__year=year, month=month)
    label = f'{month_name(month)} {year}'
    if request.method == 'POST':
        m.delete()
        messages.success(request, _('%(label)s and its payments were deleted.') % {'label': label})
        return redirect('year_detail', year=year)
    return render(request, 'core/confirm_delete.html', {
        'what': label, 'consequence': _('%(n)s payment(s) will be permanently deleted.') % {'n': m.payments.count()},
        'cancel_href': reverse('month_detail', args=[year, month])})
