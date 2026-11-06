"""The Reports pages, as the best time trackers lay them out:

- Summary (Toggl, Clockify): totals split every way, against the period before, with what stands out;
- Day (RescueTime, Rize, Timing): one day on a timeline, its breaks, and where each minute went, in words;
- Week (Toggl and Clockify's Weekly): a timesheet of tasks by day, grouped by project;
- Detailed (Toggl's Detailed): every entry, by day, to check and correct.

All of them take the same filter: a project (or "no project"), a tag, billable only."""
from datetime import timedelta
from math import ceil

from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from . import services
from .models import EntryKind, Project, Status, Tag, Task

BREAK_MIN_SECONDS = 5 * 60        # a gap this long between entries is a break
STRETCH_JOIN_SECONDS = 5 * 60     # shorter gaps don't end a stretch of work
DETAILED_LIMIT = 1000


class Filter:
    """What a report is narrowed to. Only the person's own projects and tags are taken."""

    def __init__(self, project="", tag="", billable=False):
        self.project, self.tag, self.billable = project, tag, billable
        self.project_obj = self.tag_obj = None

    @classmethod
    def from_request(cls, request):
        user, get = request.user, request.GET
        f = cls(billable=get.get("billable") == "1")
        raw = (get.get("project") or "").strip()
        if raw == "none":
            f.project = "none"
        elif raw.isdigit():
            f.project_obj = Project.objects.filter(owner=user, pk=int(raw)).first()
            f.project = str(f.project_obj.pk) if f.project_obj else ""
        raw = (get.get("tag") or "").strip()
        if raw.isdigit():
            f.tag_obj = Tag.objects.filter(owner=user, pk=int(raw)).first()
            f.tag = str(f.tag_obj.pk) if f.tag_obj else ""
        return f

    @property
    def active(self):
        return bool(self.project or self.tag or self.billable)

    def apply(self, qs, prefix=""):
        if self.project == "none":
            qs = qs.filter(**{f"{prefix}project__isnull": True})
        elif self.project:
            qs = qs.filter(**{f"{prefix}project_id": int(self.project)})
        if self.tag:
            if prefix:              # the tags' own table: an entry's other tags still count for it
                qs = qs.filter(**{f"{prefix}tags": int(self.tag)})
            else:
                qs = qs.filter(tags=int(self.tag))
        if self.billable:
            qs = qs.filter(**{f"{prefix}billable": True})
        return qs

    def __bool__(self):
        return self.active

    def query(self):
        """The filter as a query string, to carry it from one report tab to the next."""
        from urllib.parse import urlencode
        return urlencode([(k, v) for k, v in (("project", self.project), ("tag", self.tag), ("billable", "1" if self.billable else "")) if v])


def pct(part, whole):
    return round(100 * part / whole) if whole else 0


def _label(e):
    if e.task_id:
        return e.task.title
    return e.description or (e.project.name if e.project_id else _("No description"))


def _merge(spans, join=0):
    """Overlapping (or nearly touching) [start, end) spans as one."""
    out = []
    for a, b in sorted(spans):
        if out and (a - out[-1][1]).total_seconds() <= join:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _change(now, before):
    """How a figure moved against the period before: the difference, a percentage and which way."""
    diff = now - before
    return {"now": now, "before": before, "diff": abs(diff), "pct": pct(abs(diff), before) if before else None,
            "dir": "up" if diff > 0 else "down" if diff < 0 else "same"}


# ── Summary ───────────────────────────────────────────────────────────────
def previous_period(start, end):
    days = (end - start).days + 1
    return start - timedelta(days=days), start - timedelta(days=1)


def done_between(user, start, end):
    lo, hi = services.day_bounds(start)[0], services.day_bounds(end)[1]
    return Task.objects.filter(owner=user, status=Status.DONE, completed_at__gte=lo, completed_at__lt=hi)


def compare(user, t, start, end, completed, flt=None):
    """The summary's figures beside the same length of time just before (Toggl, RescueTime)."""
    p_start, p_end = previous_period(start, end)
    prev = services.totals(user, p_start, p_end, flt)
    return {
        "start": p_start, "end": p_end, "prev": prev,
        "tracked": _change(t.seconds, prev.seconds),
        "average": _change(t.daily_average, prev.daily_average),
        "done": _change(completed, done_between(user, p_start, p_end).count()),
        "focus": _change(t.focus_sessions, prev.focus_sessions),
    }


# the projects' colours (work.css [data-color]), for the donut
PALETTE = {"slate": "#64748b", "blue": "#3b82f6", "teal": "#14b8a6", "green": "#22c55e", "lime": "#84cc16", "amber": "#f59e0b",
           "orange": "#f97316", "red": "#ef4444", "pink": "#ec4899", "purple": "#8b5cf6"}


def donut(rows, total):
    """A conic gradient, one slice per row (each has "secs" and a project "p")."""
    if not total:
        return ""
    parts, at = [], 0.0
    for r in rows:
        share = 100 * r["secs"] / total
        color = PALETTE.get(getattr(r["p"], "color", "") or "slate", PALETTE["slate"])
        parts.append(f"{color} {at:.2f}% {at + share:.2f}%")
        at += share
    return "conic-gradient(" + ", ".join(parts) + ")"


def project_breakdown(t):
    """Projects, each opening onto its tasks (Toggl's grouping and sub-grouping)."""
    task_ids = {k for tasks in t.project_tasks.values() for k in tasks if k}
    found = Task.objects.in_bulk(list(task_ids))
    out = []
    for project, secs in t.by_project:
        tasks = t.project_tasks.get(project.pk if project else None, {})
        rows = sorted(({"task": found.get(k), "secs": v, "pct": pct(v, secs)} for k, v in tasks.items() if v and (k is None or k in found)),
                      key=lambda r: (r["task"] is None, -r["secs"]))
        out.append({"p": project, "secs": secs, "pct": pct(secs, t.seconds), "tasks": rows,
                    "earned": float(project.hourly_rate) * secs / 3600 if project and project.hourly_rate else None})
    return out


def highlights(t, cmp, s):
    """What stands out, in plain words (RescueTime's weekly highlights)."""
    out = []
    if not t.seconds:
        return out
    if t.by_project and t.by_project[0][0] is not None:
        p, secs = t.by_project[0]
        out.append(("folder", _("Most of your time went to %(name)s: %(time)s (%(pct)s%%).") % {
            "name": p.name, "time": services.hm(secs), "pct": pct(secs, t.seconds)}))
    if t.best_day and t.days > 1:
        day, secs = t.best_day
        out.append(("calendar", _("Your longest day was %(day)s, with %(time)s.") % {"day": _date(day), "time": services.hm(secs)}))
    hours = t.by_hour
    if sum(hours):
        start = max(range(22), key=lambda h: hours[h] + hours[h + 1] + hours[h + 2])
        share = pct(hours[start] + hours[start + 1] + hours[start + 2], sum(hours))
        if share >= 30:
            out.append(("clock", _("You do most of your work between %(a)s:00 and %(b)s:00 (%(pct)s%% of it).") % {
                "a": start, "b": start + 3, "pct": share}))
    tr = cmp["tracked"]
    if tr["before"] and tr["pct"] is not None and tr["pct"] >= 10:
        if tr["dir"] == "up":
            out.append(("trend", _("%(time)s more than the period before (+%(pct)s%%).") % {"time": services.hm(tr["diff"]), "pct": tr["pct"]}))
        else:
            out.append(("arrow-down", _("%(time)s less than the period before (−%(pct)s%%).") % {"time": services.hm(tr["diff"]), "pct": tr["pct"]}))
    off_task = t.seconds - sum(sum(v for k, v in tasks.items() if k) for tasks in t.project_tasks.values())
    if pct(off_task, t.seconds) >= 30:
        out.append(("info", _("%(pct)s%% of the time isn't on a task. Start the timer from a task and these reports say more.") % {
            "pct": pct(off_task, t.seconds)}))
    missed = [d for d, v in t.by_day.items() if not v and s.is_work_day(d) and d <= timezone.localdate()]
    if missed and t.days > 1:
        out.append(("alert", ngettext("%(count)s work day with nothing tracked.", "%(count)s work days with nothing tracked.",
                                           len(missed)) % {"count": len(missed)}))
    return out


def _date(day):
    from django.utils.formats import date_format
    return date_format(day, "D j M")


# ── Day ───────────────────────────────────────────────────────────────────
def day_report(user, day, s, today, flt=None):
    lo, hi = services.day_bounds(day)
    now = timezone.now()
    items = []
    for e in services.entries_between(user, lo, hi, flt):
        a, b = max(e.started_at, lo), min(e.ended_at or now, hi)
        if b <= a:
            continue
        la, lb = timezone.localtime(a), timezone.localtime(b)
        items.append({"e": e, "a": a, "b": b, "secs": int((b - a).total_seconds()), "label": _label(e),
                      "color": e.project.color if e.project_id else "", "running": e.is_running,
                      "start_min": la.hour * 60 + la.minute, "end_min": 24 * 60 if lb.date() > day else lb.hour * 60 + lb.minute})
    tracked = sum(i["secs"] for i in items)
    spans = _merge([(i["a"], i["b"]) for i in items])
    breaks = [{"a": spans[k][1], "b": spans[k + 1][0], "secs": int((spans[k + 1][0] - spans[k][1]).total_seconds())}
              for k in range(len(spans) - 1) if (spans[k + 1][0] - spans[k][1]).total_seconds() >= BREAK_MIN_SECONDS]
    stretches = _merge([(i["a"], i["b"]) for i in items], STRETCH_JOIN_SECONDS)
    longest = max(((b - a) for a, b in stretches), default=timedelta())

    # the timeline shows the working hours, widened to whatever was tracked outside them
    first_min = min((i["start_min"] for i in items), default=s.day_start.hour * 60)
    last_min = max((i["end_min"] for i in items), default=s.day_end.hour * 60)
    h0 = min(s.day_start.hour, first_min // 60)
    h1 = min(24, max(ceil((s.day_end.hour * 60 + s.day_end.minute) / 60), ceil(last_min / 60)))
    width = max((h1 - h0) * 60, 60)
    for i in items:
        i["left"] = round(100 * (i["start_min"] - h0 * 60) / width, 3)
        i["width"] = max(round(100 * (i["end_min"] - i["start_min"]) / width, 3), 0.4)

    # where it went: by task (or what was written), and by project
    groups, projects = {}, {}
    for i in items:
        e = i["e"]
        key = ("t", e.task_id) if e.task_id else ("d", e.description.strip().lower(), e.project_id)
        g = groups.setdefault(key, {"label": i["label"], "task": e.task if e.task_id else None, "project": e.project,
                                    "secs": 0, "sessions": 0, "first": i["a"]})
        g["secs"] += i["secs"]
        g["sessions"] += 1
        p = projects.setdefault(e.project_id, {"p": e.project, "secs": 0})
        p["secs"] += i["secs"]
    by_task = sorted(groups.values(), key=lambda g: -g["secs"])
    for g in by_task:
        g["pct"] = pct(g["secs"], tracked)
    by_project = sorted(projects.values(), key=lambda p: -p["secs"])
    for p in by_project:
        p["pct"] = pct(p["secs"], tracked)

    done = list(Task.objects.filter(owner=user, status=Status.DONE, completed_at__gte=lo, completed_at__lt=hi)
                .select_related("project").order_by("completed_at"))
    focus = [i for i in items if i["e"].kind == EntryKind.FOCUS]

    # against your usual day: the worked days of the four weeks before
    past = services.daily_seconds(user, day - timedelta(days=28), day - timedelta(days=1))
    worked = [v for v in past.values() if v]
    usual = sum(worked) // len(worked) if worked else 0
    target = s.daily_target_minutes * 60 if s.is_work_day(day) else 0
    first_day, _last = s.week_of(day)
    week = services.daily_seconds(user, first_day, first_day + timedelta(days=6))
    wpeak = max(week.values(), default=0) or 1

    hours = [0] * 24
    for i in items:
        cursor = i["a"]
        while cursor < i["b"]:
            local = timezone.localtime(cursor)
            nxt = min(i["b"], cursor + timedelta(seconds=3600 - local.minute * 60 - local.second, microseconds=-local.microsecond))
            if nxt <= cursor:
                nxt = cursor + timedelta(minutes=1)
            hours[local.hour] += int((nxt - cursor).total_seconds())
            cursor = nxt

    return {
        "day": day, "items": items, "tracked": tracked, "spans": spans, "breaks": breaks,
        "break_secs": sum(b["secs"] for b in breaks), "longest": int(longest.total_seconds()),
        "first": spans[0][0] if spans else None, "last": spans[-1][1] if spans else None,
        "span_secs": int((spans[-1][1] - spans[0][0]).total_seconds()) if spans else 0,
        "by_task": by_task, "by_project": by_project, "done": done, "focus_count": len(focus),
        "focus_secs": sum(i["secs"] for i in focus), "usual": usual, "vs_usual": _change(tracked, usual) if usual else None,
        "target": target, "target_pct": pct(tracked, target) if target else None, "target_bar": min(pct(tracked, target), 100) if target else 0,
        "switches": max(len(stretches) - 1, 0) if stretches else 0,
        "ticks": [{"h": h, "left": round(100 * (h - h0) * 60 / width, 3)} for h in range(h0, h1 + 1)],
        "hours": [{"h": h, "secs": v} for h, v in enumerate(hours)][h0:h1],
        "hour_peak": max(hours) or 1,
        "now_left": round(100 * (timezone.localtime(now).hour * 60 + timezone.localtime(now).minute - h0 * 60) / width, 3)
        if day == today and h0 * 60 <= timezone.localtime(now).hour * 60 + timezone.localtime(now).minute <= h1 * 60 else None,
        "week": [{"day": d, "secs": v, "pct": pct(v, wpeak), "is": d == day, "future": d > today} for d, v in week.items()],
        "work_day": s.is_work_day(day),
        "story": day_story(day, today, tracked, by_task, done, usual, breaks, spans),
    }


def day_story(day, today, tracked, by_task, done, usual, breaks, spans):
    """The day in a sentence or three, as RescueTime and Rize open their daily report."""
    if not tracked:
        return [_("Nothing tracked today yet. Start the timer when you begin and this page fills in as you work.")
                if day == today else _("Nothing was tracked on this day.")]
    first, last = timezone.localtime(spans[0][0]), timezone.localtime(spans[-1][1])
    out = [_("You tracked %(time)s between %(a)s and %(b)s.") % {
        "time": services.hm(tracked), "a": first.strftime("%H:%M"), "b": last.strftime("%H:%M")}]
    if by_task:
        top = by_task[0]
        out.append(_("Most of it went to “%(name)s” (%(time)s, %(pct)s%%).") % {"name": top["label"], "time": services.hm(top["secs"]), "pct": top["pct"]})
    if done:
        out.append(ngettext("You finished %(count)s task.", "You finished %(count)s tasks.", len(done)) % {"count": len(done)})
    if usual:
        diff = tracked - usual
        if abs(diff) >= 15 * 60:
            out.append((_("That's %(time)s more than your usual day.") if diff > 0 else _("That's %(time)s less than your usual day.")) % {
                "time": services.hm(abs(diff))})
    if breaks:
        out.append(ngettext("You took %(count)s break, %(time)s in all.", "You took %(count)s breaks, %(time)s in all.", len(breaks)) % {
            "count": len(breaks), "time": services.hm(sum(b["secs"] for b in breaks))})
    return out


# ── Week ──────────────────────────────────────────────────────────────────
def week_report(user, first, s, today, flt=None):
    """A timesheet: each project, and each task in it, by day (Toggl and Clockify's Weekly report)."""
    last = first + timedelta(days=6)
    t = services.totals(user, first, last, flt)
    now = timezone.now()
    bounds = [services.day_bounds(first + timedelta(days=i)) for i in range(7)]
    groups = {}
    for e in t.entries:
        g = groups.setdefault(e.project_id, {"project": e.project, "days": [0] * 7, "total": 0, "rows": {}})
        key = ("t", e.task_id) if e.task_id else ("d", e.description.strip().lower())
        row = g["rows"].setdefault(key, {"label": _label(e) if (e.task_id or e.description) else _("Not on a task"),
                                         "task": e.task if e.task_id else None, "days": [0] * 7, "total": 0})
        for i, (lo, hi) in enumerate(bounds):
            secs = services.entry_seconds_between(e, lo, hi, now)
            if secs:
                row["days"][i] += secs
                row["total"] += secs
                g["days"][i] += secs
                g["total"] += secs
    out = sorted(groups.values(), key=lambda g: -g["total"])
    for g in out:
        g["rows"] = sorted(g["rows"].values(), key=lambda r: -r["total"])
    day_totals = [sum(g["days"][i] for g in out) for i in range(7)]
    targets = [s.daily_target_minutes * 60 if s.is_work_day(first + timedelta(days=i)) else 0 for i in range(7)]
    total = sum(day_totals)
    before = services.totals(user, first - timedelta(days=7), first - timedelta(days=1), flt).seconds
    return {
        "first": first, "last": last, "groups": out, "t": t,
        "days": [{"day": first + timedelta(days=i), "secs": day_totals[i], "target": targets[i],
                  "met": targets[i] and day_totals[i] >= targets[i], "today": first + timedelta(days=i) == today,
                  "future": first + timedelta(days=i) > today, "off": not targets[i]} for i in range(7)],
        "total": total, "target": sum(targets), "target_pct": pct(total, sum(targets)) if sum(targets) else None,
        "vs_last": _change(total, before) if before else None,
        "done": done_between(user, first, last).count(),
    }


# ── Detailed ──────────────────────────────────────────────────────────────
def detailed(user, start, end, flt=None, q=""):
    """Every entry in the period, newest day first, each day with its total (Toggl's Detailed report)."""
    lo, hi = services.day_bounds(start)[0], services.day_bounds(end)[1]
    now = timezone.now()
    qs = services.entries_between(user, lo, hi, flt)
    if q:
        qs = qs.filter(Q(description__icontains=q) | Q(task__title__icontains=q) | Q(project__name__icontains=q) | Q(tags__name__icontains=q)).distinct()
    rows = list(qs.reverse()[:DETAILED_LIMIT + 1])
    more = len(rows) > DETAILED_LIMIT
    days, total = [], 0
    for e in rows[:DETAILED_LIMIT]:
        secs = services.entry_seconds_between(e, lo, hi, now)
        if not secs:
            continue
        day = timezone.localtime(max(e.started_at, lo)).date()
        if not days or days[-1]["day"] != day:
            days.append({"day": day, "secs": 0, "rows": []})
        days[-1]["rows"].append({"e": e, "secs": secs, "label": _label(e), "end": e.ended_at})
        days[-1]["secs"] += secs
        total += secs
    return {"days": days, "total": total, "count": sum(len(d["rows"]) for d in days), "more": more,
            "billable": sum(r["secs"] for d in days for r in d["rows"] if r["e"].billable)}


def presets():
    return [("week", _("This week")), ("lastweek", _("Last week")), ("month", _("This month")), ("lastmonth", _("Last month")),
            ("30", _("Last 30 days")), ("year", _("This year"))]

