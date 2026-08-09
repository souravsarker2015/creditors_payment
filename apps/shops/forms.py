from django import forms
from django.utils.translation import gettext_lazy as _
from .models import Shop, Transaction


class ShopForm(forms.ModelForm):
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


class TransactionForm(forms.ModelForm):
    class Meta:
        model = Transaction
        fields = ["transaction_type", "amount", "date", "note"]
        widgets = {
            "transaction_type": forms.Select(attrs={"class": "form-input"}),
            "amount": forms.NumberInput(attrs={"class": "form-input", "placeholder": "0.00"}),
            "date": forms.DateInput(attrs={"class": "form-input datepicker", "placeholder": _("Select Date")}),
            "note": forms.TextInput(attrs={"class": "form-input", "placeholder": _("What did you buy? (optional)")}),
        }
