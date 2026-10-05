"""Farm equipment — aerators, pumps, generators, nets, boats — and their upkeep.

What a machine cost when bought (if paid from an account) and every service
or repair are money out and farm costs. A machine can be serviced every so
many days; the farm's to-do list says when one is due.
"""
from datetime import timedelta

from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.business.core.models import MONEY, BusinessBaseModel


class Kind(models.TextChoices):
    AERATOR = "aerator", _("Aerator")
    PUMP = "pump", _("Water pump")
    GENERATOR = "generator", _("Generator")
    NET = "net", _("Net")
    BOAT = "boat", _("Boat")
    VEHICLE = "vehicle", _("Van / vehicle")
    TOOL = "tool", _("Tool / other")


class Condition(models.TextChoices):
    WORKING = "working", _("Working")
    REPAIR = "repair", _("Needs repair")
    OUT = "out", _("Out of use")


class Equipment(BusinessBaseModel):
    name = models.CharField(_("Name"), max_length=100, help_text=_("e.g. Paddle aerator 1, Shallow pump"))
    kind = models.CharField(_("Kind"), max_length=10, choices=Kind.choices, default=Kind.AERATOR)
    pond = models.ForeignKey("business_ponds.Pond", on_delete=models.SET_NULL, null=True, blank=True, related_name="equipment",
                             verbose_name=_("Used at"))
    condition = models.CharField(_("Condition"), max_length=8, choices=Condition.choices, default=Condition.WORKING)
    bought_on = models.DateField(_("Bought on"), null=True, blank=True)
    cost = models.DecimalField(_("Price paid"), default=0, validators=[MinValueValidator(0)], **MONEY)
    account = models.ForeignKey("business_finance.Account", on_delete=models.PROTECT, null=True, blank=True, related_name="+",
                                verbose_name=_("Paid from"))
    service_every_days = models.PositiveSmallIntegerField(_("Service every (days)"), null=True, blank=True,
                                                          help_text=_("e.g. 90 for an aerator's oil change. Leave empty if it doesn't need servicing."))

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "equipment"
        constraints = [models.UniqueConstraint(fields=["business", "name"], condition=models.Q(is_deleted=False), name="equipment_name_unique_per_business")]

    def __str__(self):
        return self.name

    def last_service_date(self):
        last = self.services.order_by("-date").values_list("date", flat=True).first()
        return last

    def next_service(self, last=None):
        """When it's next due for a service, or None."""
        if not self.service_every_days or self.condition == Condition.OUT:
            return None
        start = last or self.last_service_date() or self.bought_on
        return start + timedelta(days=self.service_every_days) if start else None


class ServiceKind(models.TextChoices):
    SERVICE = "service", _("Service")
    REPAIR = "repair", _("Repair")
    PART = "part", _("New part")


class Service(BusinessBaseModel):
    """A service, repair or new part for one machine."""

    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, related_name="services")
    date = models.DateField(_("Date"))
    kind = models.CharField(_("What was done"), max_length=8, choices=ServiceKind.choices, default=ServiceKind.SERVICE)
    description = models.CharField(_("Details"), max_length=160, blank=True, help_text=_("e.g. oil change, new motor winding, net mended"))
    cost = models.DecimalField(_("Cost"), default=0, validators=[MinValueValidator(0)], **MONEY)
    account = models.ForeignKey("business_finance.Account", on_delete=models.PROTECT, null=True, blank=True, related_name="+",
                                verbose_name=_("Paid from"))

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.equipment} · {self.get_kind_display()} · {self.date:%d %b %Y}"
