from django import forms
from .models import IncomeSource, IncomeTransaction


class IncomeSourceForm(forms.ModelForm):
    class Meta:
        model = IncomeSource
        fields = ["name", "description"]


class IncomeTransactionForm(forms.ModelForm):
    class Meta:
        model = IncomeTransaction
        fields = ["amount", "date", "note"]
        widgets = {
            "date": forms.DateInput(attrs={"class": "form-input datepicker", "placeholder": "Select Date"}),
            "note": forms.Textarea(attrs={"class": "form-input", "rows": 2, "placeholder": "Additional details..."}),
        }
