import calendar
from datetime import timedelta

from django.db import models
from django.db.models import Sum, Q
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class IncomeSource(models.Model):
    """A company or source of income."""

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="income_sources"
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(
        default=True,
        help_text=_("Inactive records are hidden from lists and pickers but still count in totals."),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def total_income(self):
        """Total income received from this source."""
        return (
            self.transactions.aggregate(total=Sum("amount"))["total"]
            or 0
        )


class IncomeTransaction(models.Model):
    """A single income record."""

    source = models.ForeignKey(
        IncomeSource,
        on_delete=models.CASCADE,
        related_name="transactions",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField()
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    recurring_source = models.ForeignKey(
        "RecurringIncome",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
    )

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"৳{self.amount} from {self.source.name} on {self.date}"


def _add_months(d, months):
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return d.replace(year=year, month=month, day=day)


class RecurringFrequency(models.TextChoices):
    WEEKLY = "WEEKLY", _("Weekly")
    BIWEEKLY = "BIWEEKLY", _("Every 2 Weeks")
    MONTHLY = "MONTHLY", _("Monthly")
    QUARTERLY = "QUARTERLY", _("Every 3 Months")
    YEARLY = "YEARLY", _("Yearly")


# A page-load can catch up at most this many missed occurrences at once, so a
# very stale schedule (or a bad date) can't lock up a request generating
# hundreds of rows synchronously. Any remainder is picked up on the next visit.
RECURRING_CATCHUP_LIMIT = 60

# date.weekday(): Monday=0 ... Sunday=6. Bangladesh's weekend is Friday+Saturday.
WEEKEND_WEEKDAYS = {4, 5}


class RecurringIncome(models.Model):
    """A schedule that auto-creates IncomeTransactions on a cadence (e.g. monthly salary)."""

    source = models.ForeignKey(
        IncomeSource,
        on_delete=models.CASCADE,
        related_name="recurring_incomes",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    frequency = models.CharField(max_length=10, choices=RecurringFrequency.choices)
    next_run_date = models.DateField()
    skip_weekend = models.BooleanField(default=False)
    note = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["next_run_date"]

    def __str__(self):
        return f"{self.source.name} · {self.get_frequency_display()} · ৳{self.amount}"

    def _advance(self, from_date):
        if self.frequency == RecurringFrequency.WEEKLY:
            return from_date + timedelta(days=7)
        if self.frequency == RecurringFrequency.BIWEEKLY:
            return from_date + timedelta(days=14)
        if self.frequency == RecurringFrequency.MONTHLY:
            return _add_months(from_date, 1)
        if self.frequency == RecurringFrequency.QUARTERLY:
            return _add_months(from_date, 3)
        return _add_months(from_date, 12)  # YEARLY

    def _effective_date(self, scheduled_date):
        """The actual date a payout lands on. The schedule stays anchored to `scheduled_date`
        (e.g. always the 24th) so periods don't drift; only the generated entry's date shifts."""
        if not self.skip_weekend:
            return scheduled_date
        while scheduled_date.weekday() in WEEKEND_WEEKDAYS:
            scheduled_date -= timedelta(days=1)
        return scheduled_date

    @property
    def next_effective_date(self):
        return self._effective_date(self.next_run_date)

    def generate_due_transactions(self, *, today=None):
        """Creates a transaction for every missed occurrence up to today. Returns the count created."""
        if today is None:
            today = timezone.now().date()

        created = 0
        while self.is_active and created < RECURRING_CATCHUP_LIMIT:
            effective_date = self._effective_date(self.next_run_date)
            if effective_date > today:
                break
            IncomeTransaction.objects.create(
                source=self.source,
                amount=self.amount,
                date=effective_date,
                note=self.note,
                recurring_source=self,
            )
            self.next_run_date = self._advance(self.next_run_date)
            created += 1

        if created:
            self.save(update_fields=["next_run_date", "updated_at"])
        return created


def generate_due_recurring_income(user):
    """Catches up every active recurring income schedule for this user. Returns the total transactions created."""
    today = timezone.now().date()
    due = RecurringIncome.objects.filter(
        source__user=user, is_active=True, next_run_date__lte=today
    ).select_related("source")
    total = 0
    for schedule in due:
        total += schedule.generate_due_transactions(today=today)
    return total
