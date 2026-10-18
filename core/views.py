from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET


@login_required
def home(request):
    return render(request, 'core/home.html')


@require_GET
def health(request):
    """Unauthenticated liveness check. Returns no data beyond status."""
    return JsonResponse({'status': 'ok'})
