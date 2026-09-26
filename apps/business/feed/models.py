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
