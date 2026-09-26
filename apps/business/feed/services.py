"""Feed stock and cost. Stock is never typed in: it is kg bought minus kg used."""
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from .models import FeedProduct, FeedPurchaseLine, FeedUsage

ZERO = Decimal(0)


def cost_per_kg(business):
    """Average price paid per kg, per feed (from purchase lines)."""
    rows = (FeedPurchaseLine.objects.filter(business=business, purchase__is_deleted=False)
            .values("product_id").annotate(amount=Sum("amount"), kg=Sum("kg")))
    return {r["product_id"]: (r["amount"] / r["kg"]) for r in rows if r["kg"]}


@dataclass
class StockRow:
    product: FeedProduct
    bought_kg: Decimal
    used_kg: Decimal
    avg_cost: Decimal | None

    @property
    def left_kg(self):
        return self.bought_kg - self.used_kg

    @property
    def left_bags(self):
        return (self.left_kg / self.product.bag_kg).quantize(Decimal("0.1")) if self.product.bag_kg else None

    @property
    def value(self):
        return (max(self.left_kg, ZERO) * self.avg_cost).quantize(Decimal("1")) if self.avg_cost else None

    @property
    def is_low(self):
        return self.product.low_stock_bags is not None and self.left_bags is not None and self.left_bags <= self.product.low_stock_bags

    @property
    def is_negative(self):
        return self.left_kg < 0

    @property
    def used_pct(self):
        return min(int(self.used_kg * 100 / self.bought_kg), 100) if self.bought_kg else 0


def stock(business):
    bought = dict(FeedPurchaseLine.objects.filter(business=business, purchase__is_deleted=False)
                  .values_list("product_id").annotate(kg=Sum("kg")))
    used = dict(FeedUsage.objects.filter(business=business, cycle__is_deleted=False)
                .values_list("product_id").annotate(kg=Sum("kg")))
    prices = cost_per_kg(business)
    rows = [StockRow(p, bought.get(p.pk) or ZERO, used.get(p.pk) or ZERO, prices.get(p.pk))
            for p in FeedProduct.objects.filter(business=business).select_related("bag_unit")]
    # Low or short first, then what you have the most of.
    return sorted(rows, key=lambda r: (not (r.is_low or r.is_negative), -(r.left_kg)))


def low_stock(business):
    return [r for r in stock(business) if (r.is_low or r.is_negative) and (r.bought_kg or r.used_kg)]


@transaction.atomic
def save_bulk_usage(business, day, product, entries):
    """entries: [(cycle, quantity, unit or None)] — one feeding per pond."""
    made = []
    for cycle, quantity, unit in entries:
        made.append(FeedUsage.objects.create(business=business, cycle=cycle, date=day, product=product, quantity=quantity, unit=unit))
    return made
