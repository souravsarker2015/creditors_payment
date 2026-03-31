from django.urls import path
from . import views

urlpatterns = [
    path("dashboard/", views.dashboard_view, name="debtor_dashboard"),
    path("debtors/", views.debtor_list_view, name="debtor_list"),
    path("debtors/add/", views.debtor_create_view, name="debtor_create"),
    path("debtors/<int:pk>/", views.debtor_detail_view, name="debtor_detail"),
    path("debtors/<int:pk>/edit/", views.debtor_edit_view, name="debtor_edit"),
]
