from django.urls import path

from . import views
from .views import supplies

urlpatterns = supplies.urls() + [
    path("<int:pk>/", views.item_detail_view, name="supply_detail"),
    path("<int:item_pk>/buy/", views.purchase_form_view, name="supply_buy"),
    path("purchases/<int:pk>/edit/", views.purchase_form_view, name="supply_purchase_edit"),
    path("purchases/<int:pk>/delete/", views.purchase_delete_view, name="supply_purchase_delete"),
]
