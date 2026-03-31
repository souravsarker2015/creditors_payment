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
            "date": forms.DateInput(attrs={"type": "date"}),
            "note": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if user:
            self.fields["category"].queryset = ExpenseCategory.objects.filter(user=user)
