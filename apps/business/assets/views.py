from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _g, gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.business.core.crud import Master
from apps.business.core.decorators import business_access_required

from . import services
from .forms import EquipmentForm, ServiceForm
from .models import Condition, Equipment, Service


def _decorate(objects, business):
    services.with_service_dates(objects)


equipment = Master(
    name="equipment", model=Equipment, form_class=EquipmentForm,
    title=_("Equipment"), subtitle=_("Aerators, pumps, generators, nets and boats: what they cost, their repairs, and when each needs a service."),
    add_label=_("Add equipment"), row_template="business/assets/row.html", icon="cog",
    edit_cap="enter_data", search_fields=("name", "notes"), select_related=("pond",), decorate=_decorate,
    filters=[("repair", _("Needs repair"), Q(condition=Condition.REPAIR)), ("aerator", _("Aerators"), Q(kind="aerator"))],
    empty_title=_("No equipment yet"), empty_text=_("Add your aerators, pumps and nets. Note each repair, and the app reminds you when a service is due."),
    note=(_("How equipment works"),
          _("Each machine keeps its repairs and services. What they cost counts as a farm cost, and comes out of the account you choose."),
          _("Set “Service every” (e.g. 90 days for an aerator's oil) and the farm's to-do list tells you when it's due."),
          _("When something breaks, set it to “Needs repair”. It stays on the to-do list until it's fixed.")),
)


def _item(request, pk):
    return get_object_or_404(Equipment.all_objects.select_related("pond", "account"), pk=pk, business=request.business)


@business_access_required
def equipment_detail_view(request, pk):
    e = _item(request, pk)
    services.with_service_dates([e])
    log = list(e.services.select_related("account"))
    return render(request, "business/assets/detail.html", {"e": e, "log": log, "conditions": Condition.choices})


@business_access_required(capability="enter_data")
def service_form_view(request, pk=None, equipment_pk=None):
    obj = get_object_or_404(Service, pk=pk, business=request.business) if pk else None
    e = obj.equipment if obj else _item(request, equipment_pk)
    initial = {"kind": request.GET["kind"]} if not obj and request.GET.get("kind") in ("service", "repair", "part") else None
    form = ServiceForm(request.POST or None, instance=obj, business=request.business, initial=initial)
    if request.method == "POST" and form.is_valid():
        s = form.save(commit=False)
        s.business, s.equipment = request.business, e
        s.save()
        if s.kind == "repair" and e.condition == Condition.REPAIR and request.POST.get("fixed") == "1":
            e.condition = Condition.WORKING
            e.save(update_fields=["condition", "updated_at"])
        messages.success(request, _g("Saved."))
        return redirect("business:equipment_detail", e.pk)
    return render(request, "business/assets/service_form.html", {"form": form, "e": e, "obj": obj})


@business_access_required(capability="enter_data")
@require_POST
def condition_view(request, pk):
    e = _item(request, pk)
    if request.POST.get("condition") in Condition.values:
        e.condition = request.POST["condition"]
        e.save(update_fields=["condition", "updated_at"])
        messages.success(request, _g("%(name)s: %(state)s.") % {"name": e, "state": e.get_condition_display()})
    return redirect("business:equipment_detail", e.pk)


@business_access_required(capability="delete")
@require_POST
def service_delete_view(request, pk):
    s = get_object_or_404(Service, pk=pk, business=request.business)
    s.soft_delete()
    messages.success(request, _g("Deleted."))
    return redirect("business:equipment_detail", s.equipment_id)
