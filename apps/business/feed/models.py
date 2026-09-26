from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.business.core.models import MONEY, BusinessBaseModel, Unit


class FeedForm(models.TextChoices):
    FLOATING = "floating", _("Floating")
    SINKING = "sinking", _("Sinking")
    POWDER = "powder", _("Powder / mash")
    OTHER = "other", _("Other")


class FeedStage(models.TextChoices):
    NURSERY = "nursery", _("Nursery")
    STARTER = "starter", _("Starter")
    GROWER = "grower", _("Grower")
    FINISHER = "finisher", _("Finisher")


class FeedProduct(BusinessBaseModel):
    """A feed you buy, sold in bags of a fixed size."""

    name = models.CharField(_("Name"), max_length=100)
    brand = models.CharField(_("Brand / company"), max_length=80, blank=True)
    form = models.CharField(_("Type"), max_length=10, choices=FeedForm.choices, default=FeedForm.FLOATING)
    stage = models.CharField(_("Stage"), max_length=10, choices=FeedStage.choices, blank=True)
    protein_pct = models.DecimalField(_("Protein"), max_digits=4, decimal_places=1, null=True, blank=True,
                                      validators=[MinValueValidator(0), MaxValueValidator(100)])
    bag_size = models.DecimalField(_("Bag size"), max_digits=8, decimal_places=3, default=25, validators=[MinValueValidator(0.001)])
    bag_unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="+", verbose_name=_("Bag unit"))
    default_price = models.DecimalField(_("Usual price per bag"), null=True, blank=True, validators=[MinValueValidator(0)], **MONEY)
    suppliers = models.ManyToManyField("business_parties.Party", blank=True, related_name="feed_products", verbose_name=_("Bought from"))
    low_stock_bags = models.DecimalField(_("Warn me below (bags)"), max_digits=8, decimal_places=1, null=True, blank=True,
                                         validators=[MinValueValidator(0)], help_text=_("Low-stock alert once feed stock is tracked."))

    class Meta:
        ordering = ["brand", "name"]
        constraints = [models.UniqueConstraint(fields=["business", "name"], condition=models.Q(is_deleted=False), name="feed_name_unique_per_business")]

    def __str__(self):
        return f"{self.brand} {self.name}".strip() if self.brand and self.brand.lower() not in self.name.lower() else self.name

    @property
    def bag_kg(self):
        return self.bag_size * self.bag_unit.factor

    @property
    def price_per_kg(self):
        return (self.default_price / self.bag_kg).quantize(self.default_price) if self.default_price and self.bag_kg else None


# ── Buying and using feed ───────────────────────────────────────────────────
# Quantities are entered in bags or any weight unit; `kg` is always stored so
# stock is simply (kg bought − kg used) per feed — never typed in by hand.

class FeedPurchase(BusinessBaseModel):
    supplier = models.ForeignKey("business_parties.Party", on_delete=models.PROTECT, related_name="feed_purchases", verbose_name=_("Supplier"))
    date = models.DateField(_("Date"), db_index=True)
    invoice_no = models.CharField(_("Memo / invoice no."), max_length=40, blank=True)
    transport = models.DecimalField(_("Transport / labour"), default=0, validators=[MinValueValidator(0)], **MONEY)
    discount = models.DecimalField(_("Discount"), default=0, validators=[MinValueValidator(0)], **MONEY)
    paid_now = models.DecimalField(_("Paid now"), default=0, validators=[MinValueValidator(0)], **MONEY)
    account = models.ForeignKey("business_finance.Account", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name=_("Paid from"))
    subtotal = models.DecimalField(default=0, editable=False, **MONEY)
    total = models.DecimalField(default=0, editable=False, **MONEY)

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["business", "is_deleted", "date"]), models.Index(fields=["supplier", "date"])]

    def __str__(self):
        return f"{self.supplier} · {self.date:%d %b %Y}"

    @property
    def due(self):
        return max(self.total - self.paid_now, 0)

    @property
    def payment_status(self):
        if self.paid_now >= self.total:
            return "paid"
        return "partial" if self.paid_now else "credit"

    def recalc(self):
        lines = list(self.lines.all())
        self.subtotal = sum((line.amount for line in lines), Decimal(0))
        self.total = max(self.subtotal + self.transport - self.discount, Decimal(0))
        self.save(update_fields=["subtotal", "total", "updated_at", "updated_by"])


def feed_kg(quantity, unit, product):
    """Quantity in bags (unit None) or a weight unit → kg."""
    if quantity is None:
        return None
    return quantity * (unit.factor if unit else product.bag_kg)


class FeedPurchaseLine(BusinessBaseModel):
    purchase = models.ForeignKey(FeedPurchase, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(FeedProduct, on_delete=models.PROTECT, related_name="purchase_lines", verbose_name=_("Feed"))
    quantity = models.DecimalField(_("Quantity"), max_digits=12, decimal_places=3, validators=[MinValueValidator(0.001)])
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, null=True, blank=True, related_name="+", verbose_name=_("Unit"),
                             help_text="Empty = bags")
    rate = models.DecimalField(_("Rate"), validators=[MinValueValidator(0)], **MONEY)
    amount = models.DecimalField(default=0, editable=False, **MONEY)
    kg = models.DecimalField(max_digits=14, decimal_places=3, default=0, editable=False)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.product} × {self.quantity}"

    def save(self, *args, **kwargs):
        self.amount = (self.quantity * self.rate).quantize(Decimal("0.01"))
        self.kg = feed_kg(self.quantity, self.unit, self.product)
        super().save(*args, **kwargs)


class FeedUsage(BusinessBaseModel):
    """Feed given to one pond's running cycle on one day."""

    cycle = models.ForeignKey("business_ponds.CultureCycle", on_delete=models.CASCADE, related_name="feedings", verbose_name=_("Pond"))
    date = models.DateField(_("Date"), db_index=True)
    product = models.ForeignKey(FeedProduct, on_delete=models.PROTECT, related_name="usages", verbose_name=_("Feed"))
    quantity = models.DecimalField(_("Quantity"), max_digits=12, decimal_places=3, validators=[MinValueValidator(0.001)])
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, null=True, blank=True, related_name="+", verbose_name=_("Unit"))
    kg = models.DecimalField(max_digits=14, decimal_places=3, default=0, editable=False)

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["business", "is_deleted", "date"]), models.Index(fields=["cycle", "is_deleted", "date"])]

    def __str__(self):
        return f"{self.product} {self.kg} kg · {self.date:%d %b %Y}"

    def save(self, *args, **kwargs):
        self.kg = feed_kg(self.quantity, self.unit, self.product)
        super().save(*args, **kwargs)
