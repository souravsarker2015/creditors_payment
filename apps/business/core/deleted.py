"""Everything deleted on the farm, in one place, to bring back.

Nothing in the business is deleted for good: a record is only hidden (BusinessBaseModel.soft_delete). Masters have
a Deleted tab of their own; this page holds them all, the small entries too, which have no list of their own."""
from django.apps import apps
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _, gettext_lazy as _l
from django.views.decorators.http import require_POST

from .crud import MASTERS
from .decorators import business_access_required

LIMIT = 300
KINDS = {       # what can be deleted by itself (a sale's lines go and come back with the sale)
    "business_ponds.pond": _l("Pond"), "business_ponds.culturecycle": _l("Cycle"), "business_ponds.stocking": _l("Stocking"),
    "business_ponds.mortality": _l("Deaths"), "business_ponds.sampleweighing": _l("Weighing"), "business_ponds.harvest": _l("Harvest"),
    "business_ponds.fishmove": _l("Fish moved"), "business_ponds.watertest": _l("Water test"), "business_ponds.leasepayment": _l("Lease payment"),
    "business_ponds.treatment": _l("Pond care"), "business_species.species": _l("Species"), "business_core.unit": _l("Unit"),
    "business_markets.market": _l("Market"), "business_markets.deductiontype": _l("Deduction"), "business_markets.pricecheck": _l("Market price"),
    "business_parties.party": _l("Buyer or supplier"), "business_credit.partypayment": _l("Baki payment"), "business_sales.fishsale": _l("Sale"),
    "business_feed.feedproduct": _l("Feed"), "business_feed.feedpurchase": _l("Feed purchase"), "business_feed.feedusage": _l("Feeding"),
    "business_feed.feedcount": _l("Stock count"), "business_finance.account": _l("Account"), "business_finance.category": _l("Category"),
    "business_finance.familymember": _l("Family member"), "business_finance.transaction": _l("Money in or out"), "business_finance.transfer": _l("Transfer"),
    "business_finance.recurringtransaction": _l("Regular bill"), "business_loans.lender": _l("Lender"), "business_loans.loan": _l("Loan"),
    "business_loans.loantransaction": _l("Loan entry"), "business_loans.loanratechange": _l("Rate change"), "business_calendar.calendarevent": _l("Calendar"),
    "business_staff.worker": _l("Staff"), "business_staff.earning": _l("Earning"), "business_staff.workerpayment": _l("Staff payment"),
    "business_assets.equipment": _l("Equipment"), "business_assets.service": _l("Equipment service"), "business_supplies.supplyitem": _l("Supply"),
    "business_supplies.supplypurchase": _l("Supply purchase"), "business_partners.partner": _l("Partner"), "business_partners.partnerentry": _l("Partner entry"),
    "business_papers.farmpaper": _l("Paper"),
}


def _deleted(business, kind):
    return apps.get_model(kind).all_objects.filter(business=business, is_deleted=True)


@business_access_required(capability="delete")
def deleted_view(request):
    b = request.business
    counts = {kind: _deleted(b, kind).count() for kind in KINDS}
    shown = request.GET.get("kind", "")
    if shown not in KINDS:
        shown = ""
    rows = []
    for kind in [shown] if shown else [k for k, n in counts.items() if n]:
        for obj in _deleted(b, kind).select_related("updated_by").order_by("-deleted_at")[:LIMIT]:
            rows.append({"obj": obj, "kind": kind, "label": KINDS[kind]})
    rows.sort(key=lambda r: r["obj"].deleted_at, reverse=True)
    return render(request, "business/settings/deleted.html", {
        "rows": rows[:LIMIT], "total": sum(counts.values()), "shown": shown,
        "kinds": sorted(((k, str(KINDS[k]), n) for k, n in counts.items() if n), key=lambda x: x[1]),
    })


def _why_not(request, obj):
    """What stands in the way of bringing it back, if anything."""
    from apps.business.ponds.models import CultureCycle
    from apps.business.ponds.services import running_cycle

    if isinstance(obj, CultureCycle) and obj.is_running and running_cycle(obj.pond):
        return _("%(pond)s already has a running cycle. Finish it first.") % {"pond": obj.pond}
    masters = {m.model for m in MASTERS.values()}
    if type(obj) in masters and type(obj).objects.filter(business=request.business, name__iexact=obj.name).exists():
        return _("Another one is already called “%(name)s”. Rename it first.") % {"name": obj.name}
    return None


@business_access_required(capability="delete")
@require_POST
def deleted_restore_view(request, kind, pk):
    if kind not in KINDS:
        raise Http404
    obj = _deleted(request.business, kind).filter(pk=pk).first()
    if obj is None:
        messages.info(request, _("That's already back."))
        return redirect("business:deleted")
    problem = _why_not(request, obj)
    if not problem:
        try:
            with transaction.atomic():
                obj.restore()
        except IntegrityError:
            problem = _("Something the same is already there, so this can't come back. Change that one first.")
    if problem:
        messages.error(request, problem)
    else:
        messages.success(request, _("“%(name)s” restored.") % {"name": obj})
    return redirect("business:deleted")
