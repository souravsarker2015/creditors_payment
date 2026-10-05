"""The Fish prices board: what each fish is fetching, from two sources.

* prices you note at a market (PriceCheck), and
* the rates on your own sales (by weight: mon, kg…),

all turned into a price per kg, so mon and kg rates compare directly. Sale
rates are before market deductions — the same number an aarot quotes.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.apps import apps

from .models import PriceCheck

ZERO = Decimal(0)
WINDOW_DAYS = 30          # "recently": high, low, best market
WEEKS = 12                # the little trend line


@dataclass
class Point:
    date: date
    species_id: int
    market_id: int | None
    per_kg: Decimal
    source: str            # noted | sale
    size: str = ""
    obj: object = None


def points(business, since):
    out = [Point(p.date, p.species_id, p.market_id, p.rate_kg, "noted", p.size, p)
           for p in PriceCheck.objects.filter(business=business, date__gte=since, rate_kg__gt=0)]
    if apps.is_installed("apps.business.sales"):
        from apps.business.sales.models import FishSaleLine

        lines = (FishSaleLine.objects.filter(business=business, sale__is_deleted=False, sale__date__gte=since,
                                             unit__unit_type="weight", rate__gt=0)
                 .select_related("sale", "unit"))
        for l in lines:
            out.append(Point(l.sale.date, l.species_id, l.sale.market_id, (l.rate / l.unit.factor).quantize(Decimal("0.01")), "sale", "", l.sale))
    out.sort(key=lambda p: (p.date, p.source == "noted"))
    return out


def _avg(values):
    values = list(values)
    return (sum(values, ZERO) / len(values)).quantize(Decimal("0.01")) if values else None


@dataclass
class Board:
    species: object
    latest: Point
    week_avg: Decimal | None            # last 7 days
    before_avg: Decimal | None          # the 30 days before that
    high: Decimal | None = None
    low: Decimal | None = None
    best_market: object = None
    best_market_avg: Decimal | None = None
    spark: list = field(default_factory=list)      # weekly averages, oldest first (None = no price that week)
    count: int = 0
    latest_market: object = None

    @property
    def change_pct(self):
        if self.week_avg is None or not self.before_avg:
            return None
        return int(round((self.week_avg - self.before_avg) * 100 / self.before_avg))

    @property
    def spark_path(self):
        """SVG points for a 120×32 trend line."""
        vals = [v for v in self.spark if v is not None]
        if len(vals) < 2:
            return ""
        lo, hi = min(vals), max(vals)
        span = (hi - lo) or Decimal(1)
        step = Decimal(120) / (len(self.spark) - 1)
        pts = []
        for i, v in enumerate(self.spark):
            if v is None:
                continue
            y = Decimal(28) - (v - lo) / span * Decimal(24)
            pts.append(f"{float(step * i):.1f},{float(y):.1f}")
        return " ".join(pts)


def board(business, today=None):
    from apps.business.species.models import Species

    from .models import Market

    today = today or date.today()
    since = today - timedelta(weeks=WEEKS)
    by_species = defaultdict(list)
    for p in points(business, since):
        by_species[p.species_id].append(p)
    species = {s.pk: s for s in Species.all_objects.filter(business=business, pk__in=by_species)}
    markets = {m.pk: m for m in Market.all_objects.filter(business=business)}
    out = []
    for sid, pts in by_species.items():
        if sid not in species:
            continue
        recent = [p for p in pts if p.date > today - timedelta(days=WINDOW_DAYS)]
        b = Board(
            species=species[sid], latest=pts[-1], count=len(pts),
            week_avg=_avg(p.per_kg for p in pts if p.date > today - timedelta(days=7)),
            before_avg=_avg(p.per_kg for p in pts if today - timedelta(days=37) < p.date <= today - timedelta(days=7)),
        )
        b.latest_market = markets.get(b.latest.market_id)
        if recent:
            b.high, b.low = max(p.per_kg for p in recent), min(p.per_kg for p in recent)
            per_market = defaultdict(list)
            for p in recent:
                if p.market_id:
                    per_market[p.market_id].append(p.per_kg)
            if len(per_market) > 1:
                best = max(per_market, key=lambda m: _avg(per_market[m]))
                b.best_market, b.best_market_avg = markets.get(best), _avg(per_market[best])
        start = today - timedelta(weeks=WEEKS)
        weekly = defaultdict(list)
        for p in pts:
            weekly[min((p.date - start).days // 7, WEEKS - 1)].append(p.per_kg)
        b.spark = [_avg(weekly[w]) if weekly.get(w) else None for w in range(WEEKS)]
        out.append(b)
    out.sort(key=lambda b: (b.species.order, b.species.name))
    return out


def latest_per_kg(business, species_ids, today=None):
    """{species id: latest price per kg seen in the last 30 days} — for the sale form and projections."""
    today = today or date.today()
    out = {}
    for p in points(business, today - timedelta(days=WINDOW_DAYS)):
        if p.species_id in species_ids:
            out[p.species_id] = p.per_kg
    return out
