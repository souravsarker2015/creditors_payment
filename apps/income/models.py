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
    name = models.CharField(max_length=200, verbose_name=_("Name"))
    description = models.TextField(blank=True, default="", verbose_name=_("Description"))
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
        verbose_name=_("Source"),
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name=_("Amount"))
    wallet = models.ForeignKey("wallets.Wallet", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                               verbose_name=_("Wallet"))
    date = models.DateField(verbose_name=_("Date"))
    note = models.TextField(blank=True, default="", verbose_name=_("Note"))
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
        verbose_name=_("Source"),
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name=_("Amount"))
    wallet = models.ForeignKey("wallets.Wallet", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                               verbose_name=_("Wallet"))
    frequency = models.CharField(max_length=10, choices=RecurringFrequency.choices, verbose_name=_("How often"))
    next_run_date = models.DateField(verbose_name=_("Next date"))
    start_date = models.DateField(_("Starts on"), null=True, blank=True)
    end_date = models.DateField(_("Ends on"), null=True, blank=True, help_text=_("Leave empty if it goes on. Nothing is created after this date."))
    skip_weekend = models.BooleanField(default=False, verbose_name=_("Skip weekends"))
    note = models.TextField(blank=True, default="", verbose_name=_("Note"))
    is_active = models.BooleanField(default=True, verbose_name=_("Active"))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["next_run_date"]

    def __str__(self):
        return f"{self.source.name} · {self.get_frequency_display()} · ৳{self.amount}"

    @property
    def has_ended(self):
        """Past its end date: nothing more will be created."""
        return bool(self.end_date and self.next_run_date and self.next_run_date > self.end_date)

    def _anchored_months(self, from_date, step):
        """Month-based steps stay on the start date's day: from the 31st, Jan 31 → Feb 28 → Mar 31 (not Mar 28)."""
        s = self.start_date
        if s and s.day > 28 and from_date.day == min(s.day, calendar.monthrange(from_date.year, from_date.month)[1]):
            months = (from_date.year - s.year) * 12 + from_date.month - s.month
            return _add_months(s, months + step)
        return _add_months(from_date, step)

    def _advance(self, from_date):
        if self.frequency == RecurringFrequency.WEEKLY:
            return from_date + timedelta(days=7)
        if self.frequency == RecurringFrequency.BIWEEKLY:
            return from_date + timedelta(days=14)
        if self.frequency == RecurringFrequency.MONTHLY:
            return self._anchored_months(from_date, 1)
        if self.frequency == RecurringFrequency.QUARTERLY:
            return self._anchored_months(from_date, 3)
        return self._anchored_months(from_date, 12)  # YEARLY

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
            today = timezone.localdate()

        created = 0
        while self.is_active and created < RECURRING_CATCHUP_LIMIT:
            if self.end_date and self.next_run_date > self.end_date:
                break  # the schedule has ended
            effective_date = self._effective_date(self.next_run_date)
            if effective_date > today:
                break
            IncomeTransaction.objects.create(
                source=self.source,
                amount=self.amount,
                date=effective_date,
                note=self.note,
                wallet=self.wallet,
                recurring_source=self,
            )
            self.next_run_date = self._advance(self.next_run_date)
            created += 1

        if created:
            self.save(update_fields=["next_run_date", "updated_at"])
        return created


def generate_due_recurring_income(user):
    """Catches up every active recurring income schedule for this user. Returns the total transactions created."""
    today = timezone.localdate()
    due = RecurringIncome.objects.filter(
        source__user=user, is_active=True, next_run_date__lte=today
    ).select_related("source")
    total = 0
    for schedule in due:
        total += schedule.generate_due_transactions(today=today)
    return total
