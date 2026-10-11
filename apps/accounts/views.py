import logging

from django.conf import settings
from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib import messages
from django.core.mail import send_mail
from django.http import HttpResponse, HttpResponseRedirect
from django.template.loader import render_to_string
from django.urls import reverse, reverse_lazy
from django.utils import timezone, translation
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from .forms import EmailChangeForm, LoginForm, SignupForm, ThrottledPasswordResetForm
from .models import AccentTheme, BackgroundTheme, Language, ThemeMode, UserProfile, ViewMode

logger = logging.getLogger(__name__)


def _safe_next(request):
    """Where to go after signing in: the page that asked for it, if it's ours."""
    nxt = request.POST.get("next") or request.GET.get("next") or ""
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return nxt
    return ""


def notify_password_changed(request, user):
    """Tell the owner by email that their password was changed, so a change
    they didn't make doesn't go unnoticed. Never blocks the change itself."""
    if not user.email:
        return
    ctx = {"user": user, "when": timezone.localtime(), "reset_url": request.build_absolute_uri(reverse("password_reset"))}
    try:
        send_mail(
            _("Your FinTrack password was changed"),
            render_to_string("accounts/email/password_changed.txt", ctx, request=request),
            None, [user.email], fail_silently=False,
        )
    except Exception:  # noqa: BLE001 — a mail outage mustn't undo the change
        logger.exception("Couldn't send the password-changed notice to user %s", user.pk)


def signup_view(request):
    if request.method == "POST":
        form = SignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user, backend="apps.accounts.backends.UsernameOrEmailBackend")
            messages.success(request, _("Account created successfully!"))
            return redirect("home")
    else:
        form = SignupForm()
    return render(request, "accounts/signup.html", {"form": form})


def login_view(request):
    if request.method == "POST":
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            # Remember me: keep the sign-in for SESSION_COOKIE_AGE (30 days);
            # otherwise it ends when the browser is closed.
            request.session.set_expiry(None if form.cleaned_data.get("remember_me") else 0)
            profile, _created = UserProfile.objects.get_or_create(user=user)
            translation.activate(profile.language)
            messages.success(request, _("Welcome back, %(username)s!") % {"username": user.username})
            response = redirect(_safe_next(request) or "home")
            response.set_cookie(settings.LANGUAGE_COOKIE_NAME, profile.language)
            return response
    else:
        form = LoginForm(request)
    return render(request, "accounts/login.html", {"form": form, "next": _safe_next(request)})


def logout_view(request):
    logout(request)
    messages.info(request, _("You have been logged out."))
    response = redirect("login")
    # Pages kept on the phone for working offline hold this person's figures.
    response["Clear-Site-Data"] = '"cache"'
    return response


@login_required
@require_POST
def update_preferences_view(request):
    """Persist theme/accent/background/language to the user's profile.

    Any of the fields may be posted; only the ones present are
    updated. A language change also activates the new language for this
    response and sets the language cookie Django's LocaleMiddleware reads,
    so the redirect below re-renders fully translated.
    """
    profile, _created = UserProfile.objects.get_or_create(user=request.user)

    theme_mode = request.POST.get("theme_mode")
    accent = request.POST.get("accent")
    background = request.POST.get("background")
    language = request.POST.get("language")
    view_mode = request.POST.get("view_mode")

    if view_mode in ViewMode.values:
        profile.view_mode = view_mode
    if theme_mode in ThemeMode.values:
        profile.theme_mode = theme_mode
    if accent in AccentTheme.values:
        profile.accent = accent
    if background in BackgroundTheme.values:
        profile.background = background
    if language in Language.values:
        profile.language = language
        translation.activate(language)

    profile.save()

    # Theme/accent/background/view-only changes are fired from JS as a background request —
    # the toggle already applied itself instantly client-side, so there's
    # nothing to re-render. A language change needs a real navigation
    # because translated strings are resolved server-side.
    if request.headers.get("X-Preferences-Fetch") == "1" and language not in Language.values:
        return HttpResponse(status=204)

    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or reverse("home")
    response = HttpResponseRedirect(next_url)
    if language in Language.values:
        response.set_cookie(settings.LANGUAGE_COOKIE_NAME, language)
    return response


# ── Account: email and password ───────────────────────────────────────────
@login_required
def account_view(request):
    user = request.user
    email_form = EmailChangeForm(user, prefix="email")
    password_form = PasswordChangeForm(user, prefix="pw")
    if request.method == "POST":
        if request.POST.get("action") == "email":
            email_form = EmailChangeForm(user, request.POST, prefix="email")
            if email_form.is_valid():
                email_form.save()
                messages.success(request, _("Email saved. If you forget your password, a reset link will go to %(email)s.") % {"email": user.email})
                return redirect("account_settings")
        elif request.POST.get("action") == "password":
            password_form = PasswordChangeForm(user, request.POST, prefix="pw")
            if password_form.is_valid():
                password_form.save()
                update_session_auth_hash(request, password_form.user)   # stay signed in here
                notify_password_changed(request, password_form.user)
                messages.success(request, _("Password changed."))
                return redirect("account_settings")
    return render(request, "accounts/account.html", {"email_form": email_form, "password_form": password_form})


# ── Forgot password (Django's reset flow, in the app's look) ──────────────
class PasswordResetView(auth_views.PasswordResetView):
    form_class = ThrottledPasswordResetForm
    template_name = "accounts/password_reset.html"
    email_template_name = "accounts/email/password_reset.txt"
    html_email_template_name = "accounts/email/password_reset.html"
    subject_template_name = "accounts/email/password_reset_subject.txt"
    success_url = reverse_lazy("password_reset_done")


class PasswordResetDoneView(auth_views.PasswordResetDoneView):
    template_name = "accounts/password_reset_done.html"


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("password_reset_complete")

    def form_valid(self, form):
        response = super().form_valid(form)
        notify_password_changed(self.request, form.user)
        return response


class PasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    template_name = "accounts/password_reset_complete.html"
