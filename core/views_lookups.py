from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.urls import reverse
from django.shortcuts import get_object_or_404, redirect, render

from .forms import CategoryForm, OrganisationForm
from .models import IncomeCategory, Organisation

CONFIG = {
    'organisation': {'model': Organisation, 'form': OrganisationForm, 'title': 'Organisations', 'singular': 'organisation'},
    'category': {'model': IncomeCategory, 'form': CategoryForm, 'title': 'Income categories', 'singular': 'category'},
}


@login_required
def lookup_list(request, kind):
    cfg = CONFIG[kind]
    rows = cfg['model'].objects.annotate(payment_count=Count('payments'))
    return render(request, 'core/lookup_list.html', {'kind': kind, 'cfg': cfg, 'rows': rows})


@login_required
def lookup_edit(request, kind, pk=None):
    cfg = CONFIG[kind]
    obj = get_object_or_404(cfg['model'], pk=pk) if pk else None
    form = cfg['form'](request.POST or None, instance=obj)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, f'{cfg["singular"].capitalize()} saved.')
        return redirect(f'{kind}_list')
    return render(request, 'core/lookup_form.html', {'kind': kind, 'cfg': cfg, 'form': form, 'obj': obj})


@login_required
def lookup_delete(request, kind, pk):
    cfg = CONFIG[kind]
    obj = get_object_or_404(cfg['model'], pk=pk)
    used = obj.payments.count()
    if request.method == 'POST':
        if used:
            messages.error(request, f'"{obj}" is used by {used} payment(s). Deactivate it instead.')
        else:
            obj.delete()
            messages.success(request, f'{cfg["singular"].capitalize()} deleted.')
        return redirect(f'{kind}_list')
    return render(request, 'core/confirm_delete.html', {
        'what': f'{cfg["singular"]} "{obj}"',
        'consequence': (f'It is used by {used} payment(s) and cannot be deleted; deactivate it instead.'
                        if used else 'This cannot be undone.'),
        'blocked': bool(used), 'cancel_href': reverse(f'{kind}_list', args=[])})
