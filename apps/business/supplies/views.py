from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _g, gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.business.core.crud import Master
from apps.business.core.decorators import business_access_required

from . import services
from .forms import SupplyItemForm, SupplyPurchaseForm
from .models import SupplyItem, SupplyPurchase


def _decorate(objects, business):
    for s in services.stock(business, objects):
        s.item.stock = s


def _low_first(objects):
    """Out of stock and running low on top, so the list opens with what to buy."""
    short = [o for o in objects if o.stock.is_out or o.stock.is_low]
    rest = [o for o in objects if o not in short]
    return [(_("Buy soon"), short), (_("In stock"), rest)] if short and rest else []


supplies = Master(
    name="supplies", model=SupplyItem, form_class=SupplyItemForm,
    title=_("Pond supplies"), subtitle=_("Lime, fertilizer, salt and medicine you keep in store: what's left, and what it cost."),
    add_label=_("Add a supply"), row_template="business/supplies/row.html", icon="dropper",
    edit_cap="enter_data", search_fields=("name", "notes"), select_related=("unit",), decorate=_decorate, group=_low_first,
    nav_template="business/ponds/tabs.html",
    empty_title=_("Nothing in the store yet"),
    empty_text=_("Add the lime, fertilizer and medicine you buy in bulk. Record each purchase, pick it when you treat a pond, and the stock keeps itself."),
    note=(_("How the store works"),
          _("Record what you buy here. Paying for it is money out, and anything still owed goes into the shop's baki."),
          _("When you put lime or medicine into a pond, choose it under “From your store”. The stock goes down, and the pond's cost goes up by what that amount cost you."),
          _("Set “Warn me below” and the farm's to-do list tells you before you run out.")),
)


def _item(request, pk):
    return get_object_or_404(SupplyItem.all_objects.select_related("unit"), pk=pk, business=request.business)


@business_access_required
def item_detail_view(request, pk):
    item = _item(request, pk)
    st = services.stock_for(item)
    purchases = list(item.purchases.select_related("unit", "supplier", "account"))
    uses = list(item.uses.filter(cycle__is_deleted=False).select_related("unit", "cycle__pond"))
    history = sorted([("buy", p.date, p) for p in purchases] + [("use", u.date, u) for u in uses],
                     key=lambda row: (row[1], row[2].pk), reverse=True)
    return render(request, "business/supplies/detail.html", {"item": item, "st": st, "history": history[:100]})


@business_access_required(capability="view_finance")
def purchase_form_view(request, pk=None, item_pk=None):
    obj = get_object_or_404(SupplyPurchase.objects.select_related("item__unit"), pk=pk, business=request.business) if pk else None
    item = obj.item if obj else _item(request, item_pk)
    form = SupplyPurchaseForm(request.POST or None, instance=obj, business=request.business, item=item)
    if request.method == "POST" and form.is_valid():
        p = form.save(commit=False)
        p.business, p.item = request.business, item
        p.save()
        messages.success(request, _g("Saved."))
        return redirect("business:supply_detail", item.pk)
    return render(request, "business/supplies/purchase_form.html", {"form": form, "item": item, "obj": obj})


@business_access_required(capability="delete")
@require_POST
def purchase_delete_view(request, pk):
    p = get_object_or_404(SupplyPurchase, pk=pk, business=request.business)
    p.soft_delete()
    messages.success(request, _g("Deleted."))
    return redirect("business:supply_detail", p.item_id)
