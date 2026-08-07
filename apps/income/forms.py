from django import forms
from django.utils.translation import gettext_lazy as _
from .models import IncomeSource, IncomeTransaction, RecurringIncome


class IncomeSourceForm(forms.ModelForm):
    class Meta:
        model = IncomeSource
        fields = ["name", "description"]


class IncomeTransactionForm(forms.ModelForm):
    class Meta:
        model = IncomeTransaction
        fields = ["amount", "date", "note"]
        widgets = {
            "date": forms.DateInput(attrs={"class": "form-input datepicker", "placeholder": _("Select Date")}),
            "note": forms.Textarea(attrs={"class": "form-input", "rows": 2, "placeholder": _("Additional details...")}),
        }


class RecurringIncomeForm(forms.ModelForm):
    class Meta:
        model = RecurringIncome
        fields = ["source", "amount", "frequency", "next_run_date", "skip_weekend", "note"]
        labels = {
            "next_run_date": _("Next Occurrence"),
            "skip_weekend": _("Move to the previous working day if this date falls on a Friday or Saturday"),
        }
        help_texts = {
            "skip_weekend": _("Common for bank-paid salary. Only affects which date the entry is posted on — the schedule itself stays anchored to the original date."),
        }
        widgets = {
            "source": forms.Select(attrs={"class": "form-input"}),
            "frequency": forms.Select(attrs={"class": "form-input"}),
            "amount": forms.NumberInput(attrs={"class": "form-input", "placeholder": "0.00", "min": "0.01", "step": "0.01"}),
            "next_run_date": forms.DateInput(attrs={"class": "form-input datepicker", "placeholder": _("Select Date")}),
            "skip_weekend": forms.CheckboxInput(attrs={"class": "form-checkbox"}),
            "note": forms.Textarea(attrs={"class": "form-input", "rows": 2, "placeholder": _("Optional note added to each generated entry...")}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if user:
            self.fields["source"].queryset = IncomeSource.objects.filter(user=user)
