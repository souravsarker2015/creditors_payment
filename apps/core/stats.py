"""Shared building blocks for the statistics (dashboard) pages.

Every dashboard answers the same few questions: how much, compared with last
month, what's it made of, and where is it heading. These helpers compute those
from any queryset with a date and an amount, so each view stays short and the
pages read the same way.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import DecimalField, Sum, Value
from django.db.models.functions import Coalesce, TruncMonth
from django.utils import timezone
from django.utils.translation import gettext as _

ZERO = Decimal("0")
RANK_LIMIT = 6


def month_start(d, offset=0):
    """First day of d's month, shifted by `offset` months."""
    index = d.year * 12 + (d.month - 1) + offset
    return date(index // 12, index % 12 + 1, 1)


def last_n_month_starts(n=12, today=None):
    today = today or timezone.localdate()
    return [month_start(today, -i) for i in range(n - 1, -1, -1)]


def total(qs, field="amount"):
    return qs.aggregate(t=Coalesce(Sum(field), Value(0, output_field=DecimalField())))["t"]


def monthly_series(qs, months, field="amount", date_field="date"):
    """Totals per month for `months` (a list of month starts), zero-filled."""
    rows = (
        qs.filter(**{f"{date_field}__gte": months[0]})
        .annotate(m=TruncMonth(date_field))
        .values("m")
        .annotate(t=Sum(field))
    )
    by_month = {r["m"]: r["t"] for r in rows}
    return [by_month.get(m) or ZERO for m in months]


def change(current, previous):
    """Percent change as a dict the delta chip renders; None when there's no base."""
    current, previous = Decimal(current or 0), Decimal(previous or 0)
    if previous == 0:
        return None if current == 0 else {"pct": None, "direction": "up"}
    pct = (current - previous) / abs(previous) * 100
    direction = "flat" if abs(pct) < Decimal("0.5") else ("up" if pct > 0 else "down")
    # "↑ 4080%" is hard to read; past 3× say "×41" instead.
    times = (current / previous).quantize(Decimal("1") if current / previous >= 10 else Decimal("0.1")) if pct >= 200 else None
    return {"pct": abs(pct).quantize(Decimal("1")), "direction": direction, "times": times}


def month_compare(qs, field="amount", date_field="date", today=None):
    """This month so far vs the whole of last month, plus the pace for today."""
    today = today or timezone.localdate()
    this_start, last_start = month_start(today), month_start(today, -1)
    this_month = total(qs.filter(**{f"{date_field}__gte": this_start, f"{date_field}__lte": today}), field)
    last_month = total(qs.filter(**{f"{date_field}__gte": last_start, f"{date_field}__lt": this_start}), field)
    # Same number of days into last month, so a half-finished month isn't
    # compared against a whole one.
    last_same_day = min(today.day, (this_start - timedelta(days=1)).day)
    last_to_date = total(
        qs.filter(**{f"{date_field}__gte": last_start, f"{date_field}__lte": last_start.replace(day=last_same_day)}),
        field,
    )
    return {
        "this_month": this_month,
        "last_month": last_month,
        "change": change(this_month, last_to_date),
        "last_label": last_start,
        "daily_avg": this_month / today.day,
    }


def trend_summary(values, months):
    """Average of the non-empty months and the peak month, for a trend card.
    Accepts Decimals or the floats the chart code already built."""
    values = [Decimal(str(v or 0)) for v in values]
    active = [v for v in values if v]
    if not active:
        return None
    peak = max(range(len(values)), key=lambda i: values[i])
    return {
        "average": sum(active, ZERO) / len(active),
        "active_months": len(active),
        "peak_value": values[peak],
        "peak_month": months[peak],
        "total": sum(values, ZERO),
    }


def ranked(rows, limit=RANK_LIMIT, other_label=None):
    """Turn [(label, value, url_or_None), ...] into ranked rows with share %.

    Zero/negative rows are dropped; anything past `limit` folds into one
    "Other" row. `bar` is the width relative to the biggest row, `pct` the
    share of the total.
    """
    rows = sorted(((l, Decimal(v), u) for l, v, u in rows if v and v > 0), key=lambda r: -r[1])
    grand = sum((v for _l, v, _u in rows), ZERO)
    if not grand:
        return []
    head, tail = rows[:limit], rows[limit:]
    if tail:
        # keep the list length at `limit` including the Other row
        head, tail = rows[: limit - 1], rows[limit - 1:]
        head.append(((other_label or _("Other")) + f" ({len(tail)})", sum((v for _l, v, _u in tail), ZERO), None))
    top = head[0][1]
    return [
        {"label": l, "value": v, "url": u, "pct": v / grand * 100, "bar": int(v / top * 100), "index": i}
        for i, (l, v, u) in enumerate(head)
    ]


def chart_data(rank_rows):
    """Labels/values for the donut from ranked() rows (same order, same colours)."""
    return [r["label"] for r in rank_rows], [float(r["value"]) for r in rank_rows]


def ledger_extras(*, entities, transactions, out_type, in_type, out_attr, in_attr,
                  detail_urlname, overdue, trend_out, trend_in):
    """Extra figures for the Creditors / Debtors / Shops dashboards.

    `entities` are annotated with their money-out (`out_attr`: borrowed, lent,
    bought on credit) and money-back (`in_attr`: repaid, received, paid) totals;
    `transactions` is the same filtered set of ledger rows.
    """
    from django.urls import reverse

    remaining_rows, back_rows, open_count = [], [], 0
    sum_out = sum_in = ZERO
    for e in entities:
        out, back = getattr(e, out_attr), getattr(e, in_attr)
        sum_out += out
        sum_in += back
        url = reverse(detail_urlname, args=[e.pk])
        if out - back > 0:
            open_count += 1
            remaining_rows.append((e.name, out - back, url))
        if back > 0:
            back_rows.append((e.name, back, url))
    return {
        "progress_pct": min(100, int(sum_in / sum_out * 100)) if sum_out > 0 else 0,
        "out_month": month_compare(transactions.filter(transaction_type=out_type)),
        "in_month": month_compare(transactions.filter(transaction_type=in_type)),
        "rank_remaining": ranked(remaining_rows),
        "rank_back": ranked(back_rows),
        "open_count": open_count,
        "overdue_total": sum((r.remaining_amt for r in overdue), ZERO),
        "overdue_count": len(overdue),
        "out_12": _dsum(trend_out),
        "in_12": _dsum(trend_in),
        "net_12": _dsum(trend_out) - _dsum(trend_in),
    }


def _dsum(values):
    return sum((Decimal(str(v or 0)) for v in values), ZERO)
