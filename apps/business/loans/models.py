"""Money the business has borrowed: from banks, NGOs, samities or people.

A loan stores only its terms. The schedule (what's due when, how much is
interest) is worked out by schedule.py from those terms plus the payments,
extra borrowing and rate changes recorded here.
"""
from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.business.core.models import MONEY, BusinessBaseModel

from . import schedule as engine


class LenderKind(models.TextChoices):
    BANK = "bank", _("Bank")
    NGO = "ngo", _("NGO / microfinance")
    SAMITY = "samity", _("Samity / co-operative")
    PERSON = "person", _("Person")
    OTHER = "other", _("Other")


class Lender(BusinessBaseModel):
    name = models.CharField(_("Name"), max_length=120)
    kind = models.CharField(_("Type"), max_length=10, choices=LenderKind.choices, default=LenderKind.BANK)
    phone = models.CharField(_("Phone"), max_length=30, blank=True)
    address = models.CharField(_("Branch / address"), max_length=200, blank=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["business", "is_deleted", "name"])]

    def __str__(self):
        return self.name


class RatePeriod(models.TextChoices):
    YEAR = "year", _("per year")
    MONTH = "month", _("per month")


class InterestMethod(models.TextChoices):
    REDUCING = "reducing", _("On what's still owed")
    FLAT = "flat", _("On the full amount (flat)")


class Repayment(models.TextChoices):
    END = "end", _("All at the end")
    EQUAL = "equal", _("A part every time")
    EMI = "emi", _("Equal instalments (EMI)")


class EveryUnit(models.TextChoices):
    MONTH = "month", _("months")
    WEEK = "week", _("weeks")


class Loan(BusinessBaseModel):
    lender = models.ForeignKey(Lender, on_delete=models.PROTECT, related_name="loans", verbose_name=_("Lender"))
    name = models.CharField(_("Purpose"), max_length=120, blank=True)
    account_no = models.CharField(_("Loan / account number"), max_length=60, blank=True)
    principal = models.DecimalField(_("Amount borrowed"), validators=[MinValueValidator(Decimal("1"))], **MONEY)
    taken_on = models.DateField(_("Date received"))
    rate = models.DecimalField(_("Interest rate"), max_digits=7, decimal_places=4, default=0,
                               validators=[MinValueValidator(0), MaxValueValidator(100)])
    rate_period = models.CharField(_("Rate is"), max_length=5, choices=RatePeriod.choices, default=RatePeriod.YEAR)
    method = models.CharField(_("Interest is charged"), max_length=10, choices=InterestMethod.choices, default=InterestMethod.REDUCING)
    every = models.PositiveSmallIntegerField(_("Pay every"), default=1, validators=[MinValueValidator(1), MaxValueValidator(60)])
    every_unit = models.CharField(max_length=5, choices=EveryUnit.choices, default=EveryUnit.MONTH)
    repayment = models.CharField(_("Loan amount is paid back"), max_length=5, choices=Repayment.choices, default=Repayment.END)
    first_due = models.DateField(_("First payment date"), null=True, blank=True)
    maturity = models.DateField(_("End date"), null=True, blank=True)
    closed_on = models.DateField(_("Closed on"), null=True, blank=True)

    class Meta:
        ordering = ["closed_on", "-taken_on"]
        indexes = [models.Index(fields=["business", "is_deleted", "closed_on"])]

    def __str__(self):
        return self.title

    @property
    def title(self):
        return self.name or self.lender.name

    def terms(self, **overrides):
        values = dict(
            principal=self.principal, taken_on=self.taken_on, rate=self.rate, rate_period=self.rate_period,
            method=self.method, repayment=self.repayment, every=self.every, every_unit=self.every_unit,
            first_due=self.first_due, maturity=self.maturity, closed_on=self.closed_on,
        )
        values.update(overrides)
        return engine.Terms(**values)

    def schedule(self, today=None):
        """The live schedule (cached per instance; call refresh_from_db after changes)."""
        key = ("_schedule", today)
        if getattr(self, "_schedule_key", None) != key:
            txns = list(self.transactions.all())
            self._schedule_cache = engine.build(
                self.terms(),
                payments=[(t.date, t.principal, t.interest, t.charges) for t in txns if t.kind == LoanTxnKind.PAYMENT],
                topups=[(t.date, t.principal) for t in txns if t.kind == LoanTxnKind.TOP_UP],
                rate_changes=[(c.effective_from, c.rate) for c in self.rate_changes.all()],
                today=today,
            )
            self._schedule_key = key
        return self._schedule_cache

    def refresh_from_db(self, *args, **kwargs):
        self._schedule_key = None
        super().refresh_from_db(*args, **kwargs)

    @property
    def frequency_label(self):
        return frequency_label(self.every, self.every_unit)


def frequency_label(every, unit):
    from django.utils.translation import gettext as _g, ngettext

    named = {("month", 1): _g("Monthly"), ("month", 2): _g("Every 2 months"), ("month", 3): _g("Quarterly"),
             ("month", 6): _g("Half-yearly"), ("month", 12): _g("Yearly"), ("week", 1): _g("Weekly")}
    if (unit, every) in named:
        return named[(unit, every)]
    if unit == "week":
        return ngettext("Every %(n)s week", "Every %(n)s weeks", every) % {"n": every}
    return ngettext("Every %(n)s month", "Every %(n)s months", every) % {"n": every}


class LoanTxnKind(models.TextChoices):
    PAYMENT = "payment", _("Payment")
    TOP_UP = "top_up", _("Extra borrowing")


class PaidVia(models.TextChoices):
    CASH = "cash", _("Cash")
    BANK = "bank", _("Bank transfer")
    MOBILE = "mobile", _("bKash / Nagad")
    CHEQUE = "cheque", _("Cheque")
    OTHER = "other", _("Other")


class LoanTransaction(BusinessBaseModel):
    """A payment to the lender (split into interest, principal and charges),
    or extra money borrowed on the same loan (principal only)."""

    loan = models.ForeignKey(Loan, on_delete=models.CASCADE, related_name="transactions")
    kind = models.CharField(max_length=8, choices=LoanTxnKind.choices, default=LoanTxnKind.PAYMENT)
    date = models.DateField(_("Date"))
    principal = models.DecimalField(_("Towards the loan"), default=0, validators=[MinValueValidator(0)], **MONEY)
    interest = models.DecimalField(_("Interest"), default=0, validators=[MinValueValidator(0)], **MONEY)
    charges = models.DecimalField(_("Fees / fines"), default=0, validators=[MinValueValidator(0)], **MONEY)
    paid_via = models.CharField(_("Paid by"), max_length=8, choices=PaidVia.choices, default=PaidVia.CASH)
    reference = models.CharField(_("Receipt / reference"), max_length=60, blank=True)

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["loan", "is_deleted", "date"]), models.Index(fields=["business", "date"])]

    def __str__(self):
        return f"{self.get_kind_display()} {self.total} · {self.date}"

    @property
    def total(self):
        return self.principal + self.interest + self.charges


class LoanRateChange(BusinessBaseModel):
    """The lender changed the rate from this date on (banks do this often)."""

    loan = models.ForeignKey(Loan, on_delete=models.CASCADE, related_name="rate_changes")
    effective_from = models.DateField(_("From"))
    rate = models.DecimalField(_("New rate"), max_digits=7, decimal_places=4, validators=[MinValueValidator(0), MaxValueValidator(100)])

    class Meta:
        ordering = ["effective_from"]
        constraints = [models.UniqueConstraint(fields=["loan", "effective_from"], condition=models.Q(is_deleted=False), name="one_rate_change_per_day")]

    def __str__(self):
        return f"{self.rate}% from {self.effective_from}"
