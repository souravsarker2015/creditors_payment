from django.core.validators import MinValueValidator
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
        """Opening balance for now; transactions and transfers are added in the income/expense phase."""
        return self.opening_balance

    @property
    def masked_number(self):
        return f"•••• {self.number[-4:]}" if len(self.number) > 4 else self.number
