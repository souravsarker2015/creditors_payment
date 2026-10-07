from datetime import date
from decimal import Decimal

from django.core.validators import FileExtensionValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.business.core.models import MONEY, Business, BusinessBaseModel, Unit


class PondStatus(models.TextChoices):
    IN_USE = "in_use", _("Fish in it")
    PREPARING = "preparing", _("Being prepared")
    EMPTY = "empty", _("Empty / dry")


class Ownership(models.TextChoices):
    OWN = "own", _("Own")
    LEASED = "leased", _("Leased")


def pond_photo_path(instance, filename):
    return f"business/{instance.business_id}/ponds/{filename}"


class Pond(BusinessBaseModel):
    name = models.CharField(_("Name"), max_length=80)
    code = models.CharField(_("Short code"), max_length=12, blank=True, help_text=_("e.g. P-1. Handy on small screens."))
    location = models.CharField(_("Location"), max_length=160, blank=True)
    area = models.DecimalField(_("Area"), max_digits=10, decimal_places=3, null=True, blank=True, validators=[MinValueValidator(0)])
    area_unit = models.ForeignKey(Unit, on_delete=models.PROTECT, null=True, blank=True, related_name="+", verbose_name=_("Area unit"))
    area_decimal = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True, editable=False)
    depth_ft = models.DecimalField(_("Water depth (feet)"), max_digits=5, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    status = models.CharField(_("Status"), max_length=10, choices=PondStatus.choices, default=PondStatus.IN_USE)
    ownership = models.CharField(_("Ownership"), max_length=8, choices=Ownership.choices, default=Ownership.OWN)
    lease_from = models.CharField(_("Leased from"), max_length=120, blank=True)
    lease_amount = models.DecimalField(_("Lease amount"), null=True, blank=True, validators=[MinValueValidator(0)], **MONEY)
    lease_start = models.DateField(_("Lease starts"), null=True, blank=True)
    lease_end = models.DateField(_("Lease ends"), null=True, blank=True)
    photo = models.FileField(_("Photo"), upload_to=pond_photo_path, blank=True,
                             validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp", "heic"])])
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]
        constraints = [models.UniqueConstraint(fields=["business", "name"], condition=models.Q(is_deleted=False), name="pond_name_unique_per_business")]
        indexes = [models.Index(fields=["business", "is_deleted", "status"])]

    def __str__(self):
        return f"{self.code} · {self.name}" if self.code else self.name

    def save(self, *args, **kwargs):
        self.area_decimal = (self.area * self.area_unit.factor) if (self.area and self.area_unit) else None
        super().save(*args, **kwargs)

    @property
    def is_leased(self):
        return self.ownership == Ownership.LEASED

    @property
    def lease_days(self):
        if self.is_leased and self.lease_start and self.lease_end and self.lease_end > self.lease_start:
            return (self.lease_end - self.lease_start).days + 1
        return None

    @property
    def lease_per_day(self):
        """The lease spread evenly over its days (for a cycle's share of it)."""
        days = self.lease_days
        return (self.lease_amount / days) if (days and self.lease_amount) else None

    def lease_share(self, start, end):
        """The part of the lease that falls between two dates (whole taka)."""
        per_day = self.lease_per_day
        if per_day is None:
            return Decimal(0)
        a, b = max(start, self.lease_start), min(end, self.lease_end)
        return (per_day * ((b - a).days + 1)).quantize(Decimal("1")) if b >= a else Decimal(0)

    @property
    def lease_months(self):
        if not (self.lease_start and self.lease_end):
            return None
        return max((self.lease_end.year - self.lease_start.year) * 12 + self.lease_end.month - self.lease_start.month, 0)

    @property
    def lease_days_left(self):
        return (self.lease_end - date.today()).days if self.lease_end else None

    @property
    def lease_per_decimal(self):
        if self.lease_amount and self.area_decimal:
            return (self.lease_amount / self.area_decimal).quantize(Decimal("1"))
        return None


# ── Culture cycles and what happens in them ─────────────────────────────────

class CycleStatus(models.TextChoices):
    RUNNING = "running", _("Running")
    FINISHED = "finished", _("Finished")


class CultureCycle(BusinessBaseModel):
    """One batch/season in one pond: from stocking to the last harvest.
    Stocking, feeding, deaths, weighings, harvests and sales hang off it, so
    every pond and every season has its own profit and loss."""

    pond = models.ForeignKey(Pond, on_delete=models.PROTECT, related_name="cycles", verbose_name=_("Pond"))
    name = models.CharField(_("Name"), max_length=60, blank=True, help_text=_("e.g. Carp mix 2026. Leave empty to name it by date."))
    start_date = models.DateField(_("Started on"))
    expected_harvest = models.DateField(_("Expected harvest"), null=True, blank=True)
    status = models.CharField(_("Status"), max_length=10, choices=CycleStatus.choices, default=CycleStatus.RUNNING)
    ended_on = models.DateField(_("Finished on"), null=True, blank=True)

    class Meta:
        ordering = ["-start_date", "-id"]
        constraints = [models.UniqueConstraint(fields=["pond"], condition=models.Q(status="running", is_deleted=False), name="one_running_cycle_per_pond")]
        indexes = [models.Index(fields=["business", "is_deleted", "status"])]

    def __str__(self):
        return f"{self.pond} · {self.label}"

    @property
    def label(self):
        return self.name or self.start_date.strftime("%b %Y")

    @property
    def is_running(self):
        return self.status == CycleStatus.RUNNING

    @property
    def days(self):
        return ((self.ended_on or date.today()) - self.start_date).days

    @property
    def days_to_harvest(self):
        return (self.expected_harvest - date.today()).days if (self.expected_harvest and self.is_running) else None


class Stocking(BusinessBaseModel):
    """Fingerlings released into a cycle."""

    cycle = models.ForeignKey(CultureCycle, on_delete=models.CASCADE, related_name="stockings")
    date = models.DateField(_("Date"))
    species = models.ForeignKey("business_species.Species", on_delete=models.PROTECT, related_name="+", verbose_name=_("Fish"))
    count = models.PositiveIntegerField(_("Number of fish"), null=True, blank=True)
    weight = models.DecimalField(_("Total weight"), max_digits=12, decimal_places=3, null=True, blank=True, validators=[MinValueValidator(0)])
    weight_unit = models.ForeignKey(Unit, on_delete=models.PROTECT, null=True, blank=True, related_name="+", verbose_name=_("Weight unit"))
    weight_kg = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True, editable=False)
    size = models.CharField(_("Size"), max_length=40, blank=True, help_text=_("e.g. 3–4 inch, or 20 per kg"))
    supplier = models.ForeignKey("business_parties.Party", on_delete=models.PROTECT, null=True, blank=True, related_name="+", verbose_name=_("Bought from"))
    cost = models.DecimalField(_("Total cost"), default=0, validators=[MinValueValidator(0)], **MONEY)
    paid_now = models.DecimalField(_("Paid now"), default=0, validators=[MinValueValidator(0)], **MONEY)

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["cycle", "is_deleted", "date"])]

    def __str__(self):
        return f"{self.species} · {self.date:%d %b %Y}"

    def save(self, *args, **kwargs):
        self.weight_kg = self.weight * self.weight_unit.factor if (self.weight and self.weight_unit) else None
        super().save(*args, **kwargs)

    @property
    def avg_g(self):
        if self.weight_kg and self.count:
            return (self.weight_kg * 1000 / self.count).quantize(Decimal("0.1"))
        return None

    @property
    def due(self):
        return max(self.cost - self.paid_now, 0)


class Mortality(BusinessBaseModel):
    cycle = models.ForeignKey(CultureCycle, on_delete=models.CASCADE, related_name="mortalities")
    date = models.DateField(_("Date"))
    species = models.ForeignKey("business_species.Species", on_delete=models.PROTECT, null=True, blank=True, related_name="+", verbose_name=_("Fish"))
    count = models.PositiveIntegerField(_("Number found dead"))
    cause = models.CharField(_("Likely cause"), max_length=120, blank=True, help_text=_("e.g. low oxygen, disease, bird"))

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.count} · {self.date:%d %b %Y}"


class SampleWeighing(BusinessBaseModel):
    """Catch a few fish, weigh them, and know how they're growing."""

    cycle = models.ForeignKey(CultureCycle, on_delete=models.CASCADE, related_name="weighings")
    date = models.DateField(_("Date"))
    species = models.ForeignKey("business_species.Species", on_delete=models.PROTECT, related_name="+", verbose_name=_("Fish"))
    fish_count = models.PositiveIntegerField(_("Fish weighed"), validators=[MinValueValidator(1)])
    total_weight = models.DecimalField(_("Their total weight"), max_digits=10, decimal_places=3, validators=[MinValueValidator(0.001)])
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="+", verbose_name=_("Unit"))

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.species} {self.avg_g} g · {self.date:%d %b %Y}"

    @property
    def avg_g(self):
        return (self.total_weight * self.unit.factor * 1000 / self.fish_count).quantize(Decimal("0.1"))


class Harvest(BusinessBaseModel):
    """Fish taken out of a cycle (partial or final)."""

    cycle = models.ForeignKey(CultureCycle, on_delete=models.CASCADE, related_name="harvests")
    date = models.DateField(_("Date"))
    species = models.ForeignKey("business_species.Species", on_delete=models.PROTECT, related_name="+", verbose_name=_("Fish"))
    quantity = models.DecimalField(_("Quantity"), max_digits=14, decimal_places=3, validators=[MinValueValidator(0)])
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="+", verbose_name=_("Unit"))
    base_quantity = models.DecimalField(max_digits=18, decimal_places=3, editable=False, default=0)
    fish_count = models.PositiveIntegerField(_("Number of fish"), null=True, blank=True)
    is_final = models.BooleanField(_("Last harvest of this cycle"), default=False,
                                   help_text=_("The pond has been emptied: the cycle is marked finished."))

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["cycle", "is_deleted", "date"])]

    def __str__(self):
        return f"{self.species} · {self.date:%d %b %Y}"

    def save(self, *args, **kwargs):
        self.base_quantity = (self.quantity or 0) * self.unit.factor
        super().save(*args, **kwargs)


class FishMove(BusinessBaseModel):
    """Fish netted out of one pond and released into another: nursery fry
    moved to a grow-out pond, or a crowded pond thinned out.

    No money changes hands. The fish leave one cycle and join the other, and
    so does their value (what they've cost to raise so far): it is taken off
    the first cycle's cost and added to the second's, so each pond's profit
    stays honest. `cycle` is where they came from.
    """

    cycle = models.ForeignKey(CultureCycle, on_delete=models.CASCADE, related_name="moves_out", verbose_name=_("From"))
    to_cycle = models.ForeignKey(CultureCycle, on_delete=models.CASCADE, related_name="moves_in", verbose_name=_("To"))
    date = models.DateField(_("Date"))
    species = models.ForeignKey("business_species.Species", on_delete=models.PROTECT, related_name="+", verbose_name=_("Fish"))
    count = models.PositiveIntegerField(_("Number of fish"), validators=[MinValueValidator(1)])
    weight = models.DecimalField(_("Total weight"), max_digits=12, decimal_places=3, null=True, blank=True, validators=[MinValueValidator(0)])
    weight_unit = models.ForeignKey(Unit, on_delete=models.PROTECT, null=True, blank=True, related_name="+", verbose_name=_("Weight unit"))
    weight_kg = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True, editable=False)
    value = models.DecimalField(_("Their value"), default=0, validators=[MinValueValidator(0)], **MONEY)

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["cycle", "is_deleted", "date"]), models.Index(fields=["to_cycle", "is_deleted", "date"])]

    def __str__(self):
        return f"{self.species} · {self.count} · {self.date:%d %b %Y}"

    def save(self, *args, **kwargs):
        self.weight_kg = self.weight * self.weight_unit.factor if (self.weight and self.weight_unit) else None
        super().save(*args, **kwargs)

    @property
    def avg_g(self):
        if self.weight_kg and self.count:
            return (self.weight_kg * 1000 / self.count).quantize(Decimal("0.1"))
        return None


# ── Water quality ───────────────────────────────────────────────────────────

class TimeOfDay(models.TextChoices):
    DAWN = "dawn", _("Early morning")
    DAY = "day", _("Daytime")
    EVENING = "evening", _("Evening")
    NIGHT = "night", _("Night")


READING = {"max_digits": 6, "decimal_places": 2, "null": True, "blank": True, "validators": [MinValueValidator(0)]}


class WaterTest(BusinessBaseModel):
    """One check of a pond's water. Any reading can be left empty."""

    cycle = models.ForeignKey(CultureCycle, on_delete=models.CASCADE, related_name="water_tests")
    date = models.DateField(_("Date"))
    time_of_day = models.CharField(_("Time"), max_length=8, choices=TimeOfDay.choices, blank=True)
    oxygen = models.DecimalField(_("Dissolved oxygen (mg/L)"), **READING)
    ph = models.DecimalField(_("pH"), **READING)
    temperature = models.DecimalField(_("Water temperature (°C)"), **READING)
    ammonia = models.DecimalField(_("Ammonia (mg/L)"), **READING)
    transparency = models.DecimalField(_("Transparency (cm)"), **READING)

    READINGS = ("oxygen", "ph", "temperature", "ammonia", "transparency")

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["cycle", "is_deleted", "date"])]

    def __str__(self):
        return f"{self.cycle} · {self.date:%d %b %Y}"

    def problems(self, limits):
        """[(reading, what's wrong, what to do)] for readings outside the farm's limits."""
        from .water import check

        return check(self, limits)


class LeasePayment(BusinessBaseModel):
    """Money paid to the owner of a leased pond. Out of an account; brings the
    lease's unpaid balance down."""

    pond = models.ForeignKey(Pond, on_delete=models.CASCADE, related_name="lease_payments")
    date = models.DateField(_("Date"))
    amount = models.DecimalField(_("Amount"), validators=[MinValueValidator(Decimal("0.01"))], **MONEY)
    account = models.ForeignKey("business_finance.Account", on_delete=models.PROTECT, related_name="+", verbose_name=_("Paid from"))
    reference = models.CharField(_("Receipt / reference"), max_length=60, blank=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.pond} · {self.amount} · {self.date:%d %b %Y}"


class TreatmentKind(models.TextChoices):
    LIME = "lime", _("Lime (chun)")
    FERTILIZER = "fertilizer", _("Fertilizer (urea, TSP, dung)")
    SALT = "salt", _("Salt")
    POTASH = "potash", _("Potash")
    MEDICINE = "medicine", _("Medicine / antibiotic")
    PROBIOTIC = "probiotic", _("Probiotic / water care")
    OTHER = "other", _("Other")


class Treatment(BusinessBaseModel):
    """Something put into a pond: lime, fertilizer, salt, medicine…

    Its cost (when paid from an account) is money out of that account and a
    cost of the cycle. Taken from the store (`item`), it was paid for when it
    was bought: its cost is the store's average price and no money moves now.
    A medicine can carry a waiting period: fish from the
    pond shouldn't be sold until it's over.
    """

    cycle = models.ForeignKey(CultureCycle, on_delete=models.CASCADE, related_name="treatments")
    date = models.DateField(_("Date"))
    kind = models.CharField(_("What kind"), max_length=12, choices=TreatmentKind.choices, default=TreatmentKind.LIME)
    item = models.ForeignKey("business_supplies.SupplyItem", on_delete=models.PROTECT, null=True, blank=True, related_name="uses",
                             verbose_name=_("From your store"))
    product = models.CharField(_("Product"), max_length=100, help_text=_("e.g. Dolomite lime, Oxytetracycline, Aquakleen"))
    quantity = models.DecimalField(_("Amount used"), max_digits=12, decimal_places=3, null=True, blank=True, validators=[MinValueValidator(0)])
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, null=True, blank=True, related_name="+", verbose_name=_("Unit"))
    base_quantity = models.DecimalField(max_digits=18, decimal_places=3, null=True, blank=True, editable=False)
    reason = models.CharField(_("Why"), max_length=160, blank=True, help_text=_("e.g. pond preparation, red spots on fish, low oxygen"))
    cost = models.DecimalField(_("Cost"), default=0, validators=[MinValueValidator(0)], **MONEY)
    account = models.ForeignKey("business_finance.Account", on_delete=models.PROTECT, null=True, blank=True, related_name="+",
                                verbose_name=_("Paid from"))
    withdrawal_days = models.PositiveSmallIntegerField(_("Don't sell fish for (days)"), null=True, blank=True,
                                                       help_text=_("The waiting period on the medicine's label. Leave empty if there is none."))

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["cycle", "is_deleted", "date"])]

    def __str__(self):
        return f"{self.product} · {self.date:%d %b %Y}"

    def save(self, *args, **kwargs):
        self.base_quantity = self.quantity * self.unit.factor if (self.quantity is not None and self.unit) else None
        super().save(*args, **kwargs)

    @property
    def safe_from(self):
        """The first day fish from this pond can be sold again, or None."""
        from datetime import timedelta

        return self.date + timedelta(days=self.withdrawal_days) if self.withdrawal_days else None


class PondAlerts(models.Model):
    """The farm's own warning levels. Filled with common defaults; change them
    to suit your fish and your water."""

    business = models.OneToOneField(Business, on_delete=models.CASCADE, related_name="pond_alerts")
    oxygen_min = models.DecimalField(_("Oxygen: warn below (mg/L)"), max_digits=5, decimal_places=2, default=Decimal("4"))
    ph_min = models.DecimalField(_("pH: warn below"), max_digits=4, decimal_places=2, default=Decimal("6.5"))
    ph_max = models.DecimalField(_("pH: warn above"), max_digits=4, decimal_places=2, default=Decimal("8.5"))
    temperature_min = models.DecimalField(_("Temperature: warn below (°C)"), max_digits=5, decimal_places=2, default=Decimal("20"))
    temperature_max = models.DecimalField(_("Temperature: warn above (°C)"), max_digits=5, decimal_places=2, default=Decimal("32"))
    ammonia_max = models.DecimalField(_("Ammonia: warn above (mg/L)"), max_digits=5, decimal_places=2, default=Decimal("0.5"))
    transparency_min = models.DecimalField(_("Transparency: warn below (cm)"), max_digits=5, decimal_places=1, default=Decimal("25"))
    transparency_max = models.DecimalField(_("Transparency: warn above (cm)"), max_digits=5, decimal_places=1, default=Decimal("40"))
    deaths_pct = models.DecimalField(_("Deaths: warn when more than this % of the fish die in 3 days"), max_digits=5, decimal_places=2,
                                     default=Decimal("1"), validators=[MinValueValidator(0)])
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("pond alert levels")

    def __str__(self):
        return f"{self.business} alerts"

    @classmethod
    def for_business(cls, business):
        return cls.objects.get_or_create(business=business)[0]
