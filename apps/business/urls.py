"""Every business URL lives under /business/ in the "business" namespace.
Each sub-app adds its routes here as it's built."""
from django.urls import include, path

app_name = "business"

urlpatterns = [
    path("", include("apps.business.core.urls")),
    path("loans/", include("apps.business.loans.urls")),
]
