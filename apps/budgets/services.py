"""Budget arithmetic, kept apart from views so dashboards and the
"you're close to your limit" messages all agree."""
import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.stats import total
from .models import Budget, BudgetScope

ZERO = Decimal("0")


def spending_qs(budget):
    user = budget.user
    if budget.scope == BudgetScope.BAZAR:
        return user.household_purchases.all()
    qs = user.expenses.all()
    if budget.scope == BudgetScope.CATEGORY:
        qs = qs.filter(category_id=budget.category_id)
    return qs


ROLLOVER_MONTHS = 12   # how far back what was left (or overspent) is carried


def _month_before(m):
    return (m.replace(day=1) - timedelta(days=1)).replace(day=1)


def carried_in(budget, month):
    """With rollover on, what earlier months leave for `month`: each month's limit plus what came
    in, less what was spent, passed on (as YNAB and Goodbudget's envelopes do). Overspending
    passes on as a minus. It starts from the month the budget was made, at most a year back."""
    if not budget.rollover:
        return ZERO
    first = timezone.localtime(budget.created_at).date().replace(day=1) if budget.created_at else month
    start = month
    for _i in range(ROLLOVER_MONTHS):
        if start <= first:
            break
        start = _month_before(start)
    if start >= month:
        return ZERO
    spent = {row["m"]: row["total"] for row in (
        spending_qs(budget).filter(date__gte=start, date__lt=month)
        .annotate(m=TruncMonth("date")).values("m").annotate(total=Sum("amount")))}
    carry, m = ZERO, start
    while m < month:
        carry = budget.amount + carry - (spent.get(m) or ZERO)
        m = (m + timedelta(days=32)).replace(day=1)
    return carry


def status(budget, month=None, today=None):
    """Where a budget stands for `month` (first day of it; default: this month).

    For the current month it also projects the month-end total from the pace
    so far and says how much can be spent per remaining day.
    """
    today = today or timezone.localdate()
    month = month or today.replace(day=1)
    days_in_month = calendar.monthrange(month.year, month.month)[1]
    month_end = month.replace(day=days_in_month)
    is_current = month <= today <= month_end
    last_day = today if is_current else month_end

    spent = total(spending_qs(budget).filter(date__gte=month, date__lte=last_day))
    carried = carried_in(budget, month)
    limit = max(budget.amount + carried, ZERO)
    pct = int(spent / limit * 100) if limit else (100 if spent else 0)
    remaining = limit - spent
    days_left = (month_end - today).days + 1 if is_current else 0
    projected = spent / today.day * days_in_month if is_current and today.day else spent

    if spent > limit:
        state = "over"
    elif pct >= budget.alert_at or (is_current and projected > limit):
        state = "warn"
    else:
        state = "ok"
    return {
        "budget": budget,
        "spent": spent,
        "limit": limit,
        "carried": carried,
        "carried_abs": abs(carried),
        "from_month": _month_before(month),
        "pct": pct,
        "bar": min(pct, 100),
        "remaining": remaining,
        "over_by": -remaining if remaining < 0 else ZERO,
        "per_day": remaining / days_left if days_left and remaining > 0 else ZERO,
        "days_left": days_left,
        "projected": projected,
        "is_current": is_current,
        "state": state,
        "tone": {"over": "critical", "warn": "warn", "ok": "good"}[state],
    }


def statuses(user, month=None, today=None):
    budgets = Budget.objects.filter(user=user).select_related("category", "user")
    rows = [status(b, month, today) for b in budgets]
    order = {"over": 0, "warn": 1, "ok": 2}
    return sorted(rows, key=lambda r: (order[r["state"]], -r["pct"]))


def alert_message(user, *, category_id=None, bazar=False):
    """After a new expense/purchase: a warning if it pushed a relevant budget
    past its alert level, else None."""
    qs = Budget.objects.filter(user=user).select_related("category", "user")
    if bazar:
        qs = qs.filter(scope=BudgetScope.BAZAR)
    else:
        qs = qs.filter(scope=BudgetScope.ALL_EXPENSES) | qs.filter(scope=BudgetScope.CATEGORY, category_id=category_id)
    notes = []
    for b in qs:
        s = status(b)
        if s["state"] == "over":
            notes.append(_("%(name)s is over budget: %(spent)s of %(limit)s this month.") % {
                "name": b.label, "spent": _money(s["spent"]), "limit": _money(s["limit"])})
        elif s["pct"] >= b.alert_at:
            notes.append(_("%(name)s has used %(pct)s%% of its %(limit)s budget.") % {
                "name": b.label, "pct": s["pct"], "limit": _money(s["limit"])})
    return " ".join(notes) or None


def _money(value):
    from apps.core.templatetags.ui import money
    return money(value)


def month_from_param(raw, today=None):
    """'2026-08' → date(2026, 8, 1); anything else → this month."""
    today = today or timezone.localdate()
    try:
        y, m = (int(p) for p in (raw or "").split("-"))
        return date(y, m, 1)
    except (TypeError, ValueError):
        return today.replace(day=1)
