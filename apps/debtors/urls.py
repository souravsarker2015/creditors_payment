from django.urls import path
from . import views

urlpatterns = [
    path("dashboard/", views.dashboard_view, name="debtor_dashboard"),
    path("debtors/", views.debtor_list_view, name="debtor_list"),
    path("debtors/add/", views.debtor_create_view, name="debtor_create"),
    path("debtors/import/", views.debtor_import_view, name="debtor_import"),
    path("debtors/import/template/", views.debtor_import_template_view, name="debtor_import_template"),
    path("debtors/<int:pk>/", views.debtor_detail_view, name="debtor_detail"),
    path("debtors/<int:pk>/toggle-active/", views.debtor_toggle_active_view, name="debtor_toggle_active"),
    path("debtors/<int:pk>/edit/", views.debtor_edit_view, name="debtor_edit"),
    path("debtors/<int:pk>/statement/", views.debtor_statement_view, name="debtor_statement"),
    path("transactions/<int:pk>/edit/", views.transaction_edit_view, name="debtor_transaction_edit"),
    path("transactions/<int:pk>/delete/", views.transaction_delete_view, name="debtor_transaction_delete"),
]
