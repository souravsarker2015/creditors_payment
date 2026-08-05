from django import forms
from .models import HouseholdCategory, HouseholdMember, Purchase, Settlement


class HouseholdCategoryForm(forms.ModelForm):
    class Meta:
        model = HouseholdCategory
        fields = ["name"]
        widgets = {
            "name": forms.TextInput(attrs={
                "class": "form-input",
                "placeholder": "e.g. Vegetables, Fish, Groceries",
            }),
        }


class HouseholdMemberForm(forms.ModelForm):
    class Meta:
        model = HouseholdMember
        fields = ["name", "phone", "note"]
        widgets = {
            "name": forms.TextInput(attrs={
                "class": "form-input",
                "placeholder": "Full Name",
            }),
            "phone": forms.TextInput(attrs={
                "class": "form-input",
                "placeholder": "Phone Number (optional)",
            }),
            "note": forms.Textarea(attrs={
                "class": "form-input",
                "placeholder": "Add any additional details...",
                "rows": 3,
            }),
        }


class PurchaseForm(forms.ModelForm):
    class Meta:
        model = Purchase
        fields = ["amount", "date", "category", "buyer", "description"]
        widgets = {
            "amount": forms.NumberInput(attrs={"class": "form-input", "placeholder": "0.00"}),
            "date": forms.DateInput(attrs={"class": "form-input datepicker", "placeholder": "Select Date"}),
            "category": forms.Select(attrs={"class": "form-input"}),
            "buyer": forms.Select(attrs={"class": "form-input"}),
            "description": forms.Textarea(attrs={
                "class": "form-input",
                "placeholder": "What was bought (optional)...",
                "rows": 2,
            }),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        self.fields["category"].required = False
        self.fields["category"].empty_label = "No category"
        self.fields["buyer"].required = False
        self.fields["buyer"].empty_label = "No one in particular"
        if user:
            self.fields["category"].queryset = HouseholdCategory.objects.filter(user=user)
            self.fields["buyer"].queryset = HouseholdMember.objects.filter(user=user)


class SettlementForm(forms.ModelForm):
    class Meta:
        model = Settlement
        fields = ["amount", "date", "note"]
        widgets = {
            "amount": forms.NumberInput(attrs={"class": "form-input", "placeholder": "0.00"}),
            "date": forms.DateInput(attrs={"class": "form-input datepicker", "placeholder": "Select Date"}),
            "note": forms.TextInput(attrs={"class": "form-input", "placeholder": "Quick note..."}),
        }
