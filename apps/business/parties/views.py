from django.apps import apps
from django.db.models import Q
from django.utils.translation import gettext as _g, gettext_lazy as _

from apps.business.core.crud import Master

from .forms import BuyerForm, SupplierForm
from .models import BuyerType, Party

def _balances(objects, business):
    """Current baki balance on each row (+ they owe me, − I owe them)."""
    if apps.is_installed("apps.business.credit"):
        from apps.business.credit.services import balances

        found = balances(business)
        for o in objects:
            o.balance = found.get(o.pk, 0)
    else:
        for o in objects:
            o.balance = o.opening_signed


def _can_delete(party):
    if apps.is_installed("apps.business.credit"):
        from apps.business.credit.services import ledger

        bal = ledger(party).balance
        if bal:
            return _g("%(name)s still has a balance. Settle it before deleting.") % {"name": party}
    return None


suppliers = Master(
    name="suppliers", model=Party, form_class=SupplierForm, base_filter=Q(is_supplier=True),
    title=_("Suppliers"), subtitle=_("Feed dealers, fingerling hatcheries, medicine shops — anyone you buy from, often on baki."),
    add_label=_("Add supplier"), row_template="business/parties/row.html", icon="truck", decorate=_balances, delete_check=_can_delete,
    view_cap=None, edit_cap="enter_data", search_fields=("name", "phone", "address", "contact_person"),
    empty_title=_("No suppliers yet"), empty_text=_("Add the feed dealer or hatchery you buy from. If you already owe them, enter that balance too."),
    note=(_("About suppliers"),
          _("Suppliers are people you buy from: feed, fingerlings, medicine. Anything you haven't paid them shows in Baki."),
          _("Already owed them money before you started using the app? Enter it as the opening balance on their page."),
          _("Tap a name to see their full statement: every bill and payment, with the balance after each.")),
)

buyers = Master(
    name="buyers", model=Party, form_class=BuyerForm, base_filter=Q(is_buyer=True),
    title=_("Buyers"), subtitle=_("Aratdars, paikars and others who buy your fish."),
    add_label=_("Add buyer"), row_template="business/parties/row.html", icon="users", decorate=_balances, delete_check=_can_delete,
    view_cap=None, edit_cap="enter_data", search_fields=("name", "phone", "address", "market__name"),
    select_related=("market",),
    filters=[(k, label, Q(buyer_type=k)) for k, label in BuyerType.choices if k != "other"],
    empty_title=_("No buyers yet"), empty_text=_("Add the aratdars and paikars you sell to, with their usual market."),
    note=(_("About buyers"),
          _("Buyers are aratdars, paikars and others who buy your fish. If they don't pay in full, the rest shows in Baki as money to collect."),
          _("Set a buyer's usual market: on a new sale with no market chosen yet, picking the buyer fills it in, with its deductions."),
          _("One person can be both a buyer and a supplier; their Baki is then worked out together.")),
)
