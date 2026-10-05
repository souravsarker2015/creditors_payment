from django.urls import include, path

from . import views
from .views import deduction_types, markets

urlpatterns = [
    path("deduction-types/", include(deduction_types.urls())),
    path("prices/", views.prices_view, name="prices"),
    path("prices/<int:pk>/delete/", views.price_delete_view, name="price_delete"),
    *markets.urls(),
]
