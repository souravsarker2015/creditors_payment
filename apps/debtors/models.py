import datetime
from django.db import models
from django.db.models import Sum, Q
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from apps.core.people_categories import PersonCategory
from apps.core.receipts import RECEIPT_VALIDATORS, personal_receipt_path
from apps.core.validators import above_zero

DUE_SOON_DAYS = 7


class DefaultDebtorCategory(models.TextChoices):
    """The categories everyone starts with. Each becomes a row of DebtorCategory (with this code), which the person can rename, hide or delete."""

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



class DebtorCategory(PersonCategory):
    """One of a person's debtor categories: the starters, and any they add with the + beside the dropdown."""

    STARTERS = DefaultDebtorCategory

    class Meta(PersonCategory.Meta):
        verbose_name = _("Debtor category")
        verbose_name_plural = _("Debtor categories")
        constraints = [models.UniqueConstraint(fields=["user", "name"], name="debtor_category_unique_name")]


class Debtor(models.Model):
    """A person who owes you money."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="debtors")

    name = models.CharField(max_length=200, verbose_name=_("Name"))
    category = models.ForeignKey(
        DebtorCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name="debtors",
        verbose_name=_("Category"),
    )
    phone = models.CharField(max_length=20, blank=True, default="", verbose_name=_("Phone"))
    note = models.TextField(blank=True, default="", verbose_name=_("Note"))
    due_date = models.DateField(
        null=True, blank=True, help_text=_("Next expected repayment date (optional)."),
        verbose_name=_("Due date"),
    )
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

            self.category = starting_category(DebtorCategory, self.user, self.user.debtors.all())
        super().save(*args, **kwargs)

    def get_category_display(self):
        """The category's name ("" for none) — the name the old fixed list gave this, kept for the pages and files that use it."""
        return self.category.label if self.category_id else ""

    # ── Computed properties ──────────────────────────

    @property
    def is_overdue(self):
        """True if there's an outstanding balance and the due date has passed."""
        if not self.due_date or self.remaining <= 0:
            return False
        return self.due_date < timezone.localdate()

    @property
    def is_due_soon(self):
        """True if there's an outstanding balance due within DUE_SOON_DAYS, but not yet overdue."""
        if not self.due_date or self.remaining <= 0 or self.is_overdue:
            return False
        return self.due_date <= timezone.localdate() + datetime.timedelta(days=DUE_SOON_DAYS)

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
        verbose_name=_("Debtor"),
    )
    transaction_type = models.CharField(
        max_length=10,
        choices=TYPE_CHOICES,
        default=LEND,
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
        return f"{self.get_transaction_type_display()} ৳{self.amount} — {self.debtor.name}"
