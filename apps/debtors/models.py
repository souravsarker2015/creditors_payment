import datetime
from django.db import models
from django.db.models import Sum, Q
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

DUE_SOON_DAYS = 7


class DebtorCategory(models.TextChoices):
    FAMILY = "FAMILY", _("Family")
    FRIEND = "FRIEND", _("Friend")
    BUSINESS_PARTNER = "BUSINESS_PARTNER", _("Business Partner")
    CLIENT = "CLIENT", _("Client")
    EMPLOYEE = "EMPLOYEE", _("Employee")
    TENANT = "TENANT", _("Tenant")
    SHOPKEEPER = "SHOPKEEPER", _("Shopkeeper")
    SUPPLIER = "SUPPLIER", _("Supplier")
    STUDENT = "STUDENT", _("Student")
    MEDICAL = "MEDICAL", _("Medical")
    EDUCATION = "EDUCATION", _("Education")
    OTHER = "OTHER", _("Other")


class Debtor(models.Model):
    """A person who owes you money."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="debtors")

    name = models.CharField(max_length=200)
    category = models.CharField(
        max_length=32,
        choices=DebtorCategory.choices,
        default=DebtorCategory.OTHER,
    )
    phone = models.CharField(max_length=20, blank=True, default="")
    note = models.TextField(blank=True, default="")
    due_date = models.DateField(
        null=True, blank=True, help_text=_("Next expected repayment date (optional).")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    # ── Computed properties ──────────────────────────

    @property
    def is_overdue(self):
        """True if there's an outstanding balance and the due date has passed."""
        if not self.due_date or self.remaining <= 0:
            return False
        return self.due_date < timezone.now().date()

    @property
    def is_due_soon(self):
        """True if there's an outstanding balance due within DUE_SOON_DAYS, but not yet overdue."""
        if not self.due_date or self.remaining <= 0 or self.is_overdue:
            return False
        return self.due_date <= timezone.now().date() + datetime.timedelta(days=DUE_SOON_DAYS)

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
        (LEND, _("Lent")),
        (RECEIVE, _("Received")),
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
