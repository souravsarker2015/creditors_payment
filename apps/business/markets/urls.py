from django.urls import include, path

from .views import deduction_types, markets

urlpatterns = [
    path("deduction-types/", include(deduction_types.urls())),
    *markets.urls(),
]
