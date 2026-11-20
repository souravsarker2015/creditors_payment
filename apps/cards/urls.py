from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard_view, name="card_dashboard"),
    path("add/", views.card_form_view, name="card_create"),
    path("record/<slug:kind>/", views.entry_add_view, name="card_entry_new"),
    path("<int:pk>/", views.card_detail_view, name="card_detail"),
    path("<int:pk>/edit/", views.card_form_view, name="card_edit"),
    path("<int:pk>/toggle/", views.card_toggle_view, name="card_toggle"),
    path("<int:pk>/delete/", views.card_delete_view, name="card_delete"),
    path("<int:pk>/correct/", views.card_correct_view, name="card_correct"),
    path("<int:pk>/record/<slug:kind>/", views.entry_add_view, name="card_entry_add"),
    path("<int:pk>/emi/", views.emi_form_view, name="card_emi_add"),
    path("emi/", views.emi_form_view, name="card_emi_new"),
    path("emi/<int:emi>/", views.emi_form_view, name="card_emi_edit"),
    path("emi/<int:emi>/payoff/", views.emi_payoff_view, name="card_emi_payoff"),
    path("emi/<int:emi>/delete/", views.emi_delete_view, name="card_emi_delete"),
    path("entry/<int:pk>/", views.entry_edit_view, name="card_entry_edit"),
    path("entry/<int:pk>/delete/", views.entry_delete_view, name="card_entry_delete"),
    path("lists/", views.lists_view, name="card_lists"),
    path("mobile-banking/", views.mfs_view, name="card_mfs"),
    path("mobile-banking/add/", views.mfs_add_view, name="card_mfs_add"),
    path("mobile-banking/<int:wallet>/", views.mfs_detail_view, name="card_mfs_detail"),
]
