"""Cycle figures: fish in the pond, growth, feed, costs, sales and FCR."""
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.apps import apps
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
    other_cost: Decimal = ZERO      # labour, medicine… recorded against this pond
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
        """Everything this season has cost: fingerlings, feed eaten, and any
        labour, medicine or other expense recorded against this pond."""
        return self.stocking_cost + self.feed_cost + self.other_cost

    @property
    def profit(self):
        return self.sales_net - self.cost

    @property
    def fcr(self):
        """Feed conversion ratio: kg of feed per kg of fish grown (lower is better)."""
        gained = self.harvest_kg - self.stocked_kg
        return (self.feed_kg / gained).quantize(Decimal("0.01")) if (self.feed_kg and gained > 0) else None


def _rows(cycle, name, *related):
    """The cycle's related rows — already in memory when the caller prefetched
    them (a report does), otherwise fetched for this one cycle."""
    if name in getattr(cycle, "_prefetched_objects_cache", {}):
        return getattr(cycle, name).all()
    return getattr(cycle, name).select_related(*related)


def summarize(cycle, prices=None, cache=None):
    from apps.business.feed.services import cost_per_kg

    rows = {}

    def row(sp):
        if sp.pk not in rows:
            rows[sp.pk] = SpeciesRow(species=sp)
        return rows[sp.pk]

    s = CycleSummary(cycle=cycle)
    for st in _rows(cycle, "stockings", "species"):
        r = row(st.species)
        r.stocked += st.count or 0
        r.stocked_kg += st.weight_kg or ZERO
        s.stocking_cost += st.cost
        s.stocked_kg += st.weight_kg or ZERO
    for m in _rows(cycle, "mortalities", "species"):
        if m.species:
            row(m.species).died += m.count
    for w in sorted(_rows(cycle, "weighings", "species", "unit"), key=lambda w: (w.date, w.id)):
        r = row(w.species)
        r.avg_g, r.weighed_on = w.avg_g, w.date
    for h in _rows(cycle, "harvests", "species", "unit"):
        r = row(h.species)
        r.harvested_count += h.fish_count or 0
        if h.unit.unit_type == "weight":
            r.harvested_kg += h.base_quantity
            s.harvest_kg += h.base_quantity
    if prices is None:
        prices = cost_per_kg(cycle.business)
    for f in cycle.feedings.all():
        s.feed_kg += f.kg
        s.feed_cost += f.kg * prices.get(f.product_id, ZERO)
    s.feed_cost = s.feed_cost.quantize(Decimal("0.01"))
    if apps.is_installed("apps.business.finance"):
        from apps.business.finance.services import cycle_costs

        s.other_cost = cycle_costs(cycle, cache=cache)
    if "sales" in getattr(cycle, "_prefetched_objects_cache", {}):
        sold = list(cycle.sales.all())
        s.sales_net = sum((x.net for x in sold), ZERO)
        s.sales_gross = sum((x.gross for x in sold), ZERO)
    else:
        sales = cycle.sales.aggregate(net=Sum("net"), gross=Sum("gross"))
        s.sales_net, s.sales_gross = sales["net"] or ZERO, sales["gross"] or ZERO
    s.species = sorted(rows.values(), key=lambda r: r.species.order)
    return s


PRICE_DAYS = 90   # how far back "the price you usually get" looks


def usual_price_per_kg(business, species_ids, today=None):
    """What these fish have fetched per kg lately, after market deductions.

    Each sale's deductions are shared across its lines, so this is money in
    hand per kg, not the rate on the memo.
    """
    from datetime import timedelta

    if not apps.is_installed("apps.business.sales"):
        return None
    from apps.business.sales.models import FishSaleLine

    since = (today or date.today()) - timedelta(days=PRICE_DAYS)
    money = kg = ZERO
    lines = (FishSaleLine.objects.filter(business=business, sale__is_deleted=False, sale__date__gte=since,
                                         species_id__in=species_ids, unit__unit_type="weight")
             .select_related("sale"))
    for line in lines:
        share = (line.sale.net / line.sale.gross) if line.sale.gross else Decimal(1)
        money += line.amount * share
        kg += line.base_quantity
    return (money / kg).quantize(Decimal("0.01")) if kg else None


@dataclass
class Projection:
    """What the fish still in the pond could bring in, against what the cycle has cost."""

    fish_kg: Decimal | None       # estimated, from the latest sample weighing
    cost: Decimal
    sold: Decimal                 # already sold from this cycle, net
    produced_kg: Decimal          # harvested so far + still in the pond
    usual_price: Decimal | None   # per kg, from recent sales

    @property
    def to_cover(self):
        """Costs not yet paid back by sales."""
        return max(self.cost - self.sold, ZERO)

    @property
    def break_even(self):
        """The price per kg the fish in the pond must fetch to cover the whole cycle."""
        if not self.fish_kg:
            return None
        return (self.to_cover / self.fish_kg).quantize(Decimal("0.01"))

    @property
    def cost_per_kg(self):
        """What each kg of fish grown has cost."""
        return (self.cost / self.produced_kg).quantize(Decimal("0.01")) if self.produced_kg else None


def projection(summary, today=None):
    cycle = summary.cycle
    fish_kg = summary.biomass_kg
    species_ids = [r.species.pk for r in summary.species]
    return Projection(fish_kg=fish_kg, cost=summary.cost, sold=summary.sales_net,
                      produced_kg=summary.harvest_kg + (fish_kg or ZERO),
                      usual_price=usual_price_per_kg(cycle.business, species_ids, today) if species_ids else None)


# ── Today's pond work ───────────────────────────────────────────────────────

WEIGH_EVERY_DAYS = 21     # a sample weighing this old is due again
FIRST_WEIGH_DAYS = 14     # a new cycle's first weighing
HARVEST_SOON_DAYS = 7
LEASE_SOON_DAYS = 30


@dataclass
class Task:
    kind: str        # feed | weigh | harvest | lease
    tone: str        # warn | info | critical
    title: str
    detail: str
    url: str
    action: str


def farm_tasks(business, today=None):
    """What needs doing on the ponds today, most urgent first."""
    from django.db.models import Max
    from django.urls import reverse
    from django.utils.formats import date_format
    from django.utils.translation import gettext as _, ngettext

    from .models import Pond

    today = today or date.today()
    tasks = []
    running = list(CultureCycle.objects.filter(business=business, status=CycleStatus.RUNNING)
                   .select_related("pond").annotate(last_weighed=Max("weighings__date"))
                   .order_by("pond__order", "pond__name"))

    if apps.is_installed("apps.business.feed") and running:
        from apps.business.feed.models import FeedUsage

        fed = set(FeedUsage.objects.filter(business=business, date=today, cycle__in=running).values_list("cycle_id", flat=True))
        hungry = [c for c in running if c.pk not in fed and c.start_date <= today]
        if hungry:
            names = ", ".join(c.pond.name for c in hungry[:3])
            if len(hungry) > 3:
                names = _("%(names)s and %(n)s more") % {"names": names, "n": len(hungry) - 3}
            tasks.append(Task("feed", "warn", ngettext("%(n)s pond has no feeding recorded today", "%(n)s ponds have no feeding recorded today", len(hungry)) % {"n": len(hungry)},
                              names, reverse("business:feed_usage_bulk"), _("Record feeding")))

    for c in running:
        if c.expected_harvest and c.expected_harvest <= today + timedelta(days=HARVEST_SOON_DAYS):
            days = (c.expected_harvest - today).days
            if days < 0:
                detail = ngettext("Planned date passed %(n)s day ago", "Planned date passed %(n)s days ago", -days) % {"n": -days}
            elif days == 0:
                detail = _("Planned for today")
            else:
                detail = ngettext("Planned in %(n)s day", "Planned in %(n)s days", days) % {"n": days}
            tasks.append(Task("harvest", "critical" if days < 0 else "info", _("Harvest %(pond)s") % {"pond": c.pond.name},
                              detail, reverse("business:cycle_detail", args=[c.pk]) + "?tab=harvest", _("Open")))

    for c in running:
        last = c.last_weighed
        age = (today - (last or c.start_date)).days
        if (last and age >= WEIGH_EVERY_DAYS) or (not last and age >= FIRST_WEIGH_DAYS):
            detail = (ngettext("Last weighed %(n)s day ago", "Last weighed %(n)s days ago", age) % {"n": age} if last
                      else ngettext("Not weighed yet · day %(n)s of the cycle", "Not weighed yet · day %(n)s of the cycle", age) % {"n": age})
            tasks.append(Task("weigh", "info", _("Weigh a sample in %(pond)s") % {"pond": c.pond.name},
                              detail, reverse("business:cycle_detail", args=[c.pk]) + "?add=weighing", _("Weigh")))

    for pond in Pond.objects.filter(business=business, lease_end__isnull=False,
                                    lease_end__gte=today, lease_end__lte=today + timedelta(days=LEASE_SOON_DAYS)):
        tasks.append(Task("lease", "warn", _("Lease of %(pond)s ends soon") % {"pond": pond.name},
                          _("Ends on %(date)s") % {"date": date_format(pond.lease_end, "j M Y")},
                          reverse("business:pond_detail", args=[pond.pk]), _("Open")))

    order = {"critical": 0, "warn": 1, "info": 2}
    tasks.sort(key=lambda t: order[t.tone])
    return tasks


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
