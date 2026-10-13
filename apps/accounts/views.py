import logging
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, logout, update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse, reverse_lazy
from django.utils import timezone, translation
from django.utils.encoding import force_bytes
from django.utils.http import url_has_allowed_host_and_scheme, urlsafe_base64_encode
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from . import signins, totp, twofactor
from .forms import (
    CodeForm, EmailChangeForm, LoginForm, PasswordAndCodeForm, ProfileForm, SecuritySettingsForm, SignupForm,
    ThrottledPasswordResetForm, TwoFactorVerifyForm, UserAdminForm, UserCreateForm,
)
from .models import AccentTheme, BackgroundTheme, Language, SecuritySettings, ThemeMode, TwoFactor, UserProfile, ViewMode

logger = logging.getLogger(__name__)
User = get_user_model()


def _safe_next(request):
    """Where to go after signing in: the page that asked for it, if it's ours."""
    nxt = request.POST.get("next") or request.GET.get("next") or ""
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return nxt
    return ""


def notify_password_changed(request, user):
    twofactor.notify(request, user, _("Your FinTrack password was changed"),
                     _("The password of your FinTrack account was changed on %(when)s.") % {"when": twofactor.when_text()})


def send_set_password_email(request, user, welcome=False):
    """Email a one-day link to choose a password (a new account, or an admin
    sending someone a reset). Returns True when it went out."""
    link = request.build_absolute_uri(reverse("password_reset_confirm", kwargs={
        "uidb64": urlsafe_base64_encode(force_bytes(user.pk)), "token": default_token_generator.make_token(user)}))
    ctx = {"user": user, "link": link, "welcome": welcome, "login_url": request.build_absolute_uri(reverse("login"))}
    subject = _("Your FinTrack account is ready") if welcome else _("Reset your FinTrack password")
    try:
        send_mail(subject, render_to_string("accounts/email/set_password.txt", ctx, request=request), None, [user.email])
        return True
    except Exception:  # noqa: BLE001
        logger.exception("Couldn't send the set-password email to user %s", user.pk)
        return False


def signup_view(request):
    if request.method == "POST":
        form = SignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, _("Account created successfully!"))
            return twofactor.finish_login(request, user, True, lambda: redirect("home"), new_account=True)
    else:
        form = SignupForm()
    return render(request, "accounts/signup.html", {"form": form})


def login_view(request):
    """Step one: the password. With two-step sign-in on (and this device not
    trusted), step two asks for the code before anyone is signed in."""
    if request.method == "POST":
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            remember, nxt = form.cleaned_data.get("remember_me"), _safe_next(request)
            tf = twofactor.enabled_for(user)
            if tf and not twofactor.is_trusted(request, user, tf):
                twofactor.start_pending(request, user, remember, nxt)
                return redirect("two_factor_verify")
            messages.success(request, _("Welcome back, %(username)s!") % {"username": user.username})
            return twofactor.finish_login(request, user, remember, lambda: redirect(nxt or "home"))
    else:
        form = LoginForm(request)
    return render(request, "accounts/login.html", {"form": form, "next": _safe_next(request)})


def two_factor_verify_view(request):
    user, pending = twofactor.pending_user(request)
    if user is None:
        messages.info(request, _("Please sign in again."))
        return redirect("login")
    tf = twofactor.enabled_for(user)
    if tf is None:   # turned off in the meantime
        return twofactor.finish_login(request, user, pending["remember"], lambda: redirect(pending["next"] or "home"))
    form = TwoFactorVerifyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        how = twofactor.check_code(tf, form.cleaned_data["code"])
        if how:
            nxt = pending["next"] or "home"
            response = twofactor.finish_login(request, user, pending["remember"], lambda: redirect(nxt))
            if form.cleaned_data.get("trust"):
                twofactor.trust_device(response, request, user, tf)
            if how == "recovery":
                left = tf.recovery_left
                messages.warning(request, _("You signed in with a recovery code. %(left)s left — make new ones from Account & security if you're running low.") % {"left": left})
                twofactor.notify(request, user, _("A recovery code was used on your FinTrack account"),
                                 _("Someone signed in to your FinTrack account with a recovery code on %(when)s. %(left)s codes are left.") % {"when": twofactor.when_text(), "left": left})
            else:
                messages.success(request, _("Welcome back, %(username)s!") % {"username": user.username})
            return response
        pending["tries"] = pending.get("tries", 0) + 1
        request.session[twofactor.PENDING] = pending
        if pending["tries"] >= twofactor.MAX_TRIES:
            request.session.pop(twofactor.PENDING, None)
            messages.error(request, _("Too many wrong codes. Sign in again."))
            return redirect("login")
        form.add_error("code", _("That code isn't right. Check the time on your phone, and use the newest code."))
    return render(request, "accounts/two_factor_verify.html", {"form": form, "pending_user": user})


def logout_view(request):
    signins.ended(request)
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


# ── Account & security ────────────────────────────────────────────────────
@login_required
def account_view(request):
    user = request.user
    profile_form = ProfileForm(instance=user, prefix="profile")
    email_form = EmailChangeForm(user, prefix="email")
    password_form = PasswordChangeForm(user, prefix="pw")
    policy = SecuritySettings.load()
    policy_form = SecuritySettingsForm(instance=policy, prefix="policy") if user.is_superuser else None
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "profile":
            profile_form = ProfileForm(request.POST, instance=user, prefix="profile")
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, _("Profile saved."))
                return redirect("account_settings")
        elif action == "email":
            email_form = EmailChangeForm(user, request.POST, prefix="email")
            if email_form.is_valid():
                email_form.save()
                messages.success(request, _("Email saved. If you forget your password, a reset link will go to %(email)s.") % {"email": user.email})
                return redirect(reverse("account_settings") + "#email")
        elif action == "password":
            password_form = PasswordChangeForm(user, request.POST, prefix="pw")
            if password_form.is_valid():
                password_form.save()
                update_session_auth_hash(request, password_form.user)   # stay signed in here
                signins.touch(request)
                notify_password_changed(request, password_form.user)
                messages.success(request, _("Password changed."))
                return redirect(reverse("account_settings") + "#password")
        elif action == "policy" and user.is_superuser:
            policy_form = SecuritySettingsForm(request.POST, instance=policy, prefix="policy")
            if policy_form.is_valid():
                policy = policy_form.save(commit=False)
                policy.updated_by = user
                policy.save()
                messages.success(request, _("Security settings saved."))
                return redirect(reverse("account_settings") + "#policy")
    tf = twofactor.get_two_factor(user)
    return render(request, "accounts/account.html", {
        "profile_form": profile_form, "email_form": email_form, "password_form": password_form,
        "policy_form": policy_form, "policy": policy, "tf": tf if tf and tf.enabled else None,
        "two_factor_required": policy.requires_two_factor(user),
        "sign_ins": signins.active(user, request), "recent_sign_ins": signins.recent(user),
    })


@login_required
@require_POST
def sign_out_device_view(request, pk):
    if pk == request.session.get(signins.SESSION_KEY):
        return logout_view(request)
    if signins.sign_out(request.user, pk):
        messages.success(request, _("That device is signed out."))
    return redirect(reverse("account_settings") + "#sign-ins")


@login_required
@require_POST
def sign_out_others_view(request):
    n = signins.sign_out_others(request.user, request)
    if n:
        messages.success(request, _("Signed out everywhere else (%(count)s).") % {"count": n})
    else:
        messages.info(request, _("You weren't signed in anywhere else."))
    return redirect(reverse("account_settings") + "#sign-ins")


# ── Two-step sign-in: turn on, recovery codes, turn off ───────────────────
SETUP_SECRET = "2fa_setup_secret"


@login_required
def two_factor_setup_view(request):
    user = request.user
    if twofactor.enabled_for(user):
        return redirect(reverse("account_settings") + "#two-factor")
    secret = request.session.get(SETUP_SECRET)
    if not secret or request.GET.get("new"):
        secret = request.session[SETUP_SECRET] = totp.new_secret()
    form = CodeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        step = totp.verify(secret, form.cleaned_data["code"])
        if step is None:
            form.add_error("code", _("That code isn't right. Scan the QR code again, and type the newest code from the app."))
        else:
            codes = totp.new_recovery_codes()
            tf, _created = TwoFactor.objects.get_or_create(user=user, defaults={"secret": secret})
            tf.secret, tf.enabled, tf.enabled_at, tf.last_step = secret, True, timezone.now(), step
            tf.recovery_codes = [totp.hash_code(c) for c in codes]
            tf.generation += 1
            tf.save()
            request.session.pop(SETUP_SECRET, None)
            twofactor.notify(request, user, _("Two-step sign-in is on for your FinTrack account"),
                             _("Two-step sign-in was turned on for your FinTrack account on %(when)s. From now on, signing in also needs a code from your authenticator app.") % {"when": twofactor.when_text()})
            messages.success(request, _("Two-step sign-in is on."))
            return render(request, "accounts/two_factor_codes.html", {"codes": codes, "first_time": True})
    account = user.email or user.get_username()
    return render(request, "accounts/two_factor_setup.html", {
        "form": form, "secret": secret, "secret_groups": [secret[i:i + 4] for i in range(0, len(secret), 4)],
        "uri": totp.provisioning_uri(secret, account),
        "required": SecuritySettings.load().requires_two_factor(user),
    })


@login_required
@require_POST
def two_factor_recovery_view(request):
    """New recovery codes (the old ones stop working). Needs a current code."""
    tf = twofactor.enabled_for(request.user)
    if tf is None:
        return redirect("account_settings")
    form = CodeForm(request.POST)
    if form.is_valid() and twofactor.check_code(tf, form.cleaned_data["code"], allow_recovery=False):
        codes = totp.new_recovery_codes()
        tf.recovery_codes = [totp.hash_code(c) for c in codes]
        tf.save(update_fields=["recovery_codes"])
        return render(request, "accounts/two_factor_codes.html", {"codes": codes, "first_time": False})
    messages.error(request, _("That code isn't right, so no new recovery codes were made."))
    return redirect(reverse("account_settings") + "#two-factor")


@login_required
@require_POST
def two_factor_forget_devices_view(request):
    tf = twofactor.enabled_for(request.user)
    if tf:
        tf.generation += 1
        tf.save(update_fields=["generation"])
        messages.success(request, _("Done. Every device will ask for a code at the next sign-in."))
    return redirect(reverse("account_settings") + "#two-factor")


@login_required
def two_factor_disable_view(request):
    user = request.user
    tf = twofactor.enabled_for(user)
    if tf is None:
        return redirect("account_settings")
    if SecuritySettings.load().requires_two_factor(user):
        messages.error(request, _("Two-step sign-in is required for your account, so it can't be turned off."))
        return redirect(reverse("account_settings") + "#two-factor")
    form = PasswordAndCodeForm(user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        if twofactor.check_code(tf, form.cleaned_data["code"]):
            tf.delete()
            twofactor.notify(request, user, _("Two-step sign-in is off for your FinTrack account"),
                             _("Two-step sign-in was turned off for your FinTrack account on %(when)s. Signing in now needs only the password.") % {"when": twofactor.when_text()})
            messages.success(request, _("Two-step sign-in is off."))
            return redirect(reverse("account_settings") + "#two-factor")
        form.add_error("code", _("That code isn't right."))
    return render(request, "accounts/two_factor_disable.html", {"form": form})


# ── Admin: people who use this app ────────────────────────────────────────
def _admin_only(view):
    return login_required(user_passes_test(lambda u: u.is_superuser, login_url="login")(view))


def _page_window(page, around=2):
    """Page numbers to show: first, last and a few around the current one (None = a gap)."""
    total, current = page.paginator.num_pages, page.number
    pages = sorted({1, total} | {n for n in range(current - around, current + around + 1) if 1 <= n <= total})
    out, prev = [], None
    for n in pages:
        if prev is not None and n - prev > 1:
            out.append(None)
        out.append(n)
        prev = n
    return out


@_admin_only
def user_list_view(request):
    q = request.GET.get("q", "").strip()
    users = User.objects.order_by("-is_superuser", "username").select_related("two_factor").prefetch_related("dashboard_access__dashboard")
    if q:
        users = users.filter(Q(username__icontains=q) | Q(email__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q))
    page = Paginator(users, 25).get_page(request.GET.get("page"))
    base = request.GET.copy()
    base.pop("page", None)
    return render(request, "accounts/users/list.html", {
        "page_obj": page, "q": q, "base_query_string": base.urlencode(),
        "pagination_window": _page_window(page),
        "admin_count": User.objects.filter(is_superuser=True, is_active=True).count(),
    })


@_admin_only
def user_create_view(request):
    form = UserCreateForm(request.POST or None, editor=request.user)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        form.save_access(user, request.user)
        if form.cleaned_data["password_mode"] == UserCreateForm.PASSWORD_EMAIL:
            if send_set_password_email(request, user, welcome=True):
                messages.success(request, _("%(name)s added. A link to choose a password was emailed to %(email)s.") % {"name": user.username, "email": user.email})
            else:
                messages.warning(request, _("%(name)s added, but the email couldn't be sent. Set a password for them below.") % {"name": user.username})
        else:
            messages.success(request, _("%(name)s added. They can sign in now.") % {"name": user.username})
        return redirect("user_edit", pk=user.pk)
    return render(request, "accounts/users/form.html", {"form": form, "creating": True})


@_admin_only
def user_edit_view(request, pk):
    person = get_object_or_404(User, pk=pk)
    form = UserAdminForm(instance=person, editor=request.user, prefix="u")
    password_form = SetPasswordForm(person, prefix="pw")
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "details":
            form = UserAdminForm(request.POST, instance=person, editor=request.user, prefix="u")
            if form.is_valid():
                if person.is_superuser and not form.cleaned_data.get("is_admin", True) and User.objects.filter(is_superuser=True, is_active=True).count() <= 1:
                    form.add_error("is_admin", _("This is the last admin. Make someone else an admin first."))
                else:
                    form.save()
                    form.save_access(person, request.user)
                    messages.success(request, _("Saved %(name)s.") % {"name": person.username})
                    return redirect("user_edit", pk=person.pk)
        elif action == "password":
            password_form = SetPasswordForm(person, request.POST, prefix="pw")
            if password_form.is_valid():
                password_form.save()
                notify_password_changed(request, person)
                messages.success(request, _("New password set for %(name)s. Tell them in person or by phone.") % {"name": person.username})
                return redirect("user_edit", pk=person.pk)
        elif action == "send_link":
            if not person.email:
                messages.error(request, _("%(name)s has no email. Add one first.") % {"name": person.username})
            elif send_set_password_email(request, person):
                messages.success(request, _("A link to choose a new password was emailed to %(email)s.") % {"email": person.email})
            else:
                messages.error(request, _("The email couldn't be sent. Try again, or set a password here."))
            return redirect("user_edit", pk=person.pk)
        elif action == "reset_2fa":
            TwoFactor.objects.filter(user=person).delete()
            twofactor.notify(request, person, _("Two-step sign-in is off for your FinTrack account"),
                             _("An admin turned off two-step sign-in for your FinTrack account on %(when)s (for example after a lost phone). Turn it on again from Account & security.") % {"when": twofactor.when_text()})
            messages.success(request, _("Two-step sign-in reset for %(name)s. They sign in with only the password now.") % {"name": person.username})
            return redirect("user_edit", pk=person.pk)
    return render(request, "accounts/users/form.html", {
        "form": form, "password_form": password_form, "person": person, "creating": False,
        "tf": twofactor.enabled_for(person), "is_self": person.pk == request.user.pk,
    })


def admin_login_redirect(request):
    """Django admin signs in through the app's own sign-in (with two-step)."""
    nxt = request.GET.get("next") or "/admin/"
    if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        nxt = "/admin/"
    return redirect(reverse("login") + "?" + urlencode({"next": nxt}))


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
