from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm, UserCreationForm
from django.core.cache import cache
from django.utils.translation import gettext_lazy as _

User = get_user_model()


def email_taken(email, exclude=None):
    qs = User.objects.filter(email__iexact=email)
    if exclude is not None:
        qs = qs.exclude(pk=exclude.pk)
    return qs.exists()


# Guessing passwords: after this many wrong ones in LOCK_WINDOW, signing in
# pauses for LOCK_WINDOW — for one account from one place, for one account from
# anywhere (a spread-out attack), and for one place trying many accounts.
PAIR_LIMIT = 5
ACCOUNT_LIMIT = 20
PLACE_LIMIT = 50
LOCK_WINDOW = 15 * 60


def client_ip(request):
    meta = getattr(request, "META", {}) or {}
    return (meta.get("HTTP_X_REAL_IP") or meta.get("REMOTE_ADDR") or "").strip()[:64]


def _login_keys(request, username):
    name = (username or "").strip().lower()[:150]
    place = client_ip(request)
    return {"pair": f"login-fail:{name}:{place}", "account": f"login-fail:{name}", "place": f"login-fail-ip:{place}"}


LIMITS = {"pair": PAIR_LIMIT, "account": ACCOUNT_LIMIT, "place": PLACE_LIMIT}


def login_locked(request, username):
    keys = _login_keys(request, username)
    return any(cache.get(keys[k], 0) >= LIMITS[k] for k in keys)


def login_failed(request, username):
    """Count a wrong password. Returns True when this one locked the account."""
    keys = _login_keys(request, username)
    locked_now = False
    for kind, key in keys.items():
        try:
            n = cache.incr(key)
        except ValueError:
            cache.set(key, 1, LOCK_WINDOW)
            n = 1
        if kind == "account" and n == ACCOUNT_LIMIT:
            locked_now = True
    return locked_now


def login_succeeded(request, username):
    keys = _login_keys(request, username)
    cache.delete(keys["pair"])


class LoginForm(AuthenticationForm):
    remember_me = forms.BooleanField(
        label=_("Remember me"), required=False, initial=True,
        help_text=_("Stay signed in on this device for 30 days. Untick on a shared phone or computer."),
    )

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        self.fields["username"].label = _("Username or email")
        self.fields["username"].widget.attrs.update({"autocomplete": "username", "autocapitalize": "none"})
        self.fields["password"].widget.attrs.update({"autocomplete": "current-password"})

    def clean(self):
        username = self.cleaned_data.get("username")
        if username and login_locked(self.request, username):
            raise forms.ValidationError(
                _("Too many wrong passwords. Signing in to this account is paused for %(minutes)s minutes — or reset your password now."),
                code="locked", params={"minutes": LOCK_WINDOW // 60})
        try:
            cleaned = super().clean()
        except forms.ValidationError:
            if username and self.cleaned_data.get("password") and login_failed(self.request, username):
                self._warn_owner(username)
            raise
        login_succeeded(self.request, username)
        return cleaned

    def _warn_owner(self, username):
        """Tell the account's owner someone is guessing their password."""
        from django.db.models import Q

        from .twofactor import notify, when_text

        name = username.strip()
        user = User.objects.filter(Q(username=name) | Q(email__iexact=name) if "@" in name else Q(username=name)).first()
        if user is not None and self.request is not None:
            notify(self.request, user, _("Someone is trying to sign in to your FinTrack account"),
                   _("There were %(count)s wrong passwords for your account by %(when)s, so signing in is paused for %(minutes)s minutes. "
                     "If this wasn't you, nothing is needed — but a stronger password (and two-step sign-in) keeps guessers out.")
                   % {"count": ACCOUNT_LIMIT, "when": when_text(), "minutes": LOCK_WINDOW // 60})


class SignupForm(UserCreationForm):
    email = forms.EmailField(
        label=_("Email"), max_length=254,
        help_text=_("Used only to reset your password if you forget it."),
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )

    class Meta(UserCreationForm.Meta):
        fields = ("username", "email")

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        if email_taken(email):
            raise forms.ValidationError(_("An account with this email already exists. Sign in, or reset its password."))
        return email


class EmailChangeForm(forms.Form):
    """Add or change the account's email. Asks for the password, so someone
    who finds the phone unlocked can't point password resets elsewhere."""

    email = forms.EmailField(label=_("Email"), max_length=254, widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    password = forms.CharField(label=_("Your password"), strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields["email"].initial = user.email

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        if email_taken(email, exclude=self.user):
            raise forms.ValidationError(_("Another account already uses this email."))
        return email

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not self.user.check_password(password):
            raise forms.ValidationError(_("That password isn't right."))
        return password

    def save(self):
        self.user.email = self.cleaned_data["email"]
        self.user.save(update_fields=["email"])
        return self.user


RESET_LIMIT = 3            # reset emails per address…
RESET_WINDOW = 60 * 60     # …per hour


class ThrottledPasswordResetForm(PasswordResetForm):
    """Django's reset form, sending at most RESET_LIMIT emails an hour to one
    address, so the form can't be used to flood someone's inbox. The page
    looks the same either way, so it never tells whether an address exists."""

    def save(self, *args, **kwargs):
        key = "pw-reset:" + self.cleaned_data["email"].strip().lower()
        sent = cache.get(key, 0)
        if sent >= RESET_LIMIT:
            return
        cache.set(key, sent + 1, RESET_WINDOW)
        super().save(*args, **kwargs)



class ProfileForm(forms.ModelForm):
    """Name, username and phone. Email has its own form (it asks for the password)."""

    phone = forms.CharField(label=_("Phone"), max_length=20, required=False,
                            widget=forms.TextInput(attrs={"inputmode": "tel", "autocomplete": "tel"}))

    class Meta:
        model = User
        fields = ("first_name", "last_name", "username")
        widgets = {
            "first_name": forms.TextInput(attrs={"autocomplete": "given-name"}),
            "last_name": forms.TextInput(attrs={"autocomplete": "family-name"}),
            "username": forms.TextInput(attrs={"autocomplete": "username", "autocapitalize": "none"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].help_text = _("Letters, digits and @ . + - _ only. You sign in with it.")
        profile = getattr(self.instance, "profile", None)
        if profile is not None:
            self.fields["phone"].initial = profile.phone

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(_("That username is taken."))
        return username

    def save(self, commit=True):
        user = super().save(commit)
        from .models import UserProfile

        profile, _created = UserProfile.objects.get_or_create(user=user)
        profile.phone = self.cleaned_data.get("phone", "").strip()
        profile.save(update_fields=["phone"])
        return user


class CodeForm(forms.Form):
    """The 6-digit code from the authenticator app (or a recovery code)."""

    code = forms.CharField(
        label=_("Code"), max_length=20, strip=True,
        widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "one-time-code", "autocapitalize": "none",
                                      "autofocus": True, "placeholder": "123456", "class": "otp-input"}),
    )


class TwoFactorVerifyForm(CodeForm):
    trust = forms.BooleanField(label=_("Don't ask again on this device for 30 days"), required=False)


class PasswordAndCodeForm(CodeForm):
    """Turning two-step sign-in off: the password and a current code."""

    password = forms.CharField(label=_("Your password"), strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields["code"].widget.attrs.pop("autofocus", None)
        self.fields["code"].help_text = _("From your authenticator app, or one of your recovery codes.")
        self.order_fields(["password", "code"])

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not self.user.check_password(password):
            raise forms.ValidationError(_("That password isn't right."))
        return password


class SecuritySettingsForm(forms.ModelForm):
    class Meta:
        from .models import SecuritySettings

        model = SecuritySettings
        fields = ("two_factor",)
        widgets = {"two_factor": forms.RadioSelect}


# ── Admin: people who use this app ────────────────────────────────────────
def dashboard_choices():
    from apps.business.core.models import Dashboard

    return [(d.code, d.display_name) for d in Dashboard.objects.filter(is_active=True).order_by("order", "name")]


class UserAdminForm(forms.ModelForm):
    """An admin adding or editing a person: who they are, whether they're an
    admin, and which parts of the app (dashboards) they can open."""

    email = forms.EmailField(label=_("Email"), required=False, max_length=254)
    is_admin = forms.BooleanField(label=_("Admin"), required=False,
                                  help_text=_("Admins can open every part of the app, manage people and change security settings."))
    dashboards = forms.MultipleChoiceField(label=_("Can open"), required=False, widget=forms.CheckboxSelectMultiple)

    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email", "is_active")

    def __init__(self, *args, editor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.editor = editor
        self.fields["dashboards"].choices = dashboard_choices()
        self.fields["is_active"].help_text = _("Untick to stop this person signing in. Nothing they recorded is deleted.")
        if self.instance.pk:
            self.fields["is_admin"].initial = self.instance.is_superuser
            self.fields["dashboards"].initial = list(self.instance.dashboard_access.values_list("dashboard__code", flat=True))
            if editor is not None and editor.pk == self.instance.pk:   # you can't lock yourself out
                for name in ("is_admin", "is_active"):
                    self.fields[name].disabled = True
                    self.fields[name].help_text = _("You can't change this for your own account.")
        else:
            self.fields["dashboards"].initial = [c for c, _label in self.fields["dashboards"].choices if c == "personal"]

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(_("That username is taken."))
        return username

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip()
        if email and email_taken(email, exclude=self.instance if self.instance.pk else None):
            raise forms.ValidationError(_("Another account already uses this email."))
        return email

    def save_access(self, user, granted_by):
        from apps.business.core.models import Dashboard, UserDashboardAccess

        chosen = set(self.cleaned_data.get("dashboards") or [])
        for dash in Dashboard.objects.filter(is_active=True):
            if dash.code in chosen:
                UserDashboardAccess.objects.get_or_create(user=user, dashboard=dash, defaults={"granted_by": granted_by})
            else:
                UserDashboardAccess.objects.filter(user=user, dashboard=dash).delete()
        if not UserDashboardAccess.objects.filter(user=user, is_default=True).exists():
            first = UserDashboardAccess.objects.filter(user=user).order_by("dashboard__order").first()
            if first:
                first.is_default = True
                first.save(update_fields=["is_default"])

    def save(self, commit=True):
        user = super().save(commit=False)
        if "is_admin" in self.changed_data or not user.pk:
            user.is_superuser = user.is_staff = bool(self.cleaned_data.get("is_admin"))
        if commit:
            user.save()
        return user


class UserCreateForm(UserAdminForm):
    PASSWORD_SET = "set"
    PASSWORD_EMAIL = "email"
    password_mode = forms.ChoiceField(
        label=_("Password"), widget=forms.RadioSelect, initial=PASSWORD_SET,
        choices=[(PASSWORD_SET, _("I'll set it now")), (PASSWORD_EMAIL, _("Email them a link to choose their own"))],
    )
    password1 = forms.CharField(label=_("New password"), required=False, strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(label=_("New password again"), required=False, strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    def clean(self):
        data = super().clean()
        if data.get("password_mode") == self.PASSWORD_EMAIL:
            if not data.get("email"):
                self.add_error("email", _("Needed to email the link."))
        else:
            p1, p2 = data.get("password1"), data.get("password2")
            if not p1:
                self.add_error("password1", _("Type a password, or choose to email a link."))
            elif p1 != p2:
                self.add_error("password2", _("The two passwords don't match."))
            else:
                from django.contrib.auth import password_validation

                try:
                    password_validation.validate_password(p1, User(username=data.get("username", ""), email=data.get("email", "")))
                except forms.ValidationError as e:
                    self.add_error("password1", e)
        return data

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get("password_mode") == self.PASSWORD_EMAIL:
            user.set_unusable_password()
        else:
            user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user
