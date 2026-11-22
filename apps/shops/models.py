import datetime

from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from apps.core.people_categories import PersonCategory
from apps.core.receipts import RECEIPT_VALIDATORS, personal_receipt_path
from apps.core.validators import above_zero

DUE_SOON_DAYS = 7


class DefaultShopCategory(models.TextChoices):
    """The categories everyone starts with. Each becomes a row of ShopCategory (with this code), which the person can rename, hide or delete."""

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



class ShopCategory(PersonCategory):
    """One of a person's shop categories: the starters, and any they add with the + beside the dropdown."""

    STARTERS = DefaultShopCategory

    class Meta(PersonCategory.Meta):
        verbose_name = _("Shop category")
        verbose_name_plural = _("Shop categories")
        constraints = [models.UniqueConstraint(fields=["user", "name"], name="shop_category_unique_name")]


class Shop(models.Model):
    """A local shop you buy from on credit (বাকি)."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="shops")

    name = models.CharField(max_length=200, verbose_name=_("Name"))
    category = models.ForeignKey(
        ShopCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name="shops",
        verbose_name=_("Category"),
    )
    phone = models.CharField(max_length=20, blank=True, default="", verbose_name=_("Phone"))
    due_date = models.DateField(
        null=True, blank=True, help_text=_("Next settlement due date (optional)."),
        verbose_name=_("Due date"),
    )
    note = models.TextField(blank=True, default="", verbose_name=_("Note"))
    is_active = models.BooleanField(
        default=True,
        help_text=_("Inactive records are hidden from lists and pickers but still count in totals."),
        verbose_name=_("Active"),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # A new one with no category starts in "Other", as the fixed list's default did.
        if self._state.adding and self.category_id is None and self.user_id:
            from apps.core.people_categories import starting_category

            self.category = starting_category(ShopCategory, self.user, self.user.shops.all())
        super().save(*args, **kwargs)

    def get_category_display(self):
        """The category's name ("" for none) — the name the old fixed list gave this, kept for the pages and files that use it."""
        return self.category.label if self.category_id else ""

    # ── Computed properties ──────────────────────────

    @property
    def is_overdue(self):
        """True if there's an unpaid balance and the due date has passed."""
        if not self.due_date or self.remaining <= 0:
            return False
        return self.due_date < timezone.localdate()

    @property
    def is_due_soon(self):
        """True if there's an unpaid balance due within DUE_SOON_DAYS, but not yet overdue."""
        if not self.due_date or self.remaining <= 0 or self.is_overdue:
            return False
        return self.due_date <= timezone.localdate() + datetime.timedelta(days=DUE_SOON_DAYS)

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
        verbose_name=_("Shop"),
    )
    transaction_type = models.CharField(
        max_length=10,
        choices=TYPE_CHOICES,
        default=PURCHASE,
        verbose_name=_("Type"),
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name=_("Amount"), validators=[above_zero])
    wallet = models.ForeignKey("wallets.Wallet", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                               verbose_name=_("Wallet"))
    receipt = models.FileField(_("Receipt photo"), upload_to=personal_receipt_path, blank=True, validators=RECEIPT_VALIDATORS,
                               help_text=_("Optional: a photo of the memo, slip or signed paper."))
    date = models.DateField(verbose_name=_("Date"))
    note = models.TextField(blank=True, default="", verbose_name=_("Note"))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.get_transaction_type_display()} ৳{self.amount} — {self.shop.name}"
