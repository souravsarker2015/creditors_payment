from datetime import date

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _g, gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.business.core.crud import Master
from apps.business.core.periods import fy_start, last_fy
from apps.business.core.decorators import business_access_required

from . import services
from .forms import EntryForm, PartnerForm
from .models import EntryKind, Partner, PartnerEntry


def _decorate(objects, business):
    books = services.khatas(business, objects)
    for p in objects:
        p.khata = books[p.pk]


partners = Master(
    name="partners", model=Partner, form_class=PartnerForm,
    title=_("Partners"), subtitle=_("The people who own the farm together: the money each put in or took out, and their share of the profit."),
    add_label=_("Add partner"), row_template="business/partners/row.html", icon="group",
    view_cap="view_finance", search_fields=("name", "phone", "notes"), decorate=_decorate,
    nav_template="business/partners/tabs.html",
    empty_title=_("No partners yet"),
    empty_text=_("Farm with others? Add each partner with their share. Their money in and out is kept here, and the profit is split for you."),
    note=(_("How partners work"),
          _("Record the money each partner puts in or takes out. It moves money in an account, but it isn't income or expense, so the farm's profit stays the same."),
          _("“Profit sharing” splits the farm's profit for any period by each partner's share, and shows what each has already taken out."),
          _("Run the farm alone? You don't need this page.")),
)


def _partner(request, pk):
    return get_object_or_404(Partner.all_objects, pk=pk, business=request.business)


@business_access_required(capability="view_finance")
def partner_detail_view(request, pk):
    p = _partner(request, pk)
    khata = services.khatas(request.business, [p])[p.pk]
    year = date.today().replace(month=1, day=1)
    this_year = next((r for r in services.sharing(request.business, year, date.today()).rows if r.partner.pk == p.pk), None)
    entries = list(p.entries.select_related("account"))
    return render(request, "business/partners/detail.html", {"p": p, "khata": khata, "entries": entries, "this_year": this_year})


@business_access_required(capability="view_finance")
def entry_form_view(request, pk=None, partner_pk=None):
    obj = get_object_or_404(PartnerEntry.objects.select_related("partner"), pk=pk, business=request.business) if pk else None
    p = obj.partner if obj else _partner(request, partner_pk)
    initial = {"kind": request.GET["kind"]} if not obj and request.GET.get("kind") in EntryKind.values else None
    form = EntryForm(request.POST or None, instance=obj, business=request.business, initial=initial)
    if request.method == "POST" and form.is_valid():
        e = form.save(commit=False)
        e.business, e.partner = request.business, p
        e.save()
        messages.success(request, _g("Saved."))
        return redirect("business:partner_detail", p.pk)
    return render(request, "business/partners/entry_form.html", {"form": form, "p": p, "obj": obj})


@business_access_required(capability="delete")
@require_POST
def entry_delete_view(request, pk):
    e = get_object_or_404(PartnerEntry, pk=pk, business=request.business)
    e.soft_delete()
    messages.success(request, _g("Deleted."))
    return redirect("business:partner_detail", e.partner_id)


def _period(request):
    """(key, start, end) from ?period=year|last|all or ?from=&to=."""
    today = date.today()
    key = request.GET.get("period") or "year"
    if request.GET.get("from") or request.GET.get("to"):
        try:
            start = date.fromisoformat(request.GET.get("from") or "") if request.GET.get("from") else date(today.year, 1, 1)
            end = date.fromisoformat(request.GET.get("to") or "") if request.GET.get("to") else today
            if start <= end:
                return "custom", start, end
        except ValueError:
            pass
    if key == "last":
        return key, date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    if key == "fy":
        return key, fy_start(today), today
    if key == "lastfy":
        return (key, *last_fy(today))
    if key == "all":
        first = Partner.objects.filter(business=request.business).order_by("joined_on").values_list("joined_on", flat=True).first()
        return key, min(first or today, date(today.year, 1, 1)), today
    return "year", date(today.year, 1, 1), today


@business_access_required(capability="view_finance")
def sharing_view(request):
    key, start, end = _period(request)
    s = services.sharing(request.business, start, end)
    return render(request, "business/partners/sharing.html", {"s": s, "period": key, "today": date.today()})
