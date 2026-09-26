import json
from datetime import date, timedelta

from django.apps import apps
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F, Q, Sum
from django.forms import inlineformset_factory
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.business.core.decorators import business_access_required
from apps.business.core.models import Unit
from apps.business.core.templatetags.business import bdt
from apps.business.markets.models import MarketDeduction
from apps.business.ponds.models import CultureCycle, Harvest
from apps.business.species.models import Species

from .forms import FishSaleForm, SaleDeductionForm, SaleDeductionFormSet, SaleLineForm, SaleLineFormSet, _SaleLines
from .models import FishSale, FishSaleLine, SaleDeduction


def _periods(today):
    first = today.replace(day=1)
    last_month_end = first - timedelta(days=1)
    return [
        ("month", _("This month"), first, today),
        ("last", _("Last month"), last_month_end.replace(day=1), last_month_end),
        ("year", _("This year"), today.replace(month=1, day=1), today),
        ("all", _("All"), None, None),
    ]


@business_access_required
def sale_list_view(request):
    b = request.business
    today = date.today()
    period = request.GET.get("period", "month")
    periods = _periods(today)
    key, label, start, end = next((p for p in periods if p[0] == period), periods[0])
    qs = FishSale.objects.filter(business=b).select_related("buyer", "market", "cycle__pond").prefetch_related("lines__species", "lines__unit")
    if start:
        qs = qs.filter(date__gte=start, date__lte=end)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(buyer__name__icontains=q) | Q(market__name__icontains=q) | Q(memo_no__icontains=q) | Q(lines__species__name__icontains=q) | Q(lines__species__name_bn__icontains=q)).distinct()
    dues = _sale_dues(b)
    if request.GET.get("due") == "1":
        qs = qs.filter(pk__in=list(dues))
    totals = qs.order_by().aggregate(gross=Sum("gross"), ded=Sum("deductions_total"), net=Sum("net"), received=Sum("received_now"), n=Count("id"))
    kg = FishSaleLine.objects.filter(sale__in=qs.values("pk"), unit__unit_type="weight", sale__is_deleted=False).aggregate(kg=Sum("base_quantity"))["kg"] or 0
    page = Paginator(qs, 30).get_page(request.GET.get("page"))
    for sale in page:
        sale.due_now = dues.get(sale.pk, 0)
    return render(request, "business/sales/sale_list.html", {
        "page_obj": page, "periods": periods, "period": key, "period_label": label, "q": q, "due_only": request.GET.get("due") == "1",
        "totals": totals, "kg": kg, "due_total": sum((dues.get(pk, 0) for pk in qs.values_list("pk", flat=True)), 0),
        "deleted_count": FishSale.all_objects.filter(business=b, is_deleted=True).count(),
    })


def _sale_dues(business):
    """{sale pk: still unpaid}, counting later payments when the credit ledger is installed."""
    if apps.is_installed("apps.business.credit"):
        from apps.business.credit.services import open_dues, unlinked_sale_dues

        return {**open_dues(business, "sale"), **unlinked_sale_dues(business)}
    return {s.pk: s.net - s.received_now for s in FishSale.objects.filter(business=business, net__gt=F("received_now"))}


def _form_json(business):
    units = {u.pk: {"factor": str(u.factor), "symbol": u.symbol, "type": u.unit_type} for u in Unit.objects.filter(business=business)}
    species = {s.pk: {"unit": s.default_unit_id} for s in Species.objects.filter(business=business)}
    markets = {}
    for d in MarketDeduction.objects.filter(business=business, market__is_deleted=False).select_related("deduction_type"):
        markets.setdefault(d.market_id, []).append({"type": d.deduction_type_id, "method": d.method, "value": format(d.value.normalize(), "f"), "unit": d.unit_id})
    return json.dumps({"units": units, "species": species, "markets": markets})


def _initial(request, form):
    """Starting rows for a new sale: from a harvest, and the market's usual deductions."""
    b = request.business
    lines, deductions = [], []
    harvest = Harvest.objects.filter(business=b, pk=request.GET.get("harvest")).select_related("cycle").first() if request.GET.get("harvest", "").isdigit() else None
    if harvest:
        form.initial["cycle"] = harvest.cycle_id
        form.initial["harvest"] = harvest.pk
        lines.append({"species": harvest.species_id, "quantity": format(harvest.quantity.normalize(), "f"), "unit": harvest.unit_id})
    elif request.GET.get("cycle", "").isdigit() and CultureCycle.objects.filter(business=b, pk=request.GET["cycle"]).exists():
        form.initial["cycle"] = int(request.GET["cycle"])
    market = form.initial.get("market")
    if market:
        for d in MarketDeduction.objects.filter(market_id=market, business=b):
            deductions.append({"deduction_type": d.deduction_type_id, "method": d.method, "value": format(d.value.normalize(), "f"), "unit": d.unit_id})
    return harvest, lines, deductions


@business_access_required(capability="enter_data")
def sale_form_view(request, pk=None):
    b = request.business
    sale = get_object_or_404(FishSale, pk=pk, business=b) if pk else None
    form = FishSaleForm(request.POST or None, instance=sale, business=b)
    harvest, line_initial, ded_initial = (None, [], [])
    if not sale and request.method != "POST":
        harvest, line_initial, ded_initial = _initial(request, form)
    LineSet = inlineformset_factory(FishSale, FishSaleLine, form=SaleLineForm, formset=_SaleLines, extra=len(line_initial), can_delete=True) if line_initial else SaleLineFormSet
    DedSet = inlineformset_factory(FishSale, SaleDeduction, form=SaleDeductionForm, extra=len(ded_initial), can_delete=True) if ded_initial else SaleDeductionFormSet
    instance = sale or FishSale(business=b)
    lines = LineSet(request.POST or None, instance=instance, prefix="lines", form_kwargs={"business": b}, initial=line_initial or None)
    deds = DedSet(request.POST or None, instance=instance, prefix="deds", form_kwargs={"business": b}, initial=ded_initial or None)
    if request.method == "POST" and form.is_valid() and lines.is_valid() and deds.is_valid():
        try:
            with transaction.atomic():
                obj = form.save(commit=False)
                obj.business = b
                if request.POST.get("harvest", "").isdigit():
                    obj.harvest = Harvest.objects.filter(business=b, pk=request.POST["harvest"]).first()
                obj.save()
                for fs in (lines, deds):
                    fs.instance = obj
                    for row in fs.save(commit=False):
                        row.business = b
                        row.save()
                    for row in fs.deleted_objects:
                        row.delete()
                obj.recalc()
                if obj.due and not obj.buyer_id:
                    raise _NoBuyerForDue
        except _NoBuyerForDue:
            # Baki needs someone to owe it; undo the save and ask.
            form.add_error("buyer", _("Choose the buyer who owes the rest, or enter the full amount as received."))
            if sale:
                sale.refresh_from_db()
        else:
            return _saved(request, obj)
    return render(request, "business/sales/sale_form.html", {
        "form": form, "lines": lines, "deds": deds, "obj": sale, "harvest": harvest or (sale.harvest if sale else None),
        "sale_json": _form_json(b),
    })


class _NoBuyerForDue(Exception):
    pass


def _saved(request, obj):
    if obj.due:
        messages.success(request, _("Sale saved: %(net)s net, %(due)s still to receive.") % {"net": bdt(obj.net), "due": bdt(obj.due)})
    else:
        messages.success(request, _("Sale saved: %(net)s received in full.") % {"net": bdt(obj.net)})
    return redirect("business:sale_detail", obj.pk)


@business_access_required
def sale_detail_view(request, pk):
    sale = get_object_or_404(FishSale.all_objects.select_related("buyer", "market", "cycle__pond", "account", "created_by"), pk=pk, business=request.business)
    due_now = _due_now(request, sale)
    return render(request, "business/sales/sale_detail.html", {
        "sale": sale, "lines": sale.lines.select_related("species", "unit"),
        "deductions": sale.deductions.select_related("deduction_type", "unit"),
        "later_payments": sale.later_payments.select_related("account") if apps.is_installed("apps.business.credit") else [],
        "due_now": due_now, "settled_later": sale.due - due_now if due_now is not None else None,
    })


def _due_now(request, sale):
    """What's still unpaid on this sale once later payments are counted (the
    credit ledger works that out per buyer). None when there's no ledger."""
    if sale.is_deleted or not sale.buyer_id or not apps.is_installed("apps.business.credit"):
        return None
    from apps.business.credit.services import ledger

    return ledger(sale.buyer).due_on(("sale", sale.pk))


@business_access_required(capability="delete")
@require_POST
def sale_delete_view(request, pk):
    sale = get_object_or_404(FishSale, pk=pk, business=request.business)
    sale.soft_delete()
    messages.success(request, _("Sale deleted. You can restore it from the sales list."))
    return redirect("business:sales")


@business_access_required(capability="delete")
@require_POST
def sale_restore_view(request, pk):
    sale = get_object_or_404(FishSale.all_objects, pk=pk, business=request.business, is_deleted=True)
    sale.restore()
    messages.success(request, _("Sale restored."))
    return redirect("business:sale_detail", sale.pk)


@business_access_required
def sale_deleted_view(request):
    sales = FishSale.all_objects.filter(business=request.business, is_deleted=True).select_related("buyer", "market")
    return render(request, "business/sales/sale_deleted.html", {"sales": sales})
