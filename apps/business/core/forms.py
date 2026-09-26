from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from .models import Business, Membership, Role, Unit, UnitType


class BusinessSetupForm(forms.ModelForm):
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
