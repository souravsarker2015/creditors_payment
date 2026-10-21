"""This season against the last one, at the same age.

"Day 60: fish are 410 g — last season they were 350 g on day 60" tells a
farmer far more than either number alone: growth, survival and feed use are
compared on the same day of each cycle, so an early slip shows while there's
still time to act.

The other cycle is the last finished one in the same pond; if the pond has
none, the farm's last finished cycle with the same main fish.
"""
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.utils.translation import gettext as _

from .models import CultureCycle, CycleStatus
from .services import _size_on, harvest_count

ZERO = Decimal(0)


@dataclass
class Snapshot:
    """A cycle on one day of its life."""

    day: int
    put_in: int = 0
    died: int = 0
    alive: int = 0
    weighed: bool = False         # a sample weighing by then: the size is measured, not guessed
    biomass_kg: Decimal = ZERO
    feed_kg: Decimal = ZERO
    stocked_kg: Decimal = ZERO
    out_kg: Decimal = ZERO        # harvested or moved on by then

    @property
    def size_g(self):
        return (self.biomass_kg * 1000 / self.alive).quantize(Decimal("1")) if (self.weighed and self.alive) else None

    @property
    def survival(self):
        return round(max(self.put_in - self.died, 0) * 100 / self.put_in) if self.put_in else None

    @property
    def fcr(self):
        grown = self.biomass_kg + self.out_kg - self.stocked_kg
        return (self.feed_kg / grown).quantize(Decimal("0.01")) if (self.weighed and self.feed_kg and grown > 0) else None

    @property
    def feed_per_1000(self):
        return (self.feed_kg * 1000 / self.put_in).quantize(Decimal("1")) if self.put_in else None


def snapshot(cycle, day):
    """What `cycle` looked like `day` days after it started."""
    on = cycle.start_date + timedelta(days=day)
    s = Snapshot(day=day)
    stockings = [x for x in cycle.stockings.select_related("species") if x.date <= on]
    moves_in = [m for m in cycle.moves_in.select_related("species", "cycle") if m.date <= on and not m.cycle.is_deleted]
    moves_out = [m for m in cycle.moves_out.select_related("species", "to_cycle") if m.date <= on and not m.to_cycle.is_deleted]
    weighings = sorted((w for w in cycle.weighings.select_related("unit") if w.date <= on), key=lambda w: (w.date, w.id))
    sizes = {}
    for x in stockings + moves_in:
        if x.avg_g:
            sizes.setdefault(x.species_id, []).append((x.date, x.avg_g))
    for w in weighings:
        sizes.setdefault(w.species_id, []).append((w.date, w.avg_g))
    for pts in sizes.values():
        pts.sort(key=lambda p: p[0])
    alive = {}
    for x in stockings + moves_in:
        alive[x.species_id] = alive.get(x.species_id, 0) + (x.count or 0)
        s.stocked_kg += x.weight_kg or ZERO
    s.put_in = sum(alive.values())
    for m in moves_out:
        alive[m.species_id] = alive.get(m.species_id, 0) - m.count
        s.out_kg += m.weight_kg or ZERO
    loose = 0
    for m in cycle.mortalities.all():
        if m.date > on:
            continue
        s.died += m.count
        if m.species_id in alive:
            alive[m.species_id] -= m.count
        else:
            loose += m.count
    for h in cycle.harvests.select_related("unit"):
        if h.date > on:
            continue
        n, _guess = harvest_count(h, sizes)
        alive[h.species_id] = alive.get(h.species_id, 0) - n
        if h.unit.unit_type == "weight":
            s.out_kg += h.base_quantity
    total = sum(max(v, 0) for v in alive.values())
    for sp, n in alive.items():
        n = max(n, 0)
        if loose and total:      # deaths noted without a fish: shared by how many of each are left
            n = max(n - round(loose * n / total), 0)
        s.alive += n
        g = _size_on(sizes.get(sp, []), on)
        if g:
            s.biomass_kg += Decimal(n) * g / 1000
    s.weighed = bool(weighings)
    s.feed_kg = sum((f.kg for f in cycle.feedings.all() if f.date <= on), ZERO)
    return s


def _main_species(cycle):
    counts = {}
    for st in cycle.stockings.all():
        counts[st.species_id] = counts.get(st.species_id, 0) + (st.count or 0)
    return max(counts, key=counts.get) if counts else None


def previous(cycle):
    """(the cycle to compare with, whether it's the same pond) or (None, False)."""
    done = CultureCycle.objects.filter(business=cycle.business, status=CycleStatus.FINISHED, start_date__lt=cycle.start_date).select_related("pond")
    same = done.filter(pond=cycle.pond).order_by("-start_date", "-id").first()
    if same:
        return same, True
    fish = _main_species(cycle)
    if fish is None:
        return None, False
    for other in done.exclude(pond=cycle.pond).order_by("-start_date", "-id")[:12]:
        if _main_species(other) == fish:
            return other, False
    return None, False


@dataclass
class Line:
    key: str
    label: str
    now: str
    then: str
    tone: str = ""         # good | warn | critical | "" (just for reference)
    note: str = ""


@dataclass
class Comparison:
    cycle: CultureCycle
    other: CultureCycle
    same_pond: bool
    day: int               # the day both are compared on
    other_day: int         # the other's day used (its last day, if it ended sooner)
    lines: list = field(default_factory=list)
    other_summary: object = None

    @property
    def other_ended_sooner(self):
        return self.other_day < self.day


def _tone(now, then, higher_is_better, ok, bad):
    """good / warn / critical, by how far `now` is from `then` (as a fraction)."""
    if now is None or then is None or not then:
        return ""
    change = (Decimal(now) - Decimal(then)) / Decimal(then)
    if not higher_is_better:
        change = -change
    if change >= -ok:
        return "good"
    return "warn" if change >= -bad else "critical"


def compare(cycle, today=None):
    """None when there's nothing to compare with."""
    from apps.business.core.templatetags.business import num

    from .services import summarize

    other, same_pond = previous(cycle)
    if other is None:
        return None
    today = today or date.today()
    day = max(((cycle.ended_on or today) - cycle.start_date).days, 0)
    other_day = min(day, other.days)
    now, then = snapshot(cycle, day), snapshot(other, other_day)
    c = Comparison(cycle, other, same_pond, day, other_day, other_summary=summarize(other))

    def g(v):
        return f"{num(v)} g" if v is not None else "—"

    if now.size_g is not None or then.size_g is not None:
        c.lines.append(Line("size", _("Fish size"), g(now.size_g), g(then.size_g), _tone(now.size_g, then.size_g, True, Decimal("0.03"), Decimal("0.15"))))
    if now.survival is not None and then.survival is not None:
        pts = Decimal(now.survival - then.survival) / 100
        tone = "good" if pts >= Decimal("-0.02") else "warn" if pts >= Decimal("-0.08") else "critical"
        c.lines.append(Line("survival", _("Fish alive"), f"{now.survival}%", f"{then.survival}%", tone))
    if now.fcr is not None or then.fcr is not None:
        c.lines.append(Line("fcr", _("FCR so far"), num(now.fcr) if now.fcr else "—", num(then.fcr) if then.fcr else "—",
                            _tone(now.fcr, then.fcr, False, Decimal("0.05"), Decimal("0.2")), _("Lower is better.")))
    if now.feed_per_1000 is not None and then.feed_per_1000 is not None:
        c.lines.append(Line("feed", _("Feed per 1,000 fish released"), f"{num(now.feed_per_1000)} kg", f"{num(then.feed_per_1000)} kg"))
    return c if c.lines else None
