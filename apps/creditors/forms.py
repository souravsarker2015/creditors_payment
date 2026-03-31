from django import forms
from .models import Creditor, Transaction

class CreditorForm(forms.ModelForm):
    class Meta:
        model = Creditor
        fields = ["name", "phone", "note"]
        widgets = {
            "name": forms.TextInput(attrs={
                "class": "form-input",
                "placeholder": "Full Name"
            }),
            "phone": forms.TextInput(attrs={
                "class": "form-input",
                "placeholder": "Phone Number (optional)"
            }),
            "note": forms.Textarea(attrs={
                "class": "form-input",
                "placeholder": "Add any additional details...",
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
            "date": forms.DateInput(attrs={"class": "form-input datepicker", "placeholder": "Select Date"}),
            "note": forms.TextInput(attrs={"class": "form-input", "placeholder": "Quick note..."}),
        }
