import datetime

from django.contrib import messages
from django.utils.translation import gettext as _
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import ProtectedError
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.urls import reverse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET

from .forms import ManualCorrectionForm, PaymentForm
from .models import ConversionEvent, Payment, ReportingMonth, ReportingYear
from .services import lookups, payment_list as payments_page, report_filter
from .services.i18n import date_text, month_name, number
from .services.conversion import ConversionError, convert_payment, correct_rate_manually, reapply_stored_rate
from .services.rates import get_provider
from .templatetags.money import rate


def _next_url(request):
    """Where an edit or delete started from the payments page returns to: only that page's own path (with its query
    string), never an arbitrary URL. Empty when absent or anything else."""
    target = request.GET.get('next', '')
    path = target.split('?', 1)[0]
    if path == reverse('payment_list') and url_has_allowed_host_and_scheme(target, allowed_hosts=None):
        return target
    return ''


def _persist(form, payment, keep_stored_rate):
    """Resolve combo fields, assign month from payment date, convert, save. All-or-nothing:
    a failure rolls back (including any newly created organisation/category/month)."""
    cd = form.cleaned_data
    with transaction.atomic():
        payment.organisation = lookups.resolve_organisation(cd['organisation_name'])
        payment.category = lookups.resolve_category(cd['category_name'])
        payment.month = ReportingMonth.for_date(payment.payment_date)
        if keep_stored_rate:
            reapply_stored_rate(payment)
        else:
            was_converted = payment.conversion_status == Payment.ConversionStatus.CONVERTED
            convert_payment(
                payment, get_provider(), manual_rate=form.manual_rate_value,
                manual_rate_date=cd.get('manual_rate_date'), manual_note=cd.get('manual_note', ''),
                recalculate=was_converted,
                kind=ConversionEvent.Kind.BASIS_CHANGED if was_converted else None,
                reason='Currency or payment date edited. ' + cd.get('manual_note', '') if was_converted else cd.get('manual_note', ''))
    return payment


def _handle_save(request, form, payment, keep_stored_rate, template, ctx):
    """Shared create/edit flow: validate -> get rate -> error or manual option -> save."""
    if keep_stored_rate and form.has_manual_input():
        form.add_error('manual_rate', _('The stored rate is kept when only amounts change. '
                       'Use "Recalculate" on the payment to replace it.'))
    elif not form.errors:
        try:
            _persist(form, payment, keep_stored_rate)
        except ConversionError as e:
            ctx['rate_error'] = str(e)
        except ValidationError as e:
            form.add_error(None, e)
        else:
            messages.success(request, _('Payment saved.'))
            return redirect(_next_url(request) or reverse('payment_detail', args=[payment.pk]))
    return render(request, template, {'form': form, 'show_manual': True, 'next_url': _next_url(request), **ctx})


@login_required
def payment_add(request, year, month):
    m = get_object_or_404(ReportingMonth.objects.select_related('year'), year__year=year, month=month)
    ctx = {'month': m, 'month_name': month_name(month), 'editing': False}
    if request.method == 'POST':
        form = PaymentForm(request.POST)
        if form.is_valid():
            return _handle_save(request, form, form.instance, False, 'core/payment_form.html', ctx)
        return render(request, 'core/payment_form.html', {'form': form, 'show_manual': form.has_manual_input(), **ctx})
    form = PaymentForm(initial={'payment_date': datetime.date(year, month, 1), 'currency': 'EUR'})
    return render(request, 'core/payment_form.html', {'form': form, 'show_manual': False, **ctx})


@login_required
def payment_edit(request, pk):
    payment = get_object_or_404(Payment.objects.select_related('month__year', 'organisation', 'category'), pk=pk)
    ctx = {'month': payment.month, 'month_name': month_name(payment.month.month),
           'editing': True, 'payment': payment, 'next_url': _next_url(request)}
    if request.method == 'POST':
        was_converted = payment.conversion_status == Payment.ConversionStatus.CONVERTED
        form = PaymentForm(request.POST, instance=payment)
        if form.is_valid():
            basis_changed = bool({'currency', 'payment_date'} & set(form.changed_data))
            keep = was_converted and not basis_changed
            ctx['basis_changed'] = basis_changed
            return _handle_save(request, form, payment, keep, 'core/payment_form.html', ctx)
        return render(request, 'core/payment_form.html', {'form': form, 'show_manual': form.has_manual_input(), **ctx})
    form = PaymentForm(instance=payment)
    return render(request, 'core/payment_form.html', {'form': form, 'show_manual': False, **ctx})


@login_required
def payment_detail(request, pk):
    payment = get_object_or_404(
        Payment.objects.select_related('month__year', 'organisation', 'category', 'rate_record'), pk=pk)
    return render(request, 'core/payment_detail.html', {
        'p': payment, 'month_name': month_name(payment.month.month)})


@login_required
def payment_delete(request, pk):
    payment = get_object_or_404(Payment.objects.select_related('month__year', 'organisation'), pk=pk)
    month = payment.month
    if request.method == 'POST':
        try:
            payment.delete()
        except ProtectedError:
            messages.error(request, _('This payment has corrections/reversals and cannot be deleted.'))
            return redirect('payment_detail', pk=pk)
        messages.success(request, _('Payment deleted.'))
        return redirect(_next_url(request) or reverse('month_detail', args=[month.year.year, month.month]))
    return render(request, 'core/confirm_delete.html', {
        'what': _('the payment of %(amount)s %(ccy)s from %(org)s on %(date)s') % {
            'amount': number(payment.gross_amount), 'ccy': payment.currency, 'org': payment.organisation,
            'date': date_text(payment.payment_date)},
        'consequence': _('This cannot be undone.'),
        'cancel_href': _next_url(request) or reverse('payment_detail', args=[pk])})


@login_required
def payment_recalculate(request, pk):
    """Explicit recalculation from the provider (re-requests the rate). The only automatic way
    to replace a stored rate; the previous rate stays on record and in the audit trail."""
    payment = get_object_or_404(Payment.objects.select_related('month__year', 'organisation'), pk=pk)
    ctx = {'p': payment}
    if payment.currency == 'EUR':
        messages.info(request, _('EUR payments always use rate 1; there is nothing to recalculate.'))
        return redirect('payment_detail', pk=pk)
    if request.method == 'POST':
        old_rate = payment.rate
        try:
            convert_payment(payment, get_provider(), recalculate=True, refresh=True,
                            reason=request.POST.get('reason', ''))
        except ConversionError as e:
            ctx['rate_error'] = str(e)
        else:
            if old_rate is None:
                messages.success(request, _('Payment converted.'))
            else:
                messages.success(request, _('Recalculated: rate %(old)s -> %(new)s. The previous rate remains on record.') % {
                    'old': rate(old_rate), 'new': rate(payment.rate)})
            return redirect('payment_detail', pk=pk)
    return render(request, 'core/payment_recalculate.html', ctx)


@login_required
def payment_correct_rate(request, pk):
    """Manual correction of the stored rate; a reason is mandatory and is audited."""
    payment = get_object_or_404(Payment.objects.select_related('month__year', 'organisation'), pk=pk)
    if payment.currency == 'EUR':
        messages.info(request, _('EUR payments always use rate 1.'))
        return redirect('payment_detail', pk=pk)
    converted = payment.conversion_status == Payment.ConversionStatus.CONVERTED
    form = ManualCorrectionForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        cd = form.cleaned_data
        try:
            if converted:
                correct_rate_manually(payment, cd['rate'], cd['reason'], cd['rate_date'])
            else:
                convert_payment(payment, manual_rate=cd['rate'], manual_rate_date=cd['rate_date'],
                                manual_note=cd['reason'], reason=cd['reason'])
        except ConversionError as e:
            form.add_error('rate', str(e))
        else:
            messages.success(request, _('Rate saved. The change is recorded in the payment history.'))
            return redirect('payment_detail', pk=pk)
    return render(request, 'core/payment_correct_rate.html', {'p': payment, 'form': form, 'converted': converted})


@login_required
@require_GET
def payment_list(request):
    """Phase 31 (ADR 0032, spike): payments of a year and month, limited by the report filter. Read only."""
    year, month, error = payments_page.parse_period(request.GET)
    flt, filter_error = report_filter.parse(request.GET)
    if error or filter_error:
        messages.error(request, error or filter_error)
        return redirect('payment_list')
    payments, by_currency, eur, options = payments_page.build(year, month, flt)
    known = set(ReportingYear.objects.values_list('year', flat=True))
    years = sorted(known | ({year} if year else set()), reverse=True)
    return render(request, 'core/payment_list.html', {
        'year': year, 'month': month, 'years': years, 'months': [(n, month_name(n)) for n in range(1, 13)],
        'filter': flt, 'options': options, 'payments': payments, 'by_currency': by_currency, 'eur': eur,
        'basis': payments_page.basis(year, month, flt, ignored_month=year is None and month is not None),
        'year_missing': bool(year) and year not in known,
        'clear_query': urlencode({'year': year or 'all', **({'month': month} if month else {})}),
        'next_query': urlencode({'next': request.get_full_path()})})
