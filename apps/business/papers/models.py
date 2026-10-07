"""Farm papers: licences, registrations, lease deeds and land papers, with a
photo or PDF of each and the day it runs out, so a renewal is never missed."""
import os
import uuid
from datetime import date, timedelta

from django.core.validators import MaxValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.business.core.models import BusinessBaseModel
from apps.core.receipts import RECEIPT_VALIDATORS


class PaperKind(models.TextChoices):
    TRADE = "trade", _("Trade licence")
    FISHERY = "fishery", _("Fish farm registration")
    LEASE = "lease", _("Pond lease agreement")
    LAND = "land", _("Land papers (dolil, khatian, porcha)")
    TAX = "tax", _("Tax, TIN or VAT")
    BANK = "bank", _("Bank or loan papers")
    INSURANCE = "insurance", _("Insurance")
    OTHER = "other", _("Other")


def paper_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()[:6] or ".jpg"
    return f"business/{instance.business_id}/papers/{uuid.uuid4().hex}{ext}"


class FarmPaper(BusinessBaseModel):
    title = models.CharField(_("Name"), max_length=120, help_text=_("e.g. Trade licence 2026–27"))
    kind = models.CharField(_("What kind"), max_length=10, choices=PaperKind.choices, default=PaperKind.TRADE)
    number = models.CharField(_("Number"), max_length=60, blank=True, help_text=_("Licence, registration or deed number."))
    issued_by = models.CharField(_("Issued by"), max_length=120, blank=True, help_text=_("e.g. Union Parishad, Upazila Fisheries Office"))
    pond = models.ForeignKey("business_ponds.Pond", on_delete=models.SET_NULL, null=True, blank=True, related_name="papers",
                             verbose_name=_("For pond"))
    issued_on = models.DateField(_("Issued on"), null=True, blank=True)
    expires_on = models.DateField(_("Valid until"), null=True, blank=True, help_text=_("Leave empty if it never runs out."))
    remind_days = models.PositiveSmallIntegerField(_("Remind me (days before)"), default=30, validators=[MaxValueValidator(365)])
    file = models.FileField(_("Photo or PDF"), upload_to=paper_path, blank=True, validators=RECEIPT_VALIDATORS)

    class Meta:
        ordering = [models.F("expires_on").asc(nulls_last=True), "title"]
        indexes = [models.Index(fields=["business", "is_deleted", "expires_on"])]

    def __str__(self):
        return self.title

    @property
    def days_left(self):
        return (self.expires_on - date.today()).days if self.expires_on else None

    @property
    def state(self):
        """expired | soon | valid | forever"""
        left = self.days_left
        if left is None:
            return "forever"
        if left < 0:
            return "expired"
        return "soon" if left <= self.remind_days else "valid"

    @property
    def remind_from(self):
        return self.expires_on - timedelta(days=self.remind_days) if self.expires_on else None
