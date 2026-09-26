"""Cycle figures: fish in the pond, growth, feed, costs, sales and FCR."""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from .models import CultureCycle, CycleStatus, PondStatus

ZERO = Decimal(0)


@dataclass
class SpeciesRow:
    species: object
    stocked: int = 0
    died: int = 0
    harvested_count: int = 0
    harvested_kg: Decimal = ZERO
    stocked_kg: Decimal = ZERO
    avg_g: Decimal | None = None       # latest sample weighing
    weighed_on: date | None = None

    @property
    def alive(self):
        return max(self.stocked - self.died - self.harvested_count, 0)

    @property
    def survival(self):
        return round((self.stocked - self.died) * 100 / self.stocked) if self.stocked else None

    @property
    def biomass_kg(self):
        """Estimated fish still in the pond, by weight."""
        return (self.alive * self.avg_g / 1000).quantize(Decimal("0.1")) if (self.avg_g and self.alive) else None


@dataclass
class CycleSummary:
    cycle: CultureCycle
    species: list = field(default_factory=list)
    feed_kg: Decimal = ZERO
    feed_cost: Decimal = ZERO
    stocking_cost: Decimal = ZERO
    sales_net: Decimal = ZERO
    sales_gross: Decimal = ZERO
    harvest_kg: Decimal = ZERO
    stocked_kg: Decimal = ZERO

    @property
    def stocked(self):
        return sum(s.stocked for s in self.species)

    @property
    def alive(self):
        return sum(s.alive for s in self.species)

    @property
    def died(self):
        return sum(s.died for s in self.species)

    @property
    def biomass_kg(self):
        values = [s.biomass_kg for s in self.species if s.biomass_kg]
        return sum(values, ZERO) if values else None

    @property
    def cost(self):
        """Costs recorded so far (other expenses join in the income/expense phase)."""
        return self.stocking_cost + self.feed_cost

    @property
    def profit(self):
        return self.sales_net - self.cost

    @property
    def fcr(self):
        """Feed conversion ratio: kg of feed per kg of fish grown (lower is better)."""
        gained = self.harvest_kg - self.stocked_kg
        return (self.feed_kg / gained).quantize(Decimal("0.01")) if (self.feed_kg and gained > 0) else None


def summarize(cycle):
    from apps.business.feed.services import cost_per_kg

    rows = {}

    def row(sp):
        if sp.pk not in rows:
            rows[sp.pk] = SpeciesRow(species=sp)
        return rows[sp.pk]

    s = CycleSummary(cycle=cycle)
    for st in cycle.stockings.select_related("species"):
        r = row(st.species)
        r.stocked += st.count or 0
        r.stocked_kg += st.weight_kg or ZERO
        s.stocking_cost += st.cost
        s.stocked_kg += st.weight_kg or ZERO
    for m in cycle.mortalities.select_related("species"):
        if m.species:
            row(m.species).died += m.count
    for w in cycle.weighings.select_related("species", "unit").order_by("date", "id"):
        r = row(w.species)
        r.avg_g, r.weighed_on = w.avg_g, w.date
    for h in cycle.harvests.select_related("species"):
        r = row(h.species)
        r.harvested_count += h.fish_count or 0
        if h.unit.unit_type == "weight":
            r.harvested_kg += h.base_quantity
            s.harvest_kg += h.base_quantity
    prices = cost_per_kg(cycle.business)
    for f in cycle.feedings.all():
        s.feed_kg += f.kg
        s.feed_cost += f.kg * prices.get(f.product_id, ZERO)
    s.feed_cost = s.feed_cost.quantize(Decimal("0.01"))
    sales = cycle.sales.aggregate(net=Sum("net"), gross=Sum("gross"))
    s.sales_net, s.sales_gross = sales["net"] or ZERO, sales["gross"] or ZERO
    s.species = sorted(rows.values(), key=lambda r: r.species.order)
    return s


def running_cycle(pond):
    return pond.cycles.filter(status=CycleStatus.RUNNING).first()


@transaction.atomic
def start_cycle(cycle):
    cycle.save()
    pond = cycle.pond
    if pond.status != PondStatus.IN_USE:
        pond.status = PondStatus.IN_USE
        pond.save(update_fields=["status", "updated_at", "updated_by"])
    return cycle


@transaction.atomic
def finish_cycle(cycle, on):
    cycle.status, cycle.ended_on = CycleStatus.FINISHED, on
    cycle.save(update_fields=["status", "ended_on", "updated_at", "updated_by"])
    pond = cycle.pond
    pond.status = PondStatus.EMPTY
    pond.save(update_fields=["status", "updated_at", "updated_by"])


@transaction.atomic
def reopen_cycle(cycle):
    cycle.status, cycle.ended_on = CycleStatus.RUNNING, None
    cycle.save(update_fields=["status", "ended_on", "updated_at", "updated_by"])
    pond = cycle.pond
    pond.status = PondStatus.IN_USE
    pond.save(update_fields=["status", "updated_at", "updated_by"])
