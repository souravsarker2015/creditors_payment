from django import forms
from django.utils.translation import gettext_lazy as _
from .models import Debtor, Transaction


class DebtorForm(forms.ModelForm):
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


class TransactionForm(forms.ModelForm):
    class Meta:
        model = Transaction
        fields = ["transaction_type", "amount", "date", "note"]
        widgets = {
            "transaction_type": forms.Select(attrs={"class": "form-control"}),
            "amount": forms.NumberInput(attrs={"class": "form-control", "placeholder": _("Amount (৳)")}),
            "date": forms.DateInput(attrs={"class": "form-control datepicker", "placeholder": _("Select Date")}),
            "note": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": _("Transaction details...")}),
        }
