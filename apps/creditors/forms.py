from django import forms
from django.utils.translation import gettext_lazy as _
from .models import Creditor, InterestBasis, InterestType, Transaction

class CreditorForm(forms.ModelForm):
    class Meta:
        model = Creditor
        fields = ["name", "category", "phone", "due_date", "interest_type", "interest_basis", "interest_rate", "interest_fixed_amount", "note"]
        widgets = {
            "name": forms.TextInput(attrs={
                "class": "form-input",
                "placeholder": _("Full Name")
            }),
            "category": forms.Select(attrs={
                "class": "form-input",
            }),
            "phone": forms.TextInput(attrs={
                "class": "form-input",
                "placeholder": _("Phone Number (optional)")
            }),
            "due_date": forms.DateInput(attrs={
                "class": "form-input datepicker",
                "placeholder": _("Select a due date (optional)"),
            }),
            "interest_type": forms.Select(attrs={
                "class": "form-input",
                "x-model": "interestType",
            }),
            "interest_basis": forms.Select(attrs={
                "class": "form-input",
                "x-model": "interestBasis",
            }),
            "interest_rate": forms.NumberInput(attrs={
                "class": "form-input",
                "placeholder": _("e.g. 2 (% per period, optional)"),
                "step": "0.01",
                "min": "0",
            }),
            "interest_fixed_amount": forms.NumberInput(attrs={
                "class": "form-input",
                "placeholder": _("e.g. 2000 (flat ৳ amount, optional)"),
                "step": "0.01",
                "min": "0",
            }),
            "note": forms.Textarea(attrs={
                "class": "form-input",
                "placeholder": _("Add any additional details..."),
                "rows": 3
            }),
        }

    def clean(self):
        cleaned_data = super().clean()
        interest_type = cleaned_data.get("interest_type")
        interest_basis = cleaned_data.get("interest_basis")
        interest_rate = cleaned_data.get("interest_rate")
        interest_fixed_amount = cleaned_data.get("interest_fixed_amount")

        if interest_type == InterestType.FIXED:
            # One-time flat charge — no period, no basis, no rate.
            if not interest_fixed_amount:
                self.add_error(
                    "interest_fixed_amount",
                    _("Enter a flat interest amount, or clear the interest type."),
                )
            cleaned_data["interest_rate"] = None
            cleaned_data["interest_basis"] = None
        elif interest_type:
            # A periodic type — basis decides whether rate or fixed_amount applies.
            if interest_basis == InterestBasis.FIXED:
                if not interest_fixed_amount:
                    self.add_error(
                        "interest_fixed_amount",
                        _("Enter a flat interest amount, or choose Percentage instead."),
                    )
                cleaned_data["interest_rate"] = None
            elif interest_basis == InterestBasis.PERCENTAGE:
                if not interest_rate:
                    self.add_error(
                        "interest_rate",
                        _("Enter an interest rate, or choose Fixed Amount instead."),
                    )
                cleaned_data["interest_fixed_amount"] = None
            else:
                self.add_error("interest_basis", _("Choose Percentage or Fixed Amount."))
        else:
            cleaned_data["interest_basis"] = None
            cleaned_data["interest_rate"] = None
            cleaned_data["interest_fixed_amount"] = None

        return cleaned_data

class TransactionForm(forms.ModelForm):
    class Meta:
        model = Transaction
        fields = ["transaction_type", "amount", "date", "note"]
        widgets = {
            "transaction_type": forms.Select(attrs={"class": "form-input"}),
            "amount": forms.NumberInput(attrs={"class": "form-input", "placeholder": "0.00"}),
            "date": forms.DateInput(attrs={"class": "form-input datepicker", "placeholder": _("Select Date")}),
            "note": forms.TextInput(attrs={"class": "form-input", "placeholder": _("Quick note...")}),
        }
