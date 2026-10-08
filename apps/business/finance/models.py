from django.core.validators import FileExtensionValidator, MinValueValidator
from django.db import models
from django.utils.translation import get_language, gettext_lazy as _

from apps.business.core.models import MONEY, BusinessBaseModel


class CategoryType(models.TextChoices):
    EXPENSE = "expense", _("Expense")
    INCOME = "income", _("Income")


class Scope(models.TextChoices):
    BUSINESS = "business", _("Farm business")
    HOUSEHOLD = "household", _("Household")
    PERSONAL = "personal", _("Personal")


class Category(BusinessBaseModel):
    """Income/expense category, two levels deep: e.g. Children → School fees."""

    name = models.CharField(_("Name"), max_length=80)
    name_bn = models.CharField(_("Name in Bangla"), max_length=80, blank=True)
    type = models.CharField(_("Type"), max_length=8, choices=CategoryType.choices, default=CategoryType.EXPENSE)
    scope = models.CharField(_("For"), max_length=10, choices=Scope.choices, default=Scope.BUSINESS)
    parent = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True, related_name="children",
                               verbose_name=_("Inside"))
    is_system = models.BooleanField(default=False, editable=False, help_text="Filled in automatically (e.g. fish sales).")
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["type", "scope", "order", "name"]
        constraints = [models.UniqueConstraint(fields=["business", "type", "scope", "parent", "name"], condition=models.Q(is_deleted=False),
                                               name="category_unique_per_parent")]
        indexes = [models.Index(fields=["business", "is_deleted", "type", "scope"])]

    def __str__(self):
        return f"{self.parent.display_name} › {self.display_name}" if self.parent_id else self.display_name

    def save(self, *args, **kwargs):
        if not self.pk and not self.order:  # new ones go last in their group
            last = Category.all_objects.filter(business_id=self.business_id, type=self.type, scope=self.scope, parent_id=self.parent_id).aggregate(m=models.Max("order"))["m"]
            self.order = (last or 0) + 1
        super().save(*args, **kwargs)

    @property
    def display_name(self):
        return self.name_bn if (get_language() or "").startswith("bn") and self.name_bn else self.name


class AccountKind(models.TextChoices):
    CASH = "cash", _("Cash")
    BANK = "bank", _("Bank account")
    MOBILE = "mobile", _("Mobile banking (bKash, Nagad…)")
    OTHER = "other", _("Other")


class Account(BusinessBaseModel):
    """Where money is kept: cash box, bank account, bKash…"""

    name = models.CharField(_("Name"), max_length=80)
    kind = models.CharField(_("Type"), max_length=8, choices=AccountKind.choices, default=AccountKind.CASH)
    institution = models.CharField(_("Bank / provider"), max_length=80, blank=True)
    number = models.CharField(_("Account / wallet number"), max_length=40, blank=True)
    opening_balance = models.DecimalField(_("Balance when you start"), default=0, validators=[MinValueValidator(0)], **MONEY)
    opening_date = models.DateField(_("As of"), null=True, blank=True)
    is_default = models.BooleanField(_("Use by default"), default=False, help_text=_("Picked first when you record money in or out."))

    class Meta:
        ordering = ["-is_default", "kind", "name"]
        constraints = [models.UniqueConstraint(fields=["business", "name"], condition=models.Q(is_deleted=False), name="account_name_unique_per_business")]

    def __str__(self):
        return self.name

    @property
    def balance(self):
        """Everything that has passed through this account. Worked out live in
        services.balances(); a single account falls back to computing its own."""
        from .services import balances

        return balances(self.business).get(self.pk, self.opening_balance)

    @property
    def masked_number(self):
        return f"•••• {self.number[-4:]}" if len(self.number) > 4 else self.number


class FamilyMember(BusinessBaseModel):
    """Someone in the family who brings money home from outside the farm: a son
    working abroad, a brother with a salary, a wife's tailoring… Their income
    is household money, kept apart from the farm's profit (Scope.HOUSEHOLD)."""

    name = models.CharField(_("Name"), max_length=80)
    relation = models.CharField(_("Relation"), max_length=40, blank=True, help_text=_("e.g. Son, Brother, Wife"))
    phone = models.CharField(_("Phone"), max_length=30, blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["business", "name"], condition=models.Q(is_deleted=False),
                                               name="family_member_name_unique_per_business")]

    def __str__(self):
        return f"{self.name} ({self.relation})" if self.relation else self.name


# ── Money in and out ────────────────────────────────────────────────────────

def receipt_path(instance, filename):
    return f"business/{instance.business_id}/receipts/{instance.pk or 'new'}/{filename}"


class Transaction(BusinessBaseModel):
    """One payment or receipt: farm costs, household spending, other income.

    Fish sales, feed purchases, baki payments and loan payments are NOT stored
    here — they already live in their own tables. The account balance and the
    income/expense reports read all of them together (see services.py), so
    nothing is ever entered twice.
    """

    date = models.DateField(_("Date"), db_index=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="transactions", verbose_name=_("Category"))
    account = models.ForeignKey(Account, on_delete=models.PROTECT, null=True, blank=True, related_name="transactions", verbose_name=_("Paid from / into"))
    amount = models.DecimalField(_("Amount"), validators=[MinValueValidator(0)], **MONEY)
    description = models.CharField(_("What for"), max_length=200, blank=True)
    party = models.ForeignKey("business_parties.Party", on_delete=models.SET_NULL, null=True, blank=True, related_name="transactions", verbose_name=_("Person / firm"))
    member = models.ForeignKey(FamilyMember, on_delete=models.SET_NULL, null=True, blank=True, related_name="transactions",
                               verbose_name=_("Family member"))
    cycle = models.ForeignKey("business_ponds.CultureCycle", on_delete=models.SET_NULL, null=True, blank=True,
                             related_name="expenses", verbose_name=_("For which pond"))
    receipt = models.FileField(_("Receipt photo"), upload_to=receipt_path, blank=True,
                              validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp", "pdf"])])
    recurring = models.ForeignKey("RecurringTransaction", on_delete=models.SET_NULL, null=True, blank=True, related_name="entries", editable=False)

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["business", "is_deleted", "date"]), models.Index(fields=["category", "date"]),
                   models.Index(fields=["account", "date"]), models.Index(fields=["cycle", "date"])]

    def __str__(self):
        return f"{self.category} · {self.amount} · {self.date:%d %b %Y}"

    @property
    def is_income(self):
        return self.category.type == CategoryType.INCOME

    @property
    def signed(self):
        """+ money in, − money out."""
        return self.amount if self.is_income else -self.amount


class Transfer(BusinessBaseModel):
    """Money moved between your own accounts (bank → cash, cash → bKash).
    It is not income or spending, so it has no category."""

    date = models.DateField(_("Date"), db_index=True)
    from_account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="transfers_out", verbose_name=_("From"))
    to_account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="transfers_in", verbose_name=_("To"))
    amount = models.DecimalField(_("Amount"), validators=[MinValueValidator(0)], **MONEY)
    charge = models.DecimalField(_("Charge / fee"), default=0, validators=[MinValueValidator(0)], **MONEY,
                                 help_text=_("Cash-out charge, for example. Taken off the sending account."))
    reference = models.CharField(_("Reference"), max_length=60, blank=True)

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["business", "is_deleted", "date"])]

    def __str__(self):
        return f"{self.from_account} → {self.to_account} · {self.amount}"


class Repeat(models.TextChoices):
    WEEKLY = "weekly", _("Every week")
    MONTHLY = "monthly", _("Every month")
    QUARTERLY = "quarterly", _("Every 3 months")
    HALF_YEARLY = "half", _("Every 6 months")
    YEARLY = "yearly", _("Every year")


class RecurringTransaction(BusinessBaseModel):
    """Something that comes back every month: rent, school fees, a salary.
    It never posts by itself — the app reminds you and you confirm, so a bill
    you didn't actually pay is never in your books."""

    name = models.CharField(_("Name"), max_length=100)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="recurrings", verbose_name=_("Category"))
    account = models.ForeignKey(Account, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name=_("Usually paid from"))
    amount = models.DecimalField(_("Usual amount"), validators=[MinValueValidator(0)], **MONEY)
    repeat = models.CharField(_("How often"), max_length=10, choices=Repeat.choices, default=Repeat.MONTHLY)
    start_date = models.DateField(_("Starts on"))
    end_date = models.DateField(_("Ends on"), null=True, blank=True, help_text=_("Leave empty if it goes on."))
    description = models.CharField(_("What for"), max_length=200, blank=True)
    next_due = models.DateField(_("Next one due"), null=True, blank=True)

    class Meta:
        ordering = ["next_due", "name"]
        indexes = [models.Index(fields=["business", "is_deleted", "next_due"])]

    def __str__(self):
        return self.name

    @property
    def is_finished(self):
        return self.next_due is None or (self.end_date is not None and self.next_due > self.end_date)


class Budget(BusinessBaseModel):
    """A monthly limit for one category: spend against plan."""

    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="budgets", verbose_name=_("Category"))
    month = models.DateField(_("Month"), help_text=_("The first day of the month."))
    amount = models.DecimalField(_("Planned"), validators=[MinValueValidator(0)], **MONEY)

    class Meta:
        ordering = ["-month", "category__order"]
        constraints = [models.UniqueConstraint(fields=["business", "category", "month"], condition=models.Q(is_deleted=False),
                                               name="one_budget_per_category_month")]
        indexes = [models.Index(fields=["business", "is_deleted", "month"])]

    def __str__(self):
        return f"{self.category} · {self.month:%b %Y}"
