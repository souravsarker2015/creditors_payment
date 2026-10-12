"""Feed stock and cost. Stock is never typed in: it is kg bought minus kg
used, put right by the counts you make of the store."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from .models import FeedCount, FeedProduct, FeedPurchaseLine, FeedUsage

ZERO = Decimal(0)


def cost_per_kg(business, cache=None):
    """Average price paid per kg, per feed (from purchase lines).

    Reports ask for this once per pond season, so pass a dict as `cache` to
    work it out once for the whole page.
    """
    if cache is not None and business.pk in cache:
        return cache[business.pk]
    rows = (FeedPurchaseLine.objects.filter(business=business, purchase__is_deleted=False)
            .values("product_id").annotate(amount=Sum("amount"), kg=Sum("kg")))
    totals = {r["product_id"]: [r["amount"], r["kg"]] for r in rows}
    # Feed already in the store when you started counts as bought, at the price you gave it.
    for c in FeedCount.objects.filter(business=business, opening=True, difference_kg__gt=0).values("product_id", "difference_kg", "rate_kg"):
        t = totals.setdefault(c["product_id"], [ZERO, ZERO])
        t[0] += c["difference_kg"] * c["rate_kg"]
        t[1] += c["difference_kg"]
    prices = {pk: amount / kg for pk, (amount, kg) in totals.items() if kg}
    if cache is not None:
        cache[business.pk] = prices
    return prices


@dataclass
class StockRow:
    product: FeedProduct
    bought_kg: Decimal
    used_kg: Decimal
    avg_cost: Decimal | None
    counted_kg: Decimal = ZERO     # put right by counting the store: + found or already had, − lost
    last_count: object = None

    @property
    def left_kg(self):
        return self.bought_kg - self.used_kg + self.counted_kg

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
        had = self.bought_kg + max(self.counted_kg, ZERO)
        return min(int(self.used_kg * 100 / had), 100) if had else 0


def stock(business):
    bought = dict(FeedPurchaseLine.objects.filter(business=business, purchase__is_deleted=False)
                  .values_list("product_id").annotate(kg=Sum("kg")))
    used = dict(FeedUsage.objects.filter(business=business, cycle__is_deleted=False)
                .values_list("product_id").annotate(kg=Sum("kg")))
    counted = dict(FeedCount.objects.filter(business=business).values_list("product_id").annotate(kg=Sum("difference_kg")))
    last = {}
    for c in FeedCount.objects.filter(business=business).order_by("date", "id"):
        last[c.product_id] = c
    prices = cost_per_kg(business)
    rows = [StockRow(p, bought.get(p.pk) or ZERO, used.get(p.pk) or ZERO, prices.get(p.pk), counted.get(p.pk) or ZERO, last.get(p.pk))
            for p in FeedProduct.objects.filter(business=business).select_related("bag_unit")]
    # Low or short first, then what you have the most of.
    return sorted(rows, key=lambda r: (not (r.is_low or r.is_negative), -(r.left_kg)))


def low_stock(business):
    return [r for r in stock(business) if (r.is_low or r.is_negative) and (r.bought_kg or r.used_kg or r.counted_kg)]


# ── Counting the store ──────────────────────────────────────────────────────

SAME_BAGS = Decimal("0.05")   # closer than this to the records is a match

def book_kg(business, product, day):
    """What the records say is in the store at the end of `day`."""
    bought = (FeedPurchaseLine.objects.filter(business=business, product=product, purchase__is_deleted=False, purchase__date__lte=day)
              .aggregate(kg=Sum("kg"))["kg"] or ZERO)
    used = (FeedUsage.objects.filter(business=business, product=product, cycle__is_deleted=False, date__lte=day)
            .aggregate(kg=Sum("kg"))["kg"] or ZERO)
    counted = FeedCount.objects.filter(business=business, product=product, date__lte=day).aggregate(kg=Sum("difference_kg"))["kg"] or ZERO
    return bought - used + counted


def has_records(business, product, day):
    """Any purchase, feeding or count of this feed on or before `day`."""
    return (FeedPurchaseLine.objects.filter(business=business, product=product, purchase__is_deleted=False, purchase__date__lte=day).exists()
            or FeedUsage.objects.filter(business=business, product=product, cycle__is_deleted=False, date__lte=day).exists()
            or FeedCount.objects.filter(business=business, product=product, date__lte=day).exists())


@transaction.atomic
def save_counts(business, day, entries):
    """entries: [(product, counted kg, price per kg or None)]. The price is only
    used for feed you already had: everything else is valued at the average
    price you paid. Returns the counts made."""
    prices = cost_per_kg(business)
    made = []
    for product, counted, typed_rate in entries:
        opening = not has_records(business, product, day)
        book = book_kg(business, product, day)
        if not opening and abs(counted - book) < product.bag_kg * SAME_BAGS:
            counted = book    # the page shows a tenth of a bag: typing what it says is a match
        if opening:
            rate = typed_rate if typed_rate is not None else (product.price_per_kg or ZERO)
        else:
            rate = prices.get(product.pk) or product.price_per_kg or ZERO
        made.append(FeedCount.objects.create(business=business, product=product, date=day, counted_kg=counted,
                                             book_kg=book, difference_kg=counted - book, rate_kg=rate, opening=opening))
    return made


def count_result(business, start, end):
    """Feed lost and feed found at the counts between two dates, in money.
    Feed you already had when you started isn't either."""
    lost = found = ZERO
    for c in FeedCount.objects.filter(business=business, opening=False, date__gte=start, date__lte=end):
        if c.value < 0:
            lost -= c.value
        else:
            found += c.value
    return lost, found


def last_counted(business):
    c = FeedCount.objects.filter(business=business).order_by("-date", "-id").first()
    return c.date if c else None


def days_since_count(business, today=None):
    last = last_counted(business)
    return ((today or date.today()) - last).days if last else None


@transaction.atomic
def save_bulk_usage(business, day, product, entries):
    """entries: [(cycle, quantity, unit or None)] — one feeding per pond."""
    made = []
    for cycle, quantity, unit in entries:
        made.append(FeedUsage.objects.create(business=business, cycle=cycle, date=day, product=product, quantity=quantity, unit=unit))
    return made
