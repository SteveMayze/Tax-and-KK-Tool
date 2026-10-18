from django.conf import settings
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('accounts/', include('django.contrib.auth.urls')),
    path('', include('core.urls')),
]
if settings.ENABLE_ADMIN:
    urlpatterns.insert(0, path('admin/', admin.site.urls))
