from django import forms
from .models import Contributor, Contribution

class ContributorForm(forms.ModelForm):
    class Meta:
        model = Contributor
        fields = ["name", "category", "phone", "note"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-input", "placeholder": "Full Name"}),
            "category": forms.Select(attrs={"class": "form-input"}),
            "phone": forms.TextInput(attrs={"class": "form-input", "placeholder": "Phone Number (optional)"}),
            "note": forms.Textarea(attrs={
                "class": "form-input", 
                "placeholder": "Add any additional details...",
                "rows": 3
            }),
        }

class ContributionForm(forms.ModelForm):
    class Meta:
        model = Contribution
        fields = ["amount", "date", "note"]
        widgets = {
            "amount": forms.NumberInput(attrs={"class": "form-input", "placeholder": "0.00"}),
            "date": forms.DateInput(attrs={"class": "form-input datepicker", "placeholder": "Select Date"}),
            "note": forms.Textarea(attrs={
                "class": "form-input", 
                "placeholder": "Additional details...",
                "rows": 2
            }),
        }
