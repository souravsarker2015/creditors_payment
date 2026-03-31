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
]
