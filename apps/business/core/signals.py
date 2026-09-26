from django.conf import settings
from django.contrib.auth.signals import user_logged_in
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .audit import current_user, is_paused
from .models import AuditLog, BusinessBaseModel, Dashboard, UserDashboardAccess


@receiver(post_save, sender=settings.AUTH_USER_MODEL, dispatch_uid="business_grant_new_user_dashboards")
def grant_new_user_dashboards(sender, instance, created, raw=False, **kwargs):
    """New sign-ups get the dashboards marked for everyone (the personal
    ledgers), exactly as before the business module existed."""
    if not created or raw:
        return
    for i, dash in enumerate(Dashboard.objects.filter(grant_to_new_users=True, is_active=True).order_by("order")):
        UserDashboardAccess.objects.get_or_create(user=instance, dashboard=dash, defaults={"is_default": i == 0})


@receiver(user_logged_in, dispatch_uid="business_flag_login")
def flag_login(sender, request, user, **kwargs):
    # The next page load sends the user to their default dashboard (middleware).
    if request is not None and hasattr(request, "session"):
        request.session["dashboard_after_login"] = True


# ── Audit trail for every business record ───────────────────────────────────

SKIP = {"updated_at", "updated_by", "created_at", "created_by"}


def _snapshot(obj):
    data = {}
    for f in obj._meta.concrete_fields:
        if f.name in SKIP:
            continue
        v = getattr(obj, f.attname)
        data[f.name] = v if isinstance(v, (int, bool, type(None))) else str(v)
    return data


@receiver(pre_save, dispatch_uid="business_audit_pre")
def remember_old(sender, instance, raw=False, **kwargs):
    if raw or not isinstance(instance, BusinessBaseModel) or not instance.pk or is_paused():
        return
    old = type(instance).all_objects.filter(pk=instance.pk).first()
    instance._audit_before = _snapshot(old) if old else None


@receiver(post_save, dispatch_uid="business_audit_post")
def log_save(sender, instance, created, raw=False, **kwargs):
    if raw or not isinstance(instance, BusinessBaseModel) or is_paused():
        return
    after = _snapshot(instance)
    before = getattr(instance, "_audit_before", None) or {}
    changes = {k: [before.get(k), v] for k, v in after.items() if before.get(k) != v} if not created else {}
    if created:
        action = AuditLog.Action.CREATE
    elif "is_deleted" in changes:
        action = AuditLog.Action.DELETE if instance.is_deleted else AuditLog.Action.RESTORE
    elif changes:
        action = AuditLog.Action.UPDATE
    else:
        return
    user = current_user()
    AuditLog.objects.create(
        business_id=instance.business_id, user=user if user and user.is_authenticated else None,
        action=action, model=instance._meta.label, object_id=str(instance.pk),
        object_repr=str(instance)[:200], changes={k: v for k, v in changes.items() if k not in ("deleted_at",)},
    )


@receiver(post_delete, dispatch_uid="business_audit_delete")
def log_hard_delete(sender, instance, origin=None, **kwargs):
    if not isinstance(instance, BusinessBaseModel) or is_paused():
        return
    from .models import Business
    # Deleting a whole business (one, or a queryset of them): its log goes with it.
    if isinstance(origin, Business) or getattr(origin, "model", None) is Business:
        return
    user = current_user()
    AuditLog.objects.create(
        business_id=instance.business_id, user=user if user and user.is_authenticated else None,
        action=AuditLog.Action.DELETE, model=instance._meta.label, object_id=str(instance.pk),
        object_repr=str(instance)[:200], changes={"permanently": [False, True]},
    )
