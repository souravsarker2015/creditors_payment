"""Learning roadmaps (Productivity): the list with the ready-made ones and the import, one
roadmap's canvas, its download, and the saves the canvas makes (static/js/paths.js)."""
import json

from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.http import content_disposition_header
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.trash.services import trash

from . import paths as lp
from . import services
from .access import work_required
from .models import Color, LearningPath, PathNode, PathNodeKind, PathStatus, Status, Task
from .views import render_work

MAX_UPLOAD = 2 * 1024 * 1024


def ok(**data):
    return JsonResponse({"ok": True, **data})


def bad(message, status=400):
    return JsonResponse({"ok": False, "error": message}, status=status)


@work_required
def paths_view(request):
    """My learning roadmaps (with how far along each is) and the ready-made ones to start from."""
    user = request.user
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "template":
                path = lp.from_template(user, request.POST.get("template", ""))
            else:
                path = lp.create(user, {"title": request.POST.get("title", "").strip() or _("My learning roadmap"),
                                        "steps": [{"id": "start", "title": _("First step")}]})
        except lp.Invalid as e:
            from django.contrib import messages

            messages.error(request, str(e))
            return redirect("work:paths")
        return redirect("work:path", pk=path.pk)
    show = "archived" if request.GET.get("show") == "archived" else "active"
    mine = list(LearningPath.objects.filter(owner=user, is_archived=show == "archived").prefetch_related("nodes"))
    cards = []
    for p in mine:
        s = lp.summary(p)
        s["rest"] = s["total"] - s["done"] - s["learning"] - s["skipped"]
        cards.append({"p": p, "s": s})
    started = set(LearningPath.objects.filter(owner=user).exclude(template="").values_list("template", flat=True))
    gallery = {}
    for t in lp.templates():
        t["started"] = t["key"] in started
        gallery.setdefault(t["category"], []).append(t)
    return render_work(request, "work/paths.html", {
        "cards": cards, "show": show, "archived": LearningPath.objects.filter(owner=user, is_archived=True).count(),
        "gallery": [(str(lp.CATEGORIES.get(k, k)), v) for k, v in gallery.items()],
        "prompt_tpl": lp.PROMPT,
    })


@work_required
@require_POST
def path_import(request):
    """A roadmap from a pasted text or a chosen file (JSON or outline). check=1: only say what's in it."""
    text = request.POST.get("text", "")
    f = request.FILES.get("file")
    if f:
        if f.size > MAX_UPLOAD:
            return bad(_("That file is too big (2 MB at most)."))
        try:
            text = f.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            return bad(_("That file isn't text. Choose the .json file."))
    try:
        spec = lp.read(text)
        fields, nodes, edges = lp.build(spec)
    except lp.Invalid as e:
        return bad(str(e), status=200 if request.POST.get("check") == "1" else 400)     # while checking, "not yet" is an answer
    steps = sum(1 for n in nodes if not n["parent"] and n["kind"] in (PathNodeKind.STEP, PathNodeKind.CHECKPOINT))
    info = {"title": fields["title"], "steps": steps, "boxes": sum(1 for n in nodes if n["kind"] != PathNodeKind.NOTE),
            "done": sum(1 for n in nodes if n["status"] == PathStatus.DONE), "resources": sum(len(n["resources"]) for n in nodes)}
    if request.POST.get("check") == "1":
        return ok(info=info)
    path = lp.create(request.user, spec)
    return ok(url=reverse("work:path", args=[path.pk]), info=info)


def _texts():
    return {
        "statuses": dict(PathStatus.choices), "kinds": dict(PathNodeKind.choices), "colors": dict(Color.choices),
        "saved": _("Saved"), "saving": _("Saving…"), "notSaved": _("Not saved."), "untitled": _("New topic"), "newStep": _("New step"),
        "newCheckpoint": _("Checkpoint: build something"), "newNote": _("A note"), "deleted": _("%(n)s deleted"), "deleted1": _("Deleted"),
        "undo": _("Undo"), "undone": _("Undone"), "redone": _("Redone"), "nothing": _("Nothing to undo."), "copied": _("Copied"),
        "tidied": _("Tidied up. Undo puts everything back."), "linked": _("Linked"), "unlinked": _("Unlinked"), "taskAdded": _("Task added"),
        "onToday": _("Added to Today"), "noMatch": _("No matching open tasks."), "allDone": _("All its tasks are done. Mark it as done?"),
        "openLeft": _("%(n)s of its tasks are still open."), "finishThem": _("Mark them done"), "markDone": _("Mark done"),
        "planned": _("%(n)s tasks made for the next topics. They're in Tasks."), "plannedNone": _("Every next topic already has a task."),
        "allFinished": _("Everything is done. Well done!"), "deleteRoadmap": _("Delete this learning roadmap? Its tasks stay."),
        "resetAsk": _("Set every topic back to “To learn”? The map stays as it is."), "reset": _("Progress cleared."),
        "learn": _("Learn: %(topic)s"), "deleteBoxes": _("Delete %(n)s boxes?"), "hits": _("%(n)s found"), "noHits": _("Nothing found"),
        "lineSolid": _("Solid line"), "lineDashed": _("Dashed line"), "badUrl": _("Give a link that starts with http:// or https://"),
        "done": _("done"), "learning": _("learning"), "locked": _("Layout locked: boxes can't be moved."), "unlocked": _("Layout unlocked."),
        "archived": _("Archived"), "unarchived": _("Back from the archive"),
    }


@work_required
def path_view(request, pk):
    path = get_object_or_404(LearningPath, pk=pk, owner=request.user)
    counts = lp.task_counts(path)
    payload = {
        "path": {"id": path.pk, "title": path.title, "description": path.description, "color": path.color, "archived": path.is_archived},
        "nodes": [lp.node_json(n, counts) for n in path.nodes.all()], "edges": path.edges,
        "sizes": lp.SIZES, "today": timezone.localdate().isoformat(),
        "urls": {"api": reverse("work:api_path", args=[path.pk]), "list": reverse("work:paths"), "today": reverse("work:today")},
    }
    return render_work(request, "work/path.html", {
        "path": path, "payload": payload, "texts": _texts(), "statuses": PathStatus.choices, "kinds": PathNodeKind.choices, "colors": Color.choices,
        "resource_types": lp.RESOURCE_TYPES,
    })


@work_required
def path_export_view(request, pk):
    path = get_object_or_404(LearningPath, pk=pk, owner=request.user)
    data = lp.export(path, progress=request.GET.get("progress") != "0")
    resp = HttpResponse(json.dumps(data, indent=2, ensure_ascii=False), content_type="application/json; charset=utf-8")
    resp["Content-Disposition"] = content_disposition_header(True, f"{slugify(path.title) or 'roadmap'}.learning-roadmap.json")
    return resp


@work_required
def path_example_view(request):
    resp = HttpResponse(json.dumps(lp.EXAMPLE, indent=2, ensure_ascii=False), content_type="application/json; charset=utf-8")
    resp["Content-Disposition"] = content_disposition_header(True, "example.learning-roadmap.json")
    return resp


@work_required
def path_template_view(request, key):
    """A ready-made roadmap as a file, to see the format on a real one or to change it elsewhere."""
    if key not in lp.TEMPLATES:
        raise Http404
    spec = dict(lp._template(key)[0], format=lp.FORMAT, version=lp.VERSION)
    spec.pop("category", None)
    resp = HttpResponse(json.dumps(spec, indent=2, ensure_ascii=False), content_type="application/json; charset=utf-8")
    resp["Content-Disposition"] = content_disposition_header(True, f"{key}.learning-roadmap.json")
    return resp


def _task_json(t):
    return {"id": t.pk, "title": t.title, "done": t.status == Status.DONE, "today": bool(t.my_day), "url": reverse("work:task", args=[t.pk])}


@work_required
def path_api(request, pk):
    """GET ?node=key: that box's tasks. POST: the canvas saved, the roadmap changed, or a box's tasks."""
    path = get_object_or_404(LearningPath, pk=pk, owner=request.user)
    user, p = request.user, request.POST
    if request.method != "POST":
        node = get_object_or_404(PathNode, path=path, key=request.GET.get("node", ""))
        open_, done = [], []
        for t in node.tasks.all().order_by("order", "pk"):
            (done if t.status == Status.DONE else open_).append(_task_json(t))
        return ok(tasks=open_ + done)
    action = p.get("action", "")
    if action == "save":
        try:
            graph = json.loads(p.get("graph") or "{}")
            lp.save_graph(path, graph)
        except (ValueError, lp.Invalid) as e:
            return bad(str(e) if isinstance(e, lp.Invalid) else _("Nothing to save."))
        return ok()
    if action == "rename":
        title = p.get("title", "").strip()[:150]
        if "title" in p and not title:
            return bad(_("Give it a name."))
        if title:
            path.title = title
        if "description" in p:
            path.description = p["description"].replace("\r\n", "\n")[:2000]
        if p.get("color") in Color.values:
            path.color = p["color"]
        path.save()
        return ok()
    if action == "archive":
        path.is_archived = not path.is_archived
        path.save(update_fields=["is_archived", "updated_at"])
        return ok(archived=path.is_archived)
    if action == "delete":
        item = trash(user, path, _("Learning roadmap: %(title)s") % {"title": path.title}, reverse("work:paths"))
        return ok(undo=reverse("trash_restore", args=[item.pk]), url=reverse("work:paths"))
    if action == "duplicate":
        return ok(url=reverse("work:path", args=[lp.duplicate(path).pk]))
    if action == "reset":
        path.nodes.update(status=PathStatus.TODO, done_at=None, updated_at=timezone.now())
        return ok()
    if action == "tidy":
        return ok(places=lp.tidy(path))
    if action == "plan":
        try:
            n = max(1, min(int(p.get("n", 5)), 20))
        except ValueError:
            n = 5
        made = lp.plan_next(path, user, n, today=timezone.localdate() if p.get("today") == "1" else None)
        return ok(count=len(made), nodes={t.path_node.key: True for t in made})

    # a box's tasks: the box must be saved first (the page saves before asking)
    node = PathNode.objects.filter(path=path, key=p.get("node", "")).first()
    if node is None:
        return bad(_("That topic isn't saved yet — try again in a moment."), status=409)
    if action == "task_add":
        title = p.get("title", "").strip()[:300] or (_("Learn: %(topic)s") % {"topic": node.title})[:300]
        t = Task.objects.create(owner=user, title=title, path_node=node, link=node.resources[0]["url"] if node.resources else "",
                                my_day=timezone.localdate() if p.get("today") == "1" else None, order=services.next_order(user, Status.TODO))
        if node.status == PathStatus.TODO and p.get("today") == "1":
            node.status = PathStatus.LEARNING
            node.save(update_fields=["status", "updated_at"])
        return ok(task=_task_json(t), status=node.status)
    if action == "tasks_close":
        n = 0
        for t in node.tasks.exclude(status=Status.DONE):
            services.set_done(t, True)
            n += 1
        return ok(count=n)
    if action == "task_search":
        q = p.get("q", "").strip()
        qs = Task.objects.filter(owner=user).exclude(status=Status.DONE).exclude(path_node=node)
        if q:
            qs = qs.filter(title__icontains=q)
        return ok(tasks=[_task_json(t) for t in qs.order_by("-updated_at")[:12]])
    if action in ("task_link", "task_unlink", "task_done"):
        t = get_object_or_404(Task, owner=user, pk=p.get("task") or 0)
        if action == "task_link":
            t.path_node = node
            t.save(update_fields=["path_node", "updated_at"])
        elif action == "task_unlink":
            if t.path_node_id == node.pk:
                t.path_node = None
                t.save(update_fields=["path_node", "updated_at"])
        else:
            if t.path_node_id != node.pk:
                return bad(_("That task isn't on this topic."))
            services.set_done(t, p.get("done") == "1")
            t.refresh_from_db()
        return ok(task=_task_json(t))
    return bad(_("Unknown action."))
