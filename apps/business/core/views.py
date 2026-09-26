import json

from django.apps import apps
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from .access import (BUSINESS, CAPABILITIES, PERSONAL, ROLE_CAPS, active_membership, can, create_business,
                     dashboard_url, has_dashboard, memberships)
from .decorators import business_access_required
from .forms import BusinessProfileForm, BusinessSetupForm, MemberAddForm, RoleForm, UnitForm
from .models import AuditLog, Dashboard, Membership, Role, Unit, UnitType, UserDashboardAccess


def _units_json(business):
    return json.dumps([
        {"id": u.pk, "symbol": u.symbol, "name": u.display_name, "type": u.unit_type, "factor": str(u.factor)}
        for u in Unit.objects.filter(business=business, is_active=True)
    ], ensure_ascii=False)


# ── Home & setup ────────────────────────────────────────────────────────────

@business_access_required
def home_view(request):
    b = request.business
    units = Unit.objects.filter(business=b)
    return render(request, "business/home.html", {
        "team_count": b.members.count(),
        "unit_count": units.count(),
        "mon": units.filter(symbol="mon").first(),
        "units_json": _units_json(b),
        "recent_activity": AuditLog.objects.filter(business=b).select_related("user")[:5],
        "other_businesses": memberships(request.user).exclude(business=b),
        "loans": _loans_summary(request),
    })


def _loans_summary(request):
    """Loans card on the home page (only for people who may see finance)."""
    if not (apps.is_installed("apps.business.loans") and can(request.membership, "view_finance")):
        return None
    from apps.business.loans.services import overview

    return overview(request.business)


@business_access_required(need_business=False)
def setup_view(request):
    """First visit: name the farm and confirm the mon size; units are ready at once."""
    if request.membership is not None and request.GET.get("new") != "1":
        return redirect("business:home")
    form = BusinessSetupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            business = create_business(request.user, form.cleaned_data["name"], phone=form.cleaned_data["phone"],
                                       address=form.cleaned_data["address"], mon_kg=form.cleaned_data["mon_kg"])
        request.session["business_id"] = business.pk
        messages.success(request, _("Welcome to %(name)s! Your units are ready — 1 mon = %(kg)s kg.") % {
            "name": business.name, "kg": f"{form.cleaned_data['mon_kg']:g}"})
        return redirect("business:home")
    return render(request, "business/setup.html", {"form": form})


@business_access_required(need_business=False)
@require_POST
def switch_business_view(request):
    m = memberships(request.user).filter(business_id=request.POST.get("business")).first()
    if m:
        request.session["business_id"] = m.business_id
        messages.success(request, _("Now working in %(name)s.") % {"name": m.business.name})
    return redirect("business:home")


@require_POST
def default_dashboard_view(request):
    """'Open this dashboard after login' from the switcher."""
    if not request.user.is_authenticated:
        return redirect("login")
    code = request.POST.get("dashboard")
    dash = Dashboard.objects.filter(code=code, is_active=True).first()
    if dash and has_dashboard(request.user, code):
        UserDashboardAccess.objects.filter(user=request.user).update(is_default=False)
        grant, _created = UserDashboardAccess.objects.get_or_create(user=request.user, dashboard=dash)
        grant.is_default = True
        grant.save(update_fields=["is_default"])
        messages.success(request, _("%(name)s will open after you log in.") % {"name": dash.display_name})
    nxt = request.POST.get("next") or "/"
    return redirect(nxt if url_has_allowed_host_and_scheme(nxt, {request.get_host()}) else "/")


@business_access_required(capability="manage_settings")
def profile_view(request):
    form = BusinessProfileForm(request.POST or None, instance=request.business)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Business details saved."))
        return redirect("business:profile")
    return render(request, "business/settings/profile.html", {"form": form})


# ── Units ───────────────────────────────────────────────────────────────────

@business_access_required
def unit_list_view(request):
    b = request.business
    show_deleted = request.GET.get("show") == "deleted"
    qs = (Unit.all_objects.filter(business=b, is_deleted=True) if show_deleted else Unit.objects.filter(business=b))
    groups = []
    for value, label in UnitType.choices:
        rows = [u for u in qs if u.unit_type == value]
        if rows:
            base = next((u for u in Unit.objects.filter(business=b, unit_type=value, is_base=True)), None)
            groups.append({"type": value, "label": label, "units": rows, "base": base})
    return render(request, "business/settings/units.html", {
        "groups": groups, "show_deleted": show_deleted,
        "deleted_count": Unit.all_objects.filter(business=b, is_deleted=True).count(),
        "units_json": _units_json(b),
    })


@business_access_required(capability="manage_settings")
def unit_form_view(request, pk=None):
    b = request.business
    unit = get_object_or_404(Unit, pk=pk, business=b) if pk else None
    initial = {"unit_type": request.GET.get("type")} if not unit and request.GET.get("type") in UnitType.values else None
    form = UnitForm(request.POST or None, instance=unit, business=b, initial=initial)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.business = b
        if not unit:
            obj.is_base = not Unit.objects.filter(business=b, unit_type=obj.unit_type, is_base=True).exists()
            if obj.is_base:
                obj.factor = 1
        obj.save()
        messages.success(request, _("Unit saved: %(name)s.") % {"name": obj.display_name})
        return redirect(f"{reverse('business:units')}#type-{obj.unit_type}")
    bases = {u.unit_type: u.symbol for u in Unit.objects.filter(business=b, is_base=True)}
    return render(request, "business/settings/unit_form.html", {
        "form": form, "unit": unit, "bases_json": json.dumps(bases),
    })


@business_access_required(capability="delete")
@require_POST
def unit_delete_view(request, pk):
    unit = get_object_or_404(Unit, pk=pk, business=request.business)
    if unit.is_base:
        messages.error(request, _("The base unit can't be deleted — other units are measured against it."))
    else:
        unit.soft_delete()
        messages.success(request, _("“%(name)s” moved to Deleted. You can restore it any time.") % {"name": unit.display_name})
    return redirect("business:units")


@business_access_required(capability="delete")
@require_POST
def unit_restore_view(request, pk):
    unit = get_object_or_404(Unit.all_objects, pk=pk, business=request.business, is_deleted=True)
    if Unit.objects.filter(business=request.business, symbol__iexact=unit.symbol).exists():
        messages.error(request, _("Another unit is already called “%(symbol)s”. Rename it first.") % {"symbol": unit.symbol})
        return redirect(reverse("business:units") + "?show=deleted")
    unit.restore()
    messages.success(request, _("“%(name)s” restored.") % {"name": unit.display_name})
    return redirect("business:units")


# ── Team ────────────────────────────────────────────────────────────────────

@business_access_required(capability="manage_team")
def team_view(request):
    b = request.business
    form = MemberAddForm(request.POST or None, business=b)
    if request.method == "POST" and form.is_valid():
        user = form.user
        with transaction.atomic():
            if not has_dashboard(user, BUSINESS):
                # Adding someone to your team is what gives them the Business area.
                dash = Dashboard.objects.get(code=BUSINESS)
                UserDashboardAccess.objects.get_or_create(user=user, dashboard=dash, defaults={"granted_by": request.user})
            Membership.objects.create(business=b, user=user, role=form.cleaned_data["role"], added_by=request.user)
        messages.success(request, _("%(name)s added as %(role)s.") % {"name": user.username, "role": Role(form.cleaned_data["role"]).label})
        return redirect("business:team")
    members = b.members.select_related("user").order_by("role", "user__username")
    caps = [(key, CAPABILITIES[key]) for key in CAPABILITIES]
    matrix = [{"role": r, "label": r.label, "caps": {c: c in ROLE_CAPS[r] for c in CAPABILITIES}} for r in Role]
    return render(request, "business/settings/team.html", {"form": form, "members": members, "caps": caps, "matrix": matrix})


@business_access_required(capability="manage_team")
@require_POST
def member_role_view(request, pk):
    m = get_object_or_404(Membership, pk=pk, business=request.business)
    form = RoleForm(request.POST)
    if m.role == Role.OWNER:
        messages.error(request, _("The owner's role can't be changed."))
    elif form.is_valid():
        m.role = form.cleaned_data["role"]
        m.save(update_fields=["role"])
        messages.success(request, _("%(name)s is now %(role)s.") % {"name": m.user.username, "role": m.get_role_display()})
    return redirect("business:team")


@business_access_required(capability="manage_team")
@require_POST
def member_remove_view(request, pk):
    m = get_object_or_404(Membership, pk=pk, business=request.business)
    if m.role == Role.OWNER:
        messages.error(request, _("The owner can't be removed."))
    else:
        m.delete()
        messages.success(request, _("%(name)s removed from the team.") % {"name": m.user.username})
    return redirect("business:team")


@business_access_required(capability="manage_settings")
def activity_view(request):
    qs = AuditLog.objects.filter(business=request.business).select_related("user")
    page = Paginator(qs, 30).get_page(request.GET.get("page"))
    return render(request, "business/settings/activity.html", {"page_obj": page})


# ── Admin: who can open which dashboard ─────────────────────────────────────

@staff_member_required(login_url="login")
def access_admin_view(request):
    User = get_user_model()
    q = request.GET.get("q", "").strip()
    users = User.objects.order_by("username").prefetch_related("dashboard_access__dashboard")
    if q:
        users = users.filter(Q(username__icontains=q) | Q(email__icontains=q) | Q(first_name__icontains=q))
    page = Paginator(users, 20).get_page(request.GET.get("page"))
    dashboards = list(Dashboard.objects.filter(is_active=True))
    rows = []
    for u in page:
        grants = {g.dashboard.code: g for g in u.dashboard_access.all()}
        rows.append({"user": u, "codes": set(grants), "default": next((c for c, g in grants.items() if g.is_default), None)})
    counts = dict(Dashboard.objects.annotate(n=Count("grants")).values_list("code", "n"))
    return render(request, "business/settings/access_admin.html", {
        "rows": rows, "page_obj": page, "dashboards": dashboards, "q": q,
        "dash_counts": [(d, counts.get(d.code, 0)) for d in dashboards],
    })


@staff_member_required(login_url="login")
@require_POST
def access_update_view(request, user_id):
    user = get_object_or_404(get_user_model(), pk=user_id)
    chosen = set(request.POST.getlist("dashboards"))
    default = request.POST.get("default")
    with transaction.atomic():
        for dash in Dashboard.objects.filter(is_active=True):
            if dash.code in chosen:
                UserDashboardAccess.objects.get_or_create(user=user, dashboard=dash, defaults={"granted_by": request.user})
            else:
                UserDashboardAccess.objects.filter(user=user, dashboard=dash).delete()
        UserDashboardAccess.objects.filter(user=user).update(is_default=False)
        if default in chosen:
            UserDashboardAccess.objects.filter(user=user, dashboard__code=default).update(is_default=True)
    if not chosen and not user.is_superuser:
        messages.warning(request, _("%(name)s now has no dashboards and will see a “no access” page.") % {"name": user.username})
    else:
        messages.success(request, _("Access updated for %(name)s.") % {"name": user.username})
    nxt = request.POST.get("next") or reverse("business:access_admin")
    return redirect(nxt if url_has_allowed_host_and_scheme(nxt, {request.get_host()}) else reverse("business:access_admin"))
