"""Store stock and prices. Stock = bought − put into ponds, in base units (kg, L, pcs)."""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Max, Sum

from apps.business.ponds.models import Treatment

from .models import SupplyItem, SupplyPurchase

ZERO = Decimal(0)
RECENT_DAYS = 30


def avg_cost(business, item_ids=None):
    """{item id: average price paid per base unit}."""
    rows = SupplyPurchase.objects.filter(business=business)
    if item_ids is not None:
        rows = rows.filter(item_id__in=item_ids)
    rows = rows.values("item_id").annotate(cost=Sum("cost"), qty=Sum("base_quantity"))
    return {r["item_id"]: r["cost"] / r["qty"] for r in rows if r["qty"]}


def _uses(business):
    return Treatment.objects.filter(business=business, item__isnull=False, cycle__is_deleted=False, base_quantity__isnull=False)


@dataclass
class Stock:
    item: SupplyItem
    bought: Decimal          # base units
    used: Decimal
    used_recently: Decimal   # last 30 days
    avg_cost: Decimal | None  # per base unit
    last_used: date | None

    @property
    def factor(self):
        return self.item.unit.factor

    @property
    def left_base(self):
        return self.bought - self.used

    @property
    def left(self):
        """In the item's own unit."""
        return (self.left_base / self.factor).quantize(Decimal("0.01"))

    @property
    def recent(self):
        """Used in the last 30 days, in the item's own unit."""
        return (self.used_recently / self.factor).quantize(Decimal("0.01"))

    @property
    def is_out(self):
        return self.left_base <= 0 and bool(self.bought or self.used)

    @property
    def is_low(self):
        return not self.is_out and self.item.low_stock is not None and self.left <= self.item.low_stock

    @property
    def unit_price(self):
        """Average price per item unit."""
        return (self.avg_cost * self.factor).quantize(Decimal("0.01")) if self.avg_cost else None

    @property
    def value(self):
        return (max(self.left_base, ZERO) * self.avg_cost).quantize(Decimal("1")) if self.avg_cost else None

    @property
    def used_pct(self):
        return min(int(self.used * 100 / self.bought), 100) if self.bought else 0


def stock(business, items=None, today=None):
    """One Stock per item (all the farm's items unless `items` is given)."""
    today = today or date.today()
    items = list(items if items is not None else SupplyItem.objects.filter(business=business).select_related("unit"))
    ids = [i.pk for i in items]
    bought = dict(SupplyPurchase.objects.filter(business=business, item_id__in=ids)
                  .values_list("item_id").annotate(q=Sum("base_quantity")))
    uses = _uses(business).filter(item_id__in=ids)
    used = dict(uses.values_list("item_id").annotate(q=Sum("base_quantity")))
    recent = dict(uses.filter(date__gte=today - timedelta(days=RECENT_DAYS)).values_list("item_id").annotate(q=Sum("base_quantity")))
    last = dict(uses.values_list("item_id").annotate(d=Max("date")))
    prices = avg_cost(business, ids)
    return [Stock(i, bought.get(i.pk) or ZERO, used.get(i.pk) or ZERO, recent.get(i.pk) or ZERO, prices.get(i.pk), last.get(i.pk))
            for i in items]


def stock_for(item):
    return stock(item.business, [item])[0]


def running_low(business):
    """Items that are out or below their warning level, the emptiest first."""
    return sorted((s for s in stock(business) if s.is_out or s.is_low), key=lambda s: s.left)


def use_cost(item, base_quantity):
    """What this much from the store cost, at the average price paid (None if never bought)."""
    price = avg_cost(item.business, [item.pk]).get(item.pk)
    return (base_quantity * price).quantize(Decimal("0.01")) if (price and base_quantity) else None
