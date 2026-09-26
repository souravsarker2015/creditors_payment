"""People and firms the farm trades with.

One Party model covers suppliers, buyers and anyone else, rather than separate
Supplier/Buyer tables joined by a generic foreign key: the same person is
often both (a feed dealer who also buys fish), and the credit ledger (baki),
statements and due lists need one thing to point at, search and total.
"""
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.business.core.models import MONEY, BusinessBaseModel


class BuyerType(models.TextChoices):
    ARATDAR = "aratdar", _("Aratdar / wholesaler")
    PAIKAR = "paikar", _("Paikar / trader")
    RETAIL = "retail", _("Retail / local buyer")
    OTHER = "other", _("Other")


class OpeningType(models.TextChoices):
    RECEIVABLE = "receivable", _("They owe me")
    PAYABLE = "payable", _("I owe them")


class Party(BusinessBaseModel):
    name = models.CharField(_("Name"), max_length=120)
    phone = models.CharField(_("Phone"), max_length=30, blank=True)
    address = models.CharField(_("Address"), max_length=200, blank=True)
    contact_person = models.CharField(_("Contact person"), max_length=100, blank=True)
    is_supplier = models.BooleanField(_("Supplier"), default=False, help_text=_("Sells you feed, fingerlings, medicine…"))
    is_buyer = models.BooleanField(_("Buyer"), default=False, help_text=_("Buys your fish."))
    buyer_type = models.CharField(_("Buyer type"), max_length=10, choices=BuyerType.choices, blank=True)
    market = models.ForeignKey("business_markets.Market", on_delete=models.SET_NULL, null=True, blank=True,
                               related_name="buyers", verbose_name=_("Usual market"))
    opening_balance = models.DecimalField(_("Balance before using this app"), default=0, validators=[MinValueValidator(0)], **MONEY)
    opening_type = models.CharField(_("Who owes whom"), max_length=10, choices=OpeningType.choices, default=OpeningType.PAYABLE)
    opening_date = models.DateField(_("As of"), null=True, blank=True)

    class Meta:
        verbose_name_plural = "parties"
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["business", "name"], condition=models.Q(is_deleted=False), name="party_name_unique_per_business")]
        indexes = [models.Index(fields=["business", "is_deleted", "is_supplier"]), models.Index(fields=["business", "is_deleted", "is_buyer"])]

    def __str__(self):
        return self.name

    @property
    def opening_signed(self):
        """+ they owe me, − I owe them."""
        return self.opening_balance if self.opening_type == OpeningType.RECEIVABLE else -self.opening_balance
