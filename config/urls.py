"""
Root URL configuration for creditors_payment project.

Add app-level URL includes below.
"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.creditors.urls")),
    path("debtors/", include("apps.debtors.urls")),
    path("accounts/", include("apps.accounts.urls")),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# django-debug-toolbar URLs (dev only)
if settings.DEBUG:
    try:
        import debug_toolbar

        urlpatterns += [path("__debug__/", include(debug_toolbar.urls))]
    except ImportError:
        pass
