from django.contrib import messages
from django.utils.translation import gettext as _
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .models import Payment, ReportingYear
from .services.conversion import convert_pending
from .services.i18n import date_text, number
from .services.rates import get_provider
from .services.reconciliation import build_report


def _year_param(request):
    value = request.GET.get('year') or request.POST.get('year')
    return int(value) if value and value.isdigit() else None


@login_required
def reconciliation(request):
    year = _year_param(request)
    return render(request, 'core/reconciliation.html', {
        'report': build_report(year), 'year': year, 'years': ReportingYear.objects.all()})


@login_required
@require_POST
def convert_pending_view(request):
    """Explicit bulk action: try the automatic source for every unconverted payment."""
    year = _year_param(request)
    qs = Payment.objects.filter(conversion_status=Payment.ConversionStatus.PENDING).select_related('organisation')
    if year is not None:
        qs = qs.filter(month__year__year=year)
    results = convert_pending(get_provider(), list(qs))
    done = sum(1 for _p, err in results if err is None)
    failed = [(p, err) for p, err in results if err]
    if done:
        messages.success(request, _('%(n)s payment(s) converted.') % {'n': done})
    for p, err in failed:
        messages.error(request, f'{date_text(p.payment_date)} {p.organisation} {number(p.gross_amount)} {p.currency}: {err}')
    if not results:
        messages.info(request, _('No unconverted payments.'))
    url = reverse('reconciliation')
    return redirect(f'{url}?year={year}' if year else url)
