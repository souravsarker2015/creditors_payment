from django.urls import path

from . import views

urlpatterns = [
    path("", views.wallet_list_view, name="wallet_list"),
    path("add/", views.wallet_form_view, name="wallet_create"),
    path("<int:pk>/", views.wallet_detail_view, name="wallet_detail"),
    path("<int:pk>/edit/", views.wallet_form_view, name="wallet_edit"),
    path("<int:pk>/correct/", views.correct_balance_view, name="wallet_correct"),
    path("<int:pk>/toggle/", views.wallet_toggle_view, name="wallet_toggle"),
    path("<int:pk>/delete/", views.wallet_delete_view, name="wallet_delete"),
    path("transfer/", views.transfer_form_view, name="wallet_transfer"),
    path("transfer/<int:pk>/edit/", views.transfer_form_view, name="wallet_transfer_edit"),
    path("transfer/<int:pk>/delete/", views.transfer_delete_view, name="wallet_transfer_delete"),
]
