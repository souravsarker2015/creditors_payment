from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from apps.core.people_categories import PersonCategory
from apps.core.validators import above_zero


class DefaultContributorCategory(models.TextChoices):
    """The categories everyone starts with. Each becomes a row of ContributorCategory (with this code), which the person can rename, hide or delete."""

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



class ContributorCategory(PersonCategory):
    """One of a person's contributor categories: the starters, and any they add with the + beside the dropdown."""

    STARTERS = DefaultContributorCategory

    class Meta(PersonCategory.Meta):
        verbose_name = _("Contributor category")
        verbose_name_plural = _("Contributor categories")
        constraints = [models.UniqueConstraint(fields=["user", "name"], name="contributor_category_unique_name")]


class Contributor(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="contributors")
    name = models.CharField(max_length=255, verbose_name=_("Name"))
    category = models.ForeignKey(
        ContributorCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name="contributors",
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

    def save(self, *args, **kwargs):
        # A new one with no category starts in "Other", as the fixed list's default did.
        if self._state.adding and self.category_id is None and self.user_id:
            from apps.core.people_categories import starting_category

            self.category = starting_category(ContributorCategory, self.user, self.user.contributors.all())
        super().save(*args, **kwargs)

    def get_category_display(self):
        """The category's name ("" for none) — the name the old fixed list gave this, kept for the pages and files that use it."""
        return self.category.label if self.category_id else ""

class Contribution(models.Model):
    contributor = models.ForeignKey(Contributor, on_delete=models.CASCADE, related_name="contributions", verbose_name=_("Contributor"))
    amount = models.DecimalField(max_digits=15, decimal_places=2, verbose_name=_("Amount"), validators=[above_zero])
    wallet = models.ForeignKey("wallets.Wallet", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                               verbose_name=_("Wallet"))
    date = models.DateField(verbose_name=_("Date"))
    note = models.TextField(blank=True, null=True, verbose_name=_("Note"))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.contributor.name} - {self.amount} on {self.date}"
