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


def headline(business, start, end):
    """Sales, costs and profit for one period, with kg sold."""
    from apps.business.finance.services import statement

    s = statement(business, start, end)
    sales = sales_between(business, start, end) if _installed("sales") else None
    return {
        "income": s.total_income, "expense": s.total_expense, "profit": s.profit, "margin": s.margin,
        "kg": _sale_kg(sales) if sales is not None else ZERO,
        "sale_count": sales.count() if sales is not None else 0,
        "statement": s,
    }


def monthly_trend(business, months=6, today=None):
    """Sales against costs for the last few months, for the bar chart."""
    from apps.business.finance.services import statement

    today = today or date.today()
    rows = []
    for i in range(months - 1, -1, -1):
        m = add_months(month_start(today), -i)
        s = statement(business, m, min(month_end(m), today))
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


def expense_breakdown(business, start, end, scope="business"):
    """Costs by main category, biggest first — for the donut."""
    from apps.business.finance.services import statement

    s = statement(business, start, end, scope=scope)
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
    from apps.business.ponds.models import CultureCycle, CycleStatus
    from apps.business.ponds.services import summarize

    qs = CultureCycle.objects.filter(business=business).select_related("pond")
    if pond is not None:
        qs = qs.filter(pond=pond)
    if running_only:
        qs = qs.filter(status=CycleStatus.RUNNING)
    if start:
        qs = qs.filter(Q(ended_on__isnull=True) | Q(ended_on__gte=start))
    if end:
        qs = qs.filter(start_date__lte=end)
    today = date.today()
    rows = []
    for cycle in qs:
        s = summarize(cycle)
        last = cycle.ended_on or today
        rows.append(CycleRow(cycle, cycle.pond, s, (last - cycle.start_date).days))
    rows.sort(key=lambda r: -r.profit)
    return rows


def pond_rows(business, start=None, end=None):
    """Each pond added up across its seasons in the period."""
    from apps.business.ponds.models import Pond

    by_pond = {}
    for row in cycle_rows(business, start, end):
        got = by_pond.setdefault(row.pond.pk, {"pond": row.pond, "sales": ZERO, "cost": ZERO, "cycles": 0,
                                               "feed_kg": ZERO, "harvest_kg": ZERO})
        got["sales"] += row.summary.sales_net
        got["cost"] += row.summary.cost
        got["cycles"] += 1
        got["feed_kg"] += row.summary.feed_kg
        got["harvest_kg"] += row.summary.harvest_kg
    for pond in Pond.objects.filter(business=business):
        by_pond.setdefault(pond.pk, {"pond": pond, "sales": ZERO, "cost": ZERO, "cycles": 0, "feed_kg": ZERO, "harvest_kg": ZERO})
    rows = list(by_pond.values())
    for r in rows:
        r["profit"] = r["sales"] - r["cost"]
        area = r["pond"].area_decimal
        r["per_decimal"] = (r["profit"] / area).quantize(Decimal("1")) if area else None
        gained = r["harvest_kg"]
        r["fcr"] = (r["feed_kg"] / gained).quantize(Decimal("0.01")) if (r["feed_kg"] and gained > 0) else None
    rows.sort(key=lambda r: -r["profit"])
    return rows


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
    data = {
        "today": headline(business, today, today),
        "month": headline(business, month, today),
        "year": headline(business, year, today),
        "trend": monthly_trend(business, 6, today),
        "by_species": ranked_rows(sales_by(business, year, today, "species")) if _installed("sales") else [],
        "by_market": ranked_rows(sales_by(business, year, today, "market")) if _installed("sales") else [],
        "expenses": ranked_rows(expense_breakdown(business, month, today)),
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
