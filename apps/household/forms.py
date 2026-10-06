from django import forms
from django.utils.translation import gettext_lazy as _
from apps.core.status import active_or_current
from .models import HouseholdCategory, HouseholdMember, Purchase, Settlement
from apps.core.receipts import ReceiptInput, attach_viewer
from apps.wallets.forms import WalletFieldMixin


class HouseholdCategoryForm(forms.ModelForm):
    class Meta:
        model = HouseholdCategory
        fields = ["name"]
        widgets = {
            "name": forms.TextInput(attrs={
                "class": "form-input",
                "placeholder": _("e.g. Vegetables, Fish, Groceries"),
            }),
        }


class HouseholdMemberForm(forms.ModelForm):
    class Meta:
        model = HouseholdMember
        fields = ["name", "phone", "note"]
        widgets = {
            "name": forms.TextInput(attrs={
                "class": "form-input",
                "placeholder": _("Full Name"),
            }),
            "phone": forms.TextInput(attrs={
                "class": "form-input",
                "placeholder": _("Phone Number (optional)"),
            }),
            "note": forms.Textarea(attrs={
                "class": "form-input",
                "placeholder": _("Add any additional details..."),
                "rows": 3,
            }),
        }


class PurchaseForm(WalletFieldMixin, forms.ModelForm):
    wallet_help = _("The wallet you paid from. Leave it when someone else paid — you'll owe them instead.")

    class Meta:
        model = Purchase
        fields = ["amount", "date", "category", "buyer", "wallet", "description", "receipt"]
        widgets = {
            "receipt": ReceiptInput(),
            "amount": forms.NumberInput(attrs={"class": "form-input", "placeholder": "0.00"}),
            "date": forms.DateInput(attrs={"class": "form-input datepicker", "placeholder": _("Select Date")}),
            "category": forms.Select(attrs={"class": "form-input"}),
            "buyer": forms.Select(attrs={"class": "form-input"}),
            "description": forms.Textarea(attrs={
                "class": "form-input",
                "placeholder": _("What was bought (optional)..."),
                "rows": 2,
            }),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        self.fields["category"].required = False
        self.fields["category"].empty_label = _("No category")
        self.fields["buyer"].required = False
        self.fields["buyer"].empty_label = _("No one in particular")
        self.fields["buyer"].help_text = _("Only pick someone if they paid with their own money — you'll owe it back to them.")
        self.fields["category"].quick_add = "household_category"
        self.fields["buyer"].quick_add = "household_member"
        if user:
            self.fields["category"].queryset = active_or_current(
                HouseholdCategory.objects.filter(user=user), self.instance.category_id
            )
            self.fields["buyer"].queryset = active_or_current(
                HouseholdMember.objects.filter(user=user), self.instance.buyer_id
            )
        attach_viewer(self, "bazar")

    def clean(self):
        data = super().clean()
        if data.get("buyer"):
            data["wallet"] = None   # a member fronted it: your wallet didn't move
        return data


class SettlementForm(WalletFieldMixin, forms.ModelForm):
    class Meta:
        model = Settlement
        fields = ["amount", "wallet", "date", "note"]
        widgets = {
            "amount": forms.NumberInput(attrs={"class": "form-input", "placeholder": "0.00"}),
            "date": forms.DateInput(attrs={"class": "form-input datepicker", "placeholder": _("Select Date")}),
            "note": forms.TextInput(attrs={"class": "form-input", "placeholder": _("Quick note...")}),
        }
