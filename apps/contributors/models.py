from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _


class ContributorCategory(models.TextChoices):
    FAMILY = "FAMILY", _("Family")
    FRIEND = "FRIEND", _("Friend")
    BUSINESS_PARTNER = "BUSINESS_PARTNER", _("Business Partner")
    ORGANIZATION = "ORGANIZATION", _("Organization")
    NGO = "NGO", _("NGO")
    SPONSOR = "SPONSOR", _("Sponsor")
    DONOR = "DONOR", _("Donor")
    INVESTOR = "INVESTOR", _("Investor")
    ALUMNI = "ALUMNI", _("Alumni")
    COMMUNITY = "COMMUNITY", _("Community")
    RELATIVE = "RELATIVE", _("Relative")
    OTHER = "OTHER", _("Other")


class Contributor(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="contributors")
    name = models.CharField(max_length=255)
    category = models.CharField(
        max_length=32,
        choices=ContributorCategory.choices,
        default=ContributorCategory.OTHER,
    )
    phone = models.CharField(max_length=20, blank=True, null=True)
    note = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

class Contribution(models.Model):
    contributor = models.ForeignKey(Contributor, on_delete=models.CASCADE, related_name="contributions")
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    date = models.DateField()
    note = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.contributor.name} - {self.amount} on {self.date}"
