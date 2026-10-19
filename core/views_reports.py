from django.contrib import messages
from django.utils import translation
from django.utils.translation import get_language
from django.utils.translation import gettext as _
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET

from .models import ReportingYear
from .services import report_csv
from . import glossary
from .services import i18n
from .services.policies.sbk import PolicyUnavailable
from .services.reports import REPORTS, available_years


def _spec(key):
    spec = REPORTS.get(key)
    if spec is None:
        raise Http404(_('Unknown report.'))
    return spec


def _year(request):
    """(year or None, error). Empty/'all' means every year."""
    raw = (request.GET.get('year') or '').strip()
    if raw in ('', 'all'):
        return None, None
    if not raw.isdigit() or not ReportingYear.objects.filter(year=int(raw)).exists():
        return None, _('Unknown year "%(year)s".') % {'year': raw[:10]}
    return int(raw), None


def _build(request, spec):
    year, error = _year(request)
    if error:
        return None, None, error
    if spec.needs_year and year is None:
        return None, None, _('"%(title)s" needs a specific year.') % {'title': spec.title}
    try:
        return spec.build(year), year, None
    except PolicyUnavailable as e:
        return None, None, str(e)


def _display(value, kind):
    if value is None:
        return ''
    if kind == 'money':
        return i18n.number(value, 2)
    if kind == 'pct':
        return i18n.percent(value, 1)
    if kind == 'rate':
        return i18n.plain_decimal(value)
    if kind == 'date':
        return i18n.date_text(value)
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
    # The SBK estimate's 14 column headings get an information popup whose text is the glossary entry (Phase 13).
    language = (get_language() or 'en')[:2]
    infos = [glossary.entry(c.key, language) if report.key == 'sbk' else None for c in report.columns]
    headers = [(c.label, align.get(c.kind, ''), info) for c, info in zip(report.columns, infos)]
    return render(request, 'core/report.html', {
        'report': report, 'rows': rows, 'totals': totals, 'year': year, 'spec': spec,
        'years': available_years(), 'headers': headers, 'popups': [i for i in infos if i]})


@login_required
@require_GET
def report_csv_download(request, key):
    """Generated on demand and streamed to the logged-in user; nothing is written to disk."""
    spec = _spec(key)
    # CSV exports are language-independent: English headings and labels, comma separator, dot decimals, ISO dates,
    # whatever the interface language is (the file is for bulk data input and for mixing exports).
    with translation.override('en'):
        report, year, error = _build(request, spec)
        csv_text = report_csv.render(report) if not error else ''
    if error:
        messages.error(request, error)
        return redirect('report_index')
    response = HttpResponse(csv_text, content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="report-{key}-{year or "all"}.csv"'
    response['Cache-Control'] = 'no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
