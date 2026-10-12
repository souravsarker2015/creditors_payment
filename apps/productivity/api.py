"""Small JSON endpoints behind the Productivity pages (static/js/work.js):
the timer, ticking tasks off, moving cards, autosaving notes…

Every change is a POST that carries the offline key (_ft_key), so one made
with no signal is queued on the phone and sent later — and never saved twice
(apps/core/offline.py). Times come from the phone's clock (started_at /
ended_at), so a timer stopped offline keeps the right length.
"""
import re
from datetime import timedelta
from urllib.parse import quote

from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

from apps.trash.services import trash

from . import services
from .access import work_required
from .models import (
    ChecklistItem, EntryKind, Goal, GoalStatus, GoalStep, Habit, HabitCheck, JournalEntry, LearningItem, LearningKind, LearningStatus,
    LearningUnit, Note, Priority, Project, Snippet, Status, Task, TimeEntry, link_label,
)


def ok(**data):
    return JsonResponse({"ok": True, **data})


def bad(message, status=400):
    return JsonResponse({"ok": False, "error": message}, status=status)


def _when(request, name):
    raw = request.POST.get(name)
    return parse_datetime(raw) if raw else None


def entry_json(e):
    if e is None:
        return None
    return {
        "id": e.pk, "label": e.label, "description": e.description, "started_at": e.started_at.isoformat(),
        "ended_at": e.ended_at.isoformat() if e.ended_at else None, "seconds": e.seconds,
        "task": e.task_id, "task_title": e.task.title if e.task_id else "", "project": e.project_id,
        "project_name": e.project.name if e.project_id else "", "color": e.project.color if e.project_id else "",
        "task_url": reverse("work:task", args=[e.task_id]) if e.task_id else "",
    }


def _today_seconds(user):
    today = timezone.localdate()
    return services.totals(user, today, today).seconds


# ── Timer ─────────────────────────────────────────────────────────────────
@work_required
@require_POST
def timer_start(request):
    user = request.user
    task = get_object_or_404(Task, pk=request.POST["task"], owner=user) if request.POST.get("task") else None
    project = get_object_or_404(Project, pk=request.POST["project"], owner=user) if request.POST.get("project") else None
    description = request.POST.get("description", "").strip()
    if task is None and project is None and not description:
        from .models import WorkSettings

        project = WorkSettings.for_user(user).default_project
    entry = services.start_timer(user, task=task, project=project, description=description, at=_when(request, "at"))
    return ok(running=entry_json(entry), today=_today_seconds(user))


@work_required
@require_POST
def timer_stop(request):
    entry = services.stop_timer(request.user, at=_when(request, "at"))
    return ok(stopped=entry_json(entry), running=None, today=_today_seconds(request.user))


@work_required
@require_GET
def timer_state(request):
    return ok(running=entry_json(services.running_entry(request.user)), today=_today_seconds(request.user),
              now=timezone.now().isoformat())


@work_required
@require_POST
def timer_update(request):
    """Change what the running timer is for (description / task / project)."""
    entry = services.running_entry(request.user)
    if entry is None:
        return bad(_("No timer is running."), 404)
    if "description" in request.POST:
        entry.description = request.POST["description"].strip()[:300]
    if "task" in request.POST:
        entry.task = Task.objects.filter(owner=request.user, pk=request.POST["task"] or 0).first()
        if entry.task and not request.POST.get("project"):
            entry.project = entry.task.project
    if "project" in request.POST:
        entry.project = Project.objects.filter(owner=request.user, pk=request.POST["project"] or 0).first()
    entry.save()
    return ok(running=entry_json(entry))


# ── Tasks ─────────────────────────────────────────────────────────────────
def task_row(request, task):
    return render_to_string("work/partials/task_row.html", {"t": task, "today": timezone.localdate()}, request=request)


@work_required
@require_POST
def task_add(request):
    user = request.user
    status = request.POST.get("status") if request.POST.get("status") in Status.values else Status.TODO
    project = Project.objects.filter(owner=user, pk=request.POST.get("project") or 0).first()
    goal = Goal.objects.filter(owner=user, pk=request.POST.get("goal") or 0).first()
    task = services.create_from_quick(user, request.POST.get("text", ""), status=status, project=project, goal=goal,
                                      my_day=request.POST.get("my_day") == "1", due=parse_date(request.POST.get("due") or ""))
    if task is None:
        return bad(_("Type what needs doing."))
    if request.POST.get("start") == "1":
        services.start_timer(user, task=task, at=_when(request, "at"))
    card = render_to_string("work/partials/task_card.html", {"t": task, "today": timezone.localdate()}, request=request)
    return ok(id=task.pk, title=task.title, html=task_row(request, task), card=card, url=reverse("work:task", args=[task.pk]))


@work_required
@require_POST
def task_done(request, pk):
    task = get_object_or_404(Task, pk=pk, owner=request.user)
    nxt = services.set_done(task, request.POST.get("done", "1") == "1")
    data = {"done": task.is_done}
    if nxt:
        data["next"] = {"id": nxt.pk, "due": nxt.due_date.isoformat() if nxt.due_date else None, "html": task_row(request, nxt)}
    return ok(**data)


@work_required
@require_POST
def task_move(request, pk):
    """A card dragged to a column (and between two cards)."""
    task = get_object_or_404(Task, pk=pk, owner=request.user)
    status = request.POST.get("status")
    if status not in Status.values:
        return bad("status")
    before = Task.objects.filter(owner=request.user, pk=request.POST.get("before") or 0).first()
    after = Task.objects.filter(owner=request.user, pk=request.POST.get("after") or 0).first()
    if before and after:
        task.order = (before.order + after.order) / 2
    elif before:
        task.order = before.order + 1
    elif after:
        task.order = after.order - 1
    else:
        task.order = services.next_order(request.user, status)
    if status != task.status:
        if status == Status.DONE:
            services.set_done(task, True)
        elif task.is_done:
            services.set_done(task, False)
        task.status = status
    task.save(update_fields=["order", "status", "updated_at"])
    return ok(status=task.status, order=task.order)


TASK_FIELDS = {"title", "priority", "due_date", "my_day", "project", "status", "notes", "estimate_minutes", "link", "goal", "waiting_for"}


@work_required
@require_POST
def task_update(request, pk):
    task = get_object_or_404(Task, pk=pk, owner=request.user)
    for name in TASK_FIELDS & set(request.POST):
        value = request.POST[name].strip()
        if name == "title":
            if not value:
                return bad(_("A task needs a title."))
            task.title = value[:300]
        elif name == "priority":
            task.priority = int(value) if value.isdigit() and int(value) in Priority.values else Priority.NONE
        elif name == "due_date":
            task.due_date = parse_date(value) if value else None
        elif name == "my_day":     # "1" = today, a date = that day (moved to tomorrow…), else off
            task.my_day = timezone.localdate() if value in ("1", "true", "on") else parse_date(value)
        elif name == "project":
            task.project = Project.objects.filter(owner=request.user, pk=value or 0).first()
        elif name == "status" and value in Status.values:
            if value == Status.DONE:
                services.set_done(task, True)
            elif task.is_done:
                services.set_done(task, False)
            task.status = value
        elif name == "notes":
            task.notes = value
        elif name == "estimate_minutes":
            task.estimate_minutes = int(value) if value.isdigit() else None
        elif name == "link":
            task.link = value[:500] if value.startswith(("http://", "https://")) or not value else task.link
        elif name == "goal":
            task.goal = Goal.objects.filter(owner=request.user, pk=value or 0).first()
        elif name == "waiting_for":
            task.waiting_for = value[:120]
    task.save()
    return ok(html=task_row(request, task))


@work_required
@require_POST
def task_bulk(request):
    """The same change to many tasks (the task list's select mode)."""
    ids = [int(x) for x in request.POST.get("ids", "").split(",") if x.strip().isdigit()][:500]
    action = request.POST.get("action")
    if not ids or action not in services.BULK_ACTIONS:
        return bad(_("Pick some tasks and what to do."))
    value = request.POST.get("value", "")
    if action == "due" and value and parse_date(value) is None:
        return bad("value")
    n = services.bulk(request.user, ids, action, value)
    return ok(count=n, trash=reverse("trash_list") if action == "delete" else "")


def _trash(request, obj, label, back):
    item = trash(request.user, obj, label, back)
    return ok(undo=reverse("trash_restore", args=[item.pk]))


@work_required
@require_POST
def task_delete(request, pk):
    task = get_object_or_404(Task, pk=pk, owner=request.user)
    return _trash(request, task, _("Task: %(title)s") % {"title": task.title}, reverse("work:tasks"))


@work_required
@require_POST
def checklist_add(request, pk):
    task = get_object_or_404(Task, pk=pk, owner=request.user)
    text = request.POST.get("text", "").strip()
    if not text:
        return bad(_("Type the step."))
    last = task.checklist.order_by("-order").first()
    item = task.checklist.create(text=text[:300], order=(last.order + 1) if last else 1)
    return ok(id=item.pk, text=item.text)


@work_required
@require_POST
def checklist_item(request, pk):
    item = get_object_or_404(ChecklistItem, pk=pk, task__owner=request.user)
    action = request.POST.get("action")
    if action == "delete":
        item.delete()
        return ok(deleted=True)
    if action == "text":
        item.text = request.POST.get("text", "").strip()[:300] or item.text
    else:
        item.done = request.POST.get("done", "1") == "1"
    item.save()
    task = item.task
    return ok(done=item.done, progress=[task.checklist.filter(done=True).count(), task.checklist.count()])


# ── Notes (autosave) ──────────────────────────────────────────────────────
@work_required
@require_POST
def note_save(request):
    user = request.user
    pk = request.POST.get("id")
    note = get_object_or_404(Note, pk=pk, owner=user) if pk else Note(owner=user)
    for name in ("title", "body"):
        if name in request.POST:
            setattr(note, name, request.POST[name])
    if "project" in request.POST:
        note.project = Project.objects.filter(owner=user, pk=request.POST["project"] or 0).first()
    if not note.pk and not (note.title.strip() or note.body.strip()):
        return bad(_("The note is empty."))
    note.save()
    if "tags" in request.POST:
        note.tags.set(services.tags_named(user, request.POST["tags"].replace(",", " ").split()))
    return ok(id=note.pk, title=note.display_title, url=reverse("work:note", args=[note.pk]),
              saved=timezone.localtime(note.updated_at).strftime("%H:%M"))


@work_required
@require_POST
def note_action(request, pk):
    note = get_object_or_404(Note, pk=pk, owner=request.user)
    action = request.POST.get("action")
    if action == "pin":
        note.is_pinned = not note.is_pinned
    elif action == "archive":
        note.is_archived = not note.is_archived
    elif action == "delete":
        return _trash(request, note, _("Note: %(title)s") % {"title": note.display_title}, reverse("work:notes"))
    elif action == "to_task":
        task = Task.objects.create(owner=request.user, title=note.display_title[:300], notes=note.body, project=note.project,
                                   order=services.next_order(request.user, Status.TODO))
        task.tags.set(note.tags.all())
        return ok(url=reverse("work:task", args=[task.pk]))
    note.save(update_fields=["is_pinned", "is_archived", "updated_at"])
    return ok(pinned=note.is_pinned, archived=note.is_archived)


# ── Habits, journal, focus, entries, snippets ─────────────────────────────
@work_required
@require_POST
def habit_check(request, pk):
    habit = get_object_or_404(Habit, pk=pk, owner=request.user)
    day = parse_date(request.POST.get("date", "") or "") or timezone.localdate()
    if day > timezone.localdate():
        return bad(_("That day hasn't come yet."))
    if request.POST.get("done", "1") == "1":
        HabitCheck.objects.get_or_create(habit=habit, date=day)
    else:
        HabitCheck.objects.filter(habit=habit, date=day).delete()
    checked = set(habit.checks.filter(date__gte=day - timedelta(days=400)).values_list("date", flat=True))
    return ok(done=day in checked, streak=services.habit_streak(habit, checked, timezone.localdate()))


JOURNAL_FIELDS = ("plan", "wins", "blockers", "notes")


@work_required
@require_POST
def journal_save(request):
    day = parse_date(request.POST.get("date", "") or "")
    if day is None:
        return bad("date")
    entry, _created = JournalEntry.objects.get_or_create(owner=request.user, date=day)
    for name in JOURNAL_FIELDS:
        if name in request.POST:
            setattr(entry, name, request.POST[name])
    for name in ("mood", "energy"):
        if name in request.POST:
            value = request.POST[name]
            setattr(entry, name, int(value) if value.isdigit() and 1 <= int(value) <= 5 else None)
    entry.save()
    return ok(saved=timezone.localtime(entry.updated_at).strftime("%H:%M"))


@work_required
@require_POST
def focus_log(request):
    """A finished focus session, kept as time spent on its task."""
    user = request.user
    start, end = _when(request, "started_at"), _when(request, "ended_at")
    if not (start and end) or end <= start or end - start > timedelta(hours=4):
        return bad("times")
    task = Task.objects.filter(owner=user, pk=request.POST.get("task") or 0).first()
    entry = TimeEntry.objects.create(owner=user, task=task, project=task.project if task else None, kind=EntryKind.FOCUS,
                                     description=request.POST.get("description", "").strip()[:300],
                                     started_at=services._sane(start), ended_at=services._sane(end))
    return ok(id=entry.pk, today=_today_seconds(user))


@work_required
@require_POST
def entry_delete(request, pk):
    entry = get_object_or_404(TimeEntry, pk=pk, owner=request.user)
    return _trash(request, entry, _("Time: %(what)s · %(time)s") % {"what": entry.label, "time": services.hm(entry.seconds)}, reverse("work:time"))


@work_required
@require_POST
def entry_continue(request, pk):
    """Start a new timer for the same work."""
    e = get_object_or_404(TimeEntry, pk=pk, owner=request.user)
    entry = services.start_timer(request.user, task=e.task, project=e.project, description=e.description, at=_when(request, "at"))
    return ok(running=entry_json(entry), today=_today_seconds(request.user))


@work_required
@require_POST
def snippet_action(request, pk):
    snippet = get_object_or_404(Snippet, pk=pk, owner=request.user)
    action = request.POST.get("action")
    if action == "copied":
        Snippet.objects.filter(pk=snippet.pk).update(uses=snippet.uses + 1)
        return ok(uses=snippet.uses + 1)
    if action == "favorite":
        snippet.is_favorite = not snippet.is_favorite
        snippet.save(update_fields=["is_favorite", "updated_at"])
        return ok(favorite=snippet.is_favorite)
    if action == "delete":
        return _trash(request, snippet, _("Snippet: %(title)s") % {"title": snippet.title}, reverse("work:snippets"))
    return bad("action")


@work_required
@require_GET
def search(request):
    """Command palette (Ctrl+K): tasks, notes, projects, goals, learning and snippets matching the text."""
    q = request.GET.get("q", "").strip()
    if len(q) < 2:
        return ok(results=[])
    user, out = request.user, []
    for t in Task.objects.filter(owner=user).filter(Q(title__icontains=q) | Q(link__icontains=q)).select_related("project").order_by("status", "-updated_at")[:7]:
        out.append({"kind": "task", "title": t.title, "url": reverse("work:task", args=[t.pk]), "done": t.is_done, "id": t.pk,
                    "meta": " · ".join(x for x in (t.project.name if t.project_id else "", t.link_label) if x)})
    for n in Note.objects.filter(owner=user, is_archived=False).filter(Q(title__icontains=q) | Q(body__icontains=q))[:5]:
        out.append({"kind": "note", "title": n.display_title, "url": reverse("work:note", args=[n.pk])})
    for p in Project.objects.filter(owner=user, name__icontains=q)[:3]:
        out.append({"kind": "project", "title": p.name, "url": reverse("work:project", args=[p.pk]), "meta": p.client})
    for g in Goal.objects.filter(owner=user, title__icontains=q)[:3]:
        out.append({"kind": "goal", "title": g.title, "url": reverse("work:goal", args=[g.pk]), "meta": g.get_status_display()})
    for item in LearningItem.objects.filter(owner=user).filter(Q(title__icontains=q) | Q(author__icontains=q))[:3]:
        out.append({"kind": "learning", "title": item.title, "url": reverse("work:learning_edit", args=[item.pk]),
                    "meta": " · ".join(x for x in (item.get_kind_display(), item.author) if x)})
    for sn in Snippet.objects.filter(owner=user).filter(Q(title__icontains=q) | Q(description__icontains=q))[:3]:
        out.append({"kind": "snippet", "title": sn.title, "url": reverse("work:snippets") + "?q=" + quote(sn.title), "meta": sn.get_language_display()})
    return ok(results=out)


# ── Goals ─────────────────────────────────────────────────────────────────
@work_required
@require_POST
def goal_step(request, pk):
    """Add a milestone (text) or change one (step, done / text / delete)."""
    goal = get_object_or_404(Goal, pk=pk, owner=request.user)
    sid = request.POST.get("step")
    if not sid:
        text = request.POST.get("text", "").strip()
        if not text:
            return bad(_("Type the milestone."))
        last = goal.steps.order_by("-order").first()
        step = goal.steps.create(text=text[:300], order=(last.order + 1) if last else 1)
    else:
        step = get_object_or_404(GoalStep, pk=sid, goal=goal)
        action = request.POST.get("action")
        if action == "delete":
            step.delete()
            step = None
        elif action == "text":
            step.text = request.POST.get("text", "").strip()[:300] or step.text
            step.save(update_fields=["text"])
        else:
            step.done = request.POST.get("done", "1") == "1"
            step.done_at = timezone.now() if step.done else None
            step.save(update_fields=["done", "done_at"])
    Goal.objects.filter(pk=goal.pk).update(updated_at=timezone.now())
    goal = services.with_progress([goal])[0]
    return ok(id=step.pk if step else None, text=step.text if step else "", pct=goal.pct, steps=list(goal.steps_count))


@work_required
@require_POST
def goal_value(request, pk):
    """Where a measured goal is now (or a step up/down from it)."""
    from decimal import Decimal, InvalidOperation

    goal = get_object_or_404(Goal, pk=pk, owner=request.user)
    now = goal.current_value if goal.current_value is not None else goal.start_value
    try:
        if "add" in request.POST:
            now += Decimal(request.POST["add"])
        else:
            now = Decimal(request.POST.get("value", ""))
    except InvalidOperation:
        return bad(_("Type a number."))
    goal.current_value = now
    goal.save(update_fields=["current_value", "updated_at"])
    reached = goal.has_number and goal.status == GoalStatus.ACTIVE and (
        now >= goal.target_value if goal.target_value > goal.start_value else now <= goal.target_value)
    return ok(value=str(now.normalize()), pct=goal.progress(), reached=reached)


# ── Learning ──────────────────────────────────────────────────────────────
@work_required
@require_POST
def learning_add(request):
    """One line: a title, or a link (an article, a talk) to read later."""
    text = request.POST.get("text", "").strip()
    if not text:
        return bad(_("Type a title or paste a link."))
    url = ""
    m = re.search(r"https?://\S+", text)
    if m:
        url, text = m.group(0)[:500], (text[:m.start()] + text[m.end():]).strip()
    kind = request.POST.get("kind") if request.POST.get("kind") in LearningKind.values else (
        LearningKind.VIDEO if re.search(r"youtube\.com|youtu\.be|vimeo\.com", url) else LearningKind.ARTICLE if url else LearningKind.BOOK)
    item = LearningItem.objects.create(owner=request.user, title=(text or link_label(url) or url)[:250], url=url, kind=kind,
                                       unit=LearningUnit.PERCENT if url else LearningUnit.PAGES,
                                       status=request.POST.get("status") if request.POST.get("status") in LearningStatus.values else LearningStatus.QUEUED)
    return ok(id=item.pk, url=reverse("work:learning_edit", args=[item.pk]))


@work_required
@require_POST
def learning_update(request, pk):
    """+N progress, or a new status (starting / finishing sets the dates)."""
    item = get_object_or_404(LearningItem, pk=pk, owner=request.user)
    today = timezone.localdate()
    if "add" in request.POST:
        try:
            step = int(request.POST["add"])
        except ValueError:
            return bad("add")
        item.progress = max(0, item.progress + step)
        if item.total:
            item.progress = min(item.progress, item.total)
        if item.unit == "percent":
            item.progress = min(item.progress, 100)
        if item.status == LearningStatus.QUEUED and item.progress:
            item.status, item.started_on = LearningStatus.ACTIVE, item.started_on or today
    status = request.POST.get("status")
    if status in LearningStatus.values:
        item.status = status
        if status in (LearningStatus.ACTIVE, LearningStatus.DONE):
            item.started_on = item.started_on or today
        item.finished_on = (item.finished_on or today) if status == LearningStatus.DONE else None
        if status == LearningStatus.DONE and item.total:
            item.progress = item.total
    item.save()
    return ok(progress=item.progress, total=item.total, percent=item.percent, status=item.status,
              status_label=item.get_status_display())
