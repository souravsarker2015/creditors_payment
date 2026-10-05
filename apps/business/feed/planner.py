"""How much to feed each pond today, and how long the feed in stock will last.

    feed a day = fish weight in the pond × feeding rate for their size × water factor

The fish weight comes from the cycle (fish alive × latest sample weight; before
the first weighing, the fingerlings' own weight). The rate is the usual
share of body weight carp and pangas eat a day, falling as they grow. Cold or
very warm water and low oxygen cut it — fish eat less then, and uneaten feed
spoils the water.

It's a guide, not a rule: watch whether the feed is finished in 15–20 minutes
and adjust.
"""
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Sum
from django.utils.translation import gettext_lazy as _

ZERO = Decimal(0)
RECENT_DAYS = 7          # "what you've been giving"
USE_DAYS = 14            # how long the stock lasts: at the last 14 days' rate
WEIGH_STALE_DAYS = 21

# (fish up to this many grams, % of body weight a day)
RATES = [
    (5, Decimal("10")), (20, Decimal("7")), (50, Decimal("5")), (100, Decimal("4")),
    (300, Decimal("3")), (600, Decimal("2.5")), (1000, Decimal("2")), (None, Decimal("1.5")),
]


def rate_for(grams):
    for limit, pct in RATES:
        if limit is None or grams <= limit:
            return pct
    return RATES[-1][1]


def water_factor(temperature, oxygen_low):
    """(factor, reason) from the latest water test."""
    if oxygen_low:
        return Decimal("0.5"), _("Low oxygen in the last test: feed half, and run the aerator.")
    if temperature is None:
        return Decimal(1), ""
    t = Decimal(temperature)
    if t < 18:
        return Decimal("0.3"), _("Cold water (%(t)s °C): fish eat little.") % {"t": format(t.normalize(), "f")}
    if t < 22:
        return Decimal("0.6"), _("Cool water (%(t)s °C): fish eat less.") % {"t": format(t.normalize(), "f")}
    if t > 33:
        return Decimal("0.5"), _("Very warm water (%(t)s °C): feed less, in the cool hours.") % {"t": format(t.normalize(), "f")}
    if t > 30:
        return Decimal("0.8"), _("Warm water (%(t)s °C): feed a little less.") % {"t": format(t.normalize(), "f")}
    return Decimal(1), ""


@dataclass
class FishLine:
    species: object
    alive: int
    grams: Decimal
    kg: Decimal
    rate: Decimal
    from_weighing: bool


@dataclass
class PondPlan:
    cycle: object
    fish: list = field(default_factory=list)
    factor: Decimal = Decimal(1)
    reason: str = ""
    fed_per_day: Decimal | None = None       # average of the last days actually fed
    weighed_on: date | None = None

    @property
    def fish_kg(self):
        return sum((f.kg for f in self.fish), ZERO)

    @property
    def per_day(self):
        raw = sum((f.kg * f.rate / 100 for f in self.fish), ZERO) * self.factor
        return raw.quantize(Decimal("0.1"), ROUND_HALF_UP)

    @property
    def per_meal(self):
        return (self.per_day / 2).quantize(Decimal("0.1"), ROUND_HALF_UP)

    @property
    def stale(self):
        return self.weighed_on is None or (date.today() - self.weighed_on).days > WEIGH_STALE_DAYS

    @property
    def gap_pct(self):
        """How much more (+) or less (−) you've been feeding than the plan."""
        if not self.per_day or self.fed_per_day is None:
            return None
        return int(round((self.fed_per_day - self.per_day) * 100 / self.per_day))

    @property
    def verdict(self):
        gap = self.gap_pct
        if gap is None:
            return ""
        if gap > 20:
            return "over"
        if gap < -20:
            return "under"
        return "ok"


def plans(business, today=None):
    from apps.business.ponds.models import CultureCycle, CycleStatus, PondAlerts, WaterTest
    from apps.business.ponds.services import summarize

    from .models import FeedUsage

    today = today or date.today()
    limits = PondAlerts.for_business(business)
    cycles = list(CultureCycle.objects.filter(business=business, status=CycleStatus.RUNNING).select_related("pond")
                  .order_by("pond__order", "pond__name"))
    since = today - timedelta(days=RECENT_DAYS)
    fed = dict(FeedUsage.objects.filter(business=business, cycle__in=cycles, date__gt=since, date__lte=today)
               .values_list("cycle_id").annotate(kg=Sum("kg")))
    water = {}
    for t in WaterTest.objects.filter(business=business, cycle__in=cycles, date__gte=today - timedelta(days=3)).order_by("date", "id"):
        water[t.cycle_id] = t
    out = []
    for c in cycles:
        s = summarize(c)
        p = PondPlan(cycle=c)
        for row in s.species:
            if not row.alive:
                continue
            if row.avg_g:
                grams, weighed = row.avg_g, True
                p.weighed_on = max(p.weighed_on or row.weighed_on, row.weighed_on)
            elif row.stocked and row.stocked_kg:
                grams, weighed = row.stocked_kg * 1000 / row.stocked, False
            else:
                continue
            kg = (row.alive * grams / 1000).quantize(Decimal("0.1"))
            p.fish.append(FishLine(row.species, row.alive, grams.quantize(Decimal("1")), kg, rate_for(grams), weighed))
        test = water.get(c.pk)
        oxygen_low = bool(test and test.oxygen is not None and test.oxygen < limits.oxygen_min)
        p.factor, p.reason = water_factor(test.temperature if test else None, oxygen_low)
        days = min(RECENT_DAYS, max((today - c.start_date).days, 0) + 1)
        p.fed_per_day = (fed[c.pk] / days).quantize(Decimal("0.1")) if c.pk in fed else None
        out.append(p)
    return out


@dataclass
class StockDays:
    product: object
    left_kg: Decimal
    per_day: Decimal
    days: int | None

    @property
    def runs_out(self):
        return date.today() + timedelta(days=self.days) if self.days is not None else None


def stock_days(business, today=None):
    """For each feed in stock: kg left, kg used a day lately, and how many days that lasts."""
    from .models import FeedUsage
    from .services import stock

    today = today or date.today()
    used = dict(FeedUsage.objects.filter(business=business, cycle__is_deleted=False, date__gt=today - timedelta(days=USE_DAYS), date__lte=today)
                .values_list("product_id").annotate(kg=Sum("kg")))
    out = []
    for r in stock(business):
        if r.left_kg <= 0 and not used.get(r.product.pk):
            continue
        per_day = (used.get(r.product.pk, ZERO) / USE_DAYS).quantize(Decimal("0.1"))
        days = int(max(r.left_kg, ZERO) / per_day) if per_day > 0 else None
        out.append(StockDays(r.product, r.left_kg, per_day, days))
    return sorted(out, key=lambda s: (s.days is None, s.days or 0))
