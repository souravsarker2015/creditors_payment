"""Every business URL lives under /business/ in the "business" namespace.
Each sub-app adds its routes here as it's built."""
from django.urls import include, path

app_name = "business"

urlpatterns = [
    path("", include("apps.business.core.urls")),
    path("loans/", include("apps.business.loans.urls")),
    path("ponds/", include("apps.business.ponds.urls")),
    path("species/", include("apps.business.species.urls")),
    path("markets/", include("apps.business.markets.urls")),
    path("people/", include("apps.business.parties.urls")),
    path("feed/", include("apps.business.feed.urls")),
    path("finance/", include("apps.business.finance.urls")),
    path("sales/", include("apps.business.sales.urls")),
    path("baki/", include("apps.business.credit.urls")),
]
