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
from django.utils.formats import date_format
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

from apps.trash.services import trash

from . import cards, diagrams, services
from .access import work_required
from .models import (
    Card, ChecklistItem, Color, Deck, Diagram, DiagramKind, DiagramVersion, EntryKind, Goal, GoalStatus, GoalStep, Habit, HabitCheck, JournalEntry, LearningItem, LearningKind, LearningStatus,
    LearningUnit, Note, NoteVersion, Priority, Project, SavedView, Snippet, Sprint, Status, Task, TaskActivity, TimeEntry, WorkSettings, link_label,
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
def task_row(request, task, **extra):
    return render_to_string("work/partials/task_row.html", {"t": task, "today": timezone.localdate(), **extra}, request=request)


@work_required
@require_POST
def task_add(request):
    user = request.user
    status = request.POST.get("status") if request.POST.get("status") in Status.values else Status.TODO
    project = Project.objects.filter(owner=user, pk=request.POST.get("project") or 0).first()
    goal = Goal.objects.filter(owner=user, pk=request.POST.get("goal") or 0).first()
    my_day = request.POST.get("my_day") or ""
    task = services.create_from_quick(user, request.POST.get("text", ""), status=status, project=project, goal=goal,
                                      my_day=my_day == "1" or parse_date(my_day) or False, due=parse_date(request.POST.get("due") or ""))
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
    if task.is_done:
        free = services.unblocked_by(task)
        for t in free:
            from .activity import note

            note(t, field="unblocked", title=task.title)
        if free:
            data["unblocked"] = [t.title for t in free[:3]]
    return ok(**data)


# ── Subtasks, copies and templates ─────────────────────────────────────────
@work_required
@require_POST
def subtask_add(request, pk):
    parent = get_object_or_404(Task, pk=pk, owner=request.user)
    if parent.parent_id:
        return bad(_("Subtasks go one level deep: this is already a subtask."))
    sub = services.add_subtask(parent, request.POST.get("text", ""))
    if sub is None:
        return bad(_("Type what needs doing."))
    return ok(id=sub.pk, html=task_row(request, sub, in_parent=True), counts=parent.subtask_counts)


@work_required
@require_POST
def task_duplicate(request, pk):
    from .copying import duplicate

    task = get_object_or_404(Task, pk=pk, owner=request.user)
    copy = duplicate(task)
    return ok(id=copy.pk, html=task_row(request, copy), url=reverse("work:task", args=[copy.pk]), title=copy.title)


@work_required
@require_POST
def task_template(request, pk):
    from .copying import save_template

    task = get_object_or_404(Task, pk=pk, owner=request.user)
    tpl = save_template(task, request.POST.get("name", "").strip())
    return ok(id=tpl.pk, name=tpl.name, url=reverse("work:templates"))


FILE_MAX_MB = 20
FILES_PER_TASK = 50


@work_required
@require_POST
def task_files(request, pk):
    """Files dropped or picked onto a task (any kind; the picture formats show as thumbnails)."""
    from .activity import note
    from .models import TaskFile

    task = get_object_or_404(Task, pk=pk, owner=request.user)
    files = request.FILES.getlist("file")
    if not files:
        return bad(_("Choose a file."))
    if task.files.count() + len(files) > FILES_PER_TASK:
        return bad(_("A task can keep up to %(n)s files.") % {"n": FILES_PER_TASK})
    too_big = [f.name for f in files if f.size > FILE_MAX_MB * 1024 * 1024]
    if too_big:
        return bad(_("“%(name)s” is too big (over %(mb)s MB).") % {"name": too_big[0], "mb": FILE_MAX_MB})
    rows = []
    for f in files:
        name = (f.name or "file").replace("\\", "/").rsplit("/", 1)[-1].strip()[:200] or "file"
        tf = TaskFile.objects.create(owner=request.user, task=task, file=f, name=name, size=f.size)
        note(task, field="file", added=True, name=name)
        rows.append(render_to_string("work/partials/task_file.html", {"f": tf}, request=request))
    return ok(html="".join(rows), count=task.files.count())


@work_required
@require_POST
def task_file_delete(request, pk):
    from .activity import note
    from .models import TaskFile

    tf = get_object_or_404(TaskFile, pk=pk, owner=request.user)
    task, name = tf.task, tf.name
    tf.file.delete(save=False)
    tf.delete()
    note(task, field="file", added=False, name=name)
    return ok(count=task.files.count())


# ── Task dependencies, comments and saved views ─────────────────────────────
@work_required
@require_POST
def task_blockers(request, pk):
    """add=<task id> or remove=<task id>: what this task waits on."""
    from .activity import note

    task = get_object_or_404(Task, pk=pk, owner=request.user)
    if request.POST.get("add"):
        other = get_object_or_404(Task, pk=request.POST["add"], owner=request.user)
        if not services.can_block(task, other):
            return bad(_("That would make the two tasks wait on each other."))
        if not task.blocked_by.filter(pk=other.pk).exists():
            task.blocked_by.add(other)
            note(task, field="blocked_by", added=True, title=other.title)
    elif request.POST.get("remove"):
        other = task.blocked_by.filter(pk=request.POST["remove"]).first()
        if other:
            task.blocked_by.remove(other)
            note(task, field="blocked_by", added=False, title=other.title)
    html = render_to_string("work/partials/blockers.html", {"task": task}, request=request)
    return ok(html=html, blocked=task.is_blocked)


@work_required
@require_POST
def task_comment(request, pk):
    task = get_object_or_404(Task, pk=pk, owner=request.user)
    text = request.POST.get("text", "").strip()[:5000]
    if not text:
        return bad(_("Write something first."))
    a = TaskActivity.objects.create(task=task, kind=TaskActivity.Kind.COMMENT, text=text)
    return ok(html=render_to_string("work/partials/activity_item.html", {"a": a}, request=request))


@work_required
@require_POST
def comment_delete(request, pk):
    a = get_object_or_404(TaskActivity, pk=pk, task__owner=request.user, kind=TaskActivity.Kind.COMMENT)
    a.delete()
    return ok()


VIEW_KEYS = ("view", "q", "project", "tag", "priority", "due", "goal", "done", "blocked", "sub", "by", "sort", "sprint", "kind")


@work_required
@require_POST
def view_save(request):
    """Keep the task list's current filters under a name."""
    from django.http import QueryDict

    name = request.POST.get("name", "").strip()[:60]
    if not name:
        return bad(_("Give the view a name."))
    raw = QueryDict(request.POST.get("query", "").lstrip("?"))
    query = "&".join(f"{k}={quote(raw[k])}" for k in VIEW_KEYS if raw.get(k))
    if SavedView.objects.filter(owner=request.user).count() >= 30:
        return bad(_("You can keep up to 30 views."))
    v = SavedView.objects.create(owner=request.user, name=name, query=query,
                                 order=SavedView.objects.filter(owner=request.user).count())
    return ok(id=v.pk, name=v.name, url=reverse("work:tasks") + "?" + query + ("&" if query else "") + f"sv={v.pk}")


@work_required
@require_POST
def view_action(request, pk):
    v = get_object_or_404(SavedView, pk=pk, owner=request.user)
    if request.POST.get("action") == "delete":
        v.delete()
        return ok()
    name = request.POST.get("name", "").strip()[:60]
    if name:
        v.name = name
        v.save(update_fields=["name"])
    return ok(name=v.name)


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


TASK_FIELDS = {"title", "priority", "due_date", "start_date", "sprint", "my_day", "project", "status", "notes", "estimate_minutes", "link", "goal", "waiting_for",
               "scheduled_at"}


def _local_dt(value):
    """'2026-10-12T14:30' (the person's own clock) → an aware time, or None."""
    when = parse_datetime(value) if value else None
    if when is not None and timezone.is_naive(when):
        when = timezone.make_aware(when, timezone.get_current_timezone())
    return when


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
        elif name == "start_date":
            task.start_date = parse_date(value) if value else None
        elif name == "sprint":
            task.sprint = Sprint.objects.filter(owner=request.user, pk=value or 0, completed_at__isnull=True).first()
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
        elif name == "scheduled_at":       # a block on the day planner (empty = take it off)
            task.scheduled_at = _local_dt(value)
            if value and task.scheduled_at is None:
                return bad("scheduled_at")
            if task.scheduled_at:
                day = timezone.localtime(task.scheduled_at).date()
                if task.my_day != day and task.due_date != day:
                    task.my_day = day
    if request.POST.get("later") == "1" and task.my_day and task.due_date and task.due_date < task.my_day:
        task.due_date = task.my_day            # "do it later": a due date that has come moves along, so it's really out of sight
    if "my_day" in request.POST and "scheduled_at" not in request.POST and task.scheduled_at:
        if timezone.localtime(task.scheduled_at).date() != task.my_day:     # moved to another day: off the old timeline
            task.scheduled_at = None
    if task.start_date and task.due_date and task.start_date > task.due_date:
        if "start_date" in request.POST and "due_date" not in request.POST:
            task.due_date = task.start_date    # starting after it was due: it's due that day too
        else:
            task.start_date = task.due_date    # due sooner than it was to start: it starts that day too
    task.save()
    return ok(html=task_row(request, task), scheduled_at=timezone.localtime(task.scheduled_at).strftime("%Y-%m-%dT%H:%M") if task.scheduled_at else "",
              my_day=task.my_day.isoformat() if task.my_day else "")


@work_required
@require_POST
def plan_action(request):
    """The day planner's "Fill my day" and "Clear the plan"."""
    from .views import plan_data

    day = parse_date(request.POST.get("date", "")) or timezone.localdate()
    action = request.POST.get("action")
    if action == "fill":
        placed, left = services.fill_day(request.user, day)
        return ok(placed=len(placed), left=len(left), plan=plan_data(request.user, day))
    if action == "clear":
        services.clear_plan(request.user, day)
        return ok(plan=plan_data(request.user, day))
    return bad("action")


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
    if note.pk and "body" in request.POST and request.POST["body"] != note.body:
        services.remember_note(note)        # what it said before this sitting, at most every few minutes
    for name in ("title", "body"):
        if name in request.POST:
            setattr(note, name, request.POST[name])
    if "project" in request.POST:
        note.project = Project.objects.filter(owner=user, pk=request.POST["project"] or 0).first()
    if "color" in request.POST:
        note.color = request.POST["color"] if request.POST["color"] in Color.values else ""
    if request.POST.get("pinned") == "1" and not note.pk:
        note.is_pinned = True
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
    elif action == "color":
        note.color = request.POST.get("color") if request.POST.get("color") in Color.values else ""
    elif action == "archive":
        note.is_archived = not note.is_archived
    elif action == "delete":
        return _trash(request, note, _("Note: %(title)s") % {"title": note.display_title}, reverse("work:notes"))
    elif action == "todos":            # every "- [ ] …" line becomes a task
        made = services.note_todos_to_tasks(request.user, note)
        if not made:
            return bad(_("No open to-dos here. Write them as “- [ ] something to do”."))
        note.refresh_from_db()
        return ok(count=len(made), body=note.body, saved=timezone.localtime(note.updated_at).strftime("%H:%M"),
                  updated=int(note.updated_at.timestamp() * 1000))
    elif action == "cards":            # every "question :: answer" line becomes a flashcard
        pairs = cards.parse_pairs(note.body)
        if not pairs:
            return bad(_("Write cards as “question :: answer”, one a line."))
        deck = cards.deck_named(request.user, note.display_title)
        return ok(count=cards.add_cards(request.user, deck, pairs), url=reverse("work:deck", args=[deck.pk]))
    elif action == "mindmap":          # headings and lists become a mind map
        data = diagrams.outline_map(note.display_title, note.body)
        if data is None:
            return bad(_("Write some headings or a list first — they become the branches."))
        d = Diagram.objects.create(owner=request.user, kind=DiagramKind.MINDMAP, title=note.display_title[:200], data=data, project=note.project,
                                   notes=_("Made from the note “%(title)s”.") % {"title": note.display_title})
        return ok(url=reverse("work:diagram", args=[d.pk]))
    elif action == "restore":          # an earlier version comes back (what's there now is kept too)
        v = get_object_or_404(NoteVersion, pk=request.POST.get("version") or 0, note=note)
        services.remember_note(note, force=True)
        note.title, note.body = v.title, v.body
        note.save()
        return ok(url=reverse("work:note", args=[note.pk]))
    elif action == "forget":
        NoteVersion.objects.filter(pk=request.POST.get("version") or 0, note=note).delete()
        return ok()
    elif action == "to_task":
        task = Task.objects.create(owner=request.user, title=note.display_title[:300], notes=note.body, project=note.project,
                                   order=services.next_order(request.user, Status.TODO))
        task.tags.set(note.tags.all())
        return ok(url=reverse("work:task", args=[task.pk]))
    note.save(update_fields=["is_pinned", "is_archived", "color", "updated_at"])
    return ok(pinned=note.is_pinned, archived=note.is_archived, color=note.color)


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
    same = TimeEntry.objects.filter(owner=user, kind=EntryKind.FOCUS, started_at=services._sane(start)).first()
    if same:      # the same session sent twice (two tabs, or a retry after a lost answer): keep one
        return ok(id=same.pk, today=_today_seconds(user))
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


# ── Diagrams ──────────────────────────────────────────────────────────────
@work_required
@require_POST
def diagram_save(request, pk):
    """Autosave from a diagram page: title, the drawing (shapes or text), notes and its picture."""
    d = get_object_or_404(Diagram, pk=pk, owner=request.user)
    post = request.POST
    if "source" in post or "data" in post:
        diagrams.remember(d)          # what it was before this sitting, at most every few minutes
    if "source" in post and not d.is_visual:
        if len(post["source"]) > diagrams.MAX_SOURCE:
            return bad(_("This diagram is too big to save."))
        d.source = post["source"]
        d.kind = diagrams.kind_of_source(d.source, d.kind)
    if "data" in post:
        try:
            d.data = diagrams.clean_data(d.kind, post["data"])
        except diagrams.Invalid as e:
            return bad(str(e))
    if "notes" in post:
        d.notes = post["notes"][:diagrams.MAX_SOURCE]
    if "preview" in post:
        d.preview = diagrams.clean_preview(post["preview"])
    if "project" in post:
        d.project = Project.objects.filter(owner=request.user, pk=post["project"] or 0).first()
    if "title" in post:
        d.title = post["title"].strip()[:200] or d.title
    d.save()
    return ok(saved=timezone.localtime(d.updated_at).strftime("%H:%M"), updated=int(d.updated_at.timestamp() * 1000), kind=d.kind)


@work_required
@require_POST
def diagram_action(request, pk):
    d = get_object_or_404(Diagram, pk=pk, owner=request.user)
    action = request.POST.get("action")
    if action == "pin":
        d.is_pinned = not d.is_pinned
        d.save(update_fields=["is_pinned"])
        return ok(pinned=d.is_pinned)
    if action == "archive":
        d.is_archived = not d.is_archived
        d.save(update_fields=["is_archived"])
        return ok(archived=d.is_archived, url=reverse("work:diagrams"))
    if action == "delete":
        return _trash(request, d, _("Diagram: %(title)s") % {"title": d.title}, reverse("work:diagrams"))
    if action == "duplicate":
        copy = Diagram.objects.create(owner=request.user, kind=d.kind, title=(_("%(title)s (copy)") % {"title": d.title})[:200],
                                      source=d.source, data=d.data, notes=d.notes, preview=d.preview, project=d.project)
        return ok(url=reverse("work:diagram", args=[copy.pk]))
    if action == "tasks":               # a mind map branch: each idea under it becomes a task
        if d.kind != DiagramKind.MINDMAP:
            return bad(_("Only mind maps can make tasks."))
        titles = diagrams.branch_titles(d.data, request.POST.get("node", ""))
        if not titles:
            return bad(_("Pick an idea with something written in it."))
        for title in titles:
            Task.objects.create(owner=request.user, title=title, project=d.project, order=services.next_order(request.user, Status.TODO))
        return ok(count=len(titles), url=reverse("work:tasks"))
    if action == "cards":               # a mind map as flashcards: each idea asks for the ideas under it
        if d.kind != DiagramKind.MINDMAP:
            return bad(_("Only mind maps can make flashcards."))
        pairs = cards.mindmap_pairs(d.data)
        if not pairs:
            return bad(_("Add ideas under an idea to make a card from it."))
        deck = cards.deck_named(request.user, d.title)
        return ok(count=cards.add_cards(request.user, deck, pairs), url=reverse("work:deck", args=[deck.pk]))
    if action == "version":             # keep it as it is now, with a name
        v = diagrams.remember(d, name=request.POST.get("name", "").strip() or _("Saved by hand"), force=True)
        if v is None:
            return bad(_("Draw something first."))
        return ok(version=version_json(v))
    if action == "restore":
        v = get_object_or_404(DiagramVersion, pk=request.POST.get("version") or 0, diagram=d)
        diagrams.bring_back(d, v)
        return ok(url=reverse("work:diagram", args=[d.pk]))
    if action == "forget":              # throw one version away
        DiagramVersion.objects.filter(pk=request.POST.get("version") or 0, diagram=d).delete()
        return ok()
    if action == "note":                # the diagram as a note: an outline, the Mermaid text or the design notes
        if d.kind == DiagramKind.MINDMAP:
            body = diagrams.outline_text(d.data)
        elif d.kind == DiagramKind.DRAWING:
            parts = [f"- {' '.join(str(n.get('label') or '').split())}" for n in d.data.get("nodes", []) if str(n.get("label") or "").strip()]
            body = "\n".join([f"# {d.title}", "", *parts, "", d.notes]).strip() + "\n"
        elif d.kind == DiagramKind.SYSTEM:
            parts = ["- **%s**%s" % (n.get("label") or n.get("type"), f" — {n['tech']}" if n.get("tech") else "")
                     for n in d.data.get("nodes", []) if n.get("type") not in ("zone", "note")]
            body = "\n".join([f"# {d.title}", "", _("Components") + ":", *parts, "", d.notes]).strip() + "\n"
        else:
            body = f"# {d.title}\n\n```mermaid\n{d.source.strip()}\n```\n" + (f"\n{d.notes}\n" if d.notes else "")
        note = Note.objects.create(owner=request.user, title=d.title, body=body, project=d.project)
        return ok(url=reverse("work:note", args=[note.pk]))
    return bad(_("Not allowed."))


def version_json(v):
    when = timezone.localtime(v.created_at)
    return {"id": v.pk, "name": v.name, "title": v.title, "when": when.isoformat(), "time": date_format(when, "j M, H:i"),
            "picture": reverse("work:diagram_version_preview", args=[v.diagram_id, v.pk]) if v.preview else ""}


@work_required
@require_GET
def diagram_versions(request, pk):
    d = get_object_or_404(Diagram, pk=pk, owner=request.user)
    return ok(versions=[version_json(v) for v in d.versions.defer("source", "data", "notes")[:60]])


@work_required
@require_GET
def note_versions(request, pk):
    note = get_object_or_404(Note, pk=pk, owner=request.user)
    out = []
    for v in note.versions.all()[:60]:
        when = timezone.localtime(v.created_at)
        out.append({"id": v.pk, "title": v.title, "body": v.body, "time": date_format(when, "j M, H:i"), "when": when.isoformat(),
                    "words": len(v.body.split())})
    return ok(versions=out)


# Pictures in notes: only these, checked by their first bytes (an SVG could carry a script, so it's not allowed).
IMAGE_KINDS = {b"\x89PNG\r\n\x1a\n": ".png", b"\xff\xd8\xff": ".jpg", b"GIF87a": ".gif", b"GIF89a": ".gif"}
IMAGE_MAX_MB = 8


def _image_ext(head):
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    return next((ext for magic, ext in IMAGE_KINDS.items() if head.startswith(magic)), None)


@work_required
@require_POST
def image_upload(request):
    """A picture pasted, dropped or picked into a note (or any Markdown box). Returns its private address."""
    from .models import NoteImage

    f = request.FILES.get("image")
    if not f:
        return bad(_("Choose a picture."))
    if f.size > IMAGE_MAX_MB * 1024 * 1024:
        return bad(_("The picture is too big (over %(mb)s MB).") % {"mb": IMAGE_MAX_MB})
    head = f.read(16)
    f.seek(0)
    ext = _image_ext(head)
    if ext is None:
        return bad(_("Only PNG, JPEG, GIF or WebP pictures can go in a note."))
    name = (request.POST.get("name") or f.name or "").strip()[:200]
    f.name = "image" + ext
    note = Note.objects.filter(owner=request.user, pk=request.POST.get("note") or 0).first()
    img = NoteImage.objects.create(owner=request.user, note=note, file=f, name=name, size=f.size)
    url = reverse("work:note_image", args=[img.pk])
    alt = name.rsplit(".", 1)[0].replace("[", "").replace("]", "") or _("picture")
    return ok(id=img.pk, url=url, markdown=f"![{alt}]({url})")


@work_required
@require_GET
def cards_due(request):
    """How many flashcards are waiting (for the daily reminder)."""
    return ok(due=cards.due_count(request.user), url=reverse("work:card_review"))


@work_required
@require_GET
def diagram_list(request):
    """The person's diagrams, for putting one in a note."""
    q = request.GET.get("q", "").strip()
    qs = Diagram.objects.filter(owner=request.user, is_archived=False).exclude(preview="").only("pk", "title", "kind", "updated_at")
    if q:
        qs = qs.filter(title__icontains=q)
    return ok(items=[{"id": d.pk, "title": d.title, "kind": d.get_kind_display(), "url": reverse("work:diagram", args=[d.pk]),
                      "picture": reverse("work:diagram_preview", args=[d.pk]),
                      "thumb": reverse("work:diagram_preview", args=[d.pk]) + f"?v={int(d.updated_at.timestamp())}"} for d in qs[:40]])


# ── Flashcards ────────────────────────────────────────────────────────────
def card_json(c, deck_info=False):
    today = timezone.localdate()
    out = {"id": c.pk, "front": c.front, "back": c.back, "isNew": c.is_new, "paused": c.is_suspended, "interval": c.interval,
           "due": c.due.isoformat(), "lapses": c.lapses, "previews": cards.previews(c),
           "dueText": _("new") if c.is_new else (_("due") if c.due <= today else cards.wait_label((c.due - today).days))}
    if deck_info:
        out.update(deck=c.deck.name, color=c.deck.color, deckId=c.deck_id)
    return out


@work_required
@require_POST
def card_add(request):
    """One card (front, back), or many from text: one "question :: answer" a line.
    Without a deck (shared from another app) it goes in "My cards"."""
    if request.POST.get("deck"):
        deck = get_object_or_404(Deck, pk=request.POST["deck"], owner=request.user)
    else:
        deck = cards.deck_named(request.user, _("My cards"))
    if "text" in request.POST:
        pairs = cards.parse_pairs(request.POST["text"])
        if not pairs:
            return bad(_("Write cards as “question :: answer”, one a line."))
        added = cards.add_cards(request.user, deck, pairs)
        return ok(added=added, skipped=len(pairs) - added)
    front = request.POST.get("front", "").strip()
    if not front:
        return bad(_("Write the question."))
    card = Card.objects.create(owner=request.user, deck=deck, front=front[:cards.MAX_FRONT],
                               back=request.POST.get("back", "").strip()[:cards.MAX_BACK])
    return ok(added=1, card=card_json(card), url=reverse("work:deck", args=[deck.pk]))


@work_required
@require_POST
def card_action(request, pk):
    card = get_object_or_404(Card.objects.select_related("deck"), pk=pk, owner=request.user)
    action = request.POST.get("action")
    if action == "answer":
        try:
            rating = int(request.POST.get("rating", ""))
            cards.answer(card, rating, now=_when(request, "at"))
        except ValueError:
            return bad(_("Not allowed."))
        return ok(again=card.interval == 0, review=card.review.pk, card=card_json(card, deck_info=True))
    if action == "undo":                # take the last answer back (the review's Undo)
        review = card.reviews.filter(pk=request.POST.get("review") or 0).first() or card.reviews.first()
        if review is None or not review.before:
            return bad(_("There's nothing to undo."))
        cards.undo(review)
        return ok(card=card_json(card, deck_info=True))
    if action == "save":
        front = request.POST.get("front", card.front).strip()
        if not front:
            return bad(_("Write the question."))
        card.front, card.back = front[:cards.MAX_FRONT], request.POST.get("back", card.back).strip()[:cards.MAX_BACK]
        card.save(update_fields=["front", "back", "updated_at"])
        return ok(card=card_json(card))
    if action == "pause":
        card.is_suspended = not card.is_suspended
        card.save(update_fields=["is_suspended", "updated_at"])
        return ok(card=card_json(card))
    if action == "reset":
        card.interval, card.ease, card.reps, card.lapses, card.last_reviewed, card.due = 0, 2.5, 0, 0, None, timezone.localdate()
        card.save()
        return ok(card=card_json(card))
    if action == "move":
        deck = get_object_or_404(Deck, pk=request.POST.get("deck") or 0, owner=request.user)
        card.deck = deck
        card.save(update_fields=["deck", "updated_at"])
        return ok(deck=deck.name)
    if action == "delete":
        return _trash(request, card, _("Flashcard: %(text)s") % {"text": card.front[:80]}, reverse("work:deck", args=[card.deck_id]))
    return bad(_("Not allowed."))


@work_required
@require_POST
def deck_action(request, pk):
    deck = get_object_or_404(Deck, pk=pk, owner=request.user)
    action = request.POST.get("action")
    if action == "archive":
        deck.is_archived = not deck.is_archived
        deck.save(update_fields=["is_archived", "updated_at"])
        return ok(archived=deck.is_archived, url=reverse("work:cards"))
    if action == "delete":
        return _trash(request, deck, _("Deck: %(name)s") % {"name": deck.name}, reverse("work:cards"))
    return bad(_("Not allowed."))


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
    """Command palette (Ctrl+K): tasks, notes, projects, goals, learning, diagrams, flashcards and snippets matching the text."""
    q = request.GET.get("q", "").strip()
    if len(q) < 2 and not q.isdigit():
        return ok(results=[])
    user, out = request.user, []
    tasks = Task.objects.filter(owner=user).select_related("project")
    prefix = WorkSettings.for_user(user).key_prefix or "T"
    number = re.fullmatch(rf"(?:#|{re.escape(prefix)}-)?(\d+)", q, re.I)       # "#42", "T-42" or "42": that task
    first = list(tasks.filter(pk=int(number.group(1)))) if number else []      # "#42": that task
    by_title = Q(title__icontains=q) | Q(link__icontains=q)
    deeper = (Q(notes__icontains=q) | Q(files__name__icontains=q)
              | Q(activity__kind=TaskActivity.Kind.COMMENT, activity__text__icontains=q))     # what's written in it, its files, its comments
    found = list(tasks.filter(by_title).order_by("status", "-updated_at")[:7])
    if len(found) < 7:
        found += list(tasks.filter(deeper).exclude(by_title).distinct().order_by("status", "-updated_at")[:7 - len(found)])
    for t in first + [t for t in found if t not in first]:
        out.append({"kind": "task", "title": t.title, "url": reverse("work:task", args=[t.pk]), "done": t.is_done, "id": t.pk,
                    "meta": " · ".join(x for x in (f"{prefix}-{t.pk}", t.project.name if t.project_id else "", t.link_label) if x)})
    for n in Note.objects.filter(owner=user, is_archived=False).filter(Q(title__icontains=q) | Q(body__icontains=q))[:5]:
        out.append({"kind": "note", "title": n.display_title, "url": reverse("work:note", args=[n.pk])})
    for p in Project.objects.filter(owner=user, name__icontains=q)[:3]:
        out.append({"kind": "project", "title": p.name, "url": reverse("work:project", args=[p.pk]), "meta": p.client})
    for g in Goal.objects.filter(owner=user, title__icontains=q)[:3]:
        out.append({"kind": "goal", "title": g.title, "url": reverse("work:goal", args=[g.pk]), "meta": g.get_status_display()})
    for item in LearningItem.objects.filter(owner=user).filter(Q(title__icontains=q) | Q(author__icontains=q))[:3]:
        out.append({"kind": "learning", "title": item.title, "url": reverse("work:learning_edit", args=[item.pk]),
                    "meta": " · ".join(x for x in (item.get_kind_display(), item.author) if x)})
    for dg in Diagram.objects.filter(owner=user, is_archived=False).filter(Q(title__icontains=q) | Q(notes__icontains=q)).only("pk", "title", "kind")[:4]:
        out.append({"kind": "diagram", "title": dg.title, "url": reverse("work:diagram", args=[dg.pk]), "meta": dg.get_kind_display()})
    for c in Card.objects.filter(owner=user).filter(Q(front__icontains=q) | Q(back__icontains=q)).select_related("deck")[:3]:
        out.append({"kind": "card", "title": " ".join(c.front.split())[:120], "url": reverse("work:deck", args=[c.deck_id]) + "?q=" + quote(c.front[:60]),
                    "meta": c.deck.name})
    from .models import Question

    for qn in Question.objects.filter(owner=user).filter(Q(prompt__icontains=q) | Q(companies__icontains=q)).select_related("topic")[:4]:
        out.append({"kind": "question", "title": qn.title, "url": reverse("work:question", args=[qn.pk]), "meta": f"{qn.topic.name} · {qn.get_difficulty_display()}"})
    from .models import ExamNote

    for x in ExamNote.objects.filter(owner=user).filter(Q(question__icontains=q) | Q(answer__icontains=q)).select_related("subject")[:3]:
        out.append({"kind": "exam", "title": " ".join(x.question.split())[:120], "url": reverse("work:exam_subject", args=[x.subject_id]) + f"#q{x.pk}",
                    "meta": x.subject.name})
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
