from django import forms
from django.utils.translation import gettext_lazy as _

from apps.core.status import active_or_current
from apps.expense.models import ExpenseCategory
from .models import Budget, BudgetScope


class BudgetForm(forms.ModelForm):
    class Meta:
        model = Budget
        fields = ["scope", "category", "amount", "alert_at"]
        widgets = {
            "scope": forms.RadioSelect,
            "category": forms.Select(attrs={"class": "form-input"}),
            "amount": forms.NumberInput(attrs={"class": "form-input", "placeholder": "0", "min": "1", "step": "1"}),
            "alert_at": forms.NumberInput(attrs={"class": "form-input", "min": "10", "max": "100", "step": "5"}),
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["category"].queryset = active_or_current(
            ExpenseCategory.objects.filter(user=user), self.instance.category_id
        )
        # Required only when the budget is for one category.
        scope = self.data.get(self.add_prefix("scope")) if self.is_bound else None
        self.fields["category"].required = not self.is_bound or scope == BudgetScope.CATEGORY
        self.fields["category"].empty_label = _("Choose a category…")
        self.fields["category"].quick_add = "expense_category"
        self.fields["scope"].help_text = _("A budget resets every month — set it once.")

    def clean(self):
        data = super().clean()
        scope, category = data.get("scope"), data.get("category")
        if scope == BudgetScope.CATEGORY and not category:
            self.add_error("category", _("Pick the category this budget is for."))
        if scope != BudgetScope.CATEGORY:
            data["category"] = None
        clash = Budget.objects.filter(user=self.user, scope=scope)
        if scope == BudgetScope.CATEGORY:
            clash = clash.filter(category=category)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if scope and clash.exists():
            raise forms.ValidationError(_("You already have a budget for this — edit that one instead."))
        return data
