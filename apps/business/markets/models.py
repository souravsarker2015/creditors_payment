from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import get_language, gettext_lazy as _

from apps.business.core.models import BusinessBaseModel, Unit


class DeductionMethod(models.TextChoices):
    PERCENT = "percent", _("% of the sale")
    PER_UNIT = "per_unit", _("Per unit sold")
    FIXED = "fixed", _("Fixed per sale")


class DeductionType(BusinessBaseModel):
    """Something taken off a sale at the market: aarot commission, labour,
    transport, toll/khajna, ice… Fully user-defined."""

    name = models.CharField(_("Name"), max_length=60)
    name_bn = models.CharField(_("Name in Bangla"), max_length=60, blank=True)
    method = models.CharField(_("Usually charged"), max_length=10, choices=DeductionMethod.choices, default=DeductionMethod.FIXED)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]
        constraints = [models.UniqueConstraint(fields=["business", "name"], condition=models.Q(is_deleted=False), name="deduction_type_unique_per_business")]

    def __str__(self):
        return self.name_bn if (get_language() or "").startswith("bn") and self.name_bn else self.name


class Market(BusinessBaseModel):
    """A fish market / aarot where the farm sells."""

    name = models.CharField(_("Name"), max_length=100)
    location = models.CharField(_("Location"), max_length=160, blank=True)
    phone = models.CharField(_("Phone"), max_length=30, blank=True)
    market_days = models.CharField(_("Market days"), max_length=80, blank=True, help_text=_("e.g. Every day, or Sat & Tue"))
    distance_km = models.DecimalField(_("Distance (km)"), max_digits=6, decimal_places=1, null=True, blank=True, validators=[MinValueValidator(0)])

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["business", "name"], condition=models.Q(is_deleted=False), name="market_name_unique_per_business")]

    def __str__(self):
        return self.name


class MarketDeduction(BusinessBaseModel):
    """A market's usual deduction, pre-filled on every sale there (and editable per sale)."""

    market = models.ForeignKey(Market, on_delete=models.CASCADE, related_name="deductions")
    deduction_type = models.ForeignKey(DeductionType, on_delete=models.PROTECT, related_name="+", verbose_name=_("Deduction"))
    method = models.CharField(_("How"), max_length=10, choices=DeductionMethod.choices, default=DeductionMethod.PERCENT)
    value = models.DecimalField(_("Rate"), max_digits=12, decimal_places=3, validators=[MinValueValidator(0)])
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, null=True, blank=True, related_name="+", verbose_name=_("Per"))

    class Meta:
        ordering = ["deduction_type__order", "id"]

    def __str__(self):
        return f"{self.deduction_type}: {self.describe()}"

    def describe(self):
        from apps.business.core.templatetags.business import bdt, num

        if self.method == DeductionMethod.PERCENT:
            return f"{num(self.value)}%"
        if self.method == DeductionMethod.PER_UNIT:
            return f"{bdt(self.value)}/{self.unit.symbol if self.unit else '?'}"
        return bdt(self.value)
