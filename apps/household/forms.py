from django import forms
from django.utils.translation import gettext_lazy as _
from apps.core.status import active_or_current
from .models import HouseholdCategory, HouseholdMember, Purchase, Settlement


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


class PurchaseForm(forms.ModelForm):
    class Meta:
        model = Purchase
        fields = ["amount", "date", "category", "buyer", "description"]
        widgets = {
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
        if user:
            self.fields["category"].queryset = active_or_current(
                HouseholdCategory.objects.filter(user=user), self.instance.category_id
            )
            self.fields["buyer"].queryset = active_or_current(
                HouseholdMember.objects.filter(user=user), self.instance.buyer_id
            )


class SettlementForm(forms.ModelForm):
    class Meta:
        model = Settlement
        fields = ["amount", "date", "note"]
        widgets = {
            "amount": forms.NumberInput(attrs={"class": "form-input", "placeholder": "0.00"}),
            "date": forms.DateInput(attrs={"class": "form-input datepicker", "placeholder": _("Select Date")}),
            "note": forms.TextInput(attrs={"class": "form-input", "placeholder": _("Quick note...")}),
        }
