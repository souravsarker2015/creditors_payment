"""Money that settles baki: a buyer paying for fish, or you paying a supplier.

Nothing else is stored here. A party's ledger is built on the fly from the
records that already hold the amounts (opening balance, sales, feed
purchases, stockings) plus these payments, so it can never drift out of step
when one of them is edited or deleted (see services.py).
"""
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.business.core.models import MONEY, BusinessBaseModel


class Direction(models.TextChoices):
    IN = "in", _("Received from them")
    OUT = "out", _("Paid to them")


class PartyPayment(BusinessBaseModel):
    party = models.ForeignKey("business_parties.Party", on_delete=models.PROTECT, related_name="payments", verbose_name=_("Who"))
    direction = models.CharField(_("Money"), max_length=3, choices=Direction.choices, default=Direction.IN)
    date = models.DateField(_("Date"), db_index=True)
    amount = models.DecimalField(_("Amount"), default=0, validators=[MinValueValidator(0)], **MONEY)
    discount = models.DecimalField(_("Discount / let go"), default=0, validators=[MinValueValidator(0)], **MONEY,
                                   help_text=_("Settled without money changing hands, e.g. ৳50 let go to round off."))
    account = models.ForeignKey("business_finance.Account", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name=_("Account"))
    reference = models.CharField(_("Receipt / reference"), max_length=60, blank=True)
    # Optional: the bill this payment is for. Unlinked payments settle the oldest bills first.
    sale = models.ForeignKey("business_sales.FishSale", on_delete=models.SET_NULL, null=True, blank=True, related_name="later_payments")
    feed_purchase = models.ForeignKey("business_feed.FeedPurchase", on_delete=models.SET_NULL, null=True, blank=True, related_name="later_payments")
    stocking = models.ForeignKey("business_ponds.Stocking", on_delete=models.SET_NULL, null=True, blank=True, related_name="later_payments")

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["business", "is_deleted", "date"]), models.Index(fields=["party", "date"])]

    def __str__(self):
        return f"{self.party} · {self.get_direction_display()} · {self.date:%d %b %Y}"

    @property
    def settled(self):
        """How much of the balance this clears (money plus any discount)."""
        return self.amount + self.discount

    @property
    def bill(self):
        return self.sale or self.feed_purchase or self.stocking
