from django.urls import path
from . import views

urlpatterns = [
    path("signup/", views.signup_view, name="signup"),
    path("login/", views.login_view, name="login"),
    path("login/code/", views.two_factor_verify_view, name="two_factor_verify"),
    path("logout/", views.logout_view, name="logout"),
    path("preferences/", views.update_preferences_view, name="update_preferences"),
    path("account/", views.account_view, name="account_settings"),
    path("account/two-step/", views.two_factor_setup_view, name="two_factor_setup"),
    path("account/two-step/off/", views.two_factor_disable_view, name="two_factor_disable"),
    path("account/two-step/recovery-codes/", views.two_factor_recovery_view, name="two_factor_recovery"),
    path("account/two-step/forget-devices/", views.two_factor_forget_devices_view, name="two_factor_forget_devices"),
    path("account/sign-ins/<int:pk>/out/", views.sign_out_device_view, name="sign_out_device"),
    path("account/sign-ins/out-everywhere-else/", views.sign_out_others_view, name="sign_out_others"),
    path("users/", views.user_list_view, name="user_list"),
    path("users/add/", views.user_create_view, name="user_create"),
    path("users/<int:pk>/", views.user_edit_view, name="user_edit"),
    path("password/forgot/", views.PasswordResetView.as_view(), name="password_reset"),
    path("password/forgot/sent/", views.PasswordResetDoneView.as_view(), name="password_reset_done"),
    path("password/reset/<uidb64>/<token>/", views.PasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("password/reset/done/", views.PasswordResetCompleteView.as_view(), name="password_reset_complete"),
]
