from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard_view, name="shop_dashboard"),
    path("list/", views.shop_list_view, name="shop_list"),
    path("add/", views.shop_create_view, name="shop_create"),
    path("import/", views.shop_import_view, name="shop_import"),
    path("import/template/", views.shop_import_template_view, name="shop_import_template"),
    path("<int:pk>/", views.shop_detail_view, name="shop_detail"),
    path("<int:pk>/edit/", views.shop_edit_view, name="shop_edit"),
    path("<int:pk>/statement/", views.shop_statement_view, name="shop_statement"),
    path("transactions/<int:pk>/edit/", views.transaction_edit_view, name="shop_transaction_edit"),
    path("transactions/<int:pk>/delete/", views.transaction_delete_view, name="shop_transaction_delete"),
]
