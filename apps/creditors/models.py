import datetime
from decimal import Decimal, ROUND_HALF_UP
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum, Q
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

DUE_SOON_DAYS = 7

# Day-count convention for the simple-interest estimate below: actual days
# elapsed over a 365-day year. This is an approximation — real loan
# agreements may use a different convention — so it's always presented to
# the user as an estimate, never as an authoritative figure.
INTEREST_DAYS_PER_YEAR = Decimal("365")


class CreditorCategory(models.TextChoices):
    FAMILY = "FAMILY", _("Family")
    FRIEND = "FRIEND", _("Friend")
    BUSINESS_PARTNER = "BUSINESS_PARTNER", _("Business Partner")
    BANK = "BANK", _("Bank")
    MICROFINANCE = "MICROFINANCE", _("Microfinance")
    MONEYLENDER = "MONEYLENDER", _("Moneylender")
    SUPPLIER = "SUPPLIER", _("Supplier")
    LANDLORD = "LANDLORD", _("Landlord")
    UTILITY = "UTILITY", _("Utility")
    MEDICAL = "MEDICAL", _("Medical")
    EDUCATION = "EDUCATION", _("Education")
    OTHER = "OTHER", _("Other")


class Creditor(models.Model):
    """A person you have borrowed money from."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="creditors")

    name = models.CharField(max_length=200)
    category = models.CharField(
        max_length=32,
        choices=CreditorCategory.choices,
        default=CreditorCategory.OTHER,
    )
    phone = models.CharField(max_length=20, blank=True, default="")
    note = models.TextField(blank=True, default="")
    due_date = models.DateField(
        null=True, blank=True, help_text=_("Next payment due date (optional).")
    )
    interest_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text=_("Annual simple interest rate, %% (optional). Leave blank for interest-free debt."),
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

    @property
    def last_transaction_date(self):
        """Date of the most recent transaction (borrow or repay), if any."""
        last = self.transactions.order_by("-date", "-created_at").first()
        return last.date if last else None

    @property
    def accrued_interest(self):
        """Estimated simple interest accrued on the outstanding balance since
        the last transaction (borrow, repay, or a previously posted interest
        charge). Returns 0 if there's no rate set, nothing outstanding, or no
        transaction history to measure elapsed time from.

        This is a live estimate for display only — it is never added to the
        ledger automatically. Use post_accrued_interest() to formalize it.
        """
        principal = self.remaining
        if not self.interest_rate or principal <= 0:
            return Decimal("0.00")

        last_date = self.last_transaction_date
        if not last_date:
            return Decimal("0.00")

        days_elapsed = (timezone.now().date() - last_date).days
        if days_elapsed <= 0:
            return Decimal("0.00")

        rate = self.interest_rate / Decimal("100")
        interest = principal * rate * Decimal(days_elapsed) / INTEREST_DAYS_PER_YEAR
        return interest.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def balance_with_interest(self):
        """Outstanding principal plus today's estimated accrued interest."""
        return self.remaining + self.accrued_interest

    def post_accrued_interest(self):
        """Capitalizes today's accrued interest into the ledger as a BORROW
        transaction, so it starts counting toward the principal and the
        accrual clock resets. Returns the posted Transaction, or None if
        there was nothing (worth) posting.

        Recomputes the amount itself rather than trusting a caller-supplied
        figure, so this is always in sync with the ledger at the moment
        it's called.
        """
        amount = self.accrued_interest
        if amount <= 0:
            return None
        return self.transactions.create(
            transaction_type=Transaction.BORROW,
            amount=amount,
            date=timezone.now().date(),
            note=str(_("Accrued interest (posted)")),
        )


class Transaction(models.Model):
    """A single borrow or repayment event."""

    BORROW = "BORROW"
    REPAY = "REPAY"
    TYPE_CHOICES = [
        (BORROW, _("Borrowed")),
        (REPAY, _("Repaid")),
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
