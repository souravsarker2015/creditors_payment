from django.urls import path
from . import views

urlpatterns = [
    path("dashboard/", views.dashboard_view, name="income_dashboard"),
    path("sources/", views.income_source_list_view, name="income_source_list"),
    path("sources/add/", views.income_source_create_view, name="income_source_create"),
    path("sources/<int:pk>/", views.income_source_detail_view, name="income_source_detail"),
    path("sources/<int:pk>/edit/", views.income_source_edit_view, name="income_source_edit"),
    path("transactions/<int:pk>/edit/", views.transaction_edit_view, name="income_transaction_edit"),
    path("transactions/<int:pk>/delete/", views.transaction_delete_view, name="income_transaction_delete"),
]
