"""When will the fish reach selling size?

Growth so far comes from the latest sample weighing against an earlier one (or
against the fingerlings' weight at stocking). Carried forward in a straight
line, it gives the size today and the day the fish should reach the species'
selling size. It is a rough guess on purpose: weighing every 2–3 weeks keeps
it close, and a weighing that shows no growth is a warning on its own.
"""
import math
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Prefetch, prefetch_related_objects

from .models import CultureCycle, CycleStatus, SampleWeighing

ZERO = Decimal(0)
MIN_GAP_DAYS = 7      # two weighings closer than this don't show growth reliably
STALE_DAYS = 30       # a guess carried on from an older weighing is shaky
SLOW_G_DAY = Decimal("0.1")
FAR_DAYS = 365


def _prefetch():
    return ("stockings__species", "mortalities__species", "harvests__species", "harvests__unit",
            "moves_in__species", "moves_in__cycle", "moves_out__species", "moves_out__to_cycle",
            Prefetch("weighings", queryset=SampleWeighing.objects.select_related("species", "unit")))


@dataclass
class Point:
    date: date
    grams: Decimal


@dataclass
class Forecast:
    cycle: CultureCycle
    species: object
    alive: int
    target_g: int | None
    last: Point | None = None
    growth: Decimal | None = None      # g per fish per day
    now_g: Decimal | None = None       # estimated today
    ready_on: date | None = None
    price: Decimal | None = None       # usual money in hand per kg

    @property
    def status(self):
        if self.last is None:
            return "no_weighing"
        if self.growth is None:
            return "one_weighing"
        if self.growth < SLOW_G_DAY:
            return "slow"
        if not self.target_g:
            return "no_size"
        return "ready" if self.now_g >= self.target_g else "growing"

    @property
    def days_left(self):
        return max((self.ready_on - date.today()).days, 0) if self.ready_on else None

    @property
    def far(self):
        """Over a year away: the growth is too slow to be worth a date."""
        return self.status == "growing" and self.days_left > FAR_DAYS

    @property
    def stale(self):
        return self.last is not None and (date.today() - self.last.date).days > STALE_DAYS

    @property
    def progress(self):
        if not (self.now_g and self.target_g):
            return 0
        return min(int(self.now_g * 100 / self.target_g), 100)

    @property
    def kg_at_ready(self):
        """Fish in the pond by weight once they reach selling size (or now, if past it)."""
        if not (self.alive and self.target_g):
            return None
        grams = max(self.now_g or ZERO, Decimal(self.target_g))
        return (self.alive * grams / 1000).quantize(Decimal("1"))

    @property
    def value(self):
        return (self.kg_at_ready * self.price).quantize(Decimal("1")) if (self.kg_at_ready and self.price) else None


def _points(cycle, species):
    """The fingerlings' average weight (released here or moved in), then each weighing — oldest first."""
    pts = []
    count = weight = 0
    first = None
    moved_in = [m for m in cycle.moves_in.all() if not m.cycle.is_deleted]
    for st in list(cycle.stockings.all()) + moved_in:
        if st.species_id == species.pk and st.count and st.weight_kg:
            count += st.count
            weight += st.weight_kg
            first = max(first, st.date) if first else st.date
    if count:
        pts.append(Point(first, (weight * 1000 / count).quantize(Decimal("0.1"))))
    for w in sorted((w for w in cycle.weighings.all() if w.species_id == species.pk), key=lambda w: (w.date, w.pk)):
        pts.append(Point(w.date, w.avg_g))
    return sorted(pts, key=lambda p: p.date)


def _alive(cycle):
    """{species id: (species, fish still in the pond)} — fish all taken out are left off."""
    from .services import count_fish

    return {pk: (r.species, r.alive) for pk, r in count_fish(cycle).items() if r.alive > 0 or not r.put_in}


def _price(business, species_id, today):
    """Money in hand per kg from your own recent sales; else the latest market
    price you noted (before deductions)."""
    from django.apps import apps

    from .services import usual_price_per_kg

    price = usual_price_per_kg(business, [species_id], today)
    if price is None and apps.is_installed("apps.business.markets"):
        from apps.business.markets.prices import latest_per_kg

        price = latest_per_kg(business, [species_id], today).get(species_id)
    return price


def for_cycle(cycle, today=None, prices=None):
    """One forecast per fish in a running cycle. `prices` caches {species id: price per kg}."""
    today = today or date.today()
    prices = {} if prices is None else prices
    if "weighings" not in getattr(cycle, "_prefetched_objects_cache", {}):
        prefetch_related_objects([cycle], *_prefetch())
    out = []
    for sp, alive in sorted(_alive(cycle).values(), key=lambda pair: pair[0].order):
        f = Forecast(cycle, sp, alive, sp.market_size_g)
        pts = _points(cycle, sp)
        if any(w.species_id == sp.pk for w in cycle.weighings.all()):
            f.last = pts[-1]
            base = next((p for p in reversed(pts[:-1]) if (f.last.date - p.date).days >= MIN_GAP_DAYS), None)
            if base is not None:
                f.growth = ((f.last.grams - base.grams) / (f.last.date - base.date).days).quantize(Decimal("0.01"))
                if f.growth >= SLOW_G_DAY:
                    f.now_g = (f.last.grams + f.growth * (today - f.last.date).days).quantize(Decimal("1"))
                    if f.target_g:
                        need = Decimal(f.target_g) - f.last.grams
                        f.ready_on = f.last.date + timedelta(days=max(math.ceil(need / f.growth), 0))
            if f.now_g is None:
                f.now_g = f.last.grams.quantize(Decimal("1"))
        if alive and f.target_g:
            if sp.pk not in prices:
                prices[sp.pk] = _price(cycle.business, sp.pk, today)
            f.price = prices[sp.pk]
        out.append(f)
    return out


def running_cycles(business):
    return (CultureCycle.objects.filter(business=business, status=CycleStatus.RUNNING)
            .select_related("pond").prefetch_related(*_prefetch()))


def for_farm(business, today=None):
    """Every running pond's forecasts, the soonest ready first."""
    prices = {}
    rows = [f for c in running_cycles(business) for f in for_cycle(c, today, prices)]
    order = {"ready": 0, "growing": 1, "slow": 2, "one_weighing": 3, "no_size": 4, "no_weighing": 5}
    return sorted(rows, key=lambda f: (order[f.status], f.ready_on or date.max, f.cycle.pond.name))
