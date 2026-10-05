from django.urls import path

from . import views
from .views import partners

urlpatterns = partners.urls() + [
    path("<int:pk>/", views.partner_detail_view, name="partner_detail"),
    path("<int:partner_pk>/money/", views.entry_form_view, name="partner_entry"),
    path("money/<int:pk>/edit/", views.entry_form_view, name="partner_entry_edit"),
    path("money/<int:pk>/delete/", views.entry_delete_view, name="partner_entry_delete"),
    path("sharing/", views.sharing_view, name="partner_sharing"),
]
