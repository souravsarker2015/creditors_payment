"""The business dashboard and the reports, each with a CSV you can open in Excel."""
import csv
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.formats import date_format
from django.utils.translation import gettext as _, gettext_lazy as _lazy

from apps.business.core.decorators import business_access_required

from . import services

ZERO = Decimal(0)


# ── Date range shared by every report ───────────────────────────────────────

def _parse(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def period_choices(today):
    first = today.replace(day=1)
    last_end = first - timedelta(days=1)
    return [
        ("month", _("This month"), first, today),
        ("last", _("Last month"), last_end.replace(day=1), last_end),
        ("3m", _("Last 3 months"), services.add_months(first, -2), today),
        ("year", _("This year"), today.replace(month=1, day=1), today),
        ("all", _("All time"), date(2000, 1, 1), today),
    ]


@dataclass
class Period:
    key: str
    label: str
    start: date
    end: date

    @property
    def query(self):
        if self.key == "custom":
            return f"period=custom&from={self.start:%Y-%m-%d}&to={self.end:%Y-%m-%d}"
        return f"period={self.key}"


def get_period(request, today=None):
    today = today or date.today()
    choices = period_choices(today)
    start, end = _parse(request.GET.get("from")), _parse(request.GET.get("to"))
    if start or end:
        start = start or date(2000, 1, 1)
        end = end or today
        if end < start:
            start, end = end, start
        return Period("custom", _("%(from)s – %(to)s") % {"from": date_format(start, "j M Y"), "to": date_format(end, "j M Y")}, start, end), choices
    key = request.GET.get("period", "month")
    found = next((c for c in choices if c[0] == key), choices[0])
    return Period(found[0], found[1], found[2], found[3]), choices


# ── Dashboard ───────────────────────────────────────────────────────────────

@business_access_required(capability="view_reports")
def dashboard_view(request):
    b = request.business
    today = date.today()
    data = services.dashboard(b, today)
    return render(request, "business/reports/dashboard.html", {"d": data, "today": today, "month": today.replace(day=1)})


# ── Reports index ───────────────────────────────────────────────────────────

REPORTS = [
    ("pond", _lazy("Pond profit & loss"), _lazy("Every pond: what it cost, what it sold, what it made."), "fish"),
    ("cycle", _lazy("Cycle by cycle"), _lazy("Each batch with its FCR, cost and result."), "fish"),
    ("species", _lazy("Sales by fish"), _lazy("Which fish brings in the most money."), "cart"),
    ("market", _lazy("Sales by market"), _lazy("Which aarot or buyer you sell most through."), "cart"),
    ("feed", _lazy("Feed use"), _lazy("Bought against eaten, and what it cost."), "truck"),
    ("dues", _lazy("Baki & ageing"), _lazy("Who owes you, whom you owe, and for how long."), "book"),
    ("money", _lazy("Income & expenses"), _lazy("Everything in and out, by category."), "scale"),
]


@business_access_required(capability="view_reports")
def report_index_view(request):
    period, choices = get_period(request)
    return render(request, "business/reports/index.html", {
        "reports": [{"key": k, "title": t, "text": x, "icon": i, "url": reverse("business:report", args=[k])} for k, t, x, i in REPORTS],
        "period": period, "periods": choices,
    })


# ── One report ──────────────────────────────────────────────────────────────

@business_access_required(capability="view_reports")
def report_view(request, kind):
    b = request.business
    period, choices = get_period(request)
    spec = next((r for r in REPORTS if r[0] == kind), None)
    if spec is None:
        raise Http404
    build = _BUILDERS.get(kind)
    report = build(b, period, request)
    if request.GET.get("export") == "csv":
        return _csv(f"{kind}-{period.start:%Y%m%d}-{period.end:%Y%m%d}.csv", report, b, period)
    return render(request, report.get("template", "business/reports/report.html"), {
        "kind": kind, "title": spec[1], "subtitle": spec[2], "icon": spec[3],
        "period": period, "periods": choices, "r": report, "today": date.today(),
        "export_url": f"?{period.query}&export=csv",
    })


def _csv(filename, report, business, period):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("﻿")  # so Excel shows Bangla properly
    writer = csv.writer(response)
    writer.writerow([business.name])
    writer.writerow([report["title"], period.label])
    writer.writerow([])
    writer.writerow(report["columns"])
    for row in report["rows"]:
        writer.writerow(row)
    if report.get("total"):
        writer.writerow([])
        writer.writerow(report["total"])
    return response


def _n(value):
    """Plain numbers for the CSV, so Excel adds them up."""
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return format(value.quantize(Decimal("0.01")).normalize(), "f")
    return value


# Each builder returns: title, columns, rows (for the CSV), and whatever the
# page needs to draw itself.

def _pond_report(business, period, request):
    rows = services.pond_rows(business, period.start, period.end)
    return {
        "title": _("Pond profit & loss"), "template": "business/reports/pond.html", "objects": rows,
        "columns": [_("Pond"), _("Cycles"), _("Sold"), _("Cost"), _("Profit"), _("Per decimal"), _("Feed kg"), _("Harvest kg"), _("FCR")],
        "rows": [[r["pond"].name, r["cycles"], _n(r["sales"]), _n(r["cost"]), _n(r["profit"]), _n(r["per_decimal"]),
                  _n(r["feed_kg"]), _n(r["harvest_kg"]), _n(r["fcr"])] for r in rows],
        "total": [_("Total"), "", _n(sum((r["sales"] for r in rows), ZERO)), _n(sum((r["cost"] for r in rows), ZERO)),
                  _n(sum((r["profit"] for r in rows), ZERO))],
        "sales": sum((r["sales"] for r in rows), ZERO), "cost": sum((r["cost"] for r in rows), ZERO),
        "profit": sum((r["profit"] for r in rows), ZERO),
    }


def _cycle_report(business, period, request):
    rows = services.cycle_rows(business, period.start, period.end)
    return {
        "title": _("Cycle by cycle"), "template": "business/reports/cycle.html", "objects": rows,
        "columns": [_("Pond"), _("Cycle"), _("Started"), _("Days"), _("Fish put in"), _("Alive"), _("Harvest kg"),
                    _("Feed kg"), _("FCR"), _("Cost"), _("Sold"), _("Profit")],
        "rows": [[r.pond.name, r.cycle.label, f"{r.cycle.start_date:%Y-%m-%d}", r.days, r.summary.stocked, r.summary.alive,
                  _n(r.summary.harvest_kg), _n(r.summary.feed_kg), _n(r.summary.fcr), _n(r.summary.cost),
                  _n(r.summary.sales_net), _n(r.profit)] for r in rows],
        "total": [_("Total"), "", "", "", "", "", "", "", "", _n(sum((r.summary.cost for r in rows), ZERO)),
                  _n(sum((r.summary.sales_net for r in rows), ZERO)), _n(sum((r.profit for r in rows), ZERO))],
        "profit": sum((r.profit for r in rows), ZERO),
    }


def _species_report(business, period, request):
    rows = services.sales_by(business, period.start, period.end, "species")
    total = sum((r.value for r in rows), ZERO)
    return {
        "title": _("Sales by fish"), "objects": rows, "total_value": total, "chart": True,
        "ranked": services.ranked_rows(rows, limit=8),
        "columns": [_("Fish"), _("Sold for"), _("Quantity"), _("Share")],
        "rows": [[r.label, _n(r.value), r.extra, f"{round(r.value * 100 / total)}%" if total else ""] for r in rows],
        "total": [_("Total"), _n(total)],
    }


def _market_report(business, period, request):
    markets = services.sales_by(business, period.start, period.end, "market")
    buyers = services.sales_by(business, period.start, period.end, "buyer")
    total = sum((r.value for r in markets), ZERO)
    return {
        "title": _("Sales by market"), "template": "business/reports/market.html",
        "objects": markets, "buyers": buyers, "total_value": total,
        "ranked": services.ranked_rows(markets, limit=8), "ranked_buyers": services.ranked_rows(buyers, limit=8),
        "columns": [_("Market"), _("Sold for"), _("Sales"), _("Share")],
        "rows": [[r.label, _n(r.value), r.extra, f"{round(r.value * 100 / total)}%" if total else ""] for r in markets],
        "total": [_("Total"), _n(total)],
    }


def _feed_report(business, period, request):
    rows = services.feed_report(business, period.start, period.end)
    return {
        "title": _("Feed use"), "template": "business/reports/feed.html", "objects": rows,
        "columns": [_("Feed"), _("Bought kg"), _("Bought for"), _("Eaten kg"), _("Feed cost"), _("Per kg")],
        "rows": [[r["product"].name, _n(r["bought_kg"]), _n(r["bought_amount"]), _n(r["used_kg"]), _n(r["used_cost"]), _n(r["rate"])]
                 for r in rows],
        "total": [_("Total"), _n(sum((r["bought_kg"] for r in rows), ZERO)), _n(sum((r["bought_amount"] for r in rows), ZERO)),
                  _n(sum((r["used_kg"] for r in rows), ZERO)), _n(sum((r["used_cost"] for r in rows), ZERO))],
        "used_cost": sum((r["used_cost"] for r in rows), ZERO),
    }


def _dues_report(business, period, request):
    rows = services.party_summary(business)
    receivable = sum((led.balance for led in rows if led.balance > 0), ZERO)
    payable = -sum((led.balance for led in rows if led.balance < 0), ZERO)
    labels = [_("0–30 days"), _("31–60 days"), _("61–90 days"), _("Over 90 days")]
    return {
        "title": _("Baki & ageing"), "template": "business/reports/dues.html", "objects": rows,
        "receivable": receivable, "payable": payable, "bucket_labels": labels,
        "columns": [_("Name"), _("Phone"), _("They owe"), _("You owe")] + labels + [_("Oldest days")],
        "rows": [[led.party.name, led.party.phone, _n(led.balance if led.balance > 0 else ZERO),
                  _n(-led.balance if led.balance < 0 else ZERO)] + [_n(x) for x in led.buckets] + [led.oldest_days or ""]
                 for led in rows],
        "total": [_("Total"), "", _n(receivable), _n(payable)],
    }


def _money_report(business, period, request):
    from apps.business.finance.models import Scope
    from apps.business.finance.services import statement

    scope = request.GET.get("scope", Scope.BUSINESS)
    if scope not in Scope.values:
        scope = Scope.BUSINESS
    s = statement(business, period.start, period.end, scope=scope)
    rows = [[_("Money in"), l.label, _n(l.amount)] for l in s.income]
    rows += [[_("Money out"), l.label, _n(l.amount)] for l in s.expense]
    return {
        "title": _("Income & expenses"), "template": "business/reports/money.html", "s": s,
        "scope": scope, "scopes": Scope.choices,
        "columns": [_("In or out"), _("Category"), _("Amount")], "rows": rows,
        "total": [_("Money left"), "", _n(s.profit)],
        "max_income": max((l.amount for l in s.income), default=ZERO),
        "max_expense": max((l.amount for l in s.expense), default=ZERO),
    }


_BUILDERS = {
    "pond": _pond_report, "cycle": _cycle_report, "species": _species_report, "market": _market_report,
    "feed": _feed_report, "dues": _dues_report, "money": _money_report,
}
