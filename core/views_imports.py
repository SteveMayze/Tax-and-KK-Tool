from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from .forms import ImportRowForm, ImportUploadForm
from .models import ImportBatch, ImportRow
from .services import imports as svc
from .services.conversion import ConversionError, eur_amount, for_storage
from .services.rates import get_provider


def _preview_redirect(batch):
    return redirect('import_preview', pk=batch.pk)


def _proposed_eur(row):
    if row.rate is None:
        return None
    try:
        return for_storage(eur_amount(Decimal(row.data.get('gross_amount', '')), row.rate))
    except Exception:
        return None


@login_required
def import_list(request):
    return render(request, 'core/import_list.html', {
        'batches': ImportBatch.objects.all(), 'form': ImportUploadForm(), 'columns': svc.COLUMNS,
        'required': svc.REQUIRED})


@login_required
@require_POST
def import_upload(request):
    form = ImportUploadForm(request.POST, request.FILES)
    if form.is_valid():
        try:
            batch = svc.stage_batch(form.cleaned_data['file'].read(), form.cleaned_data['file'].name, get_provider())
        except svc.ImportFileError as e:
            form.add_error('file', str(e))
        else:
            messages.success(request, 'File read. Review the rows below; nothing has been imported yet.')
            return _preview_redirect(batch)
    return render(request, 'core/import_list.html', {
        'batches': ImportBatch.objects.all(), 'form': form, 'columns': svc.COLUMNS, 'required': svc.REQUIRED})


@login_required
def import_preview(request, pk):
    batch = get_object_or_404(ImportBatch, pk=pk)
    show = request.GET.get('show', 'all')
    rows = list(batch.rows.select_related('duplicate_of_payment__organisation', 'created_payment'))
    for r in rows:
        r.proposed_eur = _proposed_eur(r)
    if show == 'problems':
        rows = [r for r in rows if r.errors or r.status == ImportRow.Status.DUPLICATE or r.rate_error or r.notes]
    return render(request, 'core/import_preview.html', {
        'batch': batch, 'rows': rows, 'show': show, 'summary': svc.summary(batch),
        'editable': batch.status == ImportBatch.Status.PREVIEW})


def _state_guard(request, batch):
    if batch.status != ImportBatch.Status.PREVIEW:
        messages.error(request, f'This import is {batch.get_status_display().lower()} and can no longer be changed.')
        return _preview_redirect(batch)
    return None


@login_required
def import_row_edit(request, pk, line):
    batch = get_object_or_404(ImportBatch, pk=pk)
    blocked = _state_guard(request, batch)
    if blocked:
        return blocked
    row = get_object_or_404(ImportRow, batch=batch, line_number=line)
    initial = {c: row.data.get(c, '') for c in svc.COLUMNS}
    form = ImportRowForm(request.POST or None, initial=initial)
    if request.method == 'POST' and form.is_valid():
        svc.update_row(row, form.cleaned_data, get_provider())
        messages.success(request, f'Line {line} updated and re-checked.')
        return _preview_redirect(batch)
    row.refresh_from_db()
    return render(request, 'core/import_row_form.html', {'batch': batch, 'row': row, 'form': form})


@login_required
@require_POST
def import_row_toggle(request, pk, line, action):
    batch = get_object_or_404(ImportBatch, pk=pk)
    blocked = _state_guard(request, batch)
    if blocked:
        return blocked
    row = get_object_or_404(ImportRow, batch=batch, line_number=line)
    if action == 'exclude':
        svc.set_excluded(row, True, get_provider())
    elif action == 'include':
        svc.set_excluded(row, False, get_provider())
    elif action == 'keep':
        svc.set_keep_duplicate(row, True)
    elif action == 'skip':
        svc.set_keep_duplicate(row, False)
    else:
        raise Http404
    return _preview_redirect(batch)


@login_required
@require_POST
def import_refresh_rates(request, pk):
    batch = get_object_or_404(ImportBatch, pk=pk)
    blocked = _state_guard(request, batch)
    if blocked:
        return blocked
    svc.refresh_rates(batch, get_provider())
    messages.success(request, 'Exchange rates requested again for all importable rows.')
    return _preview_redirect(batch)


@login_required
def import_commit(request, pk):
    batch = get_object_or_404(ImportBatch, pk=pk)
    blocked = _state_guard(request, batch)
    if blocked:
        return blocked
    summary = svc.summary(batch)
    if request.method == 'POST':
        if summary['invalid']:
            messages.error(request, f'{summary["invalid"]} row(s) are still invalid. Fix or exclude them first.')
            return _preview_redirect(batch)
        if not summary['importing']:
            messages.error(request, 'There is nothing to import.')
            return _preview_redirect(batch)
        try:
            svc.commit_batch(batch)
        except (svc.ImportStateError, ConversionError, ValidationError) as e:
            messages.error(request, f'Nothing was imported: {e}')
            return _preview_redirect(batch)
        messages.success(request, f'Imported {batch.imported_count} payment(s).')
        return _preview_redirect(batch)
    return render(request, 'core/import_commit.html', {'batch': batch, 'summary': summary})


@login_required
def import_discard(request, pk):
    batch = get_object_or_404(ImportBatch, pk=pk)
    blocked = _state_guard(request, batch)
    if blocked:
        return blocked
    if request.method == 'POST':
        svc.discard_batch(batch)
        messages.success(request, 'Import discarded. Staged rows and the stored file were removed.')
        return redirect('import_list')
    return render(request, 'core/import_discard.html', {'batch': batch})


@login_required
@require_GET
def import_file(request, pk):
    """The original upload, only for the logged-in user; there is no public URL for it."""
    batch = get_object_or_404(ImportBatch, pk=pk)
    path = svc.upload_path(batch)
    if path is None:
        raise Http404('File is not available.')
    response = FileResponse(open(path, 'rb'), as_attachment=True, filename=f'import-{batch.pk}.csv',
                            content_type='text/csv; charset=utf-8')
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@login_required
@require_GET
def import_template(request):
    response = HttpResponse(svc.TEMPLATE_CSV, content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="payments-import-template.csv"'
    return response
