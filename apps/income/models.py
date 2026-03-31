from django.db import models
from django.db.models import Sum, Q
from django.contrib.auth.models import User


class IncomeSource(models.Model):
    """A company or source of income."""

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="income_sources"
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def total_income(self):
        """Total income received from this source."""
        return (
            self.transactions.aggregate(total=Sum("amount"))["total"]
            or 0
        )


class IncomeTransaction(models.Model):
    """A single income record."""

    source = models.ForeignKey(
        IncomeSource,
        on_delete=models.CASCADE,
        related_name="transactions",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField()
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"৳{self.amount} from {self.source.name} on {self.date}"
