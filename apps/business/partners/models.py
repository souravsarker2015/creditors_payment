"""Partners (অংশীদার) who own the farm together and share its profit.

Each partner has a capital khata:

    money in the business = put in before the app + put in since − taken out

Putting money in or taking it out is money into or out of an account, but it
is not income or expense: the farm's profit doesn't change. Profit is shared
by each partner's share, and what a partner has taken out in a period is set
against their share of that period's profit.
"""
from datetime import date
from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.business.core.models import MONEY, BusinessBaseModel


class Partner(BusinessBaseModel):
    name = models.CharField(_("Name"), max_length=100)
    phone = models.CharField(_("Phone"), max_length=20, blank=True)
    share_pct = models.DecimalField(_("Share of profit (%)"), max_digits=5, decimal_places=2,
                                    validators=[MinValueValidator(0), MaxValueValidator(100)])
    joined_on = models.DateField(_("Partner since"), default=date.today)
    opening_capital = models.DecimalField(_("Money already put in"), default=0, validators=[MinValueValidator(0)], **MONEY,
                                          help_text=_("What they had put into the farm before you started using the app. Usually 0."))

    class Meta:
        ordering = ["-share_pct", "name"]
        constraints = [models.UniqueConstraint(fields=["business", "name"], condition=models.Q(is_deleted=False),
                                               name="partner_name_unique_per_business")]

    def __str__(self):
        return self.name


class EntryKind(models.TextChoices):
    IN = "in", _("Put money in")
    OUT = "out", _("Took money out")


class PartnerEntry(BusinessBaseModel):
    partner = models.ForeignKey(Partner, on_delete=models.CASCADE, related_name="entries")
    date = models.DateField(_("Date"))
    kind = models.CharField(_("What happened"), max_length=3, choices=EntryKind.choices, default=EntryKind.IN)
    amount = models.DecimalField(_("Amount"), validators=[MinValueValidator(Decimal("0.01"))], **MONEY)
    account = models.ForeignKey("business_finance.Account", on_delete=models.PROTECT, related_name="+", verbose_name=_("Account"),
                                help_text=_("Where the money went in, or came out of."))

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["business", "is_deleted", "date"])]

    def __str__(self):
        return f"{self.partner} · {self.get_kind_display()} · {self.date:%d %b %Y}"

    @property
    def is_in(self):
        return self.kind == EntryKind.IN
