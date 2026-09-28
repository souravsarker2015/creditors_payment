"""Figures worked out from past sales."""
from decimal import Decimal

from django.utils.formats import date_format

from .models import FishSaleLine

RECENT_LINES = 1000   # enough history to know every fish's latest price


def last_rates(business, exclude_sale=None):
    """The latest price for each fish, so a new sale can start from it.

    Keys are "species:market:unit type" and "species:*:unit type" (any market);
    the price is per base unit (per kg, per piece), so the sale form can turn it
    into whatever unit the user picks.
    """
    lines = (FishSaleLine.objects.filter(business=business, sale__is_deleted=False, rate__gt=0)
             .select_related("unit", "sale__market").order_by("-sale__date", "-sale_id", "-id"))
    if exclude_sale is not None:
        lines = lines.exclude(sale=exclude_sale)
    out = {}
    for line in lines[:RECENT_LINES]:
        if not line.unit.factor:
            continue
        found = {"per_base": format((line.rate / line.unit.factor).quantize(Decimal("0.0001")).normalize(), "f"),
                 "date": date_format(line.sale.date, "j M"), "market": line.sale.market.name if line.sale.market else ""}
        for market in (line.sale.market_id or 0, "*"):
            out.setdefault(f"{line.species_id}:{market}:{line.unit.unit_type}", found)
    return out
