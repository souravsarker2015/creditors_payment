from django.db import models
from django.utils.translation import gettext_lazy as _
from django.db.models import DecimalField, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.contrib.auth.models import User


class HouseholdCategory(models.Model):
    """Optional grouping for bazar/household purchases (e.g. Groceries, Fish)."""

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="household_categories"
    )
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(
        default=True,
        help_text=_("Inactive records are hidden from lists and pickers but still count in totals."),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "household categories"

    def __str__(self):
        return self.name

    @property
    def total_spent(self):
        """Total spent under this category."""
        return self.purchases.aggregate(total=Sum("amount"))["total"] or 0


class HouseholdMemberQuerySet(models.QuerySet):
    def with_balances(self):
        """Load each member's fronted and paid-back totals in the same query,
        so listing members doesn't cost two extra queries per member."""
        def summed(model, fk):
            rows = model.objects.filter(**{fk: OuterRef("pk")}).values(fk).annotate(t=Sum("amount")).values("t")
            return Coalesce(Subquery(rows), Value(0, output_field=DecimalField()))
        return self.annotate(_spent=summed(Purchase, "buyer"), _settled=summed(Settlement, "member"))


class HouseholdMember(models.Model):
    """A person who occasionally fronts their own money for household purchases.

    Tracking a member on a purchase is optional — most day-to-day bazar entries
    don't need one at all.
    """

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="household_members"
    )
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20, blank=True, default="")
    note = models.TextField(blank=True, default="")
    is_active = models.BooleanField(
        default=True,
        help_text=_("Inactive records are hidden from lists and pickers but still count in totals."),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = HouseholdMemberQuerySet.as_manager()

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    # ── Computed properties ──────────────────────────
    # Each uses the with_balances() annotation when present, else queries.

    @property
    def total_spent(self):
        """Total this member has fronted for household purchases."""
        if hasattr(self, "_spent"):
            return self._spent
        return self.purchases.aggregate(total=Sum("amount"))["total"] or 0

    @property
    def total_settled(self):
        """Total already given back to this member."""
        if hasattr(self, "_settled"):
            return self._settled
        return self.settlements.aggregate(total=Sum("amount"))["total"] or 0

    @property
    def balance_due(self):
        """Amount still owed back to this member."""
        return self.total_spent - self.total_settled

    @property
    def is_settled(self):
        """True if nothing is currently owed to this member."""
        return self.balance_due <= 0


class Purchase(models.Model):
    """A single household/bazar purchase.

    ``buyer`` and ``category`` are both optional — a purchase can simply be
    "amount + date" with nothing else, since person tracking isn't mandatory.
    """

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="household_purchases"
    )
    buyer = models.ForeignKey(
        HouseholdMember,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchases",
    )
    category = models.ForeignKey(
        HouseholdCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchases",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField()
    description = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"৳{self.amount} bazar on {self.date}"


class Settlement(models.Model):
    """Giving back the accumulated amount to a member who fronted money."""

    member = models.ForeignKey(
        HouseholdMember, on_delete=models.CASCADE, related_name="settlements"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField()
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"Settled ৳{self.amount} to {self.member.name} on {self.date}"
