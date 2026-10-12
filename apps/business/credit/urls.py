from django.urls import path

from . import views

urlpatterns = [
    path("", views.due_list_view, name="dues"),
    path("party/<int:pk>/", views.statement_view, name="party_statement"),
    path("party/<int:pk>/follow-up/", views.follow_up_view, name="party_follow_up"),
    path("payments/", views.payment_list_view, name="payments"),
    path("payments/add/", views.payment_form_view, name="payment_add"),
    path("advances/add/", views.advance_form_view, name="advance_add"),
    path("advances/<int:pk>/edit/", views.advance_form_view, name="advance_edit"),
    path("payments/<int:pk>/edit/", views.payment_form_view, name="payment_edit"),
    path("payments/<int:pk>/delete/", views.payment_delete_view, name="payment_delete"),
    path("payments/<int:pk>/restore/", views.payment_restore_view, name="payment_restore"),
]
