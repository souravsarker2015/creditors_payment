from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _


class BudgetScope(models.TextChoices):
    ALL_EXPENSES = "expenses", _("All expenses")
    CATEGORY = "category", _("One expense category")
    BAZAR = "bazar", _("Household bazar")


class Budget(models.Model):
    """A monthly spending limit. It resets every calendar month, so one
    budget keeps working without being re-entered."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="budgets")
    scope = models.CharField(_("Budget for"), max_length=10, choices=BudgetScope.choices, default=BudgetScope.CATEGORY)
    category = models.ForeignKey(
        "expense.ExpenseCategory", on_delete=models.CASCADE, null=True, blank=True, related_name="budgets",
        verbose_name=_("Category"),
    )
    amount = models.DecimalField(_("Monthly limit"), max_digits=12, decimal_places=2, validators=[MinValueValidator(1)])
    alert_at = models.PositiveSmallIntegerField(
        _("Warn me at"), default=80, validators=[MinValueValidator(10), MaxValueValidator(100)],
        help_text=_("Percent of the limit. You'll also be warned if the current pace would overshoot it."),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["scope", "category__name"]
        constraints = [
            models.UniqueConstraint(fields=["user", "category"], condition=models.Q(scope="category"), name="one_budget_per_category"),
            models.UniqueConstraint(fields=["user", "scope"], condition=~models.Q(scope="category"), name="one_budget_per_scope"),
        ]

    def __str__(self):
        return f"{self.label} · ৳{self.amount}"

    @property
    def label(self):
        if self.scope == BudgetScope.CATEGORY and self.category_id:
            return self.category.name
        return self.get_scope_display()
