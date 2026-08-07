from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard_view, name="dashboard"),
    path("creditors/", views.creditor_list_view, name="creditor_list"),
    path("creditors/add/", views.creditor_create_view, name="creditor_create"),
    path("creditors/import/", views.creditor_import_view, name="creditor_import"),
    path("creditors/import/template/", views.creditor_import_template_view, name="creditor_import_template"),
    path("creditors/<int:pk>/", views.creditor_detail_view, name="creditor_detail"),
    path("creditors/<int:pk>/edit/", views.creditor_edit_view, name="creditor_edit"),
    path("creditors/<int:pk>/statement/", views.creditor_statement_view, name="creditor_statement"),
    path("creditors/<int:pk>/post-interest/", views.creditor_post_interest_view, name="creditor_post_interest"),
    path("transactions/<int:pk>/edit/", views.transaction_edit_view, name="transaction_edit"),
    path("transactions/<int:pk>/delete/", views.transaction_delete_view, name="transaction_delete"),
]
