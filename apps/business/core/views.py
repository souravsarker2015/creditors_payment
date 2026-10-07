import json
from datetime import date, timedelta
from decimal import Decimal

from django.apps import apps
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.formats import date_format
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _, ngettext
from django.views.decorators.http import require_POST

from .access import (BUSINESS, CAPABILITIES, PERSONAL, ROLE_CAPS, active_membership, can, create_business,
                     dashboard_url, has_dashboard, memberships)
from .audit_display import describe
from .decorators import business_access_required
from .forms import (BusinessProfileForm, BusinessSetupForm, MemberAddForm, MemberCreateForm, MemberPasswordForm,
                    RoleForm, UnitForm)
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
    tasks = _farm_tasks(b) + _growth_tasks(b) + _equipment_tasks(b) + _supply_tasks(b) + _staff_tasks(request) + _paper_tasks(request) + _calendar_tasks(b)
    return render(request, "business/home.html", {
        "today": date.today(),
        "share_url": _share_url(request, tasks),
        "team_count": b.members.count(),
        "unit_count": units.count(),
        "mon": units.filter(symbol="mon").first(),
        "units_json": _units_json(b),
        "recent_activity": describe(list(AuditLog.objects.filter(business=b).select_related("user")[:5])),
        "other_businesses": memberships(request.user).exclude(business=b),
        "loans": _loans_summary(request),
        "setup_steps": _setup_steps(request),
        "has_ponds": _has_ponds(b),
        "tasks": tasks,
        "low_feed": _low_feed(b),
        "baki": _baki_summary(request),
        "money": _money_summary(request),
    })


def _has_ponds(business):
    from apps.business.ponds.models import Pond

    return Pond.objects.filter(business=business).exists()


def _farm_tasks(business):
    if not apps.is_installed("apps.business.ponds"):
        return []
    from apps.business.ponds.services import farm_tasks

    return farm_tasks(business)


def _growth_tasks(business):
    """Fish that look ready to sell, and fish that have stopped growing."""
    from apps.business.core.templatetags.business import num
    from apps.business.ponds.forecast import for_farm
    from apps.business.ponds.services import Task

    out = []
    for f in for_farm(business):
        url = reverse("business:cycle_detail", args=[f.cycle.pk])
        names = {"fish": f.species, "pond": f.cycle.pond.name}
        if f.status == "ready":
            out.append(Task("ready", "info", _("%(fish)s in %(pond)s look ready to sell") % names,
                            _("≈ %(now)s g each, selling size %(target)s g. Net a few to check.") % {"now": num(f.now_g), "target": num(f.target_g)},
                            url + "?tab=harvest", _("Plan harvest")))
        elif f.status == "slow":
            out.append(Task("slow", "warn", _("%(fish)s in %(pond)s aren't growing") % names,
                            _("The last weighings show little or no growth. Check the feed and the water."), url + "?tab=growth", _("View")))
    return out


def _equipment_tasks(business):
    """Broken machines, and services due this week."""
    if not apps.is_installed("apps.business.assets"):
        return []
    from apps.business.assets.services import needs_attention
    from apps.business.ponds.services import Task

    broken, due = needs_attention(business)
    out = [Task("equipment", "critical", _("%(name)s needs repair") % {"name": e.name}, str(e.pond or ""),
                reverse("business:equipment_detail", args=[e.pk]), _("View")) for e in broken]
    for e in due:
        late = e.next_due < date.today()
        out.append(Task("equipment", "warn" if late else "info", _("Service %(name)s") % {"name": e.name},
                        (_("Was due %(date)s") if late else _("Due %(date)s")) % {"date": date_format(e.next_due, "j M")},
                        reverse("business:equipment_service", args=[e.pk]), _("Record")))
    return out


def _supply_tasks(business):
    """Lime, medicine… out of stock or below the level set to warn at."""
    if not apps.is_installed("apps.business.supplies"):
        return []
    from apps.business.core.templatetags.business import num
    from apps.business.ponds.services import Task
    from apps.business.supplies.services import running_low

    out = []
    for st in running_low(business):
        if st.left < 0:
            left = _("%(q)s %(unit)s more used than bought. Record the purchase.") % {"q": num(-st.left), "unit": st.item.unit.symbol}
        else:
            left = _("%(q)s %(unit)s left") % {"q": num(st.left), "unit": st.item.unit.symbol}
        out.append(Task("supply", "warn" if st.is_out else "info",
                        (_("%(name)s is out of stock") if st.is_out else _("%(name)s is running low")) % {"name": st.item.name},
                        left, reverse("business:supply_detail", args=[st.item.pk]), _("View")))
    return out


def _staff_tasks(request):
    """Last month's salaries not written yet (only for people who see money)."""
    from .access import can

    if not apps.is_installed("apps.business.staff") or not can(request.membership, "view_finance"):
        return []
    from apps.business.ponds.services import Task
    from apps.business.staff.services import missing_salaries

    last_month = (date.today().replace(day=1) - timedelta(days=1)).replace(day=1)
    missing = missing_salaries(request.business, last_month)
    if not missing:
        return []
    names = ", ".join(r.worker.name for r in missing[:3])
    return [Task("salary", "warn", _("%(month)s salaries not written yet") % {"month": date_format(last_month, "F")}, names,
                 reverse("business:staff_salaries") + f"?month={last_month:%Y-%m}", _("Write"))]


def _paper_tasks(request):
    """Licences and other papers that have run out or are about to (owners and managers only)."""
    from .access import can

    if not apps.is_installed("apps.business.papers") or not can(request.membership, "manage_settings"):
        return []
    from apps.business.papers.views import due_papers
    from apps.business.ponds.services import Task

    out = []
    for p in due_papers(request.business):
        left = p.days_left
        if left < 0:
            detail = ngettext("Ran out %(n)s day ago", "Ran out %(n)s days ago", -left) % {"n": -left}
        elif left == 0:
            detail = _("Runs out today")
        else:
            detail = ngettext("Runs out in %(n)s day", "Runs out in %(n)s days", left) % {"n": left}
        detail += " · " + date_format(p.expires_on, "j M Y")
        out.append(Task("paper", "critical" if left < 0 else "warn", _("Renew: %(paper)s") % {"paper": p.title}, detail,
                        reverse("business:papers_edit", args=[p.pk]), _("Update")))
    return out


def _calendar_tasks(business):
    """Today's events from the farm calendar, and to-dos still not ticked."""
    if not apps.is_installed("apps.business.calendar"):
        return []
    from apps.business.calendar.services import todays_events
    from apps.business.ponds.services import Task

    today = date.today()
    out = []
    for i in todays_events(business, today):
        late = i.date < today
        detail = " · ".join(x for x in (i.time, i.detail, _("from %(date)s") % {"date": date_format(i.date, "j M")} if late else "") if x)
        out.append(Task("event", "warn" if late else "info", i.title, detail,
                        reverse("business:calendar") + f"?day={i.date.isoformat()}", _("View")))
    return out


def _share_url(request, tasks):
    """WhatsApp link with today's report; money only for people who may see it."""
    if not apps.is_installed("apps.business.reports"):
        return ""
    from urllib.parse import quote

    from apps.business.reports.services import daily_text

    text = daily_text(request.business, show_money=can(request.membership, "view_finance"), tasks=tasks)
    return "https://wa.me/?text=" + quote(text)


def _low_feed(business):
    from apps.business.feed.services import low_stock

    return low_stock(business)


def _setup_steps(request):
    """Getting-started steps for the master data, numbered after the fixed ones."""
    from apps.business.markets.models import Market
    from apps.business.parties.models import Party
    from apps.business.ponds.models import Pond

    b = request.business
    ponds = Pond.objects.filter(business=b).count()
    suppliers = Party.objects.filter(business=b, is_supplier=True).count()
    markets = Market.objects.filter(business=b).count()
    buyers = Party.objects.filter(business=b, is_buyer=True).count()
    first = 4 if can(request.membership, "manage_team") else 3
    steps = [
        (ponds, _("Add your ponds"), ngettext("%(n)s pond", "%(n)s ponds", ponds) % {"n": ponds} if ponds else _("Name, size and whether it's leased."), "business:ponds_add" if not ponds else "business:ponds"),
        (suppliers, _("Suppliers and feed"), ngettext("%(n)s supplier", "%(n)s suppliers", suppliers) % {"n": suppliers} if suppliers else _("Who you buy feed from, and what you already owe them."), "business:suppliers_add" if not suppliers else "business:suppliers"),
        (markets and buyers, _("Markets and buyers"), _("%(m)s markets · %(b)s buyers") % {"m": markets, "b": buyers} if markets or buyers else _("Where you sell and who buys your fish."), "business:markets_add" if not markets else "business:buyers"),
    ]
    return [{"no": first + i, "done": bool(done), "title": title, "text": text, "url": reverse(url)} for i, (done, title, text, url) in enumerate(steps)]


def _money_summary(request):
    """This month's money card: in, out, what's left, and account balances."""
    if not (apps.is_installed("apps.business.finance") and can(request.membership, "view_finance")):
        return None
    from datetime import date

    from apps.business.finance.models import Account, Scope
    from apps.business.finance.services import balances, due_recurring, statement

    b, today = request.business, date.today()
    month = today.replace(day=1)
    farm = statement(b, month, today, scope=Scope.BUSINESS)
    home = statement(b, month, today, scope=Scope.HOUSEHOLD)
    totals = balances(b)
    accounts = list(Account.objects.filter(business=b))
    for a in accounts:
        a.now = totals.get(a.pk, a.opening_balance)
    return {
        "farm": farm, "household": home.total_expense, "month": month,
        "accounts": sorted(accounts, key=lambda a: -a.now)[:4],
        "in_hand": sum(totals.values(), Decimal(0)),
        "due_recurring": due_recurring(b) if can(request.membership, "enter_data") else [],
    }


def _baki_summary(request):
    """Baki card on the home page: to collect, to pay, oldest dues and today's follow-ups."""
    if not (apps.is_installed("apps.business.credit") and can(request.membership, "view_finance")):
        return None
    from datetime import date

    from apps.business.credit.services import totals

    t = totals(request.business)
    today = date.today()
    t["oldest"] = sorted((led for led in t["ledgers"] if led.balance > 0), key=lambda led: led.oldest or today)[:4]
    t["follow_ups"] = [led for led in t["ledgers"] if led.party.follow_up_on and led.party.follow_up_on <= today]
    return t


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
    """The farm's people: make a login for someone, or add an account they already have."""
    b = request.business
    posted = request.method == "POST"
    # Which form was sent: the hidden "tab" says so. Without it, the fields
    # decide, so a post that predates the tabs still reaches the right form.
    tab = request.POST.get("tab") or request.GET.get("tab") or ""
    if tab not in ("create", "existing"):
        tab = "create" if (not posted or "password1" in request.POST) else "existing"
    create_form = MemberCreateForm(request.POST if (posted and tab == "create") else None, business=b, auto_id="id_new_%s")
    add_form = MemberAddForm(request.POST if (posted and tab == "existing") else None, business=b, auto_id="id_has_%s")
    form = create_form if tab == "create" else add_form
    if posted and form.is_valid():
        made = tab == "create"
        user = form.save() if made else form.user
        with transaction.atomic():
            if not has_dashboard(user, BUSINESS):
                # Being on a team is what gives someone the Business area.
                dash = Dashboard.objects.get(code=BUSINESS)
                UserDashboardAccess.objects.get_or_create(user=user, dashboard=dash,
                                                          defaults={"granted_by": request.user, "is_default": made})
            Membership.objects.create(business=b, user=user, role=form.cleaned_data["role"], added_by=request.user,
                                      account_created=made)
        role_label = Role(form.cleaned_data["role"]).label
        if made:
            messages.success(request, _("Login made for %(name)s as %(role)s. Give them the username and password you just typed.")
                             % {"name": user.username, "role": role_label})
        else:
            messages.success(request, _("%(name)s added as %(role)s.") % {"name": user.username, "role": role_label})
        return redirect("business:team")
    members = b.members.select_related("user").order_by("role", "user__username")
    caps = [(key, CAPABILITIES[key]) for key in CAPABILITIES]
    matrix = [{"role": r, "label": r.label, "caps": {c: c in ROLE_CAPS[r] for c in CAPABILITIES}} for r in Role]
    return render(request, "business/settings/team.html", {
        "form": add_form, "create_form": create_form, "tab": tab, "members": members, "caps": caps, "matrix": matrix,
        "password_form": MemberPasswordForm(user=request.user),
    })


@business_access_required
def guide_view(request):
    """How the farm works: the whole system on one page."""
    from . import guide

    def allowed(cap):
        return can(request.membership, cap)

    stages = guide.stages_for(allowed)
    titles = guide.step_titles()
    return render(request, "business/guide.html", {
        "stages": stages,
        "answers": guide.answers_for(titles),
        "titles": titles,
    })


@business_access_required(capability="manage_team")
@require_POST
def member_password_view(request, pk):
    """Set a new password for a login this farm created (not for accounts people brought)."""
    m = get_object_or_404(Membership.objects.select_related("user"), pk=pk, business=request.business)
    if not m.account_created or m.role == Role.OWNER:
        messages.error(request, _("This account wasn't made here, so its password can only be changed by the person themselves."))
        return redirect("business:team")
    form = MemberPasswordForm(request.POST, user=m.user)
    if form.is_valid():
        m.user.set_password(form.cleaned_data["password1"])
        m.user.save(update_fields=["password"])
        messages.success(request, _("New password set for %(name)s. Tell them what it is; they'll need it next time they sign in.")
                         % {"name": m.user.username})
    else:
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
    return redirect("business:team")


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
    page.object_list = describe(list(page.object_list))
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


# ── Farm setup hub ──────────────────────────────────────────────────────────

@business_access_required
def setup_hub_view(request):
    """Everything the farm is set up with, in one place, with counts."""
    from apps.business.feed.models import FeedProduct
    from apps.business.finance.models import Account, Category
    from apps.business.markets.models import DeductionType, Market
    from apps.business.parties.models import Party
    from apps.business.ponds.models import Pond
    from apps.business.species.models import Species

    b = request.business
    fin = can(request.membership, "view_finance")

    def tile(url, icon, title, text, count, show=True):
        return {"url": reverse(url), "icon": icon, "title": title, "text": text, "count": count} if show else None

    sections = [
        (_("Your farm"), [
            tile("business:ponds", "fish", _("Ponds"), _("Size, lease and status of each pond"), Pond.objects.filter(business=b).count()),
            tile("business:species", "fish", _("Fish species"), _("Rui, Katla, Pangas… in English and Bangla"), Species.objects.filter(business=b).count()),
            tile("business:feed_products", "banknotes", _("Feed products"), _("Brand, bag size, price and supplier"), FeedProduct.objects.filter(business=b).count()),
            tile("business:pond_alerts", "beaker", _("Pond alert levels"), _("Safe ranges for oxygen, pH, ammonia… and deaths"), None,
                 show=can(request.membership, "manage_settings")),
        ]),
        (_("Buying and selling"), [
            tile("business:suppliers", "truck", _("Suppliers"), _("Feed dealers, hatcheries, medicine shops"), Party.objects.filter(business=b, is_supplier=True).count()),
            tile("business:buyers", "users", _("Buyers"), _("Aratdars, paikars and local buyers"), Party.objects.filter(business=b, is_buyer=True).count()),
            tile("business:markets", "cart", _("Markets & aarots"), _("Where you sell and their usual deductions"), Market.objects.filter(business=b).count()),
            tile("business:deduction_types", "tag", _("Deduction types"), _("Commission, labour, khajna, ice…"), DeductionType.objects.filter(business=b).count()),
        ]),
        (_("Money and measures"), [
            tile("business:categories", "tag", _("Categories"), _("Farm, household and personal income and spending"), Category.objects.filter(business=b).count()),
            tile("business:accounts", "wallet", _("Accounts"), _("Cash, bank, bKash, Nagad"), Account.objects.filter(business=b).count(), show=fin),
            tile("business:units", "scale", _("Units"), _("kg, mon, piece, decimal, bigha…"), Unit.objects.filter(business=b).count()),
        ]),
    ]
    if apps.is_installed("apps.business.papers"):
        from apps.business.papers.models import FarmPaper

        papers = FarmPaper.objects.filter(business=b).count()
    else:
        papers = None
    sections.append((_("Papers and records"), [
        tile("business:papers", "note", _("Farm papers"), _("Licences, registrations, lease and land papers, with reminders"), papers,
             show=papers is not None and can(request.membership, "manage_settings")),
        tile("business:export", "download", _("Download all records"), _("Every record of this farm as Excel-ready files"), None,
             show=can(request.membership, "manage_team")),
    ]))
    sections = [(title, [t for t in tiles if t]) for title, tiles in sections]
    return render(request, "business/settings/setup_hub.html", {"sections": [s for s in sections if s[1]]})


@business_access_required(capability="manage_team")
def export_view(request):
    """The owner's copy of every farm record (one CSV per kind, zipped)."""
    from .export import zip_response

    AuditLog.objects.create(business=request.business, user=request.user, action=AuditLog.Action.UPDATE, model="export",
                            object_id="-", object_repr="Downloaded all records")
    return zip_response(request.business)
