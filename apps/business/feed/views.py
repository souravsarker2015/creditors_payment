import json
from datetime import date, timedelta
from decimal import Decimal

from django.apps import apps
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import F, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.utils.translation import gettext as _g, gettext_lazy as _

from apps.business.core.crud import Master
from apps.business.core.access import can
from apps.business.core.decorators import business_access_required
from apps.business.core.models import Unit
from apps.business.core.templatetags.business import bdt

from . import services
from .forms import BulkFeedingForm, FeedLineFormSet, FeedProductForm, FeedPurchaseForm, StoreCountForm
from .models import FeedCount, FeedForm, FeedProduct, FeedPurchase, FeedUsage

feed_products = Master(
    name="feed_products", model=FeedProduct, form_class=FeedProductForm,
    title=_("Feed products"), subtitle=_("The feeds you buy: bag size, usual price and who sells them."),
    add_label=_("Add feed"), row_template="business/feed/row.html", icon="banknotes", nav_template="business/feed/feed_tabs.html",
    search_fields=("name", "brand"), select_related=("bag_unit",), prefetch=("suppliers",),
    filters=[(k, label, Q(form=k)) for k, label in FeedForm.choices[:2]],
    empty_title=_("No feed products yet"), empty_text=_("Add the feeds you use — brand, bag size and price — so purchases and daily feeding are quick to enter."),
    note=(_("About feed products"),
          _("Add each feed once with its bag size and usual price. Purchases and daily feeding then take only a few taps."),
          _("Stock goes up when you buy feed and down when you record feeding in a pond."),
          _("Set a low-stock alert (in bags) to get a warning on the dashboard before you run out.")),
)


def _recalc(purchase, request):
    purchase.recalc()


def _current_dues(objects, business):
    """Each purchase's remaining due once later payments are counted."""
    if apps.is_installed("apps.business.credit"):
        from apps.business.credit.services import open_dues

        dues = open_dues(business, "feed")
        for o in objects:
            o.due_now = dues.get(o.pk, 0)
    else:
        for o in objects:
            o.due_now = o.due


feed_purchases = Master(
    name="feed_purchases", model=FeedPurchase, form_class=FeedPurchaseForm, edit_cap="enter_data",
    title=_("Feed purchases"), subtitle=_("Every bag you buy — paid now or on baki. Stock goes up automatically."),
    add_label=_("Buy feed"), row_template="business/feed/purchase_row.html", icon="truck", nav_template="business/feed/feed_tabs.html",
    search_fields=("supplier__name", "invoice_no", "lines__product__name"), select_related=("supplier",), prefetch=("lines__product",),
    filters=[("credit", _("Bought on baki"), Q(total__gt=F("paid_now")))], decorate=_current_dues,
    formset_class=FeedLineFormSet, form_template="business/feed/purchase_form.html", after_save=_recalc,
    form_context=lambda request: {"feed_json": _form_json(request.business)},
    empty_title=_("No feed bought yet"), empty_text=_("Record a purchase from the memo: the feeds, bags, rate and what you paid. What's left is owed to the supplier."),
    note=(_("About feed purchases"),
          _("Copy each purchase from the dealer's memo: the feeds, number of bags and rate."),
          _("Enter what you paid now. The rest is added to that supplier's Baki, and paying it later is done from Baki."),
          _("Feed stock goes up automatically. Feed cost reaches each pond only when that feed is eaten there.")),
)


def _form_json(business):
    products = {p.pk: {"bag_kg": str(p.bag_kg), "price": str(p.default_price or ""), "bag": str(p.bag_size.normalize())}
                for p in FeedProduct.objects.filter(business=business).select_related("bag_unit")}
    units = {u.pk: {"factor": str(u.factor), "symbol": u.symbol} for u in Unit.objects.filter(business=business, unit_type="weight")}
    return json.dumps({"products": products, "units": units, "bagWord": _g("bag")}, ensure_ascii=False)




@business_access_required
def stock_view(request):
    b = request.business
    rows = services.stock(b)
    month_start = date.today().replace(day=1)
    used_month = FeedUsage.objects.filter(business=b, date__gte=month_start).aggregate(kg=Sum("kg"))["kg"] or 0
    bought_month = FeedPurchase.objects.filter(business=b, date__gte=month_start).aggregate(t=Sum("total"))["t"] or 0
    recent = list(FeedPurchase.objects.filter(business=b).select_related("supplier")[:5])
    _current_dues(recent, b)
    if apps.is_installed("apps.business.credit"):
        from apps.business.credit.services import open_dues

        dues = sum(open_dues(b, "feed").values(), 0)
    else:
        dues = FeedPurchase.objects.filter(business=b, total__gt=F("paid_now")).aggregate(d=Sum(F("total") - F("paid_now")))["d"] or 0
    return render(request, "business/feed/stock.html", {
        "rows": [r for r in rows if r.bought_kg or r.used_kg or r.counted_kg], "unused": [r for r in rows if not (r.bought_kg or r.used_kg or r.counted_kg)],
        "value": sum((r.value or 0) for r in rows), "low": [r for r in rows if (r.is_low or r.is_negative) and (r.bought_kg or r.used_kg or r.counted_kg)],
        "used_month": used_month, "bought_month": bought_month, "dues": dues,
        "recent": recent, "last_counted": services.last_counted(b),
    })


def _bags(kg, product):
    return f"{(abs(kg) / product.bag_kg).quantize(Decimal('0.1')):,}".rstrip("0").rstrip(".") if product.bag_kg else f"{abs(kg):,.1f}"


@business_access_required
def count_view(request):
    """Count the store: the records put right by what's really there."""
    b = request.business
    form = StoreCountForm(request.POST or None, business=b)
    may_count = can(request.membership, "enter_data")
    if request.method == "POST":
        if not may_count:
            return render(request, "business/forbidden.html", {"reason": "role", "capability": "enter_data"}, status=403)
        if form.is_valid():
            made = services.save_counts(b, form.cleaned_data["date"], form.cleaned_data["entries"])
            parts = []
            for c in made:
                if c.opening:
                    parts.append(_g("%(feed)s: %(n)s bags you already had") % {"feed": c.product, "n": _bags(c.counted_kg, c.product)})
                elif c.difference_kg < 0 and can(request.membership, "view_finance"):
                    parts.append(_g("%(feed)s: %(n)s bags short (%(money)s)") % {"feed": c.product, "n": _bags(c.difference_kg, c.product), "money": bdt(abs(c.value))})
                elif c.difference_kg < 0:
                    parts.append(_g("%(feed)s: %(n)s bags short") % {"feed": c.product, "n": _bags(c.difference_kg, c.product)})
                elif c.difference_kg > 0:
                    parts.append(_g("%(feed)s: %(n)s bags more than the records") % {"feed": c.product, "n": _bags(c.difference_kg, c.product)})
                else:
                    parts.append(_g("%(feed)s: matches the records") % {"feed": c.product})
            short = any(c.difference_kg < 0 and not c.opening for c in made)
            (messages.warning if short else messages.success)(request, _g("Store counted. %(list)s.") % {"list": "; ".join(parts)})
            return redirect("business:feed_count")
    counts = list(FeedCount.objects.filter(business=b).select_related("product__bag_unit", "created_by")[:30])
    return render(request, "business/feed/count.html", {"form": form, "counts": counts, "can_count": may_count})


@business_access_required(capability="delete")
@require_POST
def count_delete_view(request, pk):
    c = get_object_or_404(FeedCount, pk=pk, business=request.business)
    c.soft_delete()
    messages.success(request, _g("Count removed. The stock is back to what the records say."))
    return redirect("business:feed_count")


@business_access_required
def usage_list_view(request):
    b = request.business
    qs = FeedUsage.objects.filter(business=b).select_related("cycle__pond", "product", "unit")
    pond = request.GET.get("pond")
    if pond and pond.isdigit():
        qs = qs.filter(cycle__pond_id=pond)
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    days, current = [], None
    for u in page:
        if current is None or current["date"] != u.date:
            current = {"date": u.date, "rows": [], "kg": 0}
            days.append(current)
        current["rows"].append(u)
        current["kg"] += u.kg
    week = FeedUsage.objects.filter(business=b, date__gte=date.today() - timedelta(days=6))
    return render(request, "business/feed/usage_list.html", {
        "days": days, "page_obj": page, "week_kg": week.aggregate(kg=Sum("kg"))["kg"] or 0,
        "today_done": FeedUsage.objects.filter(business=b, date=date.today()).exists(),
    })


@business_access_required(capability="enter_data")
def bulk_usage_view(request):
    initial = None
    if request.method != "POST" and request.GET.get("plan"):
        # "Fill from the feed plan": today's suggested kg for every pond.
        from .planner import plans

        kg = Unit.objects.filter(business=request.business, symbol="kg").first()
        initial = {f"c{p.cycle.pk}": format(p.per_day.normalize(), "f") for p in plans(request.business) if p.per_day}
        if kg:
            initial["unit"] = kg.pk
    form = BulkFeedingForm(request.POST or None, business=request.business, initial=initial)
    if not form.cycles:
        messages.info(request, _g("No pond has a running cycle. Start one from the pond's page first."))
        return redirect("business:ponds")
    if request.method == "POST" and form.is_valid():
        made = services.save_bulk_usage(request.business, form.cleaned_data["date"], form.cleaned_data["product"], form.cleaned_data["entries"])
        total = sum(u.kg for u in made)
        messages.success(request, _g("Feeding saved for %(n)s ponds — %(kg)s kg in all.") % {"n": len(made), "kg": f"{total:,.1f}".rstrip("0").rstrip(".")})
        return redirect("business:feed_usage")
    return render(request, "business/feed/bulk_usage.html", {"form": form, "feed_json": _form_json(request.business)})


@business_access_required
def plan_view(request):
    """Today's feed for each pond, from the fish in it, their size and the water."""
    from . import planner

    rows = planner.plans(request.business)
    stock = planner.stock_days(request.business)
    total_day = sum((r.per_day for r in rows), Decimal(0))
    left = sum((max(s.left_kg, Decimal(0)) for s in stock), Decimal(0))
    used_day = sum((s.per_day for s in stock), Decimal(0))
    return render(request, "business/feed/plan.html", {
        "rows": rows, "stock": stock, "total_day": total_day, "out_of_stock": bool(stock) and left <= 0,
        "stock_days": int(left / used_day) if used_day > 0 else None,
        "plan_days": int(left / total_day) if total_day > 0 else None,
        "rates": [(limit, pct) for limit, pct in planner.RATES],
    })
