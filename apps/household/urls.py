from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard_view, name="household_dashboard"),
    path("purchases/", views.purchase_list_view, name="household_list"),
    path("purchases/<int:year>/<int:month>/", views.month_detail_view, name="household_month_detail"),
    path("purchases/<int:pk>/edit/", views.purchase_edit_view, name="household_purchase_edit"),
    path("purchases/<int:pk>/delete/", views.purchase_delete_view, name="household_purchase_delete"),
    path("members/", views.member_list_view, name="household_member_list"),
    path("members/add/", views.member_create_view, name="household_member_create"),
    path("members/<int:pk>/", views.member_detail_view, name="household_member_detail"),
    path("members/<int:pk>/edit/", views.member_edit_view, name="household_member_edit"),
    path("settlements/<int:pk>/edit/", views.settlement_edit_view, name="household_settlement_edit"),
    path("settlements/<int:pk>/delete/", views.settlement_delete_view, name="household_settlement_delete"),
    path("categories/", views.category_list_view, name="household_category_list"),
    path("categories/add/", views.category_create_view, name="household_category_create"),
]
