from django.db import models
from django.db.models import Sum, Q
from django.contrib.auth.models import User


class Creditor(models.Model):
    """A person you have borrowed money from."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="creditors")

    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20, blank=True, default="")
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    # ── Computed properties ──────────────────────────

    @property
    def total_borrowed(self):
        """Total amount borrowed from this creditor."""
        return (
            self.transactions.filter(transaction_type=Transaction.BORROW).aggregate(
                total=Sum("amount")
            )["total"]
            or 0
        )

    @property
    def total_paid(self):
        """Total amount repaid to this creditor."""
        return (
            self.transactions.filter(transaction_type=Transaction.REPAY).aggregate(
                total=Sum("amount")
            )["total"]
            or 0
        )

    @property
    def remaining(self):
        """Outstanding balance to this creditor."""
        return self.total_borrowed - self.total_paid

    @property
    def is_paid(self):
        """True if nothing is owed to this creditor."""
        return self.remaining <= 0


class Transaction(models.Model):
    """A single borrow or repayment event."""

    BORROW = "BORROW"
    REPAY = "REPAY"
    TYPE_CHOICES = [
        (BORROW, "Borrowed"),
        (REPAY, "Repaid"),
    ]

    creditor = models.ForeignKey(
        Creditor,
        on_delete=models.CASCADE,
        related_name="transactions",
    )
    transaction_type = models.CharField(
        max_length=10,
        choices=TYPE_CHOICES,
        default=BORROW,
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField()
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.get_transaction_type_display()} ৳{self.amount} — {self.creditor.name}"
