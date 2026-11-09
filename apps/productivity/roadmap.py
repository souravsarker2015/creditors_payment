"""Roadmaps, as Linear, Jira Plans, ProductPlan and Aha! have them: bigger pieces of
work and milestones laid out in time and in lanes, seen as a timeline, a Now / Next /
Later board, a list or a value-against-effort chart.

What makes it more than a drawing is that it's tied to the daily work: a piece of
work's progress comes from the tasks linked to it (weighted by their story points),
the time tracked on those tasks adds up on it, and the pace they're being finished at
says when it will likely be done — and so whether it's on track.
"""
import math
from collections import defaultdict
from datetime import timedelta

from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.utils.translation import gettext_lazy

from apps.core.dates import parse_date

from . import services
from .models import (
    Color, Goal, Health, Horizon, Project, Roadmap, RoadmapItem, RoadmapItemKind, RoadmapLane, RoadmapStatus, RoadmapUpdate,
    Status, Task, TimeEntry,
)

PACE_DAYS = 28          # the pace a piece of work's tasks are finished at is measured over this many days
BEHIND = 25             # this many points of progress behind the time gone by: at risk
FINISHED = (RoadmapStatus.DONE, RoadmapStatus.DROPPED)
MOMENTUM_WEEKS = 8
SOON_DAYS = 14          # milestones this close show on Today


# ── Starting points ──────────────────────────────────────────────────────────
# (name, what it's for, colour, lanes [(name, colour)], items [(lane index or None, title, kind, status, horizon, starts in days, days long)])
TEMPLATES = {
    "blank": (gettext_lazy("Blank"), gettext_lazy("Start with an empty roadmap and one lane."), Color.BLUE,
              [(gettext_lazy("Work"), Color.BLUE)], []),
    "product": (gettext_lazy("Product roadmap"), gettext_lazy("Features, improvements and releases for an app or a product."), Color.BLUE,
                [(gettext_lazy("Features"), Color.BLUE), (gettext_lazy("Improvements"), Color.TEAL), (gettext_lazy("Tech & infrastructure"), Color.SLATE)],
                [(0, gettext_lazy("Sign-up and accounts"), "item", "active", "now", -7, 28),
                 (0, gettext_lazy("Payments"), "item", "planned", "next", 21, 35),
                 (1, gettext_lazy("Faster search"), "item", "planned", "next", 7, 21),
                 (2, gettext_lazy("Automatic backups"), "item", "idea", "later", 63, 28),
                 (None, gettext_lazy("Version 1.0 release"), "milestone", "planned", "next", 56, 0)]),
    "career": (gettext_lazy("Career plan"), gettext_lazy("Skills to learn, projects to build and the job to land."), Color.PURPLE,
               [(gettext_lazy("Skills"), Color.PURPLE), (gettext_lazy("Projects"), Color.BLUE), (gettext_lazy("Job search"), Color.GREEN)],
               [(0, gettext_lazy("System design basics"), "item", "active", "now", -14, 42),
                (1, gettext_lazy("Build a portfolio project"), "item", "planned", "next", 14, 56),
                (2, gettext_lazy("Update CV and LinkedIn"), "item", "planned", "next", 49, 14),
                (2, gettext_lazy("Start applying"), "milestone", "planned", "later", 70, 0)]),
    "learning": (gettext_lazy("Learning path"), gettext_lazy("A subject from the basics to building something real."), Color.TEAL,
                 [(gettext_lazy("Basics"), Color.TEAL), (gettext_lazy("Practice"), Color.AMBER), (gettext_lazy("Build"), Color.ORANGE)],
                 [(0, gettext_lazy("The basics"), "item", "active", "now", -7, 28),
                  (1, gettext_lazy("Exercises every day"), "item", "planned", "next", 14, 42),
                  (2, gettext_lazy("A small project of my own"), "item", "idea", "later", 56, 35),
                  (None, gettext_lazy("Exam or certificate"), "milestone", "planned", "later", 100, 0)]),
    "launch": (gettext_lazy("Launch plan"), gettext_lazy("Build it, tell people, launch — for a side project or a business."), Color.ORANGE,
               [(gettext_lazy("Build"), Color.ORANGE), (gettext_lazy("Marketing"), Color.PINK), (gettext_lazy("Launch"), Color.GREEN)],
               [(0, gettext_lazy("First working version"), "item", "active", "now", -7, 35),
                (1, gettext_lazy("Landing page"), "item", "planned", "next", 14, 14),
                (1, gettext_lazy("Tell the first 50 people"), "item", "planned", "next", 28, 28),
                (2, gettext_lazy("Launch day"), "milestone", "planned", "next", 60, 0)]),
}


def templates():
    return [{"key": k, "name": str(v[0]), "about": str(v[1]), "color": v[2], "lanes": [str(n) for n, _c in v[3]]} for k, v in TEMPLATES.items()]


@transaction.atomic
def create(user, title, template="blank", color="", today=None):
    today = today or timezone.localdate()
    name, _about, default_color, lanes, items = TEMPLATES.get(template, TEMPLATES["blank"])
    rm = Roadmap.objects.create(owner=user, title=(title or str(name))[:120], color=color if color in Color.values else default_color)
    made = [RoadmapLane.objects.create(roadmap=rm, name=str(n)[:80], color=c, order=i) for i, (n, c) in enumerate(lanes)]
    for i, (lane, text, kind, status, horizon, starts, days) in enumerate(items):
        start = today + timedelta(days=starts)
        RoadmapItem.objects.create(roadmap=rm, lane=made[lane] if lane is not None else None, title=str(text)[:200], kind=kind,
                                   status=status, horizon=horizon, order=i,
                                   start_date=start, end_date=start + timedelta(days=max(days - 1, 0)))
    return rm


@transaction.atomic
def duplicate(rm):
    copy = Roadmap.objects.create(owner=rm.owner, title=(_("%(title)s (copy)") % {"title": rm.title})[:120], description=rm.description, color=rm.color,
                                  baseline_at=rm.baseline_at)
    lanes = {}
    for lane in rm.lanes.all():
        lanes[lane.pk] = RoadmapLane.objects.create(roadmap=copy, name=lane.name, color=lane.color, order=lane.order)
    items, deps = {}, []
    for it in rm.items.all().prefetch_related("depends_on"):
        old = it.pk
        deps += [(old, d.pk) for d in it.depends_on.all()]
        it.pk = None
        it.roadmap, it.lane = copy, lanes.get(it.lane_id)
        it.save()
        items[old] = it
    for a, b in deps:
        if a in items and b in items:
            items[a].depends_on.add(items[b])
    return copy


# ── What each piece of work has done ─────────────────────────────────────────
def stats(items, today):
    """{item id: {done, total, weight_done, weight, open, recent, minutes}} for these items, in two queries."""
    ids = [i.pk for i in items]
    out = defaultdict(lambda: {"done": 0, "total": 0, "wdone": 0, "weight": 0, "open": 0, "recent": 0, "minutes": 0})
    since = timezone.now() - timedelta(days=PACE_DAYS)
    for item_id, status, points, completed in Task.objects.filter(roadmap_item_id__in=ids).values_list("roadmap_item_id", "status", "points", "completed_at"):
        s, w = out[item_id], points or 1
        s["total"] += 1
        s["weight"] += w
        if status == Status.DONE:
            s["done"] += 1
            s["wdone"] += w
            if completed and completed >= since:
                s["recent"] += 1
        else:
            s["open"] += 1
    now = timezone.now()
    for item_id, start, end in TimeEntry.objects.filter(task__roadmap_item_id__in=ids).values_list("task__roadmap_item_id", "started_at", "ended_at"):
        out[item_id]["minutes"] += max(int(((end or now) - start).total_seconds() // 60), 0)
    return out


def goal_progress(items):
    goals = services.with_progress(Goal.objects.filter(pk__in={i.goal_id for i in items if i.goal_id}))
    return {g.pk: g.pct for g in goals}


def progress_of(item, s, goals):
    """(0–100, where it comes from: done / tasks / goal / manual)."""
    if item.status == RoadmapStatus.DONE:
        return 100, "done"
    if s["total"]:
        return round(100 * s["wdone"] / s["weight"]), "tasks"
    if item.goal_id and item.goal_id in goals:
        return goals[item.goal_id], "goal"
    return item.progress or 0, "manual"


def forecast(s, today):
    """When the open tasks will likely all be done, at the pace of the last four weeks (None: no tasks open, or no pace yet)."""
    if not s["open"] or not s["recent"]:
        return None
    return today + timedelta(days=math.ceil(s["open"] / (s["recent"] / PACE_DAYS)))


def auto_health(item, progress, likely, today, known=True):
    """How it's going when nobody has said: off track once it's late, at risk when it won't make it at this pace
    or it's well behind the time gone by (only when there's progress to go by: tasks, a goal, or a figure set
    by hand — a piece nobody has measured yet isn't called behind), else on track once it has started."""
    if item.status in FINISHED or item.status == RoadmapStatus.IDEA or not item.end_date:
        return ""
    if item.end_date < today:
        return Health.OFF_TRACK
    if likely and likely > item.end_date:
        return Health.AT_RISK
    start = item.start_date or item.end_date
    if known and item.kind == RoadmapItemKind.ITEM and start < today:
        expected = 100 * (today - start).days / max((item.end_date - start).days, 1)
        if progress + BEHIND < expected:
            return Health.AT_RISK
    return Health.ON_TRACK if (item.status == RoadmapStatus.ACTIVE or start <= today) else ""


def _iso(d):
    return d.isoformat() if d else ""


def item_json(item, s, goals, today):
    pct, source = progress_of(item, s, goals)
    likely = forecast(s, today) if item.status not in FINISHED else None
    return {
        "id": item.pk, "title": item.title, "description": item.description, "kind": item.kind, "status": item.status,
        "horizon": item.horizon, "health": item.health, "auto": auto_health(item, pct, likely, today, known=source != "manual" or item.progress is not None),
        "lane": item.lane_id, "start": _iso(item.start_date), "end": _iso(item.end_date), "color": item.color,
        "progress": pct, "from": source, "manual": item.progress, "impact": item.impact, "effort": item.effort,
        "goal": item.goal_id, "project": item.project_id, "deps": sorted(d.pk for d in item.depends_on.all()),
        "tasks": {"done": s["done"], "total": s["total"], "open": s["open"]}, "minutes": s["minutes"],
        "likely": _iso(likely), "order": item.order, "done_at": item.completed_at.isoformat() if item.completed_at else "",
        "planStart": _iso(item.plan_start), "planEnd": _iso(item.plan_end),
    }


def items_json(items, today):
    items = list(items)
    st, goals = stats(items, today), goal_progress(items)
    return [item_json(i, st[i.pk], goals, today) for i in items]


def one(item, today=None):
    item = RoadmapItem.objects.prefetch_related("depends_on").get(pk=item.pk)
    return items_json([item], today or timezone.localdate())[0]


def summary(items):
    """The roadmap at a glance, from items_json rows: progress, how many are going well or badly, the next milestone."""
    live = [i for i in items if i["status"] != RoadmapStatus.DROPPED]
    health = defaultdict(int)
    for i in live:
        if i["status"] != RoadmapStatus.DONE and (i["health"] or i["auto"]):
            health[i["health"] or i["auto"]] += 1
    today = timezone.localdate().isoformat()
    upcoming = sorted((i for i in live if i["kind"] == RoadmapItemKind.MILESTONE and i["status"] != RoadmapStatus.DONE and i["end"] >= today),
                      key=lambda i: i["end"])
    return {"progress": round(sum(i["progress"] for i in live) / len(live)) if live else 0, "count": len(live),
            "done": sum(1 for i in live if i["status"] == RoadmapStatus.DONE), "active": sum(1 for i in live if i["status"] == RoadmapStatus.ACTIVE),
            "on_track": health[Health.ON_TRACK], "at_risk": health[Health.AT_RISK], "off_track": health[Health.OFF_TRACK],
            "next": upcoming[0] if upcoming else None, "minutes": sum(i["minutes"] for i in items)}


def momentum(rm, today):
    """Tasks finished and hours tracked on this roadmap, week by week, for the last eight weeks."""
    first = today - timedelta(days=today.weekday() + 7 * (MOMENTUM_WEEKS - 1))
    weeks = [{"week": _iso(first + timedelta(days=7 * i)), "done": 0, "minutes": 0} for i in range(MOMENTUM_WEEKS)]

    def slot(dt):
        n = (timezone.localtime(dt).date() - first).days // 7
        return weeks[n] if 0 <= n < MOMENTUM_WEEKS else None

    start = timezone.make_aware(timezone.datetime.combine(first, timezone.datetime.min.time()))
    for done in Task.objects.filter(roadmap_item__roadmap=rm, status=Status.DONE, completed_at__gte=start).values_list("completed_at", flat=True):
        w = slot(done)
        if w:
            w["done"] += 1
    now = timezone.now()
    for a, b in TimeEntry.objects.filter(task__roadmap_item__roadmap=rm, started_at__gte=start).values_list("started_at", "ended_at"):
        w = slot(a)
        if w:
            w["minutes"] += max(int(((b or now) - a).total_seconds() // 60), 0)
    return weeks


def lane_json(lane):
    return {"id": lane.pk, "name": lane.name, "color": lane.color, "order": lane.order}


def payload(rm, today):
    items = rm.items.select_related("lane").prefetch_related("depends_on")
    user = rm.owner
    return {
        "roadmap": {"id": rm.pk, "title": rm.title, "description": rm.description, "color": rm.color, "archived": rm.is_archived,
                    "baseline": rm.baseline_at.isoformat() if rm.baseline_at else ""},
        "lanes": [lane_json(lane) for lane in rm.lanes.all()],
        "items": items_json(items, today),
        "goals": [{"id": g.pk, "title": g.title} for g in Goal.objects.filter(owner=user).exclude(status="dropped").order_by("title")],
        "projects": [{"id": p.pk, "name": p.name, "color": p.color} for p in Project.objects.filter(owner=user, is_archived=False)],
        "momentum": momentum(rm, today), "today": _iso(today),
    }


# ── The saved plan (a baseline, as Jira Plans and MS Project keep one) ──────
@transaction.atomic
def save_plan(rm):
    """Keep every piece of work's dates as they are now, to see later how far each one moved."""
    for it in rm.items.all():
        it.plan_start, it.plan_end = it.start_date, it.end_date
        it.save(update_fields=["plan_start", "plan_end"])
    rm.baseline_at = timezone.now()
    rm.save(update_fields=["baseline_at", "updated_at"])


@transaction.atomic
def forget_plan(rm):
    rm.items.update(plan_start=None, plan_end=None)
    rm.baseline_at = None
    rm.save(update_fields=["baseline_at", "updated_at"])


# ── What waits on a piece of work moves with it (as Asana and Jira Plans do) ─
def push_waiting(item):
    """Push what waits on `item` (and what waits on those) later, just enough that each one starts
    the day after everything it waits on ends; nothing finished or undated moves.
    Returns {id: (old start, old end)} for each one moved; they're saved."""
    by_id = {i.pk: i for i in item.roadmap.items.prefetch_related("depends_on")}
    waits = defaultdict(list)                     # id → the ids waiting on it
    for i in by_id.values():
        for dep in i.depends_on.all():
            waits[dep.pk].append(i.pk)
    moved, todo, steps = {}, list(waits[item.pk]), 0
    while todo and steps < 5000:                  # (no circles can be saved; the cap is only a guard)
        steps += 1
        it = by_id[todo.pop(0)]
        if it.status in FINISHED or not it.end_date:
            continue
        ends = [by_id[d.pk].end_date for d in it.depends_on.all()
                if d.pk in by_id and by_id[d.pk].end_date and by_id[d.pk].status not in FINISHED]
        start = it.start_date or it.end_date
        if not ends or start > max(ends):
            continue
        gap = max(ends) + timedelta(days=1) - start
        moved.setdefault(it.pk, (it.start_date, it.end_date))
        it.start_date = it.start_date + gap if it.start_date else None
        it.end_date += gap
        todo += waits[it.pk]
    for pk in moved:
        by_id[pk].save(update_fields=["start_date", "end_date", "updated_at"])
    return {pk: by_id[pk] for pk in moved}, moved


# ── Elsewhere in the app: Today, a goal's page, a project's page ─────────────
def item_url(item):
    return reverse("work:roadmap", args=[item.roadmap_id]) + f"?item={item.pk}"


def attention(user, today):
    """For Today: milestones in the next two weeks, and pieces of work that are late or at risk,
    from the roadmaps in use."""
    items = list(RoadmapItem.objects.filter(roadmap__owner=user, roadmap__is_archived=False).exclude(status__in=FINISHED)
                 .select_related("roadmap").prefetch_related("depends_on"))
    soon, trouble = [], []
    if not items:
        return {"soon": soon, "trouble": trouble, "count": 0}
    rows = {r["id"]: r for r in items_json(items, today)}
    for it in items:
        r = rows[it.pk]
        health = r["health"] or r["auto"]
        if it.kind == RoadmapItemKind.MILESTONE and it.end_date and today <= it.end_date <= today + timedelta(days=SOON_DAYS):
            soon.append({"item": it, "url": item_url(it), "days": (it.end_date - today).days})
        elif health in (Health.AT_RISK, Health.OFF_TRACK) and it.status != RoadmapStatus.IDEA:
            trouble.append({"item": it, "url": item_url(it), "health": health, "label": Health(health).label, "progress": r["progress"],
                            "late": (today - it.end_date).days if it.end_date and it.end_date < today else 0})
    soon.sort(key=lambda x: x["days"])
    trouble.sort(key=lambda x: (x["health"] != Health.OFF_TRACK, x["item"].end_date or today))
    return {"soon": soon[:4], "trouble": trouble[:4], "count": len(soon) + len(trouble)}


def linked(qs, today):
    """Pieces of work (from roadmaps in use) as rows for a goal's or a project's page."""
    items = list(qs.filter(roadmap__is_archived=False).exclude(status=RoadmapStatus.DROPPED)
                 .select_related("roadmap").prefetch_related("depends_on").order_by("status", "end_date"))
    rows = {r["id"]: r for r in items_json(items, today)}
    return [{"item": it, "url": item_url(it), "progress": rows[it.pk]["progress"], "health": rows[it.pk]["health"] or rows[it.pk]["auto"]}
            for it in items]


# ── Changes, checked ─────────────────────────────────────────────────────────
class Refused(ValueError):
    pass


def _number(value, lo, hi):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if lo <= n <= hi else None


def _waits_on_itself(item, deps):
    """True when `item` waiting on `deps` would go round in a circle."""
    seen, todo = set(), list(deps)
    while todo:
        d = todo.pop()
        if d.pk == item.pk:
            return True
        if d.pk in seen:
            continue
        seen.add(d.pk)
        todo += list(d.depends_on.all())
    return False


def apply(item, data, user):
    """Changes from the page (any of its fields, as text) put on `item`, checked. Raises Refused. Saves."""
    rm = item.roadmap
    if "title" in data:
        title = data["title"].strip()[:200]
        if not title:
            raise Refused(_("Give it a title."))
        item.title = title
    if "description" in data:
        item.description = data["description"].replace("\r\n", "\n")[:20000]
    for name, choices in (("kind", RoadmapItemKind), ("horizon", Horizon), ("health", Health)):
        if name in data and data[name] in choices.values:
            setattr(item, name, data[name])
    if "color" in data and (data["color"] in Color.values or data["color"] == ""):
        item.color = data["color"]
    if "lane" in data:
        item.lane = RoadmapLane.objects.filter(roadmap=rm, pk=_number(data["lane"], 1, 2**62) or 0).first()
    for name, field in (("start", "start_date"), ("end", "end_date")):
        if name in data:
            raw = data[name].strip()
            day = parse_date(raw) if raw else None
            if raw and day is None:
                raise Refused(_("That isn't a date."))
            setattr(item, field, day)
    if item.kind == RoadmapItemKind.MILESTONE:          # one day
        item.start_date = item.end_date = item.end_date or item.start_date
    elif item.start_date and not item.end_date:
        item.end_date = item.start_date
    elif item.end_date and not item.start_date:
        item.start_date = item.end_date
    if item.start_date and item.end_date and item.start_date > item.end_date:
        raise Refused(_("The start can't be after the end."))
    if "progress" in data:
        item.progress = _number(data["progress"], 0, 100) if data["progress"] != "" else None
    for name in ("impact", "effort"):
        if name in data:
            setattr(item, name, _number(data[name], 1, 5))
    if "goal" in data:
        item.goal = Goal.objects.filter(owner=user, pk=_number(data["goal"], 1, 2**62) or 0).first()
    if "project" in data:
        item.project = Project.objects.filter(owner=user, pk=_number(data["project"], 1, 2**62) or 0).first()
    if "order" in data:
        try:
            item.order = float(data["order"])
        except ValueError:
            pass
    if "status" in data and data["status"] in RoadmapStatus.values and data["status"] != item.status:
        item.status = data["status"]
        item.completed_at = timezone.now() if item.status == RoadmapStatus.DONE else None
        if item.status == RoadmapStatus.ACTIVE:
            item.horizon = Horizon.NOW
    item.save()
    if "deps" in data:
        ids = {n for n in (_number(x, 1, 2**62) for x in data["deps"].split(",")) if n}
        deps = list(RoadmapItem.objects.filter(roadmap=rm, pk__in=ids).exclude(pk=item.pk).prefetch_related("depends_on"))
        if _waits_on_itself(item, deps):
            raise Refused(_("That would make them wait on each other."))
        item.depends_on.set(deps)
    return item


def add_update(item, health, text):
    if health not in Health.values:
        health = ""
    text = text.replace("\r\n", "\n").strip()[:5000]
    if not text and not health:
        raise Refused(_("Write how it's going, or pick its health."))
    pct = one(item)["progress"]
    up = RoadmapUpdate.objects.create(item=item, health=health, text=text, progress=pct)
    item.health = health
    item.save(update_fields=["health", "updated_at"])
    return up


def update_json(up):
    return {"id": up.pk, "health": up.health, "text": up.text, "progress": up.progress, "when": up.created_at.isoformat()}


def task_json(t):
    return {"id": t.pk, "title": t.title, "status": t.status, "done": t.status == Status.DONE, "points": t.points,
            "due": _iso(t.due_date), "url": reverse("work:task", args=[t.pk])}


def detail(item):
    """What the side panel shows beyond the item itself: its tasks and its updates."""
    open_, done = [], []
    for t in item.tasks.all().order_by("order", "pk"):
        (done if t.status == Status.DONE else open_).append(task_json(t))
    return {"tasks": open_ + done, "updates": [update_json(u) for u in item.updates.all()[:30]]}


CSV_HEAD = ("Title", "Type", "Lane", "Status", "When", "Health", "Starts", "Ends", "Progress %", "Tasks done", "Tasks", "Hours tracked",
            "Likely done", "Value", "Effort", "Goal", "Project", "Waits on", "Planned start", "Planned end", "Description")


def csv_rows(rm, today):
    items = list(rm.items.select_related("lane", "goal", "project").prefetch_related("depends_on"))
    rows = {r["id"]: r for r in items_json(items, today)}
    for it in sorted(items, key=lambda i: ((i.lane.order, i.lane_id) if i.lane else (1e9, 0), i.start_date or i.end_date or today, i.order)):
        r = rows[it.pk]
        yield (it.title, it.get_kind_display(), it.lane.name if it.lane else "", it.get_status_display(), it.get_horizon_display(),
               Health(r["health"] or r["auto"]).label if (r["health"] or r["auto"]) else "", r["start"], r["end"], r["progress"],
               r["tasks"]["done"], r["tasks"]["total"], round(r["minutes"] / 60, 1), r["likely"], it.impact or "", it.effort or "",
               it.goal.title if it.goal else "", it.project.name if it.project else "", ", ".join(d.title for d in it.depends_on.all()),
               _iso(it.plan_start), _iso(it.plan_end), it.description)


# ── As JSON: to download, to import again, or to have an AI assistant write one ──────
FORMAT = "timeline-roadmap"
VERSION = 1
MAX_ITEMS, MAX_LANES = 400, 30
_STATUS_WORDS = {"in progress": "active", "in_progress": "active", "doing": "active", "started": "active", "todo": "planned",
                 "to do": "planned", "planned": "planned", "idea": "idea", "done": "done", "finished": "done", "complete": "done",
                 "completed": "done", "dropped": "dropped", "cancelled": "dropped", "canceled": "dropped", "active": "active"}
_KIND_WORDS = {"item": "item", "work": "item", "piece": "item", "task": "item", "epic": "item", "feature": "item",
               "milestone": "milestone", "release": "milestone", "deadline": "milestone"}


class Invalid(ValueError):
    """What's wrong with a roadmap someone gave, said so they can fix it."""


def is_timeline(data):
    """True for this format (lanes of dated work), False for a learning roadmap (steps of topics)."""
    if not isinstance(data, dict):
        return False
    if data.get("format") in (FORMAT, "learning-roadmap"):
        return data["format"] == FORMAT
    return ("lanes" in data or "items" in data) and "steps" not in data


def _slug(text, taken):
    import re

    base = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:40] or "item"
    key, n = base, 2
    while key in taken:
        key, n = f"{base}-{n}", n + 1
    taken.add(key)
    return key


def export_json(rm):
    """The roadmap as the import reads it: lanes with their pieces of work, real dates, what waits on what."""
    items = list(rm.items.select_related("lane").prefetch_related("depends_on").order_by("order", "pk"))
    taken, keys = set(), {}
    for it in items:
        keys[it.pk] = _slug(it.title, taken)

    def one_(it):
        out = {"id": keys[it.pk], "title": it.title, "type": it.kind, "status": it.status, "when": it.horizon}
        if it.kind == RoadmapItemKind.MILESTONE:
            out["date"] = _iso(it.end_date)
        else:
            out["start"], out["end"] = _iso(it.start_date), _iso(it.end_date)
        for name, value in (("description", it.description), ("health", it.health), ("color", it.color), ("progress", it.progress),
                            ("value", it.impact), ("effort", it.effort)):
            if value not in ("", None):
                out[name] = value
        deps = [keys[d.pk] for d in it.depends_on.all() if d.pk in keys]
        if deps:
            out["waitsOn"] = deps
        return {k: v for k, v in out.items() if v != ""}

    lanes = [{"name": lane.name, "color": lane.color, "items": [one_(it) for it in items if it.lane_id == lane.pk]} for lane in rm.lanes.all()]
    data = {"format": FORMAT, "version": VERSION, "title": rm.title, "description": rm.description, "color": rm.color, "lanes": lanes}
    loose = [one_(it) for it in items if not it.lane_id]
    if loose:
        data["items"] = loose
    return data


def _when(raw, today, where, name):
    """A date: 2027-01-31, or a number of weeks from now (as startWeek / weeks give it)."""
    if raw in (None, ""):
        return None
    day = parse_date(str(raw).strip())
    if day is None:
        raise Invalid(_("%(where)s: “%(name)s” should be a date like 2027-01-31.") % {"where": where, "name": name})
    return day


def _int(raw, lo, hi, where, name):
    if raw in (None, ""):
        return None
    try:
        n = int(float(raw))
    except (TypeError, ValueError):
        raise Invalid(_("%(where)s: “%(name)s” should be a number.") % {"where": where, "name": name})
    return max(lo, min(hi, n))


def build(spec, today=None):
    """A timeline roadmap someone gave (dict), checked and cleaned: (fields, lanes, items). Raises Invalid with where it's wrong.
    Dates are either real ("start"/"end", or "date" for a milestone) or counted from this week ("startWeek" and "weeks")."""
    today = today or timezone.localdate()
    monday = today - timedelta(days=today.weekday())
    if not isinstance(spec, dict):
        raise Invalid(_("The JSON should be one object: { \"title\": …, \"lanes\": [ … ] }."))
    title = str(spec.get("title") or "").strip()[:120]
    if not title:
        raise Invalid(_("It has no “title”."))
    raw_lanes = spec.get("lanes") or []
    loose = spec.get("items") or []
    if not isinstance(raw_lanes, list) or not isinstance(loose, list):
        raise Invalid(_("“lanes” and “items” should be lists: [ … ]."))
    if not raw_lanes and not loose:
        raise Invalid(_("It has no “lanes” (or “items”) — nothing to put on the timeline."))
    if len(raw_lanes) > MAX_LANES:
        raise Invalid(_("At most %(n)s lanes.") % {"n": MAX_LANES})
    color = spec.get("color") if spec.get("color") in Color.values else Color.BLUE
    lanes, items, ids = [], [], set()

    def item(raw, lane, where):
        if not isinstance(raw, dict):
            raise Invalid(_("%(where)s should be an object: { \"title\": … }.") % {"where": where})
        t = str(raw.get("title") or raw.get("name") or "").strip()[:200]
        if not t:
            raise Invalid(_("%(where)s has no title.") % {"where": where})
        kind = _KIND_WORDS.get(str(raw.get("type") or raw.get("kind") or "item").lower().strip(), "item")
        status = _STATUS_WORDS.get(str(raw.get("status") or "planned").lower().strip(), "planned")
        horizon = str(raw.get("when") or raw.get("horizon") or "").lower().strip()
        horizon = horizon if horizon in Horizon.values else (Horizon.NOW if status == "active" else Horizon.NEXT)
        start, end = _when(raw.get("start"), today, where, "start"), _when(raw.get("end") or raw.get("date"), today, where, "end")
        week = _int(raw.get("startWeek"), -260, 520, where, "startWeek")
        if start is None and week is not None:
            start = monday + timedelta(weeks=week)
        weeks, days = _int(raw.get("weeks"), 0, 520, where, "weeks"), _int(raw.get("days"), 0, 3650, where, "days")
        if end is None and start is not None and (weeks or days):
            end = start + timedelta(days=(days if days else weeks * 7) - 1)
        if kind == RoadmapItemKind.MILESTONE:
            start = end = end or start
        else:
            start, end = start or end, end or start
        if start and end and start > end:
            raise Invalid(_("%(where)s starts after it ends.") % {"where": where})
        key = str(raw.get("id") or "").strip()[:64] or _slug(t, set(ids))
        if key in ids:
            raise Invalid(_("%(where)s: the id “%(id)s” is used twice.") % {"where": where, "id": key})
        ids.add(key)
        waits = raw.get("waitsOn") or raw.get("dependsOn") or []
        if isinstance(waits, str):
            waits = [waits]
        items.append({
            "key": key, "lane": lane, "title": t, "kind": kind, "status": status, "horizon": horizon, "start": start, "end": end,
            "description": str(raw.get("description") or "").replace("\r\n", "\n")[:20000],
            "health": raw.get("health") if raw.get("health") in Health.values else "",
            "color": raw.get("color") if raw.get("color") in Color.values else "",
            "progress": _int(raw.get("progress"), 0, 100, where, "progress"),
            "impact": _int(raw.get("value") if raw.get("value") is not None else raw.get("impact"), 1, 5, where, "value"),
            "effort": _int(raw.get("effort"), 1, 5, where, "effort"),
            "waits": [str(w) for w in waits if isinstance(w, (str, int))], "where": where,
        })

    for i, lane in enumerate(raw_lanes, 1):
        if not isinstance(lane, dict):
            raise Invalid(_("Lane %(n)s should be an object: { \"name\": …, \"items\": [ … ] }.") % {"n": i})
        name = str(lane.get("name") or lane.get("title") or "").strip()[:80]
        if not name:
            raise Invalid(_("Lane %(n)s has no “name”.") % {"n": i})
        lanes.append({"name": name, "color": lane.get("color") if lane.get("color") in Color.values else Color.BLUE})
        rows = lane.get("items") or []
        if not isinstance(rows, list):
            raise Invalid(_("Lane %(n)s: “items” should be a list.") % {"n": i})
        for j, raw in enumerate(rows, 1):
            item(raw, len(lanes) - 1, _("Lane %(n)s › item %(m)s") % {"n": i, "m": j})
    for j, raw in enumerate(loose, 1):
        item(raw, None, _("Item %(m)s (no lane)") % {"m": j})
    if len(items) > MAX_ITEMS:
        raise Invalid(_("That's %(n)s pieces of work — at most %(max)s.") % {"n": len(items), "max": MAX_ITEMS})
    for it in items:
        missing = [w for w in it["waits"] if w not in ids]
        if missing:
            raise Invalid(_("%(where)s waits on “%(id)s”, which isn't in it.") % {"where": it["where"], "id": missing[0]})
    graph = {it["key"]: it["waits"] for it in items}
    seen, stack = set(), set()

    def circle(k):
        if k in stack:
            return True
        if k in seen:
            return False
        seen.add(k)
        stack.add(k)
        found = any(circle(w) for w in graph[k])
        stack.discard(k)
        return found

    for it in items:
        if circle(it["key"]):
            raise Invalid(_("%(where)s: what waits on what goes round in a circle.") % {"where": it["where"]})
    fields = {"title": title, "description": str(spec.get("description") or "").replace("\r\n", "\n")[:5000], "color": color}
    return fields, lanes, items


def info(fields, lanes, items):
    """What the import box says it found."""
    ms = sum(1 for i in items if i["kind"] == RoadmapItemKind.MILESTONE)
    return {"kind": "timeline", "title": fields["title"], "lanes": len(lanes), "items": len(items) - ms, "milestones": ms,
            "undated": sum(1 for i in items if not i["end"]),
            "summary": " · ".join([_("Timeline roadmap"),
                                   ngettext("%(n)s lane", "%(n)s lanes", len(lanes)) % {"n": len(lanes)},
                                   ngettext("%(n)s piece of work", "%(n)s pieces of work", len(items) - ms) % {"n": len(items) - ms},
                                   ngettext("%(n)s milestone", "%(n)s milestones", ms) % {"n": ms}])}


@transaction.atomic
def import_json(user, spec, today=None):
    fields, lanes, items = build(spec, today)
    rm = Roadmap.objects.create(owner=user, **fields)
    made = [RoadmapLane.objects.create(roadmap=rm, name=lane["name"], color=lane["color"], order=i) for i, lane in enumerate(lanes)]
    by_key = {}
    for i, it in enumerate(items):
        by_key[it["key"]] = RoadmapItem.objects.create(
            roadmap=rm, lane=made[it["lane"]] if it["lane"] is not None else None, title=it["title"], description=it["description"],
            kind=it["kind"], status=it["status"], horizon=it["horizon"], health=it["health"], color=it["color"], start_date=it["start"],
            end_date=it["end"], progress=it["progress"], impact=it["impact"], effort=it["effort"], order=i,
            completed_at=timezone.now() if it["status"] == RoadmapStatus.DONE else None)
    for it in items:
        if it["waits"]:
            by_key[it["key"]].depends_on.set([by_key[w] for w in it["waits"]])
    return rm


EXAMPLE = {
    "format": FORMAT, "version": VERSION,
    "title": "Side project: launch in 3 months",
    "description": "A small SaaS from the first version to the first paying users.",
    "color": "orange",
    "lanes": [
        {"name": "Build", "color": "blue", "items": [
            {"id": "mvp", "title": "First working version", "status": "active", "when": "now", "startWeek": 0, "weeks": 5,
             "description": "Sign-up, the one main feature, deploy.", "value": 5, "effort": 4},
            {"id": "payments", "title": "Payments", "when": "next", "startWeek": 5, "weeks": 2, "waitsOn": ["mvp"], "value": 4, "effort": 2},
        ]},
        {"name": "Marketing", "color": "pink", "items": [
            {"id": "landing", "title": "Landing page", "startWeek": 2, "weeks": 2, "value": 3, "effort": 1},
            {"id": "first-50", "title": "Tell the first 50 people", "startWeek": 6, "weeks": 4, "waitsOn": ["landing"]},
        ]},
    ],
    "items": [
        {"id": "launch", "title": "Launch day", "type": "milestone", "startWeek": 10, "waitsOn": ["payments", "first-50"]},
    ],
}

PROMPT = """Make a timeline roadmap (a plan of work over time) for: {topic}
Context: {level}. Time span: {time}.

Answer with JSON only (no explanation), in exactly this format:
{{
  "format": "timeline-roadmap",
  "version": 1,
  "title": "short name",
  "description": "one sentence",
  "color": "blue",
  "lanes": [
    {{
      "name": "Area of work, e.g. Backend",
      "color": "blue",
      "items": [
        {{"id": "short-unique-id", "title": "Piece of work", "type": "item", "status": "planned", "when": "now",
          "startWeek": 0, "weeks": 3, "description": "1–2 sentences: what done looks like",
          "value": 4, "effort": 2, "waitsOn": []}}
      ]
    }}
  ],
  "items": [
    {{"id": "release-1", "title": "Release 1.0", "type": "milestone", "startWeek": 8, "waitsOn": ["short-unique-id"]}}
  ]
}}

Rules:
- 2 to 5 lanes, each with 3 to 8 pieces of work, in the order they happen.
- "startWeek" counts weeks from now (0 = this week); "weeks" is how long it takes. Keep everything inside the time span.
- Milestones ("type": "milestone") are one day: releases, deadlines, exams, launches. Put them in "items" or in a lane.
- "status" is one of: idea, planned, active, done, dropped. "when" is one of: now, next, later.
- "value" and "effort" are 1 (low) to 5 (high).
- "waitsOn" lists the ids of what must be finished first. No circles.
- "color" is one of: slate, blue, teal, green, lime, amber, orange, red, pink, purple.
- Every "id" is unique, lowercase, with dashes."""
