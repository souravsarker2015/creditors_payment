"""
Root URL configuration for creditors_payment project.

Add app-level URL includes below.
"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from apps.core.pwa import manifest_view, offline_view, service_worker_view

urlpatterns = [
    path("admin/", admin.site.urls),
    # Installable app: must live at the root so the service worker covers every page.
    path("manifest.webmanifest", manifest_view, name="manifest"),
    path("sw.js", service_worker_view, name="service_worker"),
    path("offline/", offline_view, name="offline"),
    path("", include("apps.creditors.urls")),
    path("networth/", include("apps.overview.urls")),
    path("debtors/", include("apps.debtors.urls")),
    path("accounts/", include("apps.accounts.urls")),
    path("income/", include("apps.income.urls")),
    path("expense/", include("apps.expense.urls")),
    path("contributors/", include("apps.contributors.urls")),
    path("household/", include("apps.household.urls")),
    path("shops/", include("apps.shops.urls")),
    path("core/", include("apps.core.urls")),
    path("budgets/", include("apps.budgets.urls")),
    path("goals/", include("apps.goals.urls")),
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
