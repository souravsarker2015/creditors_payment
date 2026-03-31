from django.db import models
from django.db.models import Sum, Q 
from django.contrib.auth.models import User


class ExpenseCategory(models.Model):
    """Grouping for different types of expenses."""

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="expense_categories"
    )
    name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def total_expense(self):
        """Total spent in this category."""
        return (
            self.expenses.aggregate(total=Sum("amount"))["total"]
            or 0
        )


class Expense(models.Model):
    """A single expenditure record."""

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="expenses"
    )
    category = models.ForeignKey(
        ExpenseCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="expenses",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField()
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"৳{self.amount} spent on {self.date}"
