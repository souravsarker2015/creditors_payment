from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.business.core.crud import Master

from .forms import BuyerForm, SupplierForm
from .models import BuyerType, Party

suppliers = Master(
    name="suppliers", model=Party, form_class=SupplierForm, base_filter=Q(is_supplier=True),
    title=_("Suppliers"), subtitle=_("Feed dealers, fingerling hatcheries, medicine shops — anyone you buy from, often on baki."),
    add_label=_("Add supplier"), row_template="business/parties/row.html", icon="truck",
    view_cap=None, edit_cap="enter_data", search_fields=("name", "phone", "address", "contact_person"),
    empty_title=_("No suppliers yet"), empty_text=_("Add the feed dealer or hatchery you buy from. If you already owe them, enter that balance too."),
)

buyers = Master(
    name="buyers", model=Party, form_class=BuyerForm, base_filter=Q(is_buyer=True),
    title=_("Buyers"), subtitle=_("Aratdars, paikars and others who buy your fish."),
    add_label=_("Add buyer"), row_template="business/parties/row.html", icon="users",
    view_cap=None, edit_cap="enter_data", search_fields=("name", "phone", "address", "market__name"),
    select_related=("market",),
    filters=[(k, label, Q(buyer_type=k)) for k, label in BuyerType.choices if k != "other"],
    empty_title=_("No buyers yet"), empty_text=_("Add the aratdars and paikars you sell to, with their usual market."),
)
