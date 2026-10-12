"""Money report: one month or one year at a glance — where the money came
from, where it went, how that compares with the period before, the biggest
spends, and loans given and taken. Printable, and downloadable as CSV.

The totals follow the same rules as Home: money in is income plus
contributions; money out is expenses plus bazar you paid for yourself (a
purchase a family member paid for is their balance, not your spending)."""
import calendar
import csv
from datetime import date
from decimal import Decimal
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.db.models import DecimalField, Sum, Value
from django.db.models.functions import Coalesce, TruncMonth
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import gettext as _

from apps.contributors.models import Contribution
from apps.core.stats import change, ranked
from apps.creditors.models import Transaction as CreditorTx
from apps.debtors.models import Transaction as DebtorTx
from apps.expense.models import Expense
from apps.goals.models import GoalEntry
from apps.household.models import Purchase
from apps.income.models import IncomeTransaction

ZERO = Decimal("0.00")


def _total(qs):
    return qs.aggregate(t=Coalesce(Sum("amount"), Value(0, output_field=DecimalField())))["t"]


def _period(request, today):
    """(kind, start, end, label) from ?month=YYYY-MM or ?year=YYYY; this month by default."""
    raw_year, raw_month = request.GET.get("year", "").strip(), request.GET.get("month", "").strip()
    if raw_year.isdigit() and 2000 <= int(raw_year) <= 2100:
        y = int(raw_year)
        return "year", date(y, 1, 1), date(y, 12, 31), str(y)
    try:
        y, m = (int(p) for p in raw_month.split("-")[:2])
        start = date(y, m, 1)
    except (TypeError, ValueError):
        start = today.replace(day=1)
    end = start.replace(day=calendar.monthrange(start.year, start.month)[1])
    return "month", start, end, date_format(start, "F Y")


def _shift(kind, start, n):
    if kind == "year":
        return date(start.year + n, 1, 1)
    index = start.year * 12 + start.month - 1 + n
    return date(index // 12, index % 12 + 1, 1)


def _query(kind, start):
    return "?" + urlencode({"year": start.year} if kind == "year" else {"month": f"{start:%Y-%m}"})


class Ledger:
    """The person's money in and money out, for any date range."""

    def __init__(self, user):
        self.income = IncomeTransaction.objects.filter(source__user=user)
        self.contrib = Contribution.objects.filter(contributor__user=user)
        self.expense = Expense.objects.filter(user=user)
        self.bazar = Purchase.objects.filter(user=user, buyer__isnull=True)

    @staticmethod
    def _in(qs, start, end):
        return qs.filter(date__gte=start, date__lte=end)

    def money_in(self, start, end):
        return _total(self._in(self.income, start, end)) + _total(self._in(self.contrib, start, end))

    def money_out(self, start, end):
        return _total(self._in(self.expense, start, end)) + _total(self._in(self.bazar, start, end))


def build(user, kind, start, end, today):
    led = Ledger(user)
    upto = min(end, today) if start <= today else end      # a period still running is counted up to today
    in_total, out_total = led.money_in(start, end), led.money_out(start, end)

    # The period before: the same number of days, so a half-gone month is
    # compared with the same half of last month.
    prev_start = _shift(kind, start, -1)
    prev_upto = prev_start + (upto - start)
    if kind == "month":
        last_day = calendar.monthrange(prev_start.year, prev_start.month)[1]
        prev_upto = min(prev_upto, prev_start.replace(day=last_day))
    partial = start <= today < end
    prev_in, prev_out = led.money_in(prev_start, prev_upto), led.money_out(prev_start, prev_upto)

    def span(qs):
        return led._in(qs, start, end)

    expense_list = reverse("expense_list")
    dates = urlencode({"date_from": start.isoformat(), "date_to": end.isoformat()})
    out_rows = []
    for r in span(led.expense).values("category_id", "category__name").annotate(t=Sum("amount")):
        label = r["category__name"] or _("No category")
        url = f"{expense_list}?{dates}" + (f"&category={r['category_id']}" if r["category_id"] else "")
        out_rows.append((label, r["t"], url))
    bazar = _total(span(led.bazar))
    if bazar:
        out_rows.append((_("Bazar (household)"), bazar, reverse("household_dashboard")))
    in_rows = [(r["source__name"], r["t"], reverse("income_source_detail", args=[r["source_id"]]))
               for r in span(led.income).values("source_id", "source__name").annotate(t=Sum("amount"))]
    in_rows += [(r["contributor__name"], r["t"], reverse("contributor_detail", args=[r["contributor_id"]]))
                for r in span(led.contrib).values("contributor_id", "contributor__name").annotate(t=Sum("amount"))]

    biggest = [{"date": e.date, "label": e.category.name if e.category else _("Expense"), "note": e.note, "amount": e.amount,
                "url": reverse("expense_edit", args=[e.pk])}
               for e in span(led.expense).select_related("category").order_by("-amount", "-date")[:6]]
    biggest += [{"date": p.date, "label": _("Bazar") + (f" · {p.category.name}" if p.category else ""), "note": getattr(p, "note", ""),
                 "amount": p.amount, "url": reverse("household_purchase_edit", args=[p.pk])}
                for p in span(led.bazar).select_related("category").order_by("-amount", "-date")[:6]]
    biggest = sorted(biggest, key=lambda r: (-r["amount"], r["date"]))[:6]

    def tx(model, owner, kind_value):
        return _total(model.objects.filter(**{f"{owner}__user": user, "transaction_type": kind_value, "date__gte": start, "date__lte": end}))

    loans = {
        "borrowed": tx(CreditorTx, "creditor", CreditorTx.BORROW),
        "repaid": tx(CreditorTx, "creditor", CreditorTx.REPAY),
        "lent": tx(DebtorTx, "debtor", DebtorTx.LEND),
        "got_back": tx(DebtorTx, "debtor", DebtorTx.RECEIVE),
    }
    goal_entries = GoalEntry.objects.filter(goal__user=user, date__gte=start, date__lte=end)
    saved_goals = _total(goal_entries.filter(kind=GoalEntry.DEPOSIT)) - _total(goal_entries.filter(kind=GoalEntry.WITHDRAW))

    months = []
    if kind == "year":
        def by_month(qs):
            rows = qs.filter(date__gte=start, date__lte=end).annotate(m=TruncMonth("date")).values("m").annotate(t=Sum("amount"))
            return {r["m"]: r["t"] for r in rows}
        ins = [by_month(led.income), by_month(led.contrib)]
        outs = [by_month(led.expense), by_month(led.bazar)]
        top = Decimal(0)
        for m in range(1, 13):
            first = date(start.year, m, 1)
            a = sum((d.get(first) or ZERO for d in ins), ZERO)
            b = sum((d.get(first) or ZERO for d in outs), ZERO)
            months.append({"start": first, "in": a, "out": b, "net": a - b, "future": first > today,
                           "url": reverse("money_report") + _query("month", first)})
            top = max(top, a, b)
        for row in months:
            row["in_bar"] = int(row["in"] / top * 100) if top else 0
            row["out_bar"] = int(row["out"] / top * 100) if top else 0

    days = max((upto - start).days + 1, 1) if start <= today else (end - start).days + 1
    entries = (span(led.expense).count() + span(led.bazar).count() + span(led.income).count() + span(led.contrib).count())
    net = in_total - out_total
    return {
        "in_total": in_total,
        "out_total": out_total,
        "net": net,
        "savings_rate": int(net / in_total * 100) if in_total > 0 else None,
        "daily_out": (out_total / days).quantize(Decimal("1")) if out_total else ZERO,
        "days": days,
        "in_change": change(in_total if not partial else led.money_in(start, upto), prev_in),
        "out_change": change(out_total if not partial else led.money_out(start, upto), prev_out),
        "prev_in": prev_in,
        "prev_out": prev_out,
        "partial": partial,
        "in_rank": ranked(in_rows),
        "out_rank": ranked(out_rows),
        "in_rows": sorted(in_rows, key=lambda r: -r[1]),
        "out_rows": sorted(out_rows, key=lambda r: -r[1]),
        "biggest": biggest,
        "loans": loans,
        "has_loans": any(loans.values()),
        "saved_goals": saved_goals,
        "months": months,
        "entries": entries,
    }


@login_required
def report_view(request):
    today = timezone.localdate()
    kind, start, end, label = _period(request, today)
    data = build(request.user, kind, start, end, today)
    if request.GET.get("format") == "csv":
        return _csv(kind, start, label, data)
    prev, nxt = _shift(kind, start, -1), _shift(kind, start, 1)
    first_year = min((d.year for d in (
        Expense.objects.filter(user=request.user).order_by("date").values_list("date", flat=True)[:1].first(),
        IncomeTransaction.objects.filter(source__user=request.user).order_by("date").values_list("date", flat=True)[:1].first(),
    ) if d), default=today.year)
    return render(request, "overview/report.html", {
        **data,
        "kind": kind,
        "start": start,
        "end": end,
        "label": label,
        "today": today,
        "prev_url": _query(kind, prev),
        "next_url": _query(kind, nxt) if nxt <= today else None,
        "this_url": _query(kind, today.replace(day=1) if kind == "month" else date(today.year, 1, 1)),
        "is_current": start <= today <= end,
        "switch_url": _query("year" if kind == "month" else "month", start if kind == "month" else
                             (today.replace(day=1) if start.year == today.year else date(start.year, 12, 1))),
        "csv_url": _query(kind, start) + "&format=csv",
        "years": list(range(today.year, min(first_year, today.year) - 1, -1)),
        "month_value": f"{start:%Y-%m}",
    })


def _csv(kind, start, label, data):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    name = f"money-report-{start.year}" + ("" if kind == "year" else f"-{start.month:02d}")
    response["Content-Disposition"] = f'attachment; filename="{name}.csv"'
    response.write("﻿")
    w = csv.writer(response)
    w.writerow([_("Money report"), label])
    w.writerow([])
    w.writerow([_("Money in"), data["in_total"]])
    w.writerow([_("Money out"), data["out_total"]])
    w.writerow([_("Saved"), data["net"]])
    w.writerow([])
    w.writerow([_("Where it came from"), _("Amount")])
    for name_, value, _url in data["in_rows"]:
        w.writerow([name_, value])
    w.writerow([])
    w.writerow([_("Where it went"), _("Amount")])
    for name_, value, _url in data["out_rows"]:
        w.writerow([name_, value])
    if data["months"]:
        w.writerow([])
        w.writerow([_("Month"), _("Money in"), _("Money out"), _("Saved")])
        for m in data["months"]:
            w.writerow([date_format(m["start"], "F Y"), m["in"], m["out"], m["net"]])
    if data["has_loans"]:
        w.writerow([])
        loans = data["loans"]
        for key, title in (("borrowed", _("Borrowed")), ("repaid", _("Paid back")), ("lent", _("Lent")), ("got_back", _("Got back"))):
            w.writerow([title, loans[key]])
    return response
