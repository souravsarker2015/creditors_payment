"""Goal progress, pace and plan. Kept apart from views so the goals pages
and the Net Worth card always agree."""
import calendar
from datetime import date, timedelta
from decimal import Decimal, ROUND_CEILING

from django.db.models import Case, DecimalField, F, Min, Q, Sum, Value, When
from django.db.models.functions import Coalesce, TruncMonth
from django.utils import timezone

from apps.core.stats import last_n_month_starts, month_start
from .models import GoalEntry, SavingsGoal

ZERO = Decimal("0")
PACE_MONTHS = 3


def _signed():
    return Case(When(kind=GoalEntry.WITHDRAW, then=-F("amount")), default=F("amount"), output_field=DecimalField())


def with_saved(qs):
    """Annotate `saved` (deposits minus withdrawals) in one query."""
    return qs.annotate(saved=Coalesce(Sum(Case(
        When(entries__kind=GoalEntry.WITHDRAW, then=-F("entries__amount")),
        default=F("entries__amount"), output_field=DecimalField(),
    )), Value(0, output_field=DecimalField())))


def months_between(start, end):
    """Whole calendar months from start's month to end's month, counting both."""
    return (end.year - start.year) * 12 + (end.month - start.month) + 1


def add_months(d, n):
    first = month_start(d, n)
    return first.replace(day=min(d.day, calendar.monthrange(first.year, first.month)[1]))


def progress(goal, today=None):
    """Everything the goal card and detail page need, in one dict."""
    today = today or timezone.localdate()
    saved = goal.saved if hasattr(goal, "saved") else (
        goal.entries.aggregate(t=Coalesce(Sum(_signed()), Value(0, output_field=DecimalField())))["t"]
    )
    target = goal.target_amount
    remaining = max(target - saved, ZERO)
    pct = int(saved / target * 100) if target else 0

    # Pace: net money added per month over the last PACE_MONTHS months
    # (or since the goal started, if it's younger).
    first = goal.entries.aggregate(d=Min("date"))["d"]
    pace = ZERO
    if first and first <= today:
        since = max(month_start(today, -(PACE_MONTHS - 1)), first.replace(day=1))
        recent = goal.entries.filter(date__gte=since, date__lte=today).aggregate(
            t=Coalesce(Sum(_signed()), Value(0, output_field=DecimalField())))["t"]
        pace = recent / months_between(since, today)

    # An active auto-save is a commitment: count it even before its first
    # deposit lands, so a freshly scheduled goal reads "On track".
    schedule = _autosave(goal)
    if schedule and schedule.is_active:
        pace = max(pace, schedule.per_month)

    info = {
        "goal": goal, "saved": saved, "target": target, "remaining": remaining,
        "pct": pct, "bar": max(0, min(pct, 100)), "pace": pace, "autosave": schedule,
        "needed_per_month": None, "months_left": None, "projected_date": None,
    }
    if saved >= target:
        info["state"] = "reached"
        return info

    if pace > 0:
        months_needed = int((remaining / pace).to_integral_value(rounding=ROUND_CEILING))
        info["projected_date"] = add_months(today, months_needed) if months_needed < 600 else None

    if goal.target_date:
        if goal.target_date < today:
            info["state"] = "overdue"
            return info
        months_left = months_between(today, goal.target_date)
        info["months_left"] = months_left
        # Whole taka, rounded up, so following the plan always gets there.
        info["needed_per_month"] = (remaining / months_left).to_integral_value(rounding=ROUND_CEILING)
        if saved <= 0 and pace <= 0:
            info["state"] = "idle"  # not started yet: show the plan, not "behind"
            return info
        on_track = pace >= info["needed_per_month"] or (
            info["projected_date"] and info["projected_date"] <= goal.target_date)
        info["state"] = "on_track" if on_track else "behind"
    else:
        info["state"] = "saving" if pace > 0 else "idle"
    return info


def _autosave(goal):
    from .models import AutoSave

    try:
        return goal.autosave
    except AutoSave.DoesNotExist:
        return None


TONES = {"reached": "good", "on_track": "good", "saving": "info", "behind": "warn", "overdue": "critical", "idle": "muted"}


def goal_rows(user, status="active", today=None):
    qs = with_saved(SavingsGoal.objects.filter(user=user).select_related("autosave"))
    if status == "archived":
        qs = qs.filter(is_active=False)
    else:
        qs = qs.filter(is_active=True)
    rows = []
    for g in qs:
        p = progress(g, today)
        p["tone"] = TONES[p["state"]]
        reached = p["state"] == "reached"
        if status == "archived" or (status == "reached") == reached:
            rows.append(p)
    order = {"overdue": 0, "behind": 1, "on_track": 2, "saving": 3, "idle": 4, "reached": 5}
    rows.sort(key=lambda r: (order[r["state"]], r["goal"].target_date or date.max, -r["pct"]))
    return rows


def monthly_net(goal, months):
    """Net saved per month for the chart."""
    rows = (goal.entries.filter(date__gte=months[0]).annotate(m=TruncMonth("date"))
            .values("m").annotate(t=Sum(_signed())))
    by = {r["m"]: r["t"] for r in rows}
    return [float(by.get(m) or 0) for m in months]


def totals(user):
    """Saved across all active goals, and how much went in this month."""
    today = timezone.localdate()
    active = GoalEntry.objects.filter(goal__user=user, goal__is_active=True)
    agg = active.aggregate(
        saved=Coalesce(Sum(_signed()), Value(0, output_field=DecimalField())),
        this_month=Coalesce(Sum("amount", filter=Q(kind=GoalEntry.DEPOSIT, date__gte=today.replace(day=1), date__lte=today)),
                            Value(0, output_field=DecimalField())),
    )
    target = SavingsGoal.objects.filter(user=user, is_active=True).aggregate(
        t=Coalesce(Sum("target_amount"), Value(0, output_field=DecimalField())))["t"]
    agg["target"] = target
    agg["pct"] = int(agg["saved"] / target * 100) if target else 0
    return agg


def last_12():
    return last_n_month_starts(12)


# ── Auto-save ──────────────────────────────────────────────────────────

def saved_amount(goal):
    return goal.entries.aggregate(t=Coalesce(Sum(_signed()), Value(0, output_field=DecimalField())))["t"]


def sync_reached(goal, today=None):
    """Stamp the day a goal is reached (clear it if money is taken back out).
    Returns True when it has just been reached."""
    reached = saved_amount(goal) >= goal.target_amount
    if reached and not goal.reached_at:
        goal.reached_at = today or timezone.localdate()
        goal.save(update_fields=["reached_at", "updated_at"])
        schedule = _autosave(goal)
        if schedule and schedule.is_active:  # nothing left to save for
            schedule.is_active = False
            schedule.save(update_fields=["is_active", "updated_at"])
        return True
    if not reached and goal.reached_at:
        goal.reached_at = None
        goal.save(update_fields=["reached_at", "updated_at"])
    return False


def run_autosave(schedule, today=None):
    """Post every deposit that's due. Returns (deposits created, goal just reached)."""
    from apps.income.models import RECURRING_CATCHUP_LIMIT

    today = today or timezone.localdate()
    goal = schedule.goal
    created = 0
    remaining = goal.target_amount - saved_amount(goal)
    while schedule.is_active and goal.is_active and created < RECURRING_CATCHUP_LIMIT:
        when = schedule.effective_date(schedule.next_run_date)
        if when > today:
            break
        if remaining <= 0:
            break
        amount = min(schedule.amount, remaining)  # never overfill
        GoalEntry.objects.create(goal=goal, kind=GoalEntry.DEPOSIT, amount=amount, date=when, is_auto=True)
        remaining -= amount
        schedule.next_run_date = schedule.advance(schedule.next_run_date)
        created += 1
    if remaining <= 0 and schedule.is_active:
        schedule.is_active = False  # goal reached: nothing more to save
    if created or not schedule.is_active:
        schedule.save(update_fields=["next_run_date", "is_active", "updated_at"])
    return created, (sync_reached(goal, today) if created else False)


def run_due_autosaves(user, today=None):
    """Catch up every due schedule for this user. Returns (deposits, names of goals just reached)."""
    from .models import AutoSave

    today = today or timezone.localdate()
    due = AutoSave.objects.filter(goal__user=user, goal__is_active=True, is_active=True,
                                  next_run_date__lte=today + timedelta(days=2)).select_related("goal")
    total, reached = 0, []
    for schedule in due:
        n, just_reached = run_autosave(schedule, today)
        total += n
        if just_reached:
            reached.append(schedule.goal.name)
    return total, reached
