"""What the farm is worth today: everything it owns, less everything it owes.

Every figure comes from records the farm already keeps, valued the careful way
a bank would: fish at what they've cost to raise (their price at recent sale
rates is shown beside it), feed and supplies at the price paid, machines at
the price paid. Nothing here is typed in.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.apps import apps
from django.urls import reverse
from django.utils.translation import gettext as _, ngettext

ZERO = Decimal(0)


def _installed(label):
    return apps.is_installed(f"apps.business.{label}")


@dataclass
class Line:
    key: str
    label: str
    amount: Decimal
    detail: str = ""
    url: str = ""


@dataclass
class Worth:
    owns: list = field(default_factory=list)
    owes: list = field(default_factory=list)
    fish_at_price: Decimal | None = None     # fish in the ponds at recent sale prices

    @property
    def total_owns(self):
        return sum((l.amount for l in self.owns), ZERO)

    @property
    def total_owes(self):
        return sum((l.amount for l in self.owes), ZERO)

    @property
    def net(self):
        return self.total_owns - self.total_owes

    @property
    def fish_gain(self):
        """How much more the fish would bring at today's prices than they've cost."""
        fish = next((l.amount for l in self.owns if l.key == "fish"), ZERO)
        return self.fish_at_price - fish if self.fish_at_price is not None else None


def farm_worth(business, today=None):
    from apps.business.core.templatetags.business import num

    today = today or date.today()
    w = Worth()

    def own(key, label, amount, detail="", url=""):
        if amount:
            w.owns.append(Line(key, label, Decimal(amount).quantize(Decimal("1")), detail, url))

    def owe(key, label, amount, detail="", url=""):
        if amount:
            w.owes.append(Line(key, label, Decimal(amount).quantize(Decimal("1")), detail, url))

    if _installed("finance"):
        from apps.business.finance.models import Account
        from apps.business.finance.services import balances

        found = balances(business)
        accounts = list(Account.objects.filter(business=business))
        cash = sum((found.get(a.pk, a.opening_balance) for a in accounts), ZERO)
        detail = ngettext("%(n)s account", "%(n)s accounts", len(accounts)) % {"n": len(accounts)}
        if cash >= 0:
            own("cash", _("Cash, bank and mobile money"), cash, detail, reverse("business:accounts"))
        else:   # more spending recorded than money: usually an opening balance not filled in
            owe("cash", _("Accounts below zero"), -cash, _("More money recorded going out than coming in. Check each account's starting balance."),
                reverse("business:accounts"))

    _fish(business, w, own, today)

    if _installed("feed"):
        from apps.business.feed.services import stock

        rows = [r for r in stock(business) if r.value]
        kg = sum((max(r.left_kg, ZERO) for r in rows), ZERO)
        own("feed", _("Feed in store"), sum((r.value for r in rows), ZERO), _("%(kg)s kg, at the price paid") % {"kg": num(kg)},
            reverse("business:feed_stock"))
    if _installed("supplies"):
        from apps.business.supplies.services import stock as supply_stock

        own("supplies", _("Lime, medicine and supplies in store"), sum((s.value or ZERO for s in supply_stock(business)), ZERO),
            _("at the price paid"), reverse("business:supplies"))
    if _installed("assets"):
        from apps.business.assets.models import Condition, Equipment

        machines = list(Equipment.objects.filter(business=business).exclude(condition=Condition.OUT))
        own("equipment", _("Equipment"), sum((m.cost for m in machines), ZERO),
            ngettext("%(n)s machine or net, at the price paid", "%(n)s machines and nets, at the price paid", len(machines)) % {"n": len(machines)},
            reverse("business:equipment"))
    if _installed("credit"):
        from apps.business.credit.services import totals

        t = totals(business)
        own("receivable", _("Baki: buyers owe you"), t["receivable"],
            ngettext("%(n)s person", "%(n)s people", t["receivable_count"]) % {"n": t["receivable_count"]}, reverse("business:dues"))
        owe("payable", _("Baki: you owe suppliers"), t["payable"],
            ngettext("%(n)s person", "%(n)s people", t["payable_count"]) % {"n": t["payable_count"]}, reverse("business:dues"))
    if _installed("staff"):
        from apps.business.staff.services import balances as worker_balances

        found = list(worker_balances(business).values())
        owe("wages", _("Wages owed to workers"), sum((v for v in found if v > 0), ZERO), "", reverse("business:staff"))
        own("advances", _("Advances with workers"), -sum((v for v in found if v < 0), ZERO), _("taken off their later pay"),
            reverse("business:staff"))
    if _installed("loans"):
        from apps.business.loans.services import overview

        o = overview(business, today)
        owe("loans", _("Loans still to repay"), o["outstanding"],
            ngettext("%(n)s loan", "%(n)s loans", o["count"]) % {"n": o["count"]}, reverse("business:loans"))
    _lease(business, owe, today)
    return w


def _fish(business, w, own, today):
    """Fish in the running ponds: at what they've cost so far (less what they've
    already brought in), and — beside it — at recent sale prices."""
    from apps.business.ponds.forecast import _price
    from apps.business.ponds.models import CultureCycle, CycleStatus
    from apps.business.ponds.services import summarize

    at_cost = ZERO
    at_price = ZERO
    priced = False
    kg = ZERO
    cycles = list(CultureCycle.objects.filter(business=business, status=CycleStatus.RUNNING).select_related("pond"))
    prices = {}
    for c in cycles:
        s = summarize(c)
        at_cost += max(s.cost - s.earned, ZERO)
        for r in s.species:
            if not r.biomass_kg:
                continue
            kg += r.biomass_kg
            if r.species.pk not in prices:
                prices[r.species.pk] = _price(business, r.species.pk, today)
            if prices[r.species.pk]:
                at_price += r.biomass_kg * prices[r.species.pk]
                priced = True
    if cycles:
        from apps.business.core.templatetags.business import num

        detail = ngettext("%(n)s pond", "%(n)s ponds", len(cycles)) % {"n": len(cycles)}
        if kg:
            detail += " · " + _("≈ %(kg)s kg of fish") % {"kg": num(kg.quantize(Decimal("1")))}
        own("fish", _("Fish in the ponds"), at_cost, detail + " · " + _("at what they've cost so far"), reverse("business:harvest_forecast"))
        if priced:
            w.fish_at_price = at_price.quantize(Decimal("1"))


def _lease(business, owe, today):
    """Leased ponds used for longer than they've been paid for."""
    from apps.business.ponds.models import Ownership, Pond
    from apps.business.ponds.services import lease_status

    behind = ZERO
    ponds = 0
    for pond in Pond.objects.filter(business=business, ownership=Ownership.LEASED, lease_start__isnull=False, lease_end__isnull=False):
        b = lease_status(pond, today).behind
        if b > 0:
            behind += b
            ponds += 1
    owe("lease", _("Pond lease used but not paid"), behind,
        ngettext("%(n)s pond", "%(n)s ponds", ponds) % {"n": ponds}, reverse("business:ponds") + "?show=leased")
