from django import forms
from django.utils.translation import gettext_lazy as _
from django.urls import reverse_lazy
from .models import Debtor, DebtorCategory, Transaction
from apps.core import people_categories
from apps.core.ledger_views import UniqueNameMixin
from apps.core.receipts import ReceiptInput, attach_viewer
from apps.wallets.forms import WalletFieldMixin


class DebtorCategoryForm(people_categories.NameForm, forms.ModelForm):
    """The + beside Category: a new category, by name."""

    class Meta:
        model = DebtorCategory
        fields = ["name"]
        widgets = {"name": forms.TextInput(attrs={"class": "form-input", "placeholder": _("e.g. Neighbour, Office colleague")})}


class DebtorForm(UniqueNameMixin, forms.ModelForm):
    owner_related_name = "debtors"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.business.core.audit import current_user

        user = self.instance.user if self.instance.user_id else current_user()
        people_categories.setup_field(self, DebtorCategory, user, user.debtors.all() if user and user.is_authenticated else None,
                                      reverse_lazy("debtor_categories"), "debtor_category")

    class Meta:
        model = Debtor
        fields = ["name", "category", "phone", "due_date", "note"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": _("Debtor's Name")}),
            "category": forms.Select(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control", "placeholder": _("Phone Number")}),
            "due_date": forms.DateInput(attrs={"class": "form-control datepicker", "placeholder": _("Select a due date (optional)")}),
            "note": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": _("Notes...")}),
        }


class TransactionForm(WalletFieldMixin, forms.ModelForm):
    class Meta:
        model = Transaction
        fields = ["transaction_type", "amount", "wallet", "date", "note", "receipt"]
        widgets = {
            "receipt": ReceiptInput(),
            "transaction_type": forms.Select(attrs={"class": "form-control"}),
            "amount": forms.NumberInput(attrs={"class": "form-control", "placeholder": _("Amount (৳)")}),
            "date": forms.DateInput(attrs={"class": "form-control datepicker", "placeholder": _("Select Date")}),
            "note": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": _("Transaction details...")}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        attach_viewer(self, "lent")
