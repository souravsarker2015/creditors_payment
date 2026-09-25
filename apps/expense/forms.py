from django import forms
from django.utils.translation import gettext_lazy as _
from apps.core.status import active_or_current
from .models import RecurringFrequency, ExpenseCategory, Expense, RecurringExpense


class ExpenseCategoryForm(forms.ModelForm):
    class Meta:
        model = ExpenseCategory
        fields = ["name"]


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ["category", "amount", "date", "note"]
        widgets = {
            "category": forms.Select(attrs={"class": "form-input"}),
            "amount": forms.NumberInput(attrs={"class": "form-input", "placeholder": "0.00"}),
            "date": forms.DateInput(attrs={"class": "form-input datepicker", "placeholder": _("Select Date")}),
            "note": forms.Textarea(attrs={"class": "form-input", "rows": 2, "placeholder": _("Expense details...")}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if user:
            self.fields["category"].queryset = active_or_current(
                ExpenseCategory.objects.filter(user=user), self.instance.category_id
            )
        self.fields["category"].empty_label = _("General (no category)")


class RecurringExpenseForm(forms.ModelForm):
    class Meta:
        model = RecurringExpense
        fields = ["category", "amount", "frequency", "next_run_date", "skip_weekend", "note"]
        labels = {
            "next_run_date": _("Next Occurrence"),
            "skip_weekend": _("Move to the previous working day if this date falls on a Friday or Saturday"),
        }
        help_texts = {
            "skip_weekend": _("Common for bank auto-debits. Only affects which date the entry is posted on — the schedule itself stays anchored to the original date."),
        }
        widgets = {
            "category": forms.Select(attrs={"class": "form-input"}),
            "frequency": forms.Select(attrs={"class": "form-input"}),
            "amount": forms.NumberInput(attrs={"class": "form-input", "placeholder": "0.00", "min": "0.01", "step": "0.01"}),
            "next_run_date": forms.DateInput(attrs={"class": "form-input datepicker", "placeholder": _("Select Date")}),
            "skip_weekend": forms.CheckboxInput(attrs={"class": "form-checkbox"}),
            "note": forms.Textarea(attrs={"class": "form-input", "rows": 2, "placeholder": _("Optional note added to each generated entry...")}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        self.fields["frequency"].choices = [("", _("Choose how often…"))] + list(RecurringFrequency.choices)
        if user:
            self.fields["category"].queryset = active_or_current(
                ExpenseCategory.objects.filter(user=user), self.instance.category_id
            )
        self.fields["category"].empty_label = _("General (no category)")
        self.fields["category"].required = False
