"""The farm's store of pond supplies: lime, fertilizer, salt, medicine…

Stock is never typed in. It is what was bought minus what was put into ponds
(pond care entries that say "from the store"), so a bag of lime bought once
and used over three months is counted once:

* buying it is money out (what was paid now, from an account) and, if
  something is still owed, a bill in the shop's baki;
* using it is a cost of that pond's cycle, at the average price paid.
"""
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.business.core.models import MONEY, BusinessBaseModel, Unit
from apps.business.ponds.models import TreatmentKind


class SupplyItem(BusinessBaseModel):
    name = models.CharField(_("Name"), max_length=100, help_text=_("e.g. Dolomite lime, Urea, Oxytetracycline"))
    kind = models.CharField(_("What kind"), max_length=12, choices=TreatmentKind.choices, default=TreatmentKind.LIME)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="+", verbose_name=_("Counted in"),
                             help_text=_("The unit the stock is shown in: kg for lime, litre or bottle for medicine."))
    low_stock = models.DecimalField(_("Warn me below"), max_digits=12, decimal_places=3, null=True, blank=True,
                                    validators=[MinValueValidator(0)], help_text=_("In the unit above. Leave empty for no warning."))
    dose_per_decimal = models.DecimalField(_("Usual dose per decimal"), max_digits=10, decimal_places=3, null=True, blank=True,
                                           validators=[MinValueValidator(0)],
                                           help_text=_("Optional, from the bag or bottle, e.g. 1 kg lime per decimal. Fills the dose when you use it."))
    withdrawal_days = models.PositiveSmallIntegerField(_("Don't sell fish for (days)"), null=True, blank=True,
                                                       help_text=_("A medicine's waiting period, filled in each time you use it."))

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["business", "name"], condition=models.Q(is_deleted=False),
                                               name="supply_item_name_unique_per_business")]

    def __str__(self):
        return self.name


class SupplyPurchase(BusinessBaseModel):
    item = models.ForeignKey(SupplyItem, on_delete=models.CASCADE, related_name="purchases")
    date = models.DateField(_("Date"))
    quantity = models.DecimalField(_("Quantity"), max_digits=12, decimal_places=3, validators=[MinValueValidator(Decimal("0.001"))])
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="+", verbose_name=_("Unit"))
    base_quantity = models.DecimalField(max_digits=18, decimal_places=3, default=0, editable=False)
    supplier = models.ForeignKey("business_parties.Party", on_delete=models.PROTECT, null=True, blank=True, related_name="+",
                                 verbose_name=_("Bought from"))
    cost = models.DecimalField(_("Total price"), default=0, validators=[MinValueValidator(0)], **MONEY)
    paid_now = models.DecimalField(_("Paid now"), default=0, validators=[MinValueValidator(0)], **MONEY)
    account = models.ForeignKey("business_finance.Account", on_delete=models.PROTECT, null=True, blank=True, related_name="+",
                                verbose_name=_("Paid from"))

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["business", "is_deleted", "date"])]

    def __str__(self):
        return f"{self.item} · {self.date:%d %b %Y}"

    @property
    def due(self):
        return max(self.cost - self.paid_now, Decimal(0))

    def save(self, *args, **kwargs):
        self.base_quantity = self.quantity * self.unit.factor
        super().save(*args, **kwargs)
