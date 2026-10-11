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

