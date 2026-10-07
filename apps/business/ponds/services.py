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
    moved_in: int = 0                  # fish brought in from another pond
    moved_out: int = 0                 # fish taken to another pond
    estimated: bool = False            # some harvested fish were counted by weight ÷ size
    mixed_died: int = 0                # this fish's share of deaths noted without a species

    @property
    def put_in(self):
        """Every fish that went into this pond: released here or brought from another pond."""
        return self.stocked + self.moved_in

    @property
    def alive(self):
        return max(self.put_in - self.died - self.mixed_died - self.harvested_count - self.moved_out, 0)

    @property
    def survival(self):
        return round(max(self.put_in - self.died - self.mixed_died, 0) * 100 / self.put_in) if self.put_in else None

    @property
    def biomass_kg(self):
        """Estimated fish still in the pond, by weight."""
        return (self.alive * self.avg_g / 1000).quantize(Decimal("0.1")) if (self.avg_g and self.alive) else None


def _size_on(points, day):
    """The fish's average weight (g) on `day`: the latest size known by then,
    else the first one known after it."""
    known = [g for d, g in points if d <= day]
    if known:
        return known[-1]
    return points[0][1] if points else None


def harvest_count(harvest, sizes):
    """How many fish a harvest took out, and whether that's an estimate.

    The number typed in wins. A harvest measured in pieces is its own count.
    One measured by weight is divided by the fish's average size at the time
    (from the sample weighings, or the fingerlings' size), so the fish left in
    the pond still go down when nobody counted.
    """
    if harvest.fish_count:
        return harvest.fish_count, False
    if harvest.unit.unit_type == "count":
        return int(harvest.base_quantity), False
    if harvest.unit.unit_type == "weight":
        g = _size_on(sizes.get(harvest.species_id, []), harvest.date)
        if g:
            return int((harvest.base_quantity * 1000 / g).to_integral_value()), True
    return 0, False


def _sizes(stockings, moves_in, weighings):
    """{species id: [(date, average g)]}, oldest first."""
    sizes = {}
    for x in list(stockings) + list(moves_in):
        if x.avg_g:
            sizes.setdefault(x.species_id, []).append((x.date, x.avg_g))
    for w in weighings:
        sizes.setdefault(w.species_id, []).append((w.date, w.avg_g))
    for pts in sizes.values():
        pts.sort(key=lambda p: p[0])
    return sizes


def count_fish(cycle):
    """{species id: SpeciesRow} — the fish put into a cycle, lost, taken out,
    and still in it (stockings, moves, deaths, harvests, weighings)."""
    rows = {}

    def row(sp):
        if sp.pk not in rows:
            rows[sp.pk] = SpeciesRow(species=sp)
        return rows[sp.pk]

    stockings = list(_rows(cycle, "stockings", "species"))
    moves_in = [m for m in _rows(cycle, "moves_in", "species", "cycle__pond") if not m.cycle.is_deleted]
    moves_out = [m for m in _rows(cycle, "moves_out", "species", "to_cycle__pond") if not m.to_cycle.is_deleted]
    weighings = sorted(_rows(cycle, "weighings", "species", "unit"), key=lambda w: (w.date, w.id))
    for st in stockings:
        r = row(st.species)
        r.stocked += st.count or 0
        r.stocked_kg += st.weight_kg or ZERO
    for m in moves_in:
        r = row(m.species)
        r.moved_in += m.count
        r.stocked_kg += m.weight_kg or ZERO
    for m in moves_out:
        row(m.species).moved_out += m.count
    mixed = 0
    for m in _rows(cycle, "mortalities", "species"):
        if m.species:
            row(m.species).died += m.count
        else:
            mixed += m.count
    for w in weighings:
        r = row(w.species)
        r.avg_g, r.weighed_on = w.avg_g, w.date
    sizes = _sizes(stockings, moves_in, weighings)
    for h in _rows(cycle, "harvests", "species", "unit"):
        r = row(h.species)
        n, guessed = harvest_count(h, sizes)
        r.harvested_count += n
        r.estimated = r.estimated or guessed
        if h.unit.unit_type == "weight":
            r.harvested_kg += h.base_quantity
    if mixed:   # "Mixed / not sure": shared out by how many of each fish are left
        alive = {pk: r.alive for pk, r in rows.items()}
        total = sum(alive.values())
        for pk, r in rows.items():
            if total:
                r.mixed_died = min(round(mixed * alive[pk] / total), alive[pk])
    return rows


@dataclass
class CycleSummary:
    cycle: CultureCycle
    species: list = field(default_factory=list)
    feed_kg: Decimal = ZERO
    feed_cost: Decimal = ZERO
    other_cost: Decimal = ZERO      # labour and other costs typed in against this pond
    care_cost: Decimal = ZERO       # lime, fertilizer, medicine put into the pond
    wage_cost: Decimal = ZERO       # staff wages written against this pond
    lease_cost: Decimal = ZERO      # this cycle's share of a leased pond's rent, by days
    stocking_cost: Decimal = ZERO
    moved_in_value: Decimal = ZERO  # fish brought from another pond, at what they'd cost there
    moved_out_value: Decimal = ZERO # fish taken to another pond: their cost goes with them
    moved_out_kg: Decimal = ZERO
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
        """Everything this season has cost: fingerlings, feed eaten, lime and
        medicine, and any labour or other expense recorded against this pond."""
        return (self.stocking_cost + self.moved_in_value + self.feed_cost + self.care_cost + self.wage_cost
                + self.lease_cost + self.other_cost)

    @property
    def earned(self):
        """Sales, plus the value of fish moved on to another pond."""
        return self.sales_net + self.moved_out_value

    @property
    def profit(self):
        return self.earned - self.cost

    @property
    def moved_in(self):
        return sum(s.moved_in for s in self.species)

    @property
    def moved_out(self):
        return sum(s.moved_out for s in self.species)

    @property
    def estimated(self):
        return any(s.estimated for s in self.species)

    @property
    def fcr(self):
        """Feed conversion ratio: kg of feed per kg of fish grown (lower is better).
        Fish moved on to another pond grew here too."""
        gained = self.harvest_kg + self.moved_out_kg - self.stocked_kg
        return (self.feed_kg / gained).quantize(Decimal("0.01")) if (self.feed_kg and gained > 0) else None


def _rows(cycle, name, *related):
    """The cycle's related rows — already in memory when the caller prefetched
    them (a report does), otherwise fetched for this one cycle."""
    if name in getattr(cycle, "_prefetched_objects_cache", {}):
        return getattr(cycle, name).all()
    return getattr(cycle, name).select_related(*related)


def summarize(cycle, prices=None, cache=None):
    from apps.business.feed.services import cost_per_kg

    rows = count_fish(cycle)
    s = CycleSummary(cycle=cycle)
    for st in _rows(cycle, "stockings", "species"):
        s.stocking_cost += st.cost
        s.stocked_kg += st.weight_kg or ZERO
    for m in _rows(cycle, "moves_in", "cycle"):
        if not m.cycle.is_deleted:
            s.moved_in_value += m.value
            s.stocked_kg += m.weight_kg or ZERO
    for m in _rows(cycle, "moves_out", "to_cycle"):
        if not m.to_cycle.is_deleted:
            s.moved_out_value += m.value
            s.moved_out_kg += m.weight_kg or ZERO
    s.harvest_kg = sum((r.harvested_kg for r in rows.values()), ZERO)
    if prices is None:
        prices = cost_per_kg(cycle.business)
    for f in cycle.feedings.all():
        s.feed_kg += f.kg
        s.feed_cost += f.kg * prices.get(f.product_id, ZERO)
    s.feed_cost = s.feed_cost.quantize(Decimal("0.01"))
    s.care_cost = sum((t.cost for t in _rows(cycle, "treatments")), ZERO)
    s.lease_cost = cycle.pond.lease_share(cycle.start_date, cycle.ended_on or date.today())
    if apps.is_installed("apps.business.staff"):
        from apps.business.staff.services import cycle_wages

        s.wage_cost = cycle_wages(cycle)
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


@dataclass
class LeaseStatus:
    pond: object
    total: Decimal
    paid: Decimal
    payments: list
    used_share: Decimal         # the part of the lease used up by today, by days

    @property
    def due(self):
        return max(self.total - self.paid, ZERO)

    @property
    def paid_pct(self):
        return min(int(self.paid * 100 / self.total), 100) if self.total else 0

    @property
    def behind(self):
        """Paid less than the share of the lease already used: worth settling."""
        return max(self.used_share - self.paid, ZERO)


def lease_status(pond, today=None):
    today = today or date.today()
    payments = list(pond.lease_payments.select_related("account"))
    paid = sum((p.amount for p in payments), ZERO)
    used = pond.lease_share(pond.lease_start, min(today, pond.lease_end)) if pond.lease_per_day else ZERO
    return LeaseStatus(pond, pond.lease_amount or ZERO, paid, payments, used)


def withdrawal(cycle, today=None):
    """The medicine whose waiting period is still running in this cycle (the
    one that ends last), or None. Fish shouldn't be sold before `safe_from`."""
    today = today or date.today()
    from .models import Treatment

    latest = None
    for t in Treatment.objects.filter(cycle=cycle, withdrawal_days__gt=0):
        if t.safe_from > today and (latest is None or t.safe_from > latest.safe_from):
            latest = t
    return latest


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
    return Projection(fish_kg=fish_kg, cost=summary.cost, sold=summary.earned,
                      produced_kg=summary.harvest_kg + summary.moved_out_kg + (fish_kg or ZERO),
                      usual_price=usual_price_per_kg(cycle.business, species_ids, today) if species_ids else None)


# ── Today's pond work ───────────────────────────────────────────────────────

WEIGH_EVERY_DAYS = 21     # a sample weighing this old is due again
RECENT_DAYS = 3           # water tests and deaths this recent count as "now"
FIRST_WEIGH_DAYS = 14     # a new cycle's first weighing
HARVEST_SOON_DAYS = 7
LEASE_SOON_DAYS = 30


@dataclass
class Task:
    kind: str        # water | deaths | feed | weigh | harvest | lease | medicine
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

    if running:
        tasks += _water_tasks(business, running, today) + _death_tasks(business, running, today)

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
                              detail, reverse("business:cycle_detail", args=[c.pk]) + "?tab=harvest", _("View")))

    for c in running:
        last = c.last_weighed
        age = (today - (last or c.start_date)).days
        if (last and age >= WEIGH_EVERY_DAYS) or (not last and age >= FIRST_WEIGH_DAYS):
            detail = (ngettext("Last weighed %(n)s day ago", "Last weighed %(n)s days ago", age) % {"n": age} if last
                      else ngettext("Not weighed yet · day %(n)s of the cycle", "Not weighed yet · day %(n)s of the cycle", age) % {"n": age})
            tasks.append(Task("weigh", "info", _("Weigh a sample in %(pond)s") % {"pond": c.pond.name},
                              detail, reverse("business:cycle_detail", args=[c.pk]) + "?add=weighing", _("Weigh")))

    for c in running:
        wait = withdrawal(c, today)
        if wait:
            tasks.append(Task("medicine", "warn", _("Don't sell fish from %(pond)s yet") % {"pond": c.pond.name},
                              _("%(product)s · waiting period ends %(date)s") % {"product": wait.product, "date": date_format(wait.safe_from, "j M")},
                              reverse("business:cycle_detail", args=[c.pk]) + "?tab=water", _("View")))

    for pond in Pond.objects.filter(business=business, lease_end__isnull=False,
                                    lease_end__gte=today, lease_end__lte=today + timedelta(days=LEASE_SOON_DAYS)):
        due = lease_status(pond, today).due
        detail = _("Ends on %(date)s") % {"date": date_format(pond.lease_end, "j M Y")}
        if due:   # no amount here: everyone on the farm sees today's tasks
            detail += " · " + _("not fully paid yet")
        tasks.append(Task("lease", "critical" if due else "warn", _("Lease of %(pond)s ends soon") % {"pond": pond.name},
                          detail, reverse("business:pond_detail", args=[pond.pk]), _("View")))

    order = {"critical": 0, "warn": 1, "info": 2}
    tasks.sort(key=lambda t: order[t.tone])
    return tasks


def _water_tasks(business, running, today):
    """The latest recent water test of each running pond, if it broke a limit."""
    from django.urls import reverse
    from django.utils.translation import gettext as _

    from .models import PondAlerts, WaterTest

    limits = PondAlerts.for_business(business)
    latest = {}
    for t in WaterTest.objects.filter(business=business, cycle__in=running, date__gte=today - timedelta(days=RECENT_DAYS)).order_by("date", "id"):
        latest[t.cycle_id] = t
    out = []
    for c in running:
        test = latest.get(c.pk)
        found = test.problems(limits) if test else []
        if found:
            out.append(Task("water", "critical", _("Water problem in %(pond)s") % {"pond": c.pond.name},
                            " · ".join(f.what for f in found), reverse("business:cycle_detail", args=[c.pk]) + "?tab=water", _("View")))
    return out


def _death_tasks(business, running, today):
    """Ponds where more fish died in the last few days than the farm's warning level."""
    from django.urls import reverse
    from django.utils.translation import gettext as _, ngettext

    from .models import Mortality, PondAlerts

    limits = PondAlerts.for_business(business)
    since = today - timedelta(days=RECENT_DAYS)
    recent = dict(Mortality.objects.filter(business=business, cycle__in=running, date__gte=since)
                  .values_list("cycle_id").annotate(n=Sum("count")))
    out = []
    for c in running:
        now = recent.get(c.pk) or 0
        if not now:
            continue
        before = sum(r.alive for r in count_fish(c).values()) + now   # fish in the pond before these deaths
        if before > 0 and Decimal(now) * 100 / before > limits.deaths_pct:
            pct = (Decimal(now) * 100 / before).quantize(Decimal("0.1"))
            out.append(Task("deaths", "critical", _("Many fish dying in %(pond)s") % {"pond": c.pond.name},
                            ngettext("%(n)s fish in the last %(days)s days (%(pct)s%% of the pond). Test the water and check for disease.",
                                     "%(n)s fish in the last %(days)s days (%(pct)s%% of the pond). Test the water and check for disease.", now)
                            % {"n": now, "days": RECENT_DAYS, "pct": pct},
                            reverse("business:cycle_detail", args=[c.pk]) + "?tab=growth", _("View")))
    return out


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
