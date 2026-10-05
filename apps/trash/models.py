"""Recently deleted: anything removed from the personal ledgers is kept here
for 30 days, with everything that was deleted along with it, so a mistaken
delete can be undone exactly as it was."""
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class DeletedItem(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="deleted_items")
    label = models.CharField(_("What"), max_length=200)
    kind = models.CharField(_("Kind"), max_length=80)
    data = models.TextField(help_text="The deleted rows as Django JSON, the ones others depend on first.")
    relinks = models.JSONField(default=list, blank=True,
                               help_text="Rows that pointed at the deleted ones and were set to empty: [model, field, [[pk, value], …]].")
    count = models.PositiveIntegerField(default=1)
    back_url = models.CharField(max_length=300, blank=True)
    deleted_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-deleted_at", "-id"]

    def __str__(self):
        return self.label
