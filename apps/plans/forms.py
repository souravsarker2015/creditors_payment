import math
from datetime import date
from decimal import Decimal

from django import forms
from django.utils.translation import gettext_lazy as _

from .models import InstallmentPlan


class PlanForm(forms.ModelForm):
    installments = forms.IntegerField(label=_("Or: how many installments"), required=False, min_value=1, max_value=600,
                                      widget=forms.NumberInput(attrs={"class": "form-input", "inputmode": "numeric", "placeholder": _("e.g. 10")}),
                                      help_text=_("Leave the amount empty and type the number of installments: the amount is worked out from what's still owed."))

    class Meta:
        model = InstallmentPlan
        fields = ["amount", "installments", "frequency", "start_date", "note"]
        widgets = {
            "amount": forms.NumberInput(attrs={"class": "form-input", "inputmode": "decimal", "step": "0.01", "placeholder": "0.00"}),
            "frequency": forms.Select(attrs={"class": "form-input"}),
            "start_date": forms.DateInput(attrs={"class": "form-input datepicker", "autocomplete": "off"}, format="%Y-%m-%d"),
            "note": forms.TextInput(attrs={"class": "form-input", "placeholder": _("e.g. agreed on the phone, after Eid")}),
        }

    def __init__(self, *args, remaining=Decimal(0), **kwargs):
        super().__init__(*args, **kwargs)
        self.remaining = remaining
        self.fields["amount"].required = False
        self.order_fields(["amount", "installments", "frequency", "start_date", "note"])

    def clean(self):
        data = super().clean()
        amount, n = data.get("amount"), data.get("installments")
        if not amount and n:
            if self.remaining <= 0:
                self.add_error("installments", _("Nothing is owed now, so there's nothing to split."))
            else:
                data["amount"] = Decimal(math.ceil(self.remaining / n))
        if not data.get("amount"):
            self.add_error("amount", _("Enter the amount of each installment, or how many installments."))
        if data.get("start_date") and data["start_date"] < date(2000, 1, 1):
            self.add_error("start_date", _("Check the date."))
        return data

    def save(self, commit=True):
        self.instance.amount = self.cleaned_data["amount"]
        return super().save(commit)
