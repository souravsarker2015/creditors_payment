from django.urls import path
from . import views

urlpatterns = [
    path("dashboard/", views.dashboard_view, name="expense_dashboard"),
    path("expenses/", views.expense_list_view, name="expense_list"),
    path("expenses/add/", views.expense_create_view, name="expense_create"),
    path("expenses/<int:pk>/edit/", views.expense_edit_view, name="expense_edit"),
    path("expenses/<int:pk>/delete/", views.expense_delete_view, name="expense_delete"),
    path("categories/", views.category_list_view, name="category_list"),
    path("categories/add/", views.category_create_view, name="category_create"),
    path("categories/<int:pk>/toggle-active/", views.category_toggle_active_view, name="category_toggle_active"),
    path("categories/import/", views.category_import_view, name="category_import"),
    path("categories/import/template/", views.category_import_template_view, name="category_import_template"),
    path("recurring/", views.recurring_expense_list_view, name="recurring_expense_list"),
    path("recurring/add/", views.recurring_expense_create_view, name="recurring_expense_create"),
    path("recurring/<int:pk>/edit/", views.recurring_expense_edit_view, name="recurring_expense_edit"),
    path("recurring/<int:pk>/toggle/", views.recurring_expense_toggle_view, name="recurring_expense_toggle"),
    path("recurring/<int:pk>/delete/", views.recurring_expense_delete_view, name="recurring_expense_delete"),
]
