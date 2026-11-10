from django import forms
from django.utils.translation import gettext_lazy as _
from .models import Shop, Transaction
from apps.core.ledger_views import UniqueNameMixin
from apps.core.receipts import ReceiptInput, attach_viewer
from apps.wallets.forms import WalletFieldMixin


class ShopForm(UniqueNameMixin, forms.ModelForm):
    owner_related_name = "shops"

    class Meta:
        model = Shop
        fields = ["name", "category", "phone", "due_date", "note"]
        widgets = {
            "name": forms.TextInput(attrs={
                "class": "form-input",
                "placeholder": _("Shop Name")
            }),
            "category": forms.Select(attrs={
                "class": "form-input",
            }),
            "phone": forms.TextInput(attrs={
                "class": "form-input",
                "placeholder": _("Phone Number (optional)")
            }),
            "due_date": forms.DateInput(attrs={"class": "form-input datepicker", "placeholder": _("Select Date")}),
            "note": forms.Textarea(attrs={
                "class": "form-input",
                "placeholder": _("Address or any additional details..."),
                "rows": 3
            }),
        }


class TransactionForm(WalletFieldMixin, forms.ModelForm):
    wallet_help = _("For a payment: the wallet you paid from. A purchase on credit doesn't move money.")

    class Meta:
        model = Transaction
        fields = ["transaction_type", "amount", "wallet", "date", "note", "receipt"]
        widgets = {
            "receipt": ReceiptInput(),
            "transaction_type": forms.Select(attrs={"class": "form-input"}),
            "amount": forms.NumberInput(attrs={"class": "form-input", "placeholder": "0.00"}),
            "date": forms.DateInput(attrs={"class": "form-input datepicker", "placeholder": _("Select Date")}),
            "note": forms.TextInput(attrs={"class": "form-input", "placeholder": _("What did you buy? (optional)")}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        attach_viewer(self, "shop", _("See the memo"))
        if "receipt" in self.fields:
            self.fields["receipt"].help_text = _("Optional: a photo of the shop's memo (খাতা) for this entry.")

    def clean(self):
        data = super().clean()
        if data.get("transaction_type") == Transaction.PURCHASE:
            data["wallet"] = None   # bought on credit: no money moved yet
        return data
