from django.urls import path
from . import views

urlpatterns = [
    path("signup/", views.signup_view, name="signup"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("preferences/", views.update_preferences_view, name="update_preferences"),
    path("account/", views.account_view, name="account_settings"),
    path("password/forgot/", views.PasswordResetView.as_view(), name="password_reset"),
    path("password/forgot/sent/", views.PasswordResetDoneView.as_view(), name="password_reset_done"),
    path("password/reset/<uidb64>/<token>/", views.PasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("password/reset/done/", views.PasswordResetCompleteView.as_view(), name="password_reset_complete"),
]
