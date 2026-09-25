from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _


class GoalColor(models.TextChoices):
    # Same six hues as the charts, so a goal keeps its colour everywhere.
    BLUE = "blue", _("Blue")
    ORANGE = "orange", _("Orange")
    GREEN = "green", _("Green")
    GOLD = "gold", _("Gold")
    PINK = "pink", _("Pink")
    TEAL = "teal", _("Teal")


class SavingsGoal(models.Model):
    """A pot of money set aside for something. What's saved is exactly what
    was put in minus what was taken out — it isn't guessed from income and
    spending, and moving money into it isn't counted as an expense."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="savings_goals")
    name = models.CharField(_("Goal"), max_length=120)
    target_amount = models.DecimalField(_("Target amount"), max_digits=12, decimal_places=2, validators=[MinValueValidator(1)])
    target_date = models.DateField(
        _("Target date"), null=True, blank=True,
        help_text=_("Optional. With a date you'll see how much to save each month to make it."),
    )
    color = models.CharField(_("Colour"), max_length=10, choices=GoalColor.choices, default=GoalColor.BLUE)
    note = models.TextField(_("Note"), blank=True, default="")
    is_active = models.BooleanField(
        default=True, help_text=_("Archived goals are hidden from the main list; their history is kept."),
    )
    reached_at = models.DateField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["target_date", "name"]

    def __str__(self):
        return self.name


class GoalEntry(models.Model):
    DEPOSIT = "DEPOSIT"
    WITHDRAW = "WITHDRAW"
    KIND_CHOICES = [(DEPOSIT, _("Add money")), (WITHDRAW, _("Take out"))]

    goal = models.ForeignKey(SavingsGoal, on_delete=models.CASCADE, related_name="entries")
    kind = models.CharField(_("Type"), max_length=10, choices=KIND_CHOICES, default=DEPOSIT)
    amount = models.DecimalField(_("Amount"), max_digits=12, decimal_places=2, validators=[MinValueValidator(1)])
    date = models.DateField(_("Date"))
    note = models.CharField(_("Note"), max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    @property
    def signed_amount(self):
        return self.amount if self.kind == self.DEPOSIT else -self.amount
