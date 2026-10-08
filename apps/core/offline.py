"""Works without internet: the server side.

At a pond or in a village the signal comes and goes. The phone (service
worker in apps/core/pwa.py, page script static/js/offline.js) keeps a copy of
the pages you open, and when a save can't reach the server it keeps the entry
on the phone and sends it later. This module makes that safe:

* Every form the phone sends carries a one-off key (``_ft_key``). The first
  time a key arrives the save goes ahead and the key is remembered; if the
  same key comes again (the connection dropped after saving, or the queue
  sends it again) nothing is saved twice — the answer is the same as before.
* ``_ft_user`` says whose phone session made the entry, so an entry kept on
  a shared phone is never saved into someone else's account.
* A save sent from the queue (header ``X-FT-Replay``) gets a short JSON answer
  instead of a page: saved / needs fixing / needs sign-in. Its "Saved!"
  message is dropped; the phone shows one summary instead.
* Pages that are safe to keep on the phone are marked ``X-FT-Offline`` — and
  so are the lists a search or filter brings in (htmx), so a search done
  before still works with no signal.
"""
import re
from datetime import timedelta

from django.contrib import messages
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.translation import gettext as _

KEY, USER, REPLAY = "_ft_key", "_ft_user", "HTTP_X_FT_REPLAY"
KEEP_DAYS = 45
# Never kept on the phone, never queued: sign-in, admin, backups, downloads.
NOT_OFFLINE = ("/accounts/", "/admin/", "/backup/", "/core/my-data", "/i18n/", "/__debug__/")


def _is_replay(request):
    return request.META.get(REPLAY) == "1"


def _answer(request, ok, why="", location=""):
    return JsonResponse({"ok": ok, "why": why, "location": location})


class OfflineMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if request.method == "POST" and user is not None and user.is_authenticated and KEY in request.POST:
            return self.keyed_save(request)
        response = self.get_response(request)
        if request.method == "GET" and user is not None and user.is_authenticated:
            self.mark_page(request, response)
        return response

    def keyed_save(self, request):
        from .models import OfflineReceipt

        key = request.POST.get(KEY, "")[:64]
        owner = request.POST.get(USER, "")
        replay = _is_replay(request)
        if owner and owner != str(request.user.pk):
            # Kept on this phone by someone else's session: never save it into this account.
            if replay:
                return _answer(request, False, "other-user")
            messages.error(request, _("That entry was made by another account on this phone, so it wasn't saved here."))
            return redirect(request.get_full_path())
        try:
            with transaction.atomic():   # a repeat key must not break an outer transaction
                receipt = OfflineReceipt.objects.create(user=request.user, key=key)
            if receipt.pk % 50 == 0:
                OfflineReceipt.objects.filter(created_at__lt=timezone.now() - timedelta(days=KEEP_DAYS)).delete()
        except IntegrityError:
            receipt = OfflineReceipt.objects.filter(user=request.user, key=key).first()
            if receipt and receipt.location:
                return _answer(request, True, "already", receipt.location) if replay else redirect(receipt.location)
            # The first copy is still being saved: try again in a moment.
            return _answer(request, False, "busy") if replay else redirect(request.get_full_path())

        response = self.get_response(request)
        status = response.status_code
        # Saved: a redirect after a form, or a non-page answer to a background save (a tick, a toggle…).
        background = 200 <= status < 300 and "text/html" not in (response.get("Content-Type") or "")
        if (300 <= status < 400 and not _to_login(response)) or background:
            receipt.location = response.get("Location", "")[:500] or request.POST.get("_ft_page", "")[:500] or "/"
            receipt.save(update_fields=["location"])
            if replay:
                _drop_messages(request)
                return _answer(request, True, "saved", receipt.location)
            return response
        # Not saved (errors on the form, signed out, refused…): forget the key so it can be sent again.
        receipt.delete()
        if not replay:
            return response
        _drop_messages(request)
        if _to_login(response):
            return _answer(request, False, "signin")
        if status == 403:
            return _answer(request, False, "refused")
        if 200 <= status < 300:
            return _answer(request, False, "fix")
        return _answer(request, False, "error")

    def mark_page(self, request, response):
        if (response.status_code == 200 and "text/html" in (response.get("Content-Type") or "")
                and not request.path.startswith(NOT_OFFLINE) and "export" not in request.GET):
            response["X-FT-Offline"] = "1"


def _to_login(response):
    try:
        login = reverse("login")
    except NoReverseMatch:
        login = "/accounts/login/"
    return 300 <= response.status_code < 400 and response.get("Location", "").split("?")[0].endswith(login)


def _drop_messages(request):
    storage = messages.get_messages(request)
    for _m in storage:
        pass
    storage.used = True


# Pages that are never fetched ahead: sign-in, downloads, imports, background
# endpoints, and buttons that do something (empty, copy, cancel…).
SKIP_NAMES = re.compile(
    r"(^admin:|^djdt:|import|template|login|logout|signup|password|preferences|my_data|offline|backup|"
    r"^search$|manifest|service_worker|switch_business|default_dashboard|export|_ics$|^business:setup$|"
    r"preview|quick|empty|copy|cancel|access_admin|budget_edit)"
)
MORE_LIMIT = 400


def offline_pages_view(request):
    """The pages to keep on this phone for when there's no signal.

    ``pages``: the everyday forms, with names (kept fresh on any connection,
    and listed on the offline screen). ``more``: every other page of the app
    the person can open, and the pages of their people, ponds, loans… (kept on
    Wi-Fi, or when they tap "Save everything now")."""
    if not request.user.is_authenticated:
        return JsonResponse({"pages": [], "more": []}, status=401)
    from apps.business.core.access import BUSINESS, PERSONAL, active_membership, can, has_dashboard

    user = request.user
    personal = has_dashboard(user, PERSONAL)
    m = active_membership(request) if has_dashboard(user, BUSINESS) else None
    pages, seen = [], set()

    def add(label, name, *args):
        try:
            url = reverse(name, args=args)
        except NoReverseMatch:
            return
        if url not in seen:
            seen.add(url)
            pages.append({"url": url, "label": str(label)})

    if personal:
        today = timezone.localdate()
        add(_("Home"), "home")
        add(_("New Expense"), "expense_create")
        add(_("Move money"), "wallet_transfer")
        add(_("Household (Bazar)"), "household_month_detail", today.year, today.month)
        for kind, label in (("income", _("I got money")), ("borrow", _("I borrowed")), ("repay", _("I paid back")),
                            ("lend", _("I lent")), ("collect", _("I got it back")), ("shop", _("Shop Dues"))):
            add(label, "pick", kind)
        for p in _people(user):
            if p["url"] not in seen:
                seen.add(p["url"])
                pages.append(p)
    if m is not None and can(m, "enter_data"):
        add(m.business.name, "business:home")
        add(_("Ponds"), "business:ponds")
        add(_("Feeding"), "business:feed_usage_bulk")
        add(_("Water"), "business:water_check")
        add(_("New sale"), "business:sale_add")
        add(_("Feed bought"), "business:feed_purchases_add")
        add(_("Work sheet"), "business:staff_work")
        add(_("Task or reminder"), "business:calendar_add")
        if can(m, "view_finance"):
            add(_("Money in or out"), "business:transaction_add")
            add(_("Baki payment"), "business:payment_add")
            add(_("Family income"), "business:family_income_add")
        from apps.business.ponds.models import CultureCycle, CycleStatus

        for c in (CultureCycle.objects.filter(business=m.business, status=CycleStatus.RUNNING)
                  .select_related("pond").order_by("pond__name")[:12]):
            add(c.pond.name, "business:cycle_detail", c.pk)

    add(_("Use without internet"), "offline_settings")
    more = [u for u in _every_page(personal, m is not None) + _detail_pages(user, personal, m) if u not in seen]
    more = list(dict.fromkeys(more))[:MORE_LIMIT]
    # "start": where the installed app opens (for someone with only the farm it leads to the farm).
    # "fallback": the "You're offline" screen, in this person's language.
    return JsonResponse({"pages": pages, "more": more, "start": reverse("home"), "fallback": reverse("offline")})


def _every_page(personal, business):
    """Every page of the app that needs nothing but its address."""
    from django.urls import URLPattern, URLResolver, get_resolver

    names = []

    def walk(patterns, ns=""):
        for p in patterns:
            if isinstance(p, URLResolver):
                walk(p.url_patterns, (f"{ns}:" if ns and p.namespace else ns) + (p.namespace or "") if p.namespace else ns)
            elif isinstance(p, URLPattern) and p.name and not p.pattern.converters:
                names.append(f"{ns}:{p.name}" if ns else p.name)

    walk(get_resolver().url_patterns)
    urls = []
    for name in names:
        if SKIP_NAMES.search(name):
            continue
        if name.startswith("business:") and not business:
            continue
        if not name.startswith("business:") and not personal:
            continue
        try:
            urls.append(reverse(name))
        except NoReverseMatch:
            pass
    return urls


def _detail_pages(user, personal, membership):
    """The pages of each person, pond, loan… — newest and most used first."""
    urls = []

    def each(name, rows, *, cap=60):
        for pk in list(rows)[:cap]:
            try:
                urls.append(reverse(name, args=[pk]))
            except NoReverseMatch:
                return

    if personal:
        from apps.contributors.models import Contributor
        from apps.creditors.models import Creditor
        from apps.debtors.models import Debtor
        from apps.goals.models import SavingsGoal
        from apps.household.models import HouseholdMember
        from apps.income.models import IncomeSource
        from apps.shops.models import Shop
        from apps.wallets.models import Wallet

        for model, name in ((Creditor, "creditor_detail"), (Debtor, "debtor_detail"), (Shop, "shop_detail"),
                            (IncomeSource, "income_source_detail"), (Contributor, "contributor_detail"),
                            (HouseholdMember, "household_member_detail"), (SavingsGoal, "goal_detail"), (Wallet, "wallet_detail")):
            each(name, model.objects.filter(user=user, is_active=True).order_by("-pk").values_list("pk", flat=True))
        today = timezone.localdate()
        for back in (1, 2):
            y, mth = today.year, today.month - back
            while mth < 1:
                y, mth = y - 1, mth + 12
            urls.append(reverse("household_month_detail", args=[y, mth]))

    if membership is not None:
        from apps.business.reports.views import REPORTS

        b = membership.business
        for kind, *_rest in REPORTS:
            urls.append(reverse("business:report", args=[kind]))
        specs = [
            ("business:pond_detail", "apps.business.ponds.models", "Pond", {}),
            ("business:cycle_detail", "apps.business.ponds.models", "CultureCycle", {}),
            ("business:loan_detail", "apps.business.loans.models", "Loan", {"closed_on__isnull": True}),
            ("business:account_detail", "apps.business.finance.models", "Account", {}),
            ("business:staff_worker", "apps.business.staff.models", "Worker", {"left_on__isnull": True}),
            ("business:equipment_detail", "apps.business.assets.models", "Equipment", {}),
            ("business:supply_detail", "apps.business.supplies.models", "SupplyItem", {}),
            ("business:partner_detail", "apps.business.partners.models", "Partner", {}),
            ("business:sale_detail", "apps.business.sales.models", "FishSale", {}),
        ]
        from importlib import import_module

        for name, module, model_name, filters in specs:
            try:
                model = getattr(import_module(module), model_name)
            except (ImportError, AttributeError):
                continue
            each(name, model.objects.filter(business=b, **filters).order_by("-pk").values_list("pk", flat=True), cap=30)
    return urls


def _people(user, limit=12):
    """The people and sources written to most recently: their pages hold the entry form."""
    from django.db.models import Max

    from apps.creditors.models import Creditor
    from apps.debtors.models import Debtor
    from apps.income.models import IncomeSource
    from apps.shops.models import Shop

    rows = []
    for model, name in ((Creditor, "creditor_detail"), (Debtor, "debtor_detail"), (Shop, "shop_detail"), (IncomeSource, "income_source_detail")):
        for o in model.objects.filter(user=user, is_active=True).annotate(last=Max("transactions__date")).order_by("-last")[:limit]:
            rows.append((o.last, o.name, reverse(name, args=[o.pk])))
    rows.sort(key=lambda r: (r[0] is not None, r[0]), reverse=True)
    return [{"url": url, "label": label} for _last, label, url in rows[:limit]]


def offline_settings_view(request):
    """"Use without internet": what's kept on this phone, what's waiting,
    and a button to keep everything ready now."""
    from django.contrib.auth.views import redirect_to_login
    from django.shortcuts import render

    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    return render(request, "core/offline_settings.html")
