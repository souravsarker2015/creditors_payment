"""What the Zakat helper remembers between visits: today's gold and silver
prices, what you hold of each, and the lines you chose to count."""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

GOLD_NISAB_G = Decimal("87.48")      # 7.5 tola
SILVER_NISAB_G = Decimal("612.36")   # 52.5 tola
RATE = Decimal("0.025")


class Basis(models.TextChoices):
    SILVER = "silver", _("Silver (52.5 tola) — the lower, safer line")
    GOLD = "gold", _("Gold (7.5 tola)")


class ZakatSettings(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="zakat_settings")
    basis = models.CharField(_("Nisab by"), max_length=6, choices=Basis.choices, default=Basis.SILVER)
    gold_price = models.DecimalField(_("Gold price per gram"), max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    silver_price = models.DecimalField(_("Silver price per gram"), max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    gold_grams = models.DecimalField(_("Gold you own (grams)"), max_digits=10, decimal_places=3, default=0, validators=[MinValueValidator(0)])
    silver_grams = models.DecimalField(_("Silver you own (grams)"), max_digits=10, decimal_places=3, default=0, validators=[MinValueValidator(0)])
    other_assets = models.DecimalField(_("Other savings & investments"), max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    other_debts = models.DecimalField(_("Other debts due now"), max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    farm_share = models.PositiveSmallIntegerField(_("Your share of the farm (%)"), default=100, validators=[MaxValueValidator(100)])
    skip = models.JSONField(default=list, blank=True, help_text="Keys of the automatic lines left out.")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Zakat settings · {self.user}"
