import calendar
import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import ProtectedError
from django.urls import reverse
from django.shortcuts import get_object_or_404, redirect, render

from .forms import ConfirmRecalculateForm, PaymentForm
from .models import Payment, ReportingMonth
from .services import lookups
from .services.conversion import ConversionError, convert_payment, reapply_stored_rate
from .services.rates import get_provider


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
            convert_payment(
                payment, get_provider(), manual_rate=form.manual_rate_value,
                manual_rate_date=cd.get('manual_rate_date'), manual_note=cd.get('manual_note', ''),
                recalculate=True)
    return payment


def _handle_save(request, form, payment, keep_stored_rate, template, ctx):
    """Shared create/edit flow: validate -> get rate -> error or manual option -> save."""
    if keep_stored_rate and form.has_manual_input():
        form.add_error('manual_rate', 'The stored rate is kept when only amounts change. '
                       'Use "Recalculate" on the payment to replace it.')
    elif not form.errors:
        try:
            _persist(form, payment, keep_stored_rate)
        except ConversionError as e:
            ctx['rate_error'] = str(e)
        except ValidationError as e:
            form.add_error(None, e)
        else:
            messages.success(request, 'Payment saved.')
            return redirect('payment_detail', pk=payment.pk)
    return render(request, template, {'form': form, 'show_manual': True, **ctx})


@login_required
def payment_add(request, year, month):
    m = get_object_or_404(ReportingMonth.objects.select_related('year'), year__year=year, month=month)
    ctx = {'month': m, 'month_name': calendar.month_name[month], 'editing': False}
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
    ctx = {'month': payment.month, 'month_name': calendar.month_name[payment.month.month],
           'editing': True, 'payment': payment}
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
        'p': payment, 'month_name': calendar.month_name[payment.month.month]})


@login_required
def payment_delete(request, pk):
    payment = get_object_or_404(Payment.objects.select_related('month__year', 'organisation'), pk=pk)
    month = payment.month
    if request.method == 'POST':
        try:
            payment.delete()
        except ProtectedError:
            messages.error(request, 'This payment has corrections/reversals and cannot be deleted.')
            return redirect('payment_detail', pk=pk)
        messages.success(request, 'Payment deleted.')
        return redirect('month_detail', year=month.year.year, month=month.month)
    return render(request, 'core/confirm_delete.html', {
        'what': f'the payment of {payment.gross_amount} {payment.currency} from {payment.organisation} on {payment.payment_date}',
        'consequence': 'This cannot be undone.',
        'cancel_href': reverse('payment_detail', args=[pk])})


@login_required
def payment_recalculate(request, pk):
    """Explicit recalculation: the only way to replace a stored rate."""
    payment = get_object_or_404(Payment.objects.select_related('month__year', 'organisation'), pk=pk)
    ctx = {'p': payment}
    if request.method == 'POST':
        form = ConfirmRecalculateForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            try:
                convert_payment(
                    payment, get_provider(), manual_rate=(cd['manual_rate'] or '').strip() or None,
                    manual_rate_date=cd['manual_rate_date'], manual_note=cd['manual_note'], recalculate=True)
            except ConversionError as e:
                ctx['rate_error'] = str(e)
            else:
                messages.success(request, 'Payment recalculated. The previous rate remains on record.')
                return redirect('payment_detail', pk=pk)
    else:
        form = ConfirmRecalculateForm()
    return render(request, 'core/payment_recalculate.html', {'form': form, **ctx})
