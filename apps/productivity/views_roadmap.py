"""Roadmaps (Productivity): the list of them, one roadmap's page, its download,
and the background saves the page makes (static/js/roadmap.js)."""
from django.db.models import Max
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.http import content_disposition_header
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.csvsafe import safe_writer
from apps.trash.services import trash

from . import roadmap as rmp
from . import services
from .access import work_required
from .models import Color, Health, Horizon, Roadmap, RoadmapItem, RoadmapItemKind, RoadmapLane, RoadmapStatus, RoadmapUpdate, Status, Task
from .views import render_work


def ok(**data):
    return JsonResponse({"ok": True, **data})


def bad(message, status=400):
    return JsonResponse({"ok": False, "error": message}, status=status)


def _today():
    return timezone.localdate()


@work_required
def roadmaps_view(request):
    """Every roadmap as a card (its progress, what's at risk, the next milestone) and a new one from a starting point."""
    user, today = request.user, _today()
    if request.method == "POST":
        rm = rmp.create(user, request.POST.get("title", "").strip(), request.POST.get("template", "blank"), request.POST.get("color", ""), today)
        return redirect("work:roadmap", pk=rm.pk)
    show = "archived" if request.GET.get("show") == "archived" else "active"
    roadmaps = list(Roadmap.objects.filter(owner=user, is_archived=show == "archived"))
    items = {}
    for it in RoadmapItem.objects.filter(roadmap__in=roadmaps).prefetch_related("depends_on"):
        items.setdefault(it.roadmap_id, []).append(it)
    cards = []
    for rm in roadmaps:
        rows = rmp.items_json(items.get(rm.pk, []), today)
        cards.append({"r": rm, "s": rmp.summary(rows), "bars": _mini(rows, today)})
    return render_work(request, "work/roadmaps.html", {
        "cards": cards, "show": show, "templates": rmp.templates(), "colors": Color.choices,
        "archived": Roadmap.objects.filter(owner=user, is_archived=True).count(),
    })


def _mini(rows, today):
    """A tiny timeline for the card: each dated piece of work as a bar over the months around today."""
    from datetime import date, timedelta

    first, days = today - timedelta(days=30), 180
    out = []
    for r in rows:
        if not r["end"] or r["status"] == RoadmapStatus.DROPPED:
            continue
        a, b = (r["start"] or r["end"]), r["end"]
        a, b = date.fromisoformat(a), date.fromisoformat(b)
        if b < first or (a - first).days > days:
            continue
        left = max((a - first).days, 0) * 100 / days
        out.append({"row": len(out) % 4, "left": round(left, 2), "width": round(max(min((b - first).days + 1, days) * 100 / days - left, 1.2), 2),
                    "ms": r["kind"] == RoadmapItemKind.MILESTONE, "health": r["health"] or r["auto"], "done": r["status"] == RoadmapStatus.DONE})
    return {"bars": out[:14], "today": round(30 * 100 / days, 2)}


def _texts():
    return {
        "statuses": dict(RoadmapStatus.choices), "horizons": dict(Horizon.choices), "healths": dict(Health.choices), "kinds": dict(RoadmapItemKind.choices),
        "colors": dict(Color.choices),
        "noLane": _("No lane"), "newItem": _("New piece of work"), "newMilestone": _("New milestone"), "saved": _("Saved"), "saving": _("Saving…"),
        "notSaved": _("Not saved."), "deleted": _("Deleted."), "itemDeleted": _("“%(title)s” deleted."), "laneDeleted": _("Lane deleted. Its items are now in “No lane”."),
        "deleteLane": _("Delete the lane “%(name)s”? Its items stay, without a lane."), "deleteItem": _("Delete “%(title)s”? Its tasks stay."),
        "deleteRoadmap": _("Delete this roadmap and everything on it? Linked tasks stay."), "archived": _("Archived"), "unarchived": _("Back from the archive"),
        "laneName": _("Lane name"), "newLane": _("New lane"), "today": _("Today"), "auto": _("Estimated"), "late": _("late"),
        "daysLate": _("%(n)s days late"), "dayLate": _("1 day late"), "daysLeft": _("%(n)s days left"), "dayLeft": _("1 day left"), "dueToday": _("Due today"),
        "likely": _("At this pace: done by %(date)s"), "likelyLate": _("At this pace: done by %(date)s — %(n)s days after the end"),
        "noPace": _("No tasks finished in the last 4 weeks, so there's no pace to go by yet."),
        "allDone": _("Every task is done. Mark it as done?"), "conflict": _("Starts before “%(title)s” ends."),
        "tasksOf": _("%(done)s of %(total)s tasks"), "fromTasks": _("From its tasks"), "fromGoal": _("From its goal"), "byHand": _("Set by hand"),
        "updatePosted": _("Update posted"), "taskAdded": _("Task added"), "linked": _("Linked"), "unlinked": _("Unlinked"), "noMatch": _("No matching open tasks."),
        "copied": _("Copied"), "noDates": _("No dates"), "quickWins": _("Quick wins"), "bigBets": _("Big bets"), "fillIns": _("Fill-ins"), "timeSinks": _("Time sinks"),
        "hours": _("%(h)s h"), "minutes": _("%(m)s min"), "week": _("Week of %(date)s"), "doneTasks": _("%(n)s tasks done"), "scheduled": _("Put on the timeline"),
        "dupDone": _("Copy made"), "dragHint": _("Drag to move · drag the ends to change the dates · double-click empty space to add"),
        "moved": _("Moved to %(where)s"), "items": _("%(n)s items"), "item1": _("1 item"),
        "quickHint": _("Worth a lot, little work: do these first."), "bigHint": _("Worth a lot, a lot of work: plan them well."),
        "fillHint": _("Little work, little value: when there's time."), "sinkHint": _("A lot of work for little: question them."), "removeDep": _("Stop waiting on it"), "filtersOn": _("Filters on"),
    }


@work_required
def roadmap_view(request, pk):
    rm = get_object_or_404(Roadmap, pk=pk, owner=request.user)
    return render_work(request, "work/roadmap.html", {
        "rm": rm, "payload": rmp.payload(rm, _today()), "texts": _texts(), "colors": Color.choices,
        "statuses": RoadmapStatus.choices, "horizons": Horizon.choices, "healths": Health.choices[1:],
        "others": Roadmap.objects.filter(owner=request.user, is_archived=False).exclude(pk=rm.pk).only("pk", "title")[:20],
    })


@work_required
def roadmap_export_view(request, pk):
    rm = get_object_or_404(Roadmap, pk=pk, owner=request.user)
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = content_disposition_header(True, f"roadmap-{rm.pk}.csv")
    resp.write("﻿")
    w = safe_writer(resp)
    w.writerow(rmp.CSV_HEAD)
    for row in rmp.csv_rows(rm, _today()):
        w.writerow(row)
    return resp


# ── Background saves ─────────────────────────────────────────────────────────
def _next_order(qs):
    return (qs.aggregate(m=Max("order"))["m"] or 0) + 1


@work_required
@require_POST
def roadmap_api(request, pk):
    """The roadmap itself and its lanes, and a new piece of work on it."""
    rm = get_object_or_404(Roadmap, pk=pk, owner=request.user)
    action, p = request.POST.get("action", ""), request.POST
    if action == "save":
        if "title" in p:
            title = p["title"].strip()[:120]
            if not title:
                return bad(_("Give it a name."))
            rm.title = title
        if "description" in p:
            rm.description = p["description"].replace("\r\n", "\n")[:5000]
        if p.get("color") in Color.values:
            rm.color = p["color"]
        rm.save()
        return ok()
    if action == "archive":
        rm.is_archived = not rm.is_archived
        rm.save(update_fields=["is_archived", "updated_at"])
        return ok(archived=rm.is_archived, url=reverse("work:roadmaps"))
    if action == "delete":
        item = trash(request.user, rm, _("Roadmap: %(title)s") % {"title": rm.title}, reverse("work:roadmaps"))
        return ok(undo=reverse("trash_restore", args=[item.pk]), url=reverse("work:roadmaps"))
    if action == "duplicate":
        return ok(url=reverse("work:roadmap", args=[rmp.duplicate(rm).pk]))
    if action == "lane_add":
        name = p.get("name", "").strip()[:80] or _("New lane")
        lane = RoadmapLane.objects.create(roadmap=rm, name=name, color=p.get("color") if p.get("color") in Color.values else Color.SLATE,
                                          order=_next_order(rm.lanes))
        rm.save(update_fields=["updated_at"])
        return ok(lane=rmp.lane_json(lane))
    if action in ("lane_save", "lane_delete"):
        lane = get_object_or_404(RoadmapLane, roadmap=rm, pk=p.get("lane") or 0)
        if action == "lane_delete":
            lane.delete()
            return ok()
        if "name" in p:
            lane.name = p["name"].strip()[:80] or lane.name
        if p.get("color") in Color.values:
            lane.color = p["color"]
        if "order" in p:
            try:
                lane.order = float(p["order"])
            except ValueError:
                pass
        lane.save()
        return ok(lane=rmp.lane_json(lane))
    if action == "item_add":
        item = RoadmapItem(roadmap=rm, order=_next_order(rm.items))
        if "title" not in p or not p["title"].strip():
            return bad(_("Give it a title."))
        try:
            rmp.apply(item, p, request.user)
        except rmp.Refused as e:
            if item.pk:
                item.delete()
            return bad(str(e))
        rm.save(update_fields=["updated_at"])
        return ok(item=rmp.one(item))
    return bad(_("Unknown action."))


@work_required
def item_api(request, pk):
    """GET: the side panel's tasks and updates. POST: a change to the piece of work, its tasks or its updates."""
    item = get_object_or_404(RoadmapItem.objects.select_related("roadmap"), pk=pk, roadmap__owner=request.user)
    user, today = request.user, _today()
    if request.method != "POST":
        return ok(**rmp.detail(item))
    action, p = request.POST.get("action", ""), request.POST

    def done(**more):
        Roadmap.objects.filter(pk=item.roadmap_id).update(updated_at=timezone.now())
        return ok(item=rmp.one(item, today), **more)

    if action == "save":
        try:
            rmp.apply(item, p, user)
        except rmp.Refused as e:
            return bad(str(e))
        return done()
    if action == "delete":
        tr = trash(user, item, _("Roadmap item: %(title)s") % {"title": item.title}, reverse("work:roadmap", args=[item.roadmap_id]))
        return ok(undo=reverse("trash_restore", args=[tr.pk]))
    if action == "duplicate":
        deps = list(item.depends_on.all())
        item.pk = None
        item.title = (_("%(title)s (copy)") % {"title": item.title})[:200]
        item.order += 0.5
        item.completed_at = None if item.status != RoadmapStatus.DONE else item.completed_at
        item.save()
        item.depends_on.set(deps)
        return done()
    if action == "update":
        try:
            up = rmp.add_update(item, p.get("health", ""), p.get("text", ""))
        except rmp.Refused as e:
            return bad(str(e))
        return done(update=rmp.update_json(up))
    if action == "update_delete":
        get_object_or_404(RoadmapUpdate, item=item, pk=p.get("update") or 0).delete()
        latest = item.updates.first()
        item.health = latest.health if latest else ""
        item.save(update_fields=["health", "updated_at"])
        return done()
    if action == "task_add":
        title = p.get("title", "").strip()[:300]
        if not title:
            return bad(_("Write the task first."))
        t = Task.objects.create(owner=user, title=title, roadmap_item=item, project=item.project, goal=item.goal,
                                order=services.next_order(user, Status.TODO))
        return done(task=rmp.task_json(t))
    if action in ("task_link", "task_unlink", "task_done"):
        t = get_object_or_404(Task, owner=user, pk=p.get("task") or 0)
        if action == "task_link":
            t.roadmap_item = item
            t.save(update_fields=["roadmap_item", "updated_at"])
        elif action == "task_unlink":
            if t.roadmap_item_id == item.pk:
                t.roadmap_item = None
                t.save(update_fields=["roadmap_item", "updated_at"])
        else:
            if t.roadmap_item_id != item.pk:
                return bad(_("That task isn't on this piece of work."))
            services.set_done(t, p.get("done") == "1")
        return done(task=rmp.task_json(t))
    if action == "task_search":
        q = p.get("q", "").strip()
        qs = Task.objects.filter(owner=user).exclude(status=Status.DONE).exclude(roadmap_item=item)
        if q:
            qs = qs.filter(title__icontains=q)
        return ok(tasks=[{**rmp.task_json(t), "elsewhere": t.roadmap_item.title if t.roadmap_item_id else ""}
                         for t in qs.select_related("roadmap_item").order_by("-updated_at")[:12]])
    return bad(_("Unknown action."))

