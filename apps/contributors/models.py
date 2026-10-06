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
    name = models.CharField(max_length=255, verbose_name=_("Name"))
    category = models.CharField(
        max_length=32,
        choices=ContributorCategory.choices,
        default=ContributorCategory.OTHER,
        verbose_name=_("Category"),
    )
    phone = models.CharField(max_length=20, blank=True, null=True, verbose_name=_("Phone"))
    note = models.TextField(blank=True, null=True, verbose_name=_("Note"))
    is_active = models.BooleanField(
        default=True,
        help_text=_("Inactive records are hidden from lists and pickers but still count in totals."),
        verbose_name=_("Active"),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

class Contribution(models.Model):
    contributor = models.ForeignKey(Contributor, on_delete=models.CASCADE, related_name="contributions", verbose_name=_("Contributor"))
    amount = models.DecimalField(max_digits=15, decimal_places=2, verbose_name=_("Amount"))
    wallet = models.ForeignKey("wallets.Wallet", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                               verbose_name=_("Wallet"))
    date = models.DateField(verbose_name=_("Date"))
    note = models.TextField(blank=True, null=True, verbose_name=_("Note"))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.contributor.name} - {self.amount} on {self.date}"
