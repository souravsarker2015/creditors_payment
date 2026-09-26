import json
from datetime import date, timedelta

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import F, Q, Sum
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _g, gettext_lazy as _

from apps.business.core.crud import Master
from apps.business.core.decorators import business_access_required
from apps.business.core.models import Unit

from . import services
from .forms import BulkFeedingForm, FeedLineFormSet, FeedProductForm, FeedPurchaseForm
from .models import FeedForm, FeedProduct, FeedPurchase, FeedUsage

feed_products = Master(
    name="feed_products", model=FeedProduct, form_class=FeedProductForm,
    title=_("Feed products"), subtitle=_("The feeds you buy: bag size, usual price and who sells them."),
    add_label=_("Add feed"), row_template="business/feed/row.html", icon="banknotes", nav_template="business/feed/feed_tabs.html",
    search_fields=("name", "brand"), select_related=("bag_unit",), prefetch=("suppliers",),
    filters=[(k, label, Q(form=k)) for k, label in FeedForm.choices[:2]],
    empty_title=_("No feed products yet"), empty_text=_("Add the feeds you use — brand, bag size and price — so purchases and daily feeding are quick to enter."),
)


def _recalc(purchase, request):
    purchase.recalc()


feed_purchases = Master(
    name="feed_purchases", model=FeedPurchase, form_class=FeedPurchaseForm, edit_cap="enter_data",
    title=_("Feed purchases"), subtitle=_("Every bag you buy — paid now or on baki. Stock goes up automatically."),
    add_label=_("Buy feed"), row_template="business/feed/purchase_row.html", icon="truck", nav_template="business/feed/feed_tabs.html",
    search_fields=("supplier__name", "invoice_no", "lines__product__name"), select_related=("supplier",), prefetch=("lines__product",),
    filters=[("credit", _("With dues"), Q(total__gt=F("paid_now")))],
    formset_class=FeedLineFormSet, form_template="business/feed/purchase_form.html", after_save=_recalc,
    form_context=lambda request: {"feed_json": _form_json(request.business)},
    empty_title=_("No feed bought yet"), empty_text=_("Record a purchase from the memo: the feeds, bags, rate and what you paid. What's left is owed to the supplier."),
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
    dues = FeedPurchase.objects.filter(business=b, total__gt=F("paid_now")).aggregate(d=Sum(F("total") - F("paid_now")))["d"] or 0
    return render(request, "business/feed/stock.html", {
        "rows": [r for r in rows if r.bought_kg or r.used_kg], "unused": [r for r in rows if not (r.bought_kg or r.used_kg)],
        "value": sum((r.value or 0) for r in rows), "low": [r for r in rows if (r.is_low or r.is_negative) and (r.bought_kg or r.used_kg)],
        "used_month": used_month, "bought_month": bought_month, "dues": dues,
        "recent": FeedPurchase.objects.filter(business=b).select_related("supplier")[:5],
    })


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
    form = BulkFeedingForm(request.POST or None, business=request.business)
    if not form.cycles:
        messages.info(request, _g("No pond has a running cycle. Start one from the pond's page first."))
        return redirect("business:ponds")
    if request.method == "POST" and form.is_valid():
        made = services.save_bulk_usage(request.business, form.cleaned_data["date"], form.cleaned_data["product"], form.cleaned_data["entries"])
        total = sum(u.kg for u in made)
        messages.success(request, _g("Feeding saved for %(n)s ponds — %(kg)s kg in all.") % {"n": len(made), "kg": f"{total:,.1f}".rstrip("0").rstrip(".")})
        return redirect("business:feed_usage")
    return render(request, "business/feed/bulk_usage.html", {"form": form, "feed_json": _form_json(request.business)})
