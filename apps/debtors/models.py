from django.db import models
from django.db.models import Sum, Q
from django.contrib.auth.models import User


class Debtor(models.Model):
    """A person who owes you money."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="debtors")

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
    def total_lent(self):
        """Total amount lent to this debtor."""
        return (
            self.transactions.filter(transaction_type=Transaction.LEND).aggregate(
                total=Sum("amount")
            )["total"]
            or 0
        )

    @property
    def total_received(self):
        """Total amount received (collected) from this debtor."""
        return (
            self.transactions.filter(transaction_type=Transaction.RECEIVE).aggregate(
                total=Sum("amount")
            )["total"]
            or 0
        )

    @property
    def remaining(self):
        """Outstanding balance this person owes you."""
        return self.total_lent - self.total_received

    @property
    def is_paid(self):
        """True if the debtor has paid everything back."""
        return self.remaining <= 0


class Transaction(models.Model):
    """A single lending or receiving event."""

    LEND = "LEND"
    RECEIVE = "RECEIVE"
    TYPE_CHOICES = [
        (LEND, "Lent"),
        (RECEIVE, "Received"),
    ]

    debtor = models.ForeignKey(
        Debtor,
        on_delete=models.CASCADE,
        related_name="transactions",
    )
    transaction_type = models.CharField(
        max_length=10,
        choices=TYPE_CHOICES,
        default=LEND,
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField()
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.get_transaction_type_display()} ৳{self.amount} — {self.debtor.name}"
