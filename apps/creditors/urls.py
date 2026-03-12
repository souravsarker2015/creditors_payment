from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard_view, name="dashboard"),
    path("signup/", views.signup_view, name="signup"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("creditors/", views.creditor_list_view, name="creditor_list"),
    path("creditors/add/", views.creditor_create_view, name="creditor_create"),
    path("creditors/<int:pk>/", views.creditor_detail_view, name="creditor_detail"),
    path("creditors/<int:pk>/edit/", views.creditor_edit_view, name="creditor_edit"),
]
