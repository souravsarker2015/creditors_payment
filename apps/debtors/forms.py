from django import forms
from .models import Debtor, Transaction


class DebtorForm(forms.ModelForm):
    class Meta:
        model = Debtor
        fields = ["name", "category", "phone", "note"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Debtor's Name"}),
            "category": forms.Select(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "Phone Number"}),
            "note": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Notes..."}),
        }


class TransactionForm(forms.ModelForm):
    class Meta:
        model = Transaction
        fields = ["transaction_type", "amount", "date", "note"]
        widgets = {
            "transaction_type": forms.Select(attrs={"class": "form-control"}),
            "amount": forms.NumberInput(attrs={"class": "form-control", "placeholder": "Amount (৳)"}),
            "date": forms.DateInput(attrs={"class": "form-control datepicker", "placeholder": "Select Date"}),
            "note": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Transaction details..."}),
        }
