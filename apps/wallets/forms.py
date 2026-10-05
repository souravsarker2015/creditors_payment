from datetime import date
from decimal import Decimal

from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Transfer, Wallet

MONEY_ATTRS = {"inputmode": "decimal", "step": "0.01", "placeholder": "0.00"}


def _user_wallets(user, keep=None):
    qs = Wallet.objects.filter(user=user, is_active=True)
    if keep:
        qs = qs | Wallet.objects.filter(user=user, pk=keep)
    return qs.distinct()


class WalletFieldMixin:
    """Adds the "Wallet" choice to an entry form (expense, income, payment…).

    The forms are built in many places without the user, so the signed-in
    person comes from the request (set by the dashboard middleware). With no
    wallets yet the field is left out, so nothing changes for anyone who
    doesn't use them.
    """

    wallet_help = _("Which of your wallets the money went through. Leave empty if you don't track it.")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.business.core.audit import current_user

        field = self.fields.get("wallet")
        if field is None:
            return
        user = current_user()
        wallets = _user_wallets(user, self.instance.wallet_id) if (user is not None and user.is_authenticated) else Wallet.objects.none()
        if not wallets.exists():
            del self.fields["wallet"]
            return
        field.queryset = wallets
        field.empty_label = _("Not from a wallet")
        field.help_text = self.wallet_help
        field.widget.attrs.setdefault("class", "form-input")
        if not self.instance.pk and "wallet" not in self.initial:
            default = wallets.filter(is_default=True).first()
            if default:
                self.initial["wallet"] = default.pk


class WalletForm(forms.ModelForm):
    class Meta:
        model = Wallet
        fields = ["name", "kind", "number", "opening_balance", "opening_date", "is_default", "note"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-input", "placeholder": _("e.g. Cash, bKash, Sonali Bank")}),
            "kind": forms.Select(attrs={"class": "form-input"}),
            "number": forms.TextInput(attrs={"class": "form-input", "inputmode": "numeric"}),
            "opening_balance": forms.NumberInput(attrs={"class": "form-input", **MONEY_ATTRS}),
            "opening_date": forms.DateInput(attrs={"class": "form-input datepicker", "autocomplete": "off"}, format="%Y-%m-%d"),
            "note": forms.Textarea(attrs={"class": "form-input", "rows": 2}),
        }
        help_texts = {
            "opening_balance": _("What it holds on the date below. Everything you record from then on moves it."),
            "opening_date": _("Usually today."),
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if Wallet.objects.filter(user=self.user, name__iexact=name).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(_("You already have a wallet called “%(name)s”.") % {"name": name})
        return name


class TransferForm(forms.ModelForm):
    class Meta:
        model = Transfer
        fields = ["from_wallet", "to_wallet", "amount", "fee", "date", "note"]
        widgets = {
            "from_wallet": forms.Select(attrs={"class": "form-input"}),
            "to_wallet": forms.Select(attrs={"class": "form-input"}),
            "amount": forms.NumberInput(attrs={"class": "form-input", **MONEY_ATTRS}),
            "fee": forms.NumberInput(attrs={"class": "form-input", **MONEY_ATTRS}),
            "date": forms.DateInput(attrs={"class": "form-input datepicker", "autocomplete": "off"}, format="%Y-%m-%d"),
            "note": forms.Textarea(attrs={"class": "form-input", "rows": 2}),
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        keep = [self.instance.from_wallet_id, self.instance.to_wallet_id] if self.instance.pk else []
        qs = (Wallet.objects.filter(user=user, is_active=True) | Wallet.objects.filter(user=user, pk__in=keep)).distinct()
        self.fields["from_wallet"].queryset = self.fields["to_wallet"].queryset = qs
        self.fields["fee"].required = False

    def clean(self):
        data = super().clean()
        data["fee"] = data.get("fee") or Decimal(0)
        if data.get("from_wallet") and data.get("from_wallet") == data.get("to_wallet"):
            self.add_error("to_wallet", _("Choose a different wallet to send to."))
        if data.get("amount") is not None and data["amount"] <= 0:
            self.add_error("amount", _("Enter an amount above zero."))
        if data["fee"] < 0:
            self.add_error("fee", _("The fee can't be below zero."))
        if data.get("date") and data["date"] > date.today():
            self.add_error("date", _("This date is in the future."))
        return data


class CorrectBalanceForm(forms.Form):
    """Type what the wallet really holds; the difference is recorded as a correction."""

    actual = forms.DecimalField(label=_("What it really holds now"), max_digits=12, decimal_places=2,
                                widget=forms.NumberInput(attrs={"class": "form-input", **MONEY_ATTRS}))
    note = forms.CharField(label=_("Note"), required=False, max_length=200,
                           widget=forms.TextInput(attrs={"class": "form-input", "placeholder": _("e.g. counted the cash box")}))
