from django.urls import path
from . import views

urlpatterns = [
    path("dashboard/", views.dashboard_view, name="income_dashboard"),
    path("sources/", views.income_source_list_view, name="income_source_list"),
    path("sources/add/", views.income_source_create_view, name="income_source_create"),
    path("sources/import/", views.income_source_import_view, name="income_source_import"),
    path("sources/import/template/", views.income_source_import_template_view, name="income_source_import_template"),
    path("sources/<int:pk>/", views.income_source_detail_view, name="income_source_detail"),
    path("sources/<int:pk>/edit/", views.income_source_edit_view, name="income_source_edit"),
    path("sources/<int:pk>/statement/", views.income_source_statement_view, name="income_source_statement"),
    path("transactions/<int:pk>/edit/", views.transaction_edit_view, name="income_transaction_edit"),
    path("transactions/<int:pk>/delete/", views.transaction_delete_view, name="income_transaction_delete"),
]
