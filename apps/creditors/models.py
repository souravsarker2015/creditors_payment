import datetime
from decimal import Decimal, ROUND_HALF_UP
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum, Q
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

DUE_SOON_DAYS = 7


class InterestType(models.TextChoices):
    FIXED = "FIXED", _("Fixed Amount")
    MONTHLY = "MONTHLY", _("Monthly")
    QUARTERLY = "QUARTERLY", _("Every 3 Months")
    SEMI_ANNUAL = "SEMI_ANNUAL", _("Every 6 Months")
    YEARLY = "YEARLY", _("Yearly")


# Day-count convention for the period-rate estimate below: actual days
# elapsed over an approximate period length. This is an approximation —
# real loan agreements may use a different convention (e.g. calendar
# months) — so it's always presented to the user as an estimate, never as
# an authoritative figure.
INTEREST_PERIOD_DAYS = {
    InterestType.MONTHLY: Decimal(30),
    InterestType.QUARTERLY: Decimal(91),
    InterestType.SEMI_ANNUAL: Decimal(182),
    InterestType.YEARLY: Decimal(365),
}

# Natural-language period noun for sentences like "2% per {noun}" — distinct
# from InterestType's choice labels, which are phrased for a dropdown
# ("Every 3 Months") rather than a sentence ("per 3 months").
INTEREST_PERIOD_NOUN = {
    InterestType.MONTHLY: _("month"),
    InterestType.QUARTERLY: _("3 months"),
    InterestType.SEMI_ANNUAL: _("6 months"),
    InterestType.YEARLY: _("year"),
}


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
    interest_type = models.CharField(
        max_length=16,
        choices=InterestType.choices,
        null=True,
        blank=True,
        help_text=_("How interest is charged (optional). Leave blank for interest-free debt."),
    )
    interest_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text=_("Interest rate per period, %% — used for Monthly/Every 3 Months/Every 6 Months/Yearly."),
    )
    interest_fixed_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text=_("A flat interest amount (৳) — used only when the type is Fixed Amount."),
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
    def interest_period_noun(self):
        """Natural-language period noun for sentences, e.g. '2% per month'.
        None for FIXED (period-less) or when no interest type is set."""
        return INTEREST_PERIOD_NOUN.get(self.interest_type)

    @property
    def accrued_interest(self):
        """Estimated interest owed right now, on top of the outstanding
        balance. Returns 0 if there's no interest type set or nothing
        outstanding.

        - Fixed Amount: the configured flat amount, as-is, until it's
          posted (post_accrued_interest() clears it afterwards so the same
          fixed charge can't be posted twice).
        - Monthly / Every 3 Months / Every 6 Months / Yearly: simple
          interest on the outstanding balance — rate% × (actual days since
          the last transaction ÷ the period's approximate day count) — so
          a partial period accrues a proportional amount rather than
          jumping in whole-period steps.

        This is a live estimate for display only — it is never added to
        the ledger automatically. Use post_accrued_interest() to formalize
        it.
        """
        principal = self.remaining
        if not self.interest_type or principal <= 0:
            return Decimal("0.00")

        if self.interest_type == InterestType.FIXED:
            if not self.interest_fixed_amount:
                return Decimal("0.00")
            return self.interest_fixed_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        if not self.interest_rate:
            return Decimal("0.00")

        last_date = self.last_transaction_date
        if not last_date:
            return Decimal("0.00")

        days_elapsed = (timezone.now().date() - last_date).days
        if days_elapsed <= 0:
            return Decimal("0.00")

        period_days = INTEREST_PERIOD_DAYS[self.interest_type]
        rate = self.interest_rate / Decimal(100)
        periods_elapsed = Decimal(days_elapsed) / period_days
        interest = principal * rate * periods_elapsed
        return interest.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def balance_with_interest(self):
        """Outstanding principal plus today's estimated accrued interest."""
        return self.remaining + self.accrued_interest

    def post_accrued_interest(self):
        """Capitalizes today's accrued interest into the ledger as a BORROW
        transaction, so it starts counting toward the principal (and, for
        period-rate types, resets the accrual clock). Returns the posted
        Transaction, or None if there was nothing (worth) posting.

        Recomputes the amount itself rather than trusting a caller-supplied
        figure, so this is always in sync with the ledger at the moment
        it's called.
        """
        amount = self.accrued_interest
        if amount <= 0:
            return None
        transaction = self.transactions.create(
            transaction_type=Transaction.BORROW,
            amount=amount,
            date=timezone.now().date(),
            note=str(_("Accrued interest (posted)")),
        )
        if self.interest_type == InterestType.FIXED:
            # A flat charge is a one-off — clear it so it isn't offered
            # again until a new fixed amount is configured. The posted
            # transaction remains as the permanent record.
            self.interest_fixed_amount = None
            self.save(update_fields=["interest_fixed_amount"])
        return transaction


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
