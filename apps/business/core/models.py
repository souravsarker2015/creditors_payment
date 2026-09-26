"""Business module core: dashboard access, the farm (Business) and its team,
the shared base model every business record uses, units, and the audit log.

Nothing here touches the existing apps' tables; users are linked only through
settings.AUTH_USER_MODEL.
"""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import get_language, gettext_lazy as _

MONEY = {"max_digits": 14, "decimal_places": 2}


# ── Dashboards & access ─────────────────────────────────────────────────────

class Dashboard(models.Model):
    """A top-level area of the app a user can be given, e.g. the existing
    personal ledgers or the fish-farm business."""

    code = models.SlugField(unique=True)
    name = models.CharField(max_length=80)
    name_bn = models.CharField(max_length=80, blank=True)
    description = models.CharField(max_length=160, blank=True)
    url_name = models.CharField(max_length=80, help_text="URL name of its home page.")
    icon = models.CharField(max_length=30, default="wallet")
    order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    grant_to_new_users = models.BooleanField(
        default=False, help_text="New sign-ups get this dashboard automatically.")

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name

    @property
    def display_name(self):
        return self.name_bn if (get_language() or "").startswith("bn") and self.name_bn else self.name


class UserDashboardAccess(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="dashboard_access")
    dashboard = models.ForeignKey(Dashboard, on_delete=models.CASCADE, related_name="grants")
    is_default = models.BooleanField(default=False, help_text="Where this user lands after logging in.")
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    granted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "dashboard"], name="one_grant_per_dashboard")]

    def __str__(self):
        return f"{self.user} → {self.dashboard}"


# ── The farm and its team ───────────────────────────────────────────────────

class Business(models.Model):
    """One farm/business. Every business record belongs to one, so staff can
    enter data for the owner's farm and one person can run several farms."""

    name = models.CharField(_("Business name"), max_length=120)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="owned_businesses")
    phone = models.CharField(_("Phone"), max_length=30, blank=True)
    address = models.CharField(_("Address"), max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "businesses"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Role(models.TextChoices):
    OWNER = "owner", _("Owner")
    MANAGER = "manager", _("Manager")
    DATA_ENTRY = "data_entry", _("Data entry")
    VIEWER = "viewer", _("Viewer")


class Membership(models.Model):
    """A person's role in one business. Roles are per business (not global
    groups): someone can manage one farm and only enter data for another."""

    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="business_memberships")
    role = models.CharField(_("Role"), max_length=12, choices=Role.choices, default=Role.DATA_ENTRY)
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["business", "user"], name="one_membership_per_business")]
        ordering = ["business", "role", "user__username"]

    def __str__(self):
        return f"{self.user} · {self.get_role_display()} · {self.business}"


# ── Shared base model ───────────────────────────────────────────────────────

class AliveManager(models.Manager):
    """Default manager: hides soft-deleted rows."""

    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class BusinessBaseModel(models.Model):
    """Base for every business record: owned by one Business, stamped with who
    and when, soft-deletable (restorable), and audited (see signals.py)."""

    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", editable=False)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", editable=False)
    is_active = models.BooleanField(_("Active"), default=True)
    notes = models.TextField(_("Notes"), blank=True, default="")
    is_deleted = models.BooleanField(default=False, editable=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True, editable=False)

    objects = AliveManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True
        # Related lookups (e.g. a sale's unit) must still resolve a deleted row.
        base_manager_name = "all_objects"

    def save(self, *args, **kwargs):
        from .audit import current_user

        user = current_user()
        if user and user.is_authenticated:
            if not self.pk and not self.created_by_id:
                self.created_by = user
            self.updated_by = user
        super().save(*args, **kwargs)

    def soft_delete(self):
        self.is_deleted, self.deleted_at = True, timezone.now()
        self.save(update_fields=["is_deleted", "deleted_at", "updated_at", "updated_by"])

    def restore(self):
        self.is_deleted, self.deleted_at = False, None
        self.save(update_fields=["is_deleted", "deleted_at", "updated_at", "updated_by"])


# ── Units ───────────────────────────────────────────────────────────────────

class UnitType(models.TextChoices):
    WEIGHT = "weight", _("Weight")
    COUNT = "count", _("Count")
    VOLUME = "volume", _("Volume")
    AREA = "area", _("Area")
    OTHER = "other", _("Other")


BASE_UNITS = {UnitType.WEIGHT: "kg", UnitType.COUNT: "pcs", UnitType.VOLUME: "L", UnitType.AREA: "dec", UnitType.OTHER: "unit"}


class Unit(BusinessBaseModel):
    """A unit of measure. Each type has one base unit (kg, piece, litre,
    decimal); every other unit stores how many base units one of it is, so
    any two units of a type convert consistently (1 mon = 40 kg, editable)."""

    name = models.CharField(_("Name"), max_length=40)
    name_bn = models.CharField(_("Name in Bangla"), max_length=40, blank=True)
    symbol = models.CharField(_("Short name"), max_length=12)
    unit_type = models.CharField(_("Measures"), max_length=10, choices=UnitType.choices, default=UnitType.WEIGHT)
    factor = models.DecimalField(
        _("Equals (in base unit)"), max_digits=18, decimal_places=6, default=Decimal("1"),
        validators=[MinValueValidator(Decimal("0.000001"))],
        help_text=_("How many base units one of this is, e.g. 1 mon = 40 kg."))
    is_base = models.BooleanField(default=False, editable=False)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["unit_type", "-is_base", "order", "name"]
        constraints = [
            models.UniqueConstraint(fields=["business", "symbol"], condition=models.Q(is_deleted=False), name="unit_symbol_unique_per_business"),
        ]
        indexes = [models.Index(fields=["business", "unit_type"])]

    def __str__(self):
        return self.display_name

    @property
    def display_name(self):
        return self.name_bn if (get_language() or "").startswith("bn") and self.name_bn else self.name

    def base_unit(self):
        return Unit.objects.filter(business_id=self.business_id, unit_type=self.unit_type, is_base=True).first()


class QuantityMixin(models.Model):
    """Quantity in the unit the user picked, plus the same amount in the base
    unit (kg for weight) so reports can add up mon, kg and grams together."""

    quantity = models.DecimalField(_("Quantity"), max_digits=14, decimal_places=3, validators=[MinValueValidator(0)])
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="+", verbose_name=_("Unit"))
    base_quantity = models.DecimalField(max_digits=18, decimal_places=3, editable=False, default=0)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.base_quantity = (self.quantity or 0) * self.unit.factor
        super().save(*args, **kwargs)


# ── Audit trail ─────────────────────────────────────────────────────────────

class AuditLog(models.Model):
    class Action(models.TextChoices):
        CREATE = "create", _("Created")
        UPDATE = "update", _("Changed")
        DELETE = "delete", _("Deleted")
        RESTORE = "restore", _("Restored")

    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="audit_log")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    action = models.CharField(max_length=10, choices=Action.choices)
    model = models.CharField(max_length=80)
    object_id = models.CharField(max_length=40)
    object_repr = models.CharField(max_length=200)
    changes = models.JSONField(default=dict, blank=True)
    at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-at"]
        indexes = [models.Index(fields=["business", "-at"]), models.Index(fields=["model", "object_id"])]

    def __str__(self):
        return f"{self.at:%Y-%m-%d %H:%M} {self.user} {self.action} {self.model} #{self.object_id}"
