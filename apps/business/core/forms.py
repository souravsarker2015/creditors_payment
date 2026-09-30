from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from .models import Business, Membership, Role, Unit, UnitType


class BusinessSetupForm(forms.ModelForm):
    tips = {
        "mon_kg": _("A mon is the weight markets sell fish by. It's 40 kg in most places; set it to what your market uses."),
    }
    mon_kg = forms.DecimalField(
        label=_("1 mon equals how many kg?"), initial=Decimal("40"), min_value=Decimal("1"), max_value=Decimal("100"),
        max_digits=6, decimal_places=3,
        help_text=_("Most markets use 40 kg. You can change this any time in Units."),
        widget=forms.NumberInput(attrs={"class": "form-input", "step": "0.001", "inputmode": "decimal"}),
    )

    class Meta:
        model = Business
        fields = ["name", "phone", "address"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-input", "placeholder": _("e.g. Rahman Fish Farm"), "autofocus": True}),
            "phone": forms.TextInput(attrs={"class": "form-input", "inputmode": "tel", "placeholder": "01XXXXXXXXX"}),
            "address": forms.TextInput(attrs={"class": "form-input", "placeholder": _("Village, upazila, district")}),
        }


class BusinessProfileForm(forms.ModelForm):
    class Meta:
        model = Business
        fields = ["name", "phone", "address"]
        widgets = BusinessSetupForm.Meta.widgets


class UnitForm(forms.ModelForm):
    tips = {
        "symbol": _("The short name shown next to numbers, e.g. kg, mon, pcs."),
        "unit_type": _("What it measures. Only units of the same kind can be converted into each other."),
        "name_bn": _("Shown instead of the English name when the app is in Bangla."),
    }
    class Meta:
        model = Unit
        fields = ["name", "name_bn", "symbol", "unit_type", "factor", "notes"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-input", "placeholder": _("e.g. Mon (maund)")}),
            "name_bn": forms.TextInput(attrs={"class": "form-input", "placeholder": _("e.g. মণ")}),
            "symbol": forms.TextInput(attrs={"class": "form-input", "placeholder": _("e.g. mon")}),
            "unit_type": forms.Select(attrs={"class": "form-input"}),
            "factor": forms.NumberInput(attrs={"class": "form-input", "step": "any", "inputmode": "decimal"}),
            "notes": forms.Textarea(attrs={"class": "form-input", "rows": 2}),
        }

    def __init__(self, *args, business, **kwargs):
        super().__init__(*args, **kwargs)
        self.business = business
        if self.instance.pk and self.instance.is_base:
            # The base unit defines the scale for its type; its factor is always 1.
            self.fields["factor"].disabled = True
            self.fields["unit_type"].disabled = True
            self.fields["factor"].help_text = _("This is the base unit — other units are measured against it.")
        if self.instance.pk:
            self.fields["unit_type"].disabled = True

    def clean_symbol(self):
        symbol = self.cleaned_data["symbol"].strip()
        clash = Unit.objects.filter(business=self.business, symbol__iexact=symbol).exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError(_("You already have a unit called “%(symbol)s”.") % {"symbol": symbol})
        return symbol


class MemberAddForm(forms.Form):
    tips = {
        "username": _("They need their own account in this app first. Ask them for the username they sign in with."),
        "role": _("Decides what they can see and do. See “What each role can do” on this page. You can change it any time."),
    }
    username = forms.CharField(label=_("Username"), widget=forms.TextInput(attrs={"class": "form-input", "autocomplete": "off", "placeholder": _("Their FinTrack username")}))
    role = forms.ChoiceField(label=_("Role"), choices=[c for c in Role.choices if c[0] != Role.OWNER], initial=Role.DATA_ENTRY,
                             widget=forms.Select(attrs={"class": "form-input"}))

    def __init__(self, *args, business, **kwargs):
        super().__init__(*args, **kwargs)
        self.business = business

    def clean_username(self):
        name = self.cleaned_data["username"].strip()
        user = get_user_model().objects.filter(username__iexact=name).first()
        if user is None:
            raise forms.ValidationError(_("No one with that username. Ask them to sign up first, then add them here."))
        if Membership.objects.filter(business=self.business, user=user).exists():
            raise forms.ValidationError(_("%(name)s is already on your team.") % {"name": user.username})
        self.user = user
        return name


class RoleForm(forms.Form):
    role = forms.ChoiceField(choices=[c for c in Role.choices if c[0] != Role.OWNER])


def _password_widget():
    return forms.PasswordInput(attrs={"class": "form-input", "autocomplete": "new-password"}, render_value=True)


class _PasswordPair(forms.Form):
    """A new password, typed twice, checked against the site's password rules."""

    password1 = forms.CharField(label=_("Password"), strip=False, widget=_password_widget(),
                                help_text=_("At least 8 characters, not only numbers, and not something easy like “password”."))
    password2 = forms.CharField(label=_("Password again"), strip=False, widget=_password_widget())

    def _user_for_rules(self):
        return None

    def clean(self):
        data = super().clean()
        p1, p2 = data.get("password1"), data.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", _("The two passwords don't match."))
        elif p1:
            try:
                password_validation.validate_password(p1, self._user_for_rules())
            except ValidationError as e:
                self.add_error("password1", e)
        return data


class MemberCreateForm(_PasswordPair):
    """The owner makes a login for someone on the team."""

    tips = {
        "username": _("What they type to sign in. Letters, numbers and @ . + - _ only, no spaces. E.g. rahim or rahim.farm"),
        "role": _("Decides what they can see and do. See “What each role can do” on this page. You can change it any time."),
    }
    full_name = forms.CharField(label=_("Their name"), max_length=150, widget=forms.TextInput(attrs={"class": "form-input", "placeholder": _("e.g. Rahim Mia")}))
    username = forms.CharField(label=_("Username"), max_length=150, validators=[UnicodeUsernameValidator()],
                               widget=forms.TextInput(attrs={"class": "form-input", "autocomplete": "off", "autocapitalize": "none", "spellcheck": "false"}))
    role = forms.ChoiceField(label=_("Role"), choices=[c for c in Role.choices if c[0] != Role.OWNER], initial=Role.DATA_ENTRY,
                             widget=forms.Select(attrs={"class": "form-input"}))
    field_order = ["full_name", "username", "password1", "password2", "role"]

    def __init__(self, *args, business, **kwargs):
        super().__init__(*args, **kwargs)
        self.business = business

    def clean_username(self):
        name = self.cleaned_data["username"].strip()
        if get_user_model().objects.filter(username__iexact=name).exists():
            raise forms.ValidationError(_("That username is taken. Try another, e.g. with the farm's name after it."))
        return name

    def _user_for_rules(self):
        User = get_user_model()
        return User(username=self.cleaned_data.get("username", ""), first_name=self.cleaned_data.get("full_name", ""))

    def save(self):
        return get_user_model().objects.create_user(username=self.cleaned_data["username"], password=self.cleaned_data["password1"],
                                                    first_name=self.cleaned_data["full_name"].strip())


class MemberPasswordForm(_PasswordPair):
    """A new password for a login this farm created."""

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def _user_for_rules(self):
        return self.user
