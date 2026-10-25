from django.contrib import messages
from django.utils import timezone, translation
from django.utils.translation import get_language
from django.utils.translation import gettext as _
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET

from .models import ReportingYear
from .services import report_csv, report_filter, report_pdf
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


def _filter(request):
    """(ReportFilter, error). Parsed once per request; the same error style as the year."""
    return report_filter.parse(request.GET)


def _build(request, spec):
    """(report, year, filter, error). A filter passed to a report that cannot honour it is ignored and said so."""
    year, error = _year(request)
    if error:
        return None, None, None, error
    flt, error = _filter(request)
    if error:
        return None, None, None, error
    if spec.needs_year and year is None:
        return None, None, None, _('"%(title)s" needs a specific year.') % {'title': spec.title}
    try:
        if spec.supports_filter:
            return spec.build(year, flt=flt), year, flt, None
        report = spec.build(year)
    except PolicyUnavailable as e:
        return None, None, None, str(e)
    if flt.is_active:
        report.basis.insert(1, (_('Filter'), _('Not applied to this report: it is a whole-person assessment and cannot be '
                                               'computed over part of the income. The figures are the unfiltered ones.')))
    return report, year, flt, None


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
    year, error = _year(request)
    flt, flt_error = _filter(request)
    if error or flt_error:
        messages.error(request, error or flt_error)
        year, flt = None, report_filter.NO_FILTER
    return render(request, 'core/report_index.html', {
        'specs': REPORTS.values(), 'years': available_years(), 'year': year, 'filter': flt,
        'options': report_filter.options(year, flt)})


@login_required
@require_GET
def report_view(request, key):
    spec = _spec(key)
    report, year, flt, error = _build(request, spec)
    if error:
        messages.error(request, error)
        return redirect('report_index')
    if flt.is_active and not spec.supports_filter:
        messages.warning(request, _('The organisation and category filter does not apply to "%(title)s": the figures below '
                                    'are unfiltered.') % {'title': spec.title})
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
        'years': available_years(), 'headers': headers, 'popups': [i for i in infos if i],
        'filter': flt, 'options': report_filter.options(year, flt) if spec.supports_filter else None,
        'csv_query': flt.querystring(year), 'index_query': flt.querystring(year)})


@login_required
@require_GET
def report_csv_download(request, key):
    """Generated on demand and streamed to the logged-in user; nothing is written to disk."""
    spec = _spec(key)
    # CSV exports are language-independent: English headings and labels, comma separator, dot decimals, ISO dates,
    # whatever the interface language is (the file is for bulk data input and for mixing exports).
    with translation.override('en'):
        report, year, flt, error = _build(request, spec)
        csv_text = report_csv.render(report) if not error else ''
    if error:
        messages.error(request, error)
        return redirect('report_index')
    response = HttpResponse(csv_text, content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="report-{key}-{year or "all"}{"-filtered" if spec.supports_filter and flt.is_active else ""}.csv"'
    response['Cache-Control'] = 'no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@login_required
@require_GET
def report_pdf_download(request, key):
    """Landscape A4 PDF of the same report as the page, in the interface language. Generated on demand, nothing stored."""
    spec = _spec(key)
    report, year, flt, error = _build(request, spec)
    if error:
        messages.error(request, error)
        return redirect('report_index')
    align = {'int': 'num', 'money': 'num', 'rate': 'num', 'pct': 'num'}
    rows = [[(_display(r.get(c.key), c.kind), align.get(c.kind, '')) for c in report.columns] for r in report.rows]
    totals = ([(_display(report.totals.get(c.key), c.kind), align.get(c.kind, '')) for c in report.columns]
              if report.totals else None)
    generated = _('Generated %(when)s') % {'when': i18n.date_text(timezone.localdate())}
    pdf = report_pdf.render(report, [c.label for c in report.columns], rows, totals,
                            language=(get_language() or 'en')[:2], with_signature=(key == 'tax_summary'),
                            generated_text=generated)
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="report-{key}-{year or "all"}{"-filtered" if spec.supports_filter and flt.is_active else ""}.pdf"'
    response['Cache-Control'] = 'no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
