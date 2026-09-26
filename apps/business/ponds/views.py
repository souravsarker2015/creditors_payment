from dataclasses import dataclass
from datetime import date

from django import forms as dj_forms
from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _g, gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.business.core.crud import Master
from apps.business.core.decorators import business_access_required
from apps.business.feed.forms import FeedUsageForm
from apps.business.feed.models import FeedUsage

from . import services
from .forms import CycleForm, HarvestForm, MortalityForm, PondForm, StockingForm, WeighingForm
from .models import CultureCycle, Harvest, Mortality, Pond, PondStatus, SampleWeighing, Stocking

def _with_cycles(objects, business):
    running = {c.pond_id: c for c in CultureCycle.objects.filter(business=business, status="running", pond__in=objects)}
    for pond in objects:
        pond.current = running.get(pond.pk)


ponds = Master(
    name="ponds", model=Pond, form_class=PondForm,
    title=_("Ponds"), subtitle=_("Every pond or gher you farm — its size, whether it's leased, and what's in it now."),
    add_label=_("Add pond"), row_template="business/ponds/card.html", cards=True, icon="fish",
    search_fields=("name", "code", "location", "lease_from"), select_related=("area_unit",), decorate=_with_cycles,
    filters=[("in_use", _("Fish in it"), Q(status=PondStatus.IN_USE)),
             ("leased", _("Leased"), Q(ownership="leased"))],
    empty_title=_("Add your first pond"), empty_text=_("Give it a name and size. Stocking, feeding and harvests will be recorded per pond, so you'll see what each one earns."),
)


# ── Pond page, cycles and pond entries ──────────────────────────────────────


@dataclass(frozen=True)
class EntryKind:
    key: str
    model: type
    form: type
    title: str      # "Add stocking"
    icon: str
    tab: str


ENTRY_KINDS = {k.key: k for k in [
    EntryKind("feeding", FeedUsage, FeedUsageForm, _("Record feeding"), "banknotes", "feeding"),
    EntryKind("stocking", Stocking, StockingForm, _("Add fingerlings"), "fish", "stocking"),
    EntryKind("weighing", SampleWeighing, WeighingForm, _("Sample weighing"), "scale", "growth"),
    EntryKind("mortality", Mortality, MortalityForm, _("Record deaths"), "alert", "growth"),
    EntryKind("harvest", Harvest, HarvestForm, _("Record harvest"), "cart", "harvest"),
]}


def _for_popup(form):
    """Popups use the phone's own date picker and skip nested "+ Add new"."""
    for f in form.fields.values():
        if isinstance(f.widget, dj_forms.DateInput):
            f.widget.input_type = "date"
            f.widget.attrs["class"] = "form-input"
        if getattr(f, "biz_quick_add", None):
            f.biz_quick_add = None
    return form


def _cycle(request, pk):
    return get_object_or_404(CultureCycle.objects.select_related("pond"), pk=pk, business=request.business)


@business_access_required
def pond_detail_view(request, pk):
    pond = get_object_or_404(Pond, pk=pk, business=request.business)
    cycles = list(pond.cycles.all())
    current = next((c for c in cycles if c.is_running), None)
    return render(request, "business/ponds/pond_detail.html", {
        "pond": pond, "current": current, "past": [c for c in cycles if not c.is_running],
        "summary": services.summarize(current) if current else None,
        "cycle_form": _for_popup(CycleForm(business=request.business, prefix="cycle")),
        "past_summaries": [(c, services.summarize(c)) for c in cycles if not c.is_running][:10],
    })


@business_access_required(capability="enter_data")
def cycle_start_view(request, pk):
    pond = get_object_or_404(Pond, pk=pk, business=request.business)
    if services.running_cycle(pond):
        messages.error(request, _g("%(pond)s already has a running cycle. Finish it first.") % {"pond": pond})
        return redirect("business:pond_detail", pond.pk)
    form = CycleForm(request.POST or None, business=request.business, prefix="cycle")
    if request.method == "POST" and form.is_valid():
        cycle = form.save(commit=False)
        cycle.business, cycle.pond = request.business, pond
        services.start_cycle(cycle)
        messages.success(request, _g("New cycle started in %(pond)s. Add the fingerlings you released.") % {"pond": pond})
        return redirect(reverse("business:cycle_detail", args=[cycle.pk]) + "?add=stocking")
    return render(request, "business/ponds/entry_form.html", {"form": form, "title": _g("Start a new cycle"), "back": reverse("business:pond_detail", args=[pond.pk]), "back_label": str(pond)})


@business_access_required
def cycle_detail_view(request, pk):
    cycle = _cycle(request, pk)
    b = request.business
    popups = [(k, kind, _for_popup(kind.form(business=b, cycle=cycle, prefix=k)), reverse("business:entry_add", args=[cycle.pk, k]))
              for k, kind in ENTRY_KINDS.items()]
    feedings = list(cycle.feedings.select_related("product", "unit")[:60])
    harvests = list(cycle.harvests.select_related("species", "unit"))
    sales = list(cycle.sales.select_related("buyer", "market"))
    return render(request, "business/ponds/cycle_detail.html", {
        "cycle": cycle, "pond": cycle.pond, "s": services.summarize(cycle),
        "popups": popups,
        "stockings": list(cycle.stockings.select_related("species", "supplier", "weight_unit")),
        "feedings": feedings, "feed_by_product": _feed_by_product(cycle),
        "mortalities": cycle.mortalities.select_related("species"),
        "weighings": cycle.weighings.select_related("species", "unit"),
        "harvests": harvests, "sales": sales, "harvest_sale_count": len(harvests) + len(sales),
        "open": request.GET.get("add") if request.GET.get("add") in ENTRY_KINDS and cycle.is_running else None,
        "tab": request.GET.get("tab") or "overview",
        "today": date.today(),
    })


def _feed_by_product(cycle):
    from django.db.models import Sum

    return cycle.feedings.values("product__name", "product__brand").annotate(kg=Sum("kg")).order_by("-kg")


@business_access_required(capability="enter_data")
def cycle_edit_view(request, pk):
    cycle = _cycle(request, pk)
    form = CycleForm(request.POST or None, instance=cycle, business=request.business)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _g("Cycle updated."))
        return redirect("business:cycle_detail", cycle.pk)
    return render(request, "business/ponds/entry_form.html", {"form": form, "title": _g("Edit cycle"), "back": reverse("business:cycle_detail", args=[cycle.pk]), "back_label": str(cycle)})


@business_access_required(capability="enter_data")
@require_POST
def cycle_finish_view(request, pk):
    cycle = _cycle(request, pk)
    if cycle.is_running:
        try:
            on = date.fromisoformat(request.POST.get("ended_on", ""))
        except ValueError:
            on = date.today()
        services.finish_cycle(cycle, max(on, cycle.start_date))
        messages.success(request, _g("Cycle finished. %(pond)s is marked empty — start a new cycle when you restock.") % {"pond": cycle.pond})
    else:
        if services.running_cycle(cycle.pond):
            messages.error(request, _g("%(pond)s already has a running cycle.") % {"pond": cycle.pond})
        else:
            services.reopen_cycle(cycle)
            messages.success(request, _g("Cycle reopened."))
    return redirect("business:cycle_detail", cycle.pk)


@business_access_required(capability="delete")
@require_POST
def cycle_delete_view(request, pk):
    cycle = _cycle(request, pk)
    cycle.soft_delete()
    messages.success(request, _g("Cycle deleted. You can ask an admin to restore it."))
    return redirect("business:pond_detail", cycle.pond_id)


def _entry_saved(request, kind, obj, cycle):
    if kind.key == "harvest" and obj.is_final and cycle.is_running:
        services.finish_cycle(cycle, obj.date)
        messages.success(request, _g("Harvest saved and the cycle is finished."))
    else:
        messages.success(request, _g("Saved."))


@business_access_required(capability="enter_data")
def entry_add_view(request, pk, kind):
    cycle = _cycle(request, pk)
    kind = ENTRY_KINDS[kind]
    form = kind.form(request.POST or None, business=request.business, cycle=cycle, prefix=kind.key)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.business, obj.cycle = request.business, cycle
        obj.save()
        _entry_saved(request, kind, obj, cycle)
        if kind.key == "harvest" and request.POST.get("then") == "sell":
            return redirect(reverse("business:sale_add") + f"?harvest={obj.pk}")
        return redirect(reverse("business:cycle_detail", args=[cycle.pk]) + f"?tab={kind.tab}")
    return render(request, "business/ponds/entry_form.html", {"form": form, "title": kind.title, "back": reverse("business:cycle_detail", args=[cycle.pk]), "back_label": str(cycle)})


@business_access_required(capability="enter_data")
def entry_edit_view(request, kind, pk):
    kind = ENTRY_KINDS[kind]
    obj = get_object_or_404(kind.model, pk=pk, business=request.business)
    form = kind.form(request.POST or None, instance=obj, business=request.business, cycle=obj.cycle)
    if request.method == "POST" and form.is_valid():
        form.save()
        _entry_saved(request, kind, obj, obj.cycle)
        return redirect(reverse("business:cycle_detail", args=[obj.cycle_id]) + f"?tab={kind.tab}")
    return render(request, "business/ponds/entry_form.html", {"form": form, "title": kind.title, "back": reverse("business:cycle_detail", args=[obj.cycle_id]), "back_label": str(obj.cycle)})


@business_access_required(capability="delete")
@require_POST
def entry_delete_view(request, kind, pk):
    kind = ENTRY_KINDS[kind]
    obj = get_object_or_404(kind.model, pk=pk, business=request.business)
    obj.soft_delete()
    messages.success(request, _g("Deleted."))
    return redirect(reverse("business:cycle_detail", args=[obj.cycle_id]) + f"?tab={kind.tab}")
