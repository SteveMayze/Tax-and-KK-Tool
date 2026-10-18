from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET

from .models import ReportingYear
from .services import report_csv
from .services.money import round_for_display
from .services.reports import REPORTS, available_years


def _spec(key):
    spec = REPORTS.get(key)
    if spec is None:
        raise Http404('Unknown report.')
    return spec


def _year(request):
    """(year or None, error). Empty/'all' means every year."""
    raw = (request.GET.get('year') or '').strip()
    if raw in ('', 'all'):
        return None, None
    if not raw.isdigit() or not ReportingYear.objects.filter(year=int(raw)).exists():
        return None, f'Unknown year "{raw[:10]}".'
    return int(raw), None


def _build(request, spec):
    year, error = _year(request)
    if error:
        return None, None, error
    if spec.needs_year and year is None:
        return None, None, f'"{spec.title}" needs a specific year.'
    return spec.build(year), year, None


def _display(value, kind):
    if value is None:
        return ''
    if kind == 'money':
        return f'{round_for_display(Decimal(value), 2):,.2f}'
    if kind == 'pct':
        return f'{round_for_display(Decimal(value) * 100, 1):.1f}%'
    if kind == 'rate':
        return report_csv.fmt(value, 'rate')
    if kind == 'date':
        return value.isoformat()
    return str(value)


@login_required
@require_GET
def report_index(request):
    return render(request, 'core/report_index.html', {'specs': REPORTS.values(), 'years': available_years()})


@login_required
@require_GET
def report_view(request, key):
    spec = _spec(key)
    report, year, error = _build(request, spec)
    if error:
        messages.error(request, error)
        return redirect('report_index')
    align = {'int': 'num', 'money': 'num', 'rate': 'num', 'pct': 'num'}
    rows = [[(_display(r.get(c.key), c.kind), align.get(c.kind, '')) for c in report.columns] for r in report.rows]
    totals = ([(_display(report.totals.get(c.key), c.kind), align.get(c.kind, '')) for c in report.columns]
              if report.totals else None)
    return render(request, 'core/report.html', {
        'report': report, 'rows': rows, 'totals': totals, 'year': year, 'spec': spec,
        'years': available_years(), 'headers': [(c.label, align.get(c.kind, '')) for c in report.columns]})


@login_required
@require_GET
def report_csv_download(request, key):
    """Generated on demand and streamed to the logged-in user; nothing is written to disk."""
    spec = _spec(key)
    report, year, error = _build(request, spec)
    if error:
        messages.error(request, error)
        return redirect('report_index')
    response = HttpResponse(report_csv.render(report), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="report-{key}-{year or "all"}.csv"'
    response['Cache-Control'] = 'no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
