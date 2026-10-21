"""Whole-farm costs, shared out between the ponds.

Electricity, a guard's monthly salary, transport, repairs to a machine that
serves every pond… are paid for the farm, not for one pond. Left out, every
pond looks more profitable than it is, and the farm's profit doesn't match the
sum of its ponds'.

Each such cost is shared, on the day it was spent, between the cycles that
had fish in the water that day — by pond size (the default) or equally. A cost
on a day when no pond had fish isn't given to any pond.

What counts:
- farm costs typed in without a pond (Money → expense, "For: farm"),
- staff wages written without a pond,
- repairs and servicing — to the machine's own pond when it has one.

Not shared: equipment bought (a machine lasts years), loan interest (it's the
cost of the money, not of growing fish), pond leases and fingerlings, feed and
medicine (already charged to their own pond).
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.apps import apps
from django.db.models import Sum
from django.utils.translation import gettext as _

from .models import CultureCycle

ZERO = Decimal(0)
CENT = Decimal("0.01")


@dataclass
class Shares:
    """{cycle id: {what: amount}} and what no pond took."""

    by_cycle: dict = field(default_factory=lambda: defaultdict(lambda: defaultdict(Decimal)))
    unshared: Decimal = ZERO
    rule: str = "area"

    def total(self, cycle_id):
        return sum(self.by_cycle.get(cycle_id, {}).values(), ZERO).quantize(CENT)

    def lines(self, cycle_id):
        """[(what, amount)] for one cycle, biggest first."""
        got = self.by_cycle.get(cycle_id, {})
        return sorted(((k, v.quantize(CENT)) for k, v in got.items() if v.quantize(CENT)), key=lambda kv: -kv[1])


def _costs(business):
    """[(date, what, amount, pond id or None)] — every whole-farm running cost."""
    out = []
    if apps.is_installed("apps.business.finance"):
        from apps.business.finance.models import CategoryType, Scope, Transaction

        rows = (Transaction.objects.filter(business=business, cycle__isnull=True, category__scope=Scope.BUSINESS, category__type=CategoryType.EXPENSE)
                .values("date", "category__parent__name", "category__parent__name_bn", "category__name", "category__name_bn")
                .annotate(t=Sum("amount")))
        from django.utils.translation import get_language

        bn = (get_language() or "").startswith("bn")
        for r in rows:
            name, name_bn = ((r["category__parent__name"], r["category__parent__name_bn"]) if r["category__parent__name"]
                             else (r["category__name"], r["category__name_bn"]))
            out.append((r["date"], (name_bn if bn and name_bn else name) or _("Other costs"), r["t"], None))
    if apps.is_installed("apps.business.staff"):
        from apps.business.staff.models import Earning, EarningKind

        for r in Earning.objects.filter(business=business, cycle__isnull=True).values("date", "kind").annotate(t=Sum("amount")):
            out.append((r["date"], _("Staff wages"), -r["t"] if r["kind"] == EarningKind.DEDUCTION else r["t"], None))
    if apps.is_installed("apps.business.assets"):
        from apps.business.assets.models import Service

        for r in Service.objects.filter(business=business, cost__gt=0).values("date", "equipment__pond_id").annotate(t=Sum("cost")):
            out.append((r["date"], _("Repairs & servicing"), r["t"], r["equipment__pond_id"]))
    return out


def shares(business, today=None):
    """Every running and past cycle's share of the whole-farm costs."""
    from apps.business.core.models import ShareCosts

    rule = getattr(business, "share_costs", ShareCosts.AREA) or ShareCosts.AREA
    out = Shares(rule=rule)
    if rule == ShareCosts.NONE:
        return out
    today = today or date.today()
    cycles = list(CultureCycle.objects.filter(business=business).select_related("pond")
                  .values_list("pk", "pond_id", "start_date", "ended_on", "pond__area_decimal"))
    if not cycles:
        return out
    by_area = rule == ShareCosts.AREA and all(c[4] for c in cycles)   # one pond with no size → share equally

    def open_on(day, pond_id=None):
        return [c for c in cycles if c[2] <= day <= (c[3] or today) and (pond_id is None or c[1] == pond_id)]

    for day, what, amount, pond_id in _costs(business):
        if not amount:
            continue
        takers = (open_on(day, pond_id) if pond_id else []) or open_on(day)
        if not takers:
            out.unshared += amount
            continue
        weights = [Decimal(c[4]) if by_area else Decimal(1) for c in takers]
        whole = sum(weights)
        for c, w in zip(takers, weights):
            out.by_cycle[c[0]][what] += amount * w / whole
    return out


def cycle_share(cycle, cache=None):
    """One cycle's share. A page with many cycles passes a `cache` dict so the
    farm's costs are worked out once."""
    if cache is not None:
        if "shares" not in cache:
            cache["shares"] = shares(cycle.business)
        return cache["shares"]
    return shares(cycle.business)
