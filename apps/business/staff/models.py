"""Farm workers and their pay.

Each worker has a running balance, like a khata:

    balance = opening + earned − paid

What they earn is written down as it happens (days worked, a month's salary,
a bonus, or a deduction), so changing someone's rate later never changes what
they earned before. Positive balance: the farm still owes them. Negative: they
hold an advance.

Earnings are the farm's labour cost (in reports, and in a pond's cycle when
one is chosen). Payments are money out of an account; an advance is a payment
made before the work is done.
"""
import calendar
from datetime import date
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.business.core.models import MONEY, BusinessBaseModel


class PayType(models.TextChoices):
    MONTHLY = "monthly", _("Monthly salary")
    DAILY = "daily", _("Daily wage")


class Worker(BusinessBaseModel):
    name = models.CharField(_("Name"), max_length=100)
    phone = models.CharField(_("Phone"), max_length=20, blank=True)
    job = models.CharField(_("Work"), max_length=60, blank=True, help_text=_("e.g. guard, feeder, manager, net puller"))
    pay_type = models.CharField(_("Paid by"), max_length=8, choices=PayType.choices, default=PayType.MONTHLY)
    rate = models.DecimalField(_("Salary or wage"), validators=[MinValueValidator(0)], **MONEY,
                               help_text=_("Per month for a monthly salary, per day for a daily wage."))
    started_on = models.DateField(_("Started on"), default=date.today)
    left_on = models.DateField(_("Left on"), null=True, blank=True, help_text=_("Leave empty while they still work here."))
    address = models.CharField(_("Address"), max_length=160, blank=True)
    opening_balance = models.DecimalField(_("Balance when you start"), default=0, **MONEY,
                                          help_text=_("Wages you already owed them (+), or an advance they already had (−). Usually 0."))

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["business", "name"], condition=models.Q(is_deleted=False), name="worker_name_unique_per_business")]

    def __str__(self):
        return self.name

    @property
    def is_monthly(self):
        return self.pay_type == PayType.MONTHLY

    @property
    def has_left(self):
        return bool(self.left_on and self.left_on < date.today())

    def works_on(self, day):
        return self.started_on <= day and (self.left_on is None or day <= self.left_on)

    def salary_for(self, month):
        """A month's salary, for only the days they worked here that month (whole taka)."""
        first = month.replace(day=1)
        last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
        start, end = max(first, self.started_on), min(last, self.left_on or last)
        if end < start:
            return Decimal(0)
        days, total = (end - start).days + 1, (last - first).days + 1
        return (self.rate * days / total).quantize(Decimal("1"))


class EarningKind(models.TextChoices):
    WORK = "work", _("Days worked")
    SALARY = "salary", _("Monthly salary")
    BONUS = "bonus", _("Bonus / extra")
    DEDUCTION = "deduction", _("Deduction / fine")


class Earning(BusinessBaseModel):
    """What a worker earned (or lost, for a deduction): the farm's labour cost."""

    worker = models.ForeignKey(Worker, on_delete=models.CASCADE, related_name="earnings")
    date = models.DateField(_("Date"))
    kind = models.CharField(_("What for"), max_length=10, choices=EarningKind.choices, default=EarningKind.WORK)
    days = models.DecimalField(_("Days"), max_digits=5, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    rate = models.DecimalField(_("Rate"), null=True, blank=True, **MONEY)
    month = models.DateField(_("Month"), null=True, blank=True, editable=False)
    amount = models.DecimalField(_("Amount"), validators=[MinValueValidator(0)], **MONEY)
    cycle = models.ForeignKey("business_ponds.CultureCycle", on_delete=models.SET_NULL, null=True, blank=True,
                              related_name="staff_earnings", verbose_name=_("Pond"),
                              help_text=_("Optional: work done for one pond counts towards that pond's cost."))

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["business", "is_deleted", "date"])]
        constraints = [models.UniqueConstraint(fields=["worker", "month"], condition=models.Q(is_deleted=False, kind="salary"),
                                               name="one_salary_per_worker_month")]

    def __str__(self):
        return f"{self.worker} · {self.get_kind_display()} · {self.date:%d %b %Y}"

    @property
    def signed(self):
        return -self.amount if self.kind == EarningKind.DEDUCTION else self.amount

    def save(self, *args, **kwargs):
        if self.kind == EarningKind.WORK and self.days is not None and self.rate is not None:
            self.amount = (self.days * self.rate).quantize(Decimal("0.01"))
        self.month = self.date.replace(day=1) if self.kind == EarningKind.SALARY else None
        super().save(*args, **kwargs)


class PaymentKind(models.TextChoices):
    WAGE = "wage", _("Wages / salary")
    ADVANCE = "advance", _("Advance")


class WorkerPayment(BusinessBaseModel):
    """Money handed to a worker. Out of an account; lowers what the farm owes them."""

    worker = models.ForeignKey(Worker, on_delete=models.CASCADE, related_name="payments")
    date = models.DateField(_("Date"))
    kind = models.CharField(_("What for"), max_length=8, choices=PaymentKind.choices, default=PaymentKind.WAGE)
    amount = models.DecimalField(_("Amount"), validators=[MinValueValidator(Decimal("0.01"))], **MONEY)
    account = models.ForeignKey("business_finance.Account", on_delete=models.PROTECT, related_name="+", verbose_name=_("Paid from"))

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["business", "is_deleted", "date"])]

    def __str__(self):
        return f"{self.worker} · {self.amount} · {self.date:%d %b %Y}"
