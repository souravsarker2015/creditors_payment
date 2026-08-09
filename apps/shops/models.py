import datetime

from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

DUE_SOON_DAYS = 7


class ShopCategory(models.TextChoices):
    GROCERY = "GROCERY", _("Grocery")
    PHARMACY = "PHARMACY", _("Pharmacy")
    VEGETABLE = "VEGETABLE", _("Vegetable & Fruit")
    BAKERY = "BAKERY", _("Bakery")
    HARDWARE = "HARDWARE", _("Hardware Store")
    CLOTHING = "CLOTHING", _("Clothing")
    ELECTRONICS = "ELECTRONICS", _("Electronics")
    STATIONERY = "STATIONERY", _("Stationery")
    RESTAURANT = "RESTAURANT", _("Restaurant")
    OTHER = "OTHER", _("Other")


class Shop(models.Model):
    """A local shop you buy from on credit (বাকি)."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="shops")

    name = models.CharField(max_length=200)
    category = models.CharField(
        max_length=32,
        choices=ShopCategory.choices,
        default=ShopCategory.OTHER,
    )
    phone = models.CharField(max_length=20, blank=True, default="")
    due_date = models.DateField(
        null=True, blank=True, help_text=_("Next settlement due date (optional).")
    )
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    # ── Computed properties ──────────────────────────

    @property
    def is_overdue(self):
        """True if there's an unpaid balance and the due date has passed."""
        if not self.due_date or self.remaining <= 0:
            return False
        return self.due_date < timezone.now().date()

    @property
    def is_due_soon(self):
        """True if there's an unpaid balance due within DUE_SOON_DAYS, but not yet overdue."""
        if not self.due_date or self.remaining <= 0 or self.is_overdue:
            return False
        return self.due_date <= timezone.now().date() + datetime.timedelta(days=DUE_SOON_DAYS)

    @property
    def total_due(self):
        """Total amount put on credit (বাকি) at this shop."""
        return (
            self.transactions.filter(transaction_type=Transaction.PURCHASE).aggregate(
                total=models.Sum("amount")
            )["total"]
            or 0
        )

    @property
    def total_paid(self):
        """Total amount already paid to this shop."""
        return (
            self.transactions.filter(transaction_type=Transaction.PAYMENT).aggregate(
                total=models.Sum("amount")
            )["total"]
            or 0
        )

    @property
    def remaining(self):
        """Outstanding due (বাকি) still owed to this shop."""
        return self.total_due - self.total_paid

    @property
    def is_paid(self):
        """True if nothing is currently owed to this shop."""
        return self.remaining <= 0


class Transaction(models.Model):
    """A single purchase-on-credit or payment event for a shop."""

    PURCHASE = "PURCHASE"
    PAYMENT = "PAYMENT"
    TYPE_CHOICES = [
        (PURCHASE, _("Purchase (বাকি)")),
        (PAYMENT, _("Payment")),
    ]

    shop = models.ForeignKey(
        Shop,
        on_delete=models.CASCADE,
        related_name="transactions",
    )
    transaction_type = models.CharField(
        max_length=10,
        choices=TYPE_CHOICES,
        default=PURCHASE,
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField()
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.get_transaction_type_display()} ৳{self.amount} — {self.shop.name}"
