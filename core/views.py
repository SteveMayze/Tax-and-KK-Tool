import calendar
from collections import defaultdict

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.urls import reverse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from .context_processors import SESSION_KEY
from .currencies import SUPPORTED_CURRENCIES
from .forms import YearForm, YearNotesForm
from .models import Payment, ReportingMonth, ReportingYear
from .services.aggregation import (
    actual_totals, average_of_actuals, normalised_monthly_totals, year_payments)
from .services.normalisation import is_recurring, monthly_equivalent


@require_GET
def health(request):
    """Unauthenticated liveness check. Returns no data beyond status."""
    return JsonResponse({'status': 'ok'})


@login_required
@require_POST
def set_display_currency(request):
    code = request.POST.get('display_currency')
    if code in SUPPORTED_CURRENCIES:
        request.session[SESSION_KEY] = code
    else:
        messages.error(request, 'Unsupported display currency.')
    target = request.POST.get('next', '')
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        target = '/'
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
        messages.success(request, f'Year {year.year} added.')
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
        'number': n, 'name': calendar.month_name[n], 'obj': existing.get(n),
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
        messages.success(request, 'Notes saved.')
    return redirect('year_detail', year=year)


@login_required
def year_delete(request, year):
    y = get_object_or_404(ReportingYear, year=year)
    if request.method == 'POST':
        y.delete()
        messages.success(request, f'Year {year} and all its months and payments were deleted.')
        return redirect('home')
    return render(request, 'core/confirm_delete.html', {
        'what': f'year {year}',
        'consequence': f'{y.months.count()} month(s) and {year_payments(y).count()} payment(s) will be permanently deleted.',
        'cancel_href': reverse('year_detail', args=[year])})


@login_required
@require_POST
def month_add(request, year, month):
    y = get_object_or_404(ReportingYear, year=year)
    if not 1 <= month <= 12:
        messages.error(request, 'Month must be between 1 and 12.')
        return redirect('year_detail', year=year)
    _, created = ReportingMonth.objects.get_or_create(year=y, month=month)
    messages.success(request, f'{calendar.month_name[month]} {year} added.' if created else 'Month already exists.')
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
        'month': m, 'month_name': calendar.month_name[month], 'rows': rows,
        'actual': actual_totals(payments), 'normalised': normalised_monthly_totals(payments)})


@login_required
def month_delete(request, year, month):
    m = get_object_or_404(ReportingMonth, year__year=year, month=month)
    label = f'{calendar.month_name[month]} {year}'
    if request.method == 'POST':
        m.delete()
        messages.success(request, f'{label} and its payments were deleted.')
        return redirect('year_detail', year=year)
    return render(request, 'core/confirm_delete.html', {
        'what': label, 'consequence': f'{m.payments.count()} payment(s) will be permanently deleted.',
        'cancel_href': reverse('month_detail', args=[year, month])})
