from django.db import models
from django.utils.translation import get_language, gettext_lazy as _

from apps.business.core.models import BusinessBaseModel, Unit

COLORS = ["#0e7490", "#b45309", "#7c3aed", "#15803d", "#be123c", "#1d4ed8", "#a16207", "#0f766e", "#9333ea", "#c2410c"]


class Species(BusinessBaseModel):
    """A fish (or prawn) the farm raises or sells: Rui/রুই, Pangas/পাঙ্গাস…"""

    name = models.CharField(_("Name"), max_length=60)
    name_bn = models.CharField(_("Name in Bangla"), max_length=60, blank=True)
    scientific_name = models.CharField(_("Scientific name"), max_length=80, blank=True)
    default_unit = models.ForeignKey(Unit, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                                     verbose_name=_("Usually sold by"))
    color = models.CharField(_("Colour"), max_length=7, default="#0e7490", help_text=_("Used for this fish in charts."))
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name_plural = "species"
        ordering = ["order", "name"]
        constraints = [models.UniqueConstraint(fields=["business", "name"], condition=models.Q(is_deleted=False), name="species_name_unique_per_business")]

    def __str__(self):
        return self.display_name

    def save(self, *args, **kwargs):
        if not self.pk and not self.order:  # new ones go last
            last = Species.all_objects.filter(business_id=self.business_id).aggregate(m=models.Max("order"))["m"]
            self.order = (last or 0) + 1
        super().save(*args, **kwargs)

    @property
    def display_name(self):
        return self.name_bn if (get_language() or "").startswith("bn") and self.name_bn else self.name
