from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard_view, name="dashboard"),
    path("signup/", views.signup_view, name="signup"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("creditors/", views.creditor_list_view, name="creditor_list"),
]
