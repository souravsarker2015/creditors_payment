from datetime import date
from decimal import Decimal

from django.core.validators import FileExtensionValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.business.core.models import MONEY, BusinessBaseModel, Unit


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
