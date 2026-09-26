"""Fish sales: what was sold (lines), what the market took off (deductions),
and what was received now. The rest is due — the credit ledger picks it up."""
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.business.core.models import MONEY, BusinessBaseModel, QuantityMixin, Unit
from apps.business.markets.models import DeductionMethod

CENT = Decimal("0.01")


class FishSale(BusinessBaseModel):
    date = models.DateField(_("Date"), db_index=True)
    market = models.ForeignKey("business_markets.Market", on_delete=models.PROTECT, null=True, blank=True, related_name="sales", verbose_name=_("Market"))
    buyer = models.ForeignKey("business_parties.Party", on_delete=models.PROTECT, null=True, blank=True, related_name="fish_purchases", verbose_name=_("Buyer"))
    cycle = models.ForeignKey("business_ponds.CultureCycle", on_delete=models.SET_NULL, null=True, blank=True, related_name="sales", verbose_name=_("From pond"))
    harvest = models.ForeignKey("business_ponds.Harvest", on_delete=models.SET_NULL, null=True, blank=True, related_name="sales", verbose_name=_("Harvest"))
    memo_no = models.CharField(_("Memo no."), max_length=40, blank=True)
    received_now = models.DecimalField(_("Received now"), default=0, validators=[MinValueValidator(0)], **MONEY)
    account = models.ForeignKey("business_finance.Account", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name=_("Received into"))
    gross = models.DecimalField(default=0, editable=False, **MONEY)
    deductions_total = models.DecimalField(default=0, editable=False, **MONEY)
    net = models.DecimalField(default=0, editable=False, **MONEY)

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["business", "is_deleted", "date"]), models.Index(fields=["buyer", "date"]),
                   models.Index(fields=["market", "date"]), models.Index(fields=["cycle", "date"])]

    def __str__(self):
        who = self.buyer or self.market
        return f"{who} · {self.date:%d %b %Y}" if who else f"{self.date:%d %b %Y}"

    @property
    def due(self):
        return max(self.net - self.received_now, Decimal(0))

    @property
    def payment_status(self):
        if self.received_now >= self.net:
            return "paid"
        return "partial" if self.received_now else "credit"

    def recalc(self):
        """Line amounts, then each deduction, then gross/net. Kept in the model
        so every way of saving a sale (form, admin, tests) agrees."""
        lines = list(self.lines.select_related("unit"))
        self.gross = sum((line.amount for line in lines), Decimal(0))
        total = Decimal(0)
        for d in self.deductions.select_related("unit"):
            d.amount = d.compute(self.gross, lines)
            d.save(update_fields=["amount"])
            total += d.amount
        self.deductions_total = total
        self.net = self.gross - total
        self.save(update_fields=["gross", "deductions_total", "net", "updated_at", "updated_by"])


class FishSaleLine(QuantityMixin, BusinessBaseModel):
    sale = models.ForeignKey(FishSale, on_delete=models.CASCADE, related_name="lines")
    species = models.ForeignKey("business_species.Species", on_delete=models.PROTECT, related_name="+", verbose_name=_("Fish"))
    rate = models.DecimalField(_("Rate"), validators=[MinValueValidator(0)], help_text=_("Per unit chosen"), **MONEY)
    amount = models.DecimalField(default=0, editable=False, **MONEY)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.species} {self.quantity} {self.unit.symbol}"

    def save(self, *args, **kwargs):
        self.amount = ((self.quantity or 0) * (self.rate or 0)).quantize(CENT)
        super().save(*args, **kwargs)


class SaleDeduction(BusinessBaseModel):
    sale = models.ForeignKey(FishSale, on_delete=models.CASCADE, related_name="deductions")
    deduction_type = models.ForeignKey("business_markets.DeductionType", on_delete=models.PROTECT, related_name="+", verbose_name=_("Deduction"))
    method = models.CharField(_("How"), max_length=10, choices=DeductionMethod.choices, default=DeductionMethod.FIXED)
    value = models.DecimalField(_("Rate"), max_digits=12, decimal_places=3, validators=[MinValueValidator(0)])
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, null=True, blank=True, related_name="+", verbose_name=_("Per"))
    amount = models.DecimalField(default=0, editable=False, **MONEY)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.deduction_type}: {self.amount}"

    def compute(self, gross, lines):
        if self.method == DeductionMethod.PERCENT:
            return (gross * self.value / 100).quantize(CENT)
        if self.method == DeductionMethod.PER_UNIT:
            return (self.value * sold_in(lines, self.unit)).quantize(CENT)
        return self.value.quantize(CENT)


def sold_in(lines, unit):
    """Total sold, expressed in `unit` (only lines measured the same way count:
    a per-mon charge applies to fish sold by weight, a per-piece one by count)."""
    if unit is None:
        return Decimal(0)
    base = sum((line.base_quantity for line in lines if line.unit.unit_type == unit.unit_type), Decimal(0))
    return base / unit.factor
