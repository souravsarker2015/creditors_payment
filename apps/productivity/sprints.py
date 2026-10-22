"""Sprints, as in Jira: a fixed stretch of work with the tasks picked for it.

While it runs, the burndown shows how many of its tasks are still open each
day against a straight line to zero. Closing it moves what's left to the next
sprint (or back to the backlog) and keeps a summary — done, left, the
burndown — so velocity (tasks finished per sprint) can be read later.
"""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from .models import Sprint, Status, Task

DEFAULT_DAYS = 14


def current(user, today=None):
    """The running sprint (the earliest-started, if more than one), or None."""
    today = today or timezone.localdate()
    return Sprint.objects.filter(owner=user, completed_at__isnull=True, start_date__lte=today).order_by("start_date", "pk").first()


def open_sprints(user):
    return Sprint.objects.filter(owner=user, completed_at__isnull=True).order_by("start_date", "pk")


def suggest(user, today=None):
    """Name and dates for a new sprint: right after the last one, as long as it was."""
    today = today or timezone.localdate()
    last = Sprint.objects.filter(owner=user).order_by("-end_date", "-pk").first()
    days = last.length if last else DEFAULT_DAYS
    start = max(today, last.end_date + timedelta(days=1)) if last and not last.completed_at else today
    n = Sprint.objects.filter(owner=user).count() + 1
    return {"name": _("Sprint %(n)s") % {"n": n}, "start_date": start, "end_date": start + timedelta(days=days - 1)}


def _done_on(task):
    return timezone.localtime(task.completed_at).date() if task.is_done and task.completed_at else None


def burndown(sprint, today=None):
    """[(day, open tasks at the end of it)] from the start to today (or the end), and the
    straight line from all of them to none — or what was kept when it was closed."""
    today = today or timezone.localdate()
    if sprint.completed_at and sprint.summary.get("burndown"):
        from datetime import date
        points = [(date.fromisoformat(d), n) for d, n in sprint.summary["burndown"]]
        total = sprint.summary.get("done", 0) + sprint.summary.get("left", 0)
    else:
        tasks = list(sprint.tasks.only("status", "completed_at"))
        total = len(tasks)
        last = min(today, sprint.end_date)
        points, day = [], sprint.start_date
        while day <= last:
            points.append((day, sum(1 for t in tasks if not (_done_on(t) and _done_on(t) <= day))))
            day += timedelta(days=1)
    return {"points": points, "total": total, "days": sprint.length}


def chart(sprint, today=None, width=600, height=180):
    """The burndown as SVG coordinates: the ideal line, the real one, today."""
    b = burndown(sprint, today)
    top = max(b["total"], 1)
    step = width / max(b["days"] - 1, 1)
    y = lambda n: round(height - n * height / top, 1)  # noqa: E731
    real = " ".join(f"{round(i * step, 1)},{y(n)}" for i, (_d, n) in enumerate(b["points"]))
    return {"ideal": f"0,{y(b['total'])} {width},{height}", "real": real, "w": width, "h": height, "total": b["total"],
            "left": b["points"][-1][1] if b["points"] else b["total"],
            "dot": {"x": round(100 * (len(b["points"]) - 1) * step / width, 2), "y": round(100 * (y(b["points"][-1][1]) + 8) / (height + 16), 2)} if b["points"] else None}   # the latest day, in % of the chart


@transaction.atomic
def close(sprint, move_to=None):
    """Ends a sprint: its open tasks go to `move_to` (another sprint) or back to the backlog."""
    today = timezone.localdate()
    b = burndown(sprint, today)
    tasks = list(sprint.tasks.all())
    done = [t for t in tasks if t.is_done]
    left = [t for t in tasks if not t.is_done]
    sprint.summary = {
        "done": len(done), "left": len(left), "done_minutes": sum(t.estimate_minutes or 0 for t in done),
        "done_points": sum(t.points or 0 for t in done), "left_points": sum(t.points or 0 for t in left),
        "burndown": [[d.isoformat(), n] for d, n in b["points"]],
    }
    sprint.completed_at = timezone.now()
    sprint.save(update_fields=["summary", "completed_at"])
    for t in left:
        t.sprint = move_to
        t.save(update_fields=["sprint", "updated_at"])
    return len(left)


def velocity(user, n=6):
    """The last few closed sprints: [(sprint, done, left)], oldest first — in story
    points when those sprints used them, else in tasks. Returns (rows, "points" | "tasks")."""
    closed = list(Sprint.objects.filter(owner=user, completed_at__isnull=False).order_by("-end_date", "-pk")[:n])
    unit = "points" if any(s.summary.get("done_points") or s.summary.get("left_points") for s in closed) else "tasks"
    if unit == "points":
        return [(s, s.summary.get("done_points", 0), s.summary.get("left_points", 0)) for s in reversed(closed)], unit
    return [(s, s.summary.get("done", 0), s.summary.get("left", 0)) for s in reversed(closed)], unit


def add_tasks(sprint, ids):
    """Puts the person's open tasks (by id) in the sprint; their subtasks come too."""
    tasks = Task.objects.filter(owner=sprint.owner, pk__in=ids).exclude(status=Status.DONE)
    n = 0
    for t in tasks:
        for x in [t, *t.subtasks.exclude(status=Status.DONE)]:
            if x.sprint_id != sprint.pk:
                x.sprint = sprint
                x.save(update_fields=["sprint", "updated_at"])
                n += 1
    return n
