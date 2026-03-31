from django import forms
from .models import ExpenseCategory, Expense


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
            "date": forms.DateInput(attrs={"class": "form-input datepicker", "placeholder": "Select Date"}),
            "note": forms.Textarea(attrs={"class": "form-input", "rows": 2, "placeholder": "Expense details..."}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if user:
            self.fields["category"].queryset = ExpenseCategory.objects.filter(user=user)
