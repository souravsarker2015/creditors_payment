"""The figures behind the dashboard and the reports.

Everything is read from the records themselves — sales, feed, ponds, baki and
the money pages — so a report never disagrees with the page it came from.
Each function returns plain rows that a template can show and a CSV can save.
"""
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.apps import apps
from django.db.models import Count, F, Q, Sum
from django.urls import reverse
from django.utils.translation import gettext as _

ZERO = Decimal(0)


def _installed(label):
    return apps.is_installed(f"apps.business.{label}")


def month_start(day):
    return day.replace(day=1)


def month_end(day):
    return day.replace(day=monthrange(day.year, day.month)[1])


def add_months(day, n):
    total = day.year * 12 + day.month - 1 + n
    return date(total // 12, total % 12 + 1, 1)


# ── Dashboard ───────────────────────────────────────────────────────────────

@dataclass
class Row:
    """One line of a ranked list or a chart."""

    label: str
    value: Decimal = ZERO
    extra: str = ""
    url: str = ""
    pk: int = 0


def sales_between(business, start, end):
    from apps.business.sales.models import FishSale

    return FishSale.objects.filter(business=business, date__gte=start, date__lte=end)


def _sale_kg(sales):
    from apps.business.sales.models import FishSaleLine

    return FishSaleLine.objects.filter(sale__in=sales.values("pk"), sale__is_deleted=False, unit__unit_type="weight"
                                       ).aggregate(kg=Sum("base_quantity"))["kg"] or ZERO


def headline(business, start, end, cache=None):
    """Sales, costs and profit for one period, with kg sold."""
    from apps.business.finance.services import statement

    s = statement(business, start, end, cache=cache)
    sales = sales_between(business, start, end) if _installed("sales") else None
    fish = next((l.amount for l in s.income if l.key == "sales"), ZERO)
    return {
        "income": s.total_income, "expense": s.total_expense, "profit": s.profit, "margin": s.margin,
        "fish": fish, "other_income": s.total_income - fish,
        "kg": _sale_kg(sales) if sales is not None else ZERO,
        "sale_count": sales.count() if sales is not None else 0,
        "statement": s,
    }


def monthly_trend(business, months=6, today=None, cache=None):
    """Sales against costs for the last few months, for the bar chart."""
    from apps.business.finance.services import statement

    today = today or date.today()
    rows = []
    for i in range(months - 1, -1, -1):
        m = add_months(month_start(today), -i)
        s = statement(business, m, min(month_end(m), today), cache=cache)
        rows.append({"month": m, "label": f"{m:%b}", "income": s.total_income, "expense": s.total_expense, "profit": s.profit})
    return rows


def sales_by(business, start, end, field_name):
    """Sales split by species, market or buyer."""
    from apps.business.sales.models import FishSale, FishSaleLine

    sales = sales_between(business, start, end)
    if field_name == "species":
        # Lines are gross; a sale's deductions belong to the whole memo, so
        # each fish carries its share of them and the total matches the net.
        rows = (FishSaleLine.objects.filter(sale__in=sales.values("pk"), sale__is_deleted=False)
                .values("species__name", "species__name_bn", "species_id")
                .annotate(total=Sum("amount"), kg=Sum("base_quantity", filter=Q(unit__unit_type="weight")))
                .order_by("-total"))
        gross = sum((r["total"] or ZERO for r in rows), ZERO)
        net = sales.aggregate(n=Sum("net"))["n"] or ZERO
        share = (net / gross) if gross else Decimal(1)
        return [Row(_display(r["species__name"], r["species__name_bn"]),
                    ((r["total"] or ZERO) * share).quantize(Decimal("0.01")),
                    _kg_text(r["kg"]), pk=r["species_id"]) for r in rows]
    lookup = {"market": ("market__name", "market_id"), "buyer": ("buyer__name", "buyer_id")}[field_name]
    rows = (sales.exclude(**{f"{lookup[1]}__isnull": True}).values(lookup[0], lookup[1])
            .annotate(total=Sum("net"), n=Count("id")).order_by("-total"))
    out = []
    for r in rows:
        url = reverse("business:party_statement", args=[r[lookup[1]]]) if field_name == "buyer" and _installed("credit") else ""
        out.append(Row(r[lookup[0]], r["total"] or ZERO,
                       _("%(n)s sales") % {"n": r["n"]} if r["n"] != 1 else _("1 sale"), url, r[lookup[1]]))
    return out


def _display(name, name_bn):
    from django.utils.translation import get_language

    return name_bn if (get_language() or "").startswith("bn") and name_bn else name


def _kg_text(kg):
    from apps.business.core.templatetags.business import num

    return _("%(kg)s kg") % {"kg": num(kg)} if kg else ""


def expense_breakdown(business, start, end, scope="business", cache=None):
    """Costs by main category, biggest first — for the donut."""
    from apps.business.finance.services import statement

    s = statement(business, start, end, scope=scope, cache=cache)
    return [Row(l.label, l.amount, "", l.url) for l in s.expense]


# ── Pond and cycle reports ──────────────────────────────────────────────────

@dataclass
class CycleRow:
    cycle: object
    pond: object
    summary: object
    days: int = 0

    @property
    def profit(self):
        return self.summary.profit

    @property
    def per_decimal(self):
        area = self.pond.area_decimal
        return (self.profit / area).quantize(Decimal("1")) if area else None


def cycle_rows(business, start=None, end=None, pond=None, running_only=False):
    """Every season with its own cost, sales, FCR and result."""
    from apps.business.feed.services import cost_per_kg
    from apps.business.ponds.models import CultureCycle, CycleStatus
    from apps.business.ponds.services import summarize

    # One query per kind of record for the whole page, not per season.
    qs = (CultureCycle.objects.filter(business=business).select_related("pond")
          .prefetch_related("stockings__species", "treatments", "moves_in__species", "moves_in__cycle", "moves_out__species", "moves_out__to_cycle", "staff_earnings", "mortalities__species", "weighings__species", "weighings__unit",
                            "harvests__species", "harvests__unit", "feedings", "sales"))
    if pond is not None:
        qs = qs.filter(pond=pond)
    if running_only:
        qs = qs.filter(status=CycleStatus.RUNNING)
    if start:
        qs = qs.filter(Q(ended_on__isnull=True) | Q(ended_on__gte=start))
    if end:
        qs = qs.filter(start_date__lte=end)
    today = date.today()
    prices = cost_per_kg(business)   # once for the whole page, not per season
    cache = {}
    rows = []
    for cycle in qs:
        s = summarize(cycle, prices=prices, cache=cache)
        last = cycle.ended_on or today
        rows.append(CycleRow(cycle, cycle.pond, s, (last - cycle.start_date).days))
    rows.sort(key=lambda r: -r.profit)
    return rows


def pond_rows(business, start=None, end=None):
    """Each pond added up across its seasons in the period."""
    from apps.business.ponds.models import Pond

    by_pond = {}
    for row in cycle_rows(business, start, end):
        got = by_pond.setdefault(row.pond.pk, {"pond": row.pond, "sales": ZERO, "cost": ZERO, "cycles": 0, "moved": ZERO,
                                               "feed_kg": ZERO, "harvest_kg": ZERO, "stocked_kg": ZERO, "moved_kg": ZERO})
        got["sales"] += row.summary.sales_net
        got["moved"] += row.summary.moved_out_value     # fish passed on to another pond, at their value
        got["moved_kg"] += row.summary.moved_out_kg
        got["cost"] += row.summary.cost
        got["cycles"] += 1
        got["feed_kg"] += row.summary.feed_kg
        got["harvest_kg"] += row.summary.harvest_kg
        got["stocked_kg"] += row.summary.stocked_kg
    for pond in Pond.objects.filter(business=business):
        by_pond.setdefault(pond.pk, {"pond": pond, "sales": ZERO, "cost": ZERO, "cycles": 0, "feed_kg": ZERO, "harvest_kg": ZERO,
                                     "stocked_kg": ZERO, "moved": ZERO, "moved_kg": ZERO})
    rows = list(by_pond.values())
    for r in rows:
        r["profit"] = r["sales"] + r["moved"] - r["cost"]
        area = r["pond"].area_decimal
        r["per_decimal"] = (r["profit"] / area).quantize(Decimal("1")) if area else None
        gained = r["harvest_kg"] + r["moved_kg"] - r["stocked_kg"]   # same rule as a cycle's own FCR
        r["fcr"] = (r["feed_kg"] / gained).quantize(Decimal("0.01")) if (r["feed_kg"] and gained > 0) else None
    rows.sort(key=lambda r: -r["profit"])
    return rows


def fingerling_rows(business, start, end):
    """Each hatchery or seller of fingerlings released in the period: how many,
    what they cost, and how they did — the share still alive (deaths recorded)
    and how fast they grew. When one pond got fish of the same kind from two
    sellers, both share that pond's result."""
    from apps.business.ponds.models import Stocking
    from apps.business.ponds.services import count_fish

    stockings = list(Stocking.objects.filter(business=business, cycle__is_deleted=False, date__gte=start, date__lte=end)
                     .select_related("supplier", "species", "cycle"))
    counts = {}
    rows = {}
    for st in stockings:
        if st.cycle_id not in counts:
            counts[st.cycle_id] = count_fish(st.cycle)
        fish = counts[st.cycle_id].get(st.species_id)
        key = st.supplier_id or 0
        r = rows.setdefault(key, {"supplier": st.supplier, "fish": 0, "cost": ZERO, "priced": 0, "cycles": set(), "species": set(),
                                  "alive_w": ZERO, "alive_n": 0, "growth_w": ZERO, "growth_n": 0})
        n = st.count or 0
        r["fish"] += n
        r["cycles"].add(st.cycle_id)
        r["species"].add(str(st.species))
        if st.cost and n:
            r["cost"] += st.cost
            r["priced"] += n
        if fish and fish.survival is not None and n:
            r["alive_w"] += Decimal(fish.survival) * n
            r["alive_n"] += n
        if fish and fish.avg_g and fish.weighed_on and st.avg_g and fish.weighed_on > st.date and n:
            r["growth_w"] += (fish.avg_g - st.avg_g) / (fish.weighed_on - st.date).days * n
            r["growth_n"] += n
    out = []
    for r in rows.values():
        out.append({
            "supplier": r["supplier"], "fish": r["fish"], "cost": r["cost"], "cycles": len(r["cycles"]),
            "species": ", ".join(sorted(r["species"])),
            "per_1000": (r["cost"] * 1000 / r["priced"]).quantize(Decimal("1")) if r["priced"] else None,
            "survival": round(r["alive_w"] / r["alive_n"]) if r["alive_n"] else None,
            "growth": (r["growth_w"] / r["growth_n"]).quantize(Decimal("0.1")) if r["growth_n"] else None,
        })
    out.sort(key=lambda r: (r["survival"] is None, -(r["survival"] or 0), -r["fish"]))
    return out


def feed_report(business, start, end):
    """Feed bought and eaten, by feed, with what it cost."""
    from apps.business.feed.models import FeedPurchaseLine, FeedUsage
    from apps.business.feed.services import cost_per_kg

    prices = cost_per_kg(business)
    bought = {r["product_id"]: r for r in FeedPurchaseLine.objects.filter(
        business=business, purchase__is_deleted=False, purchase__date__gte=start, purchase__date__lte=end
    ).values("product_id").annotate(kg=Sum("kg"), amount=Sum("amount"))}
    used = {r["product_id"]: r for r in FeedUsage.objects.filter(
        business=business, cycle__is_deleted=False, date__gte=start, date__lte=end
    ).values("product_id").annotate(kg=Sum("kg"))}
    from apps.business.feed.models import FeedProduct

    rows = []
    for p in FeedProduct.objects.filter(business=business):
        b = bought.get(p.pk, {})
        u = used.get(p.pk, {})
        used_kg = u.get("kg") or ZERO
        rows.append({
            "product": p, "bought_kg": b.get("kg") or ZERO, "bought_amount": b.get("amount") or ZERO,
            "used_kg": used_kg, "used_cost": (used_kg * prices.get(p.pk, ZERO)).quantize(Decimal("0.01")),
            "rate": prices.get(p.pk),
        })
    rows = [r for r in rows if r["bought_kg"] or r["used_kg"]]
    rows.sort(key=lambda r: -r["used_kg"])
    return rows


# ── Money reports ───────────────────────────────────────────────────────────

def party_summary(business):
    """Who owes what, both ways, for the dues report."""
    if not _installed("credit"):
        return []
    from apps.business.credit.services import build

    rows = [led for led in build(business).values() if led.balance]
    rows.sort(key=lambda led: -abs(led.balance))
    return rows


def loan_summary(business):
    if not _installed("loans"):
        return None
    from apps.business.loans.services import overview

    return overview(business)


# ── Dashboard put together ──────────────────────────────────────────────────

def ranked_rows(rows, limit=6):
    """The shared ranked list: share bars, "Other" folding, donut colours."""
    from apps.core.stats import ranked

    return ranked([(r.label, r.value, r.url or None) for r in rows], limit=limit)


def dashboard(business, today=None):
    today = today or date.today()
    month = month_start(today)
    year = today.replace(month=1, day=1)
    cache = {}   # feed prices and category names, looked up once for the page
    data = {
        "today": headline(business, today, today, cache),
        "month": headline(business, month, today, cache),
        "year": headline(business, year, today, cache),
        "trend": monthly_trend(business, 6, today, cache),
        "by_species": ranked_rows(sales_by(business, year, today, "species")) if _installed("sales") else [],
        "by_market": ranked_rows(sales_by(business, year, today, "market")) if _installed("sales") else [],
        "expenses": ranked_rows(expense_breakdown(business, month, today, cache=cache)),
        "running": cycle_rows(business, running_only=True),
        "loans": loan_summary(business),
    }
    if _installed("credit"):
        from apps.business.credit.services import totals

        data["baki"] = totals(business)
    if _installed("feed"):
        from apps.business.feed.services import low_stock

        data["low_feed"] = low_stock(business)
    if _installed("finance"):
        from apps.business.finance.models import Account
        from apps.business.finance.services import balances

        found = balances(business)
        data["in_hand"] = sum(found.values(), ZERO)
        accounts = list(Account.objects.filter(business=business))
        for a in accounts:
            a.now = found.get(a.pk, a.opening_balance)
        data["accounts"] = sorted(accounts, key=lambda a: -a.now)
    return data


# ── The day's report, to send on WhatsApp ───────────────────────────────────

def daily_text(business, today=None, show_money=False, tasks=()):
    """A short plain-text summary of today: sales, feed, deaths, money, and what's left to do."""
    from django.utils.formats import date_format
    from django.utils.translation import ngettext

    from apps.business.core.templatetags.business import bdt, num

    today = today or date.today()
    lines = [f"*{business.name}* · {date_format(today, 'j F Y')}", ""]
    if _installed("sales"):
        sales = sales_between(business, today, today)
        n = sales.count()
        if n:
            kg = _sale_kg(sales)
            text = ngettext("Fish sold: %(n)s sale", "Fish sold: %(n)s sales", n) % {"n": n}
            if kg:
                text += " · " + _("%(kg)s kg") % {"kg": num(kg)}
            if show_money:
                text += " · " + bdt(sales.aggregate(v=Sum("net"))["v"] or ZERO)
            lines.append(text)
        else:
            lines.append(_("Fish sold: none today"))
    if _installed("feed"):
        from apps.business.feed.models import FeedUsage

        fed = FeedUsage.objects.filter(business=business, date=today, cycle__is_deleted=False).aggregate(kg=Sum("kg"), ponds=Count("cycle", distinct=True))
        if fed["kg"]:
            lines.append(ngettext("Feed given: %(kg)s kg in %(n)s pond", "Feed given: %(kg)s kg in %(n)s ponds", fed["ponds"])
                         % {"kg": num(fed["kg"]), "n": fed["ponds"]})
        else:
            lines.append(_("Feed given: not recorded yet"))
    from apps.business.ponds.models import Mortality

    dead = Mortality.objects.filter(business=business, date=today, cycle__is_deleted=False).aggregate(n=Sum("count"))["n"] or 0
    lines.append(ngettext("Deaths: %(n)s fish", "Deaths: %(n)s fish", dead) % {"n": num(dead)} if dead else _("Deaths: none recorded"))
    if show_money and _installed("finance"):
        from apps.business.finance.services import statement

        s = statement(business, today, today)
        lines.append(_("Money in: %(i)s · out: %(o)s") % {"i": bdt(s.total_income), "o": bdt(s.total_expense)})
    if tasks:
        lines += ["", _("Still to do:")] + [f"• {t.title}" for t in tasks]
    return "\n".join(lines)
