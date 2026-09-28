from django.db.models import Count, Q
from django.utils.translation import gettext_lazy as _

from apps.business.core.crud import Master

from .forms import DeductionTypeForm, MarketDeductionFormSet, MarketForm
from .models import DeductionType, Market, MarketDeduction


def _deductions(objects, business):
    rows = MarketDeduction.objects.filter(market__in=objects).select_related("deduction_type", "unit")
    by_market = {}
    for r in rows:
        by_market.setdefault(r.market_id, []).append(r)
    for m in objects:
        m.deduction_rows = by_market.get(m.pk, [])


markets = Master(
    name="markets", model=Market, form_class=MarketForm,
    title=_("Markets & aarots"), subtitle=_("Where you sell fish, and what each one takes off a sale — commission, labour, khajna, ice…"),
    add_label=_("Add market"), row_template="business/markets/row.html", icon="cart",
    search_fields=("name", "location"),
    annotate=lambda qs, b: qs.annotate(buyer_count=Count("buyers", filter=Q(buyers__is_deleted=False))),
    decorate=_deductions,
    formset_class=MarketDeductionFormSet, formset_template="business/markets/deductions.html",
    empty_title=_("No markets yet"), empty_text=_("Add the aarots you sell at with their usual commission and charges. Every sale there will start with them filled in."),
    note=(_("How markets and deductions work"),
          _("Each market or aarot keeps its usual deductions: commission, labour, khajna, ice and so on."),
          _("When you record a sale at that market, these deductions are filled in for you. You can still change them on each sale."),
          _("A deduction can be a % of the sale, an amount per unit sold (e.g. ৳20 per mon), or a fixed amount per sale.")),
)

deduction_types = Master(
    name="deduction_types", model=DeductionType, form_class=DeductionTypeForm,
    title=_("Deduction types"), subtitle=_("Charges that can be taken off a sale. Add your own — e.g. association fee, weighing."),
    add_label=_("Add deduction type"), row_template="business/markets/deduction_type_row.html", icon="tag",
    search_fields=("name", "name_bn"),
    delete_check=lambda o: _("It's used by a market. Remove it there first.") if MarketDeduction.objects.filter(deduction_type=o).exists() else None,
    empty_title=_("No deduction types"), empty_text=_("Add the charges markets take off a sale."),
    note=(_("About deduction types"),
          _("These are the names of charges a market can take off a sale. Add any your markets use."),
          _("Set the actual amount on each market (Markets & aarots), or on a single sale.")),
)
