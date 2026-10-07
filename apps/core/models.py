from django.conf import settings
from django.db import models


class OfflineReceipt(models.Model):
    """A save that carried an offline key (see apps/core/offline.py).

    Lets the phone send the same entry again — after a dropped connection,
    or from its offline queue — without it being saved twice."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    key = models.CharField(max_length=64)
    location = models.CharField(max_length=500, blank=True, default="")  # empty while the save is in progress
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "key"], name="one_receipt_per_key")]
        indexes = [models.Index(fields=["created_at"])]

    def __str__(self):
        return f"{self.user_id}:{self.key}"
