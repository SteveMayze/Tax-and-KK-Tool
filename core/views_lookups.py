from django.contrib import messages
from django.utils.translation import gettext as _, gettext_lazy
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.urls import reverse
from django.shortcuts import get_object_or_404, redirect, render

from .forms import CategoryForm, OrganisationForm
from .models import IncomeCategory, Organisation
from .services import org_countries

CONFIG = {
    'organisation': {'model': Organisation, 'form': OrganisationForm, 'title': gettext_lazy('Organisations'),
                     'singular': gettext_lazy('organisation')},
    'category': {'model': IncomeCategory, 'form': CategoryForm, 'title': gettext_lazy('Income categories'),
                 'singular': gettext_lazy('category')},
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
        messages.success(request, _('%(item)s saved.') % {'item': str(cfg['singular']).capitalize()})
        return redirect(f'{kind}_list')
    return render(request, 'core/lookup_form.html', {'kind': kind, 'cfg': cfg, 'form': form, 'obj': obj})


@login_required
def lookup_delete(request, kind, pk):
    cfg = CONFIG[kind]
    obj = get_object_or_404(cfg['model'], pk=pk)
    used = obj.payments.count()
    if request.method == 'POST':
        if used:
            messages.error(request, _('"%(obj)s" is used by %(n)s payment(s). Deactivate it instead.') % {'obj': obj, 'n': used})
        else:
            obj.delete()
            messages.success(request, _('%(item)s deleted.') % {'item': str(cfg['singular']).capitalize()})
        return redirect(f'{kind}_list')
    return render(request, 'core/confirm_delete.html', {
        'what': f'{cfg["singular"]} "{obj}"',
        'consequence': (_('It is used by %(n)s payment(s) and cannot be deleted; deactivate it instead.') % {'n': used}
                        if used else _('This cannot be undone.')),
        'blocked': bool(used), 'cancel_href': reverse(f'{kind}_list', args=[])})


@login_required
def organisation_countries(request):
    """Proposes a country for organisations that have none, where every payment has the same non-EUR currency. Changes
    nothing until the owner ticks organisations and confirms (POST); the country applied is the server's own proposal."""
    proposals = org_countries.organisation_proposals()
    if request.method == 'POST':
        ticked = set(request.POST.getlist('org'))
        applied = 0
        for org, code, _ccy, _n in proposals:
            if str(org.pk) in ticked:
                org.country = code
                org.save()
                applied += 1
        messages.success(request, _('Country set for %(n)s organisation(s).') % {'n': applied})
        return redirect('organisation_countries')
    return render(request, 'core/organisation_countries.html', {'proposals': proposals})
