from django.urls import path

from . import views

urlpatterns = [
    path("", views.sale_list_view, name="sales"),
    path("add/", views.sale_form_view, name="sale_add"),
    path("deleted/", views.sale_deleted_view, name="sales_deleted"),
    path("<int:pk>/", views.sale_detail_view, name="sale_detail"),
    path("<int:pk>/edit/", views.sale_form_view, name="sale_edit"),
    path("<int:pk>/delete/", views.sale_delete_view, name="sale_delete"),
    path("<int:pk>/restore/", views.sale_restore_view, name="sale_restore"),
]
