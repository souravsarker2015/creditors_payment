from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.business.core.models import BusinessBaseModel


class Category(models.TextChoices):
    WORK = "work", _("Farm work")
    TASK = "task", _("To do")
    MONEY = "money", _("Money")
    FESTIVAL = "festival", _("Holiday / festival")
    PERSONAL = "personal", _("Personal")


class Repeat(models.TextChoices):
    NONE = "", _("Doesn't repeat")
    WEEKLY = "weekly", _("Every week")
    MONTHLY = "monthly", _("Every month (English date)")
    BN_MONTHLY = "bn_monthly", _("Every month (Bangla date)")
    YEARLY = "yearly", _("Every year (English date)")
    BN_YEARLY = "bn_yearly", _("Every year (Bangla date)")


class CalendarEvent(BusinessBaseModel):
    """Something the farm wants on its calendar: a job, a reminder, a festival."""

    title = models.CharField(_("What"), max_length=150)
    date = models.DateField(_("Date"))
    end_date = models.DateField(_("Until"), null=True, blank=True)
    time = models.TimeField(_("Time"), null=True, blank=True)
    category = models.CharField(_("Kind"), max_length=10, choices=Category.choices, default=Category.WORK)
    pond = models.ForeignKey("business_ponds.Pond", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name=_("Pond"))
    repeat = models.CharField(_("Repeat"), max_length=10, choices=Repeat.choices, blank=True, default="")
    repeat_until = models.DateField(_("Repeat until"), null=True, blank=True)
    done = models.BooleanField(_("Done"), default=False)

    class Meta:
        ordering = ["date", "time", "id"]
        indexes = [models.Index(fields=["business", "is_deleted", "date"])]

    def __str__(self):
        return self.title

    def clean(self):
        if self.end_date and self.end_date < self.date:
            raise ValidationError({"end_date": _("This has to be on or after the start date.")})
        if self.repeat and self.end_date:
            raise ValidationError({"end_date": _("A repeating event can only be one day long.")})
        if self.repeat_until and self.repeat_until < self.date:
            raise ValidationError({"repeat_until": _("This has to be after the first date.")})

    @property
    def is_task(self):
        return self.category == Category.TASK
