"""Dashboard access, the active business, and role capabilities.

Two separate questions:
  * Can this person open a dashboard at all?  → UserDashboardAccess (set by an admin)
  * What may they do inside a business?       → Membership.role (set by the owner)
Superusers can open every dashboard.
"""
from django.urls import NoReverseMatch, reverse
from django.utils.translation import gettext_lazy as _

from .models import Business, Dashboard, Membership, Role, UserDashboardAccess

PERSONAL = "personal"
BUSINESS = "business"

# What each role may do. Kept in code (not global Django groups) because a
# role is per business: one person can manage farm A and only enter data on B.
CAPABILITIES = {
    "enter_data": _("Add and edit day-to-day records (sales, feed, stocking…)"),
    "delete": _("Delete and restore records"),
    "view_reports": _("See profit, loss and reports"),
    "view_finance": _("See income, expenses and household spending"),
    "manage_settings": _("Change units, species, markets and other settings"),
    "manage_team": _("Add or remove people and change their roles"),
}
ROLE_CAPS = {
    Role.OWNER: set(CAPABILITIES),
    Role.MANAGER: {"enter_data", "delete", "view_reports", "view_finance", "manage_settings"},
    Role.DATA_ENTRY: {"enter_data"},
    Role.VIEWER: {"view_reports"},
}


def _cache(request, key, compute):
    store = request.__dict__.setdefault("_business_access_cache", {})
    if key not in store:
        store[key] = compute()
    return store[key]


def user_dashboards(user):
    """Active dashboards this user may open, in menu order."""
    qs = Dashboard.objects.filter(is_active=True)
    if not user.is_superuser:
        qs = qs.filter(grants__user=user)
    return list(qs.order_by("order", "name").distinct())


def has_dashboard(user, code):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return Dashboard.objects.filter(code=code, is_active=True).exists()
    return UserDashboardAccess.objects.filter(user=user, dashboard__code=code, dashboard__is_active=True).exists()


def default_dashboard(user):
    grant = (UserDashboardAccess.objects.filter(user=user, is_default=True, dashboard__is_active=True)
             .select_related("dashboard").first())
    return grant.dashboard if grant else None


def dashboard_url(dashboard):
    try:
        return reverse(dashboard.url_name)
    except NoReverseMatch:
        return "/"


def request_dashboards(request):
    return _cache(request, "dashboards", lambda: user_dashboards(request.user))


def memberships(user):
    return Membership.objects.filter(user=user).select_related("business").order_by("business__name")


def active_membership(request):
    """The business the user is working in: the one chosen this session, else
    their first. None when they don't belong to any business yet."""
    def compute():
        chosen = request.session.get("business_id")
        mine = memberships(request.user)
        return (mine.filter(business_id=chosen).first() if chosen else None) or mine.first()
    return _cache(request, "membership", compute)


def can(membership, capability):
    if membership is None:
        return False
    if membership.user.is_superuser:
        return True
    return capability in ROLE_CAPS.get(membership.role, set())


def create_business(user, name, **fields):
    """New business with its creator as owner, seeded with standard units."""
    from .units import seed_units

    business = Business.objects.create(name=name, owner=user, **{k: v for k, v in fields.items() if k != "mon_kg"})
    Membership.objects.create(business=business, user=user, role=Role.OWNER, added_by=user)
    seed_units(business, mon_kg=fields.get("mon_kg"))
    return business
