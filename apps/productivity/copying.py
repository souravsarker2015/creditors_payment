"""Making tasks again: a copy of one task, a task kept as a template, and a
whole project copied with its open work.

A copy keeps what describes the work (notes, priority, estimate, tags, link,
goal, the checklist — unticked — and the subtasks) and leaves out what
happened to it (time tracked, comments, done). Templates store due dates as
"so many days after you use it", so a template made today works next month.
"""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from . import services
from .models import Project, Status, Task, TaskTemplate

COPIED = ("notes", "priority", "estimate_minutes", "link", "goal_id", "repeat", "repeat_every", "repeat_days", "repeat_from_done", "waiting_for")


def _clone(task, **changes):
    fields = {f: getattr(task, f) for f in COPIED}
    fields.update(owner=task.owner, title=task.title, project=task.project, due_date=task.due_date, start_date=task.start_date,
                  status=Status.TODO if task.status == Status.DONE else task.status, order=services.next_order(task.owner, Status.TODO))
    fields.update(changes)
    new = Task.objects.create(**fields)
    new.tags.set(task.tags.all())
    for item in task.checklist.all():
        new.checklist.create(text=item.text, order=item.order)
    return new


@transaction.atomic
def duplicate(task):
    """A copy of a task, right beside it, with its open subtasks copied too."""
    copy = _clone(task, title=(_("%(title)s (copy)") % {"title": task.title})[:300], parent=task.parent)
    for sub in task.subtasks.exclude(status=Status.DONE):
        _clone(sub, parent=copy)
    return copy


# ── Templates ─────────────────────────────────────────────────────────────
def _offset(day, base):
    return (day - base).days if day else None


def save_template(task, name):
    base = timezone.localdate()
    data = {
        "title": task.title, "notes": task.notes, "priority": task.priority, "estimate": task.estimate_minutes,
        "tags": list(task.tags.values_list("name", flat=True)), "project": task.project_id, "link": task.link,
        "due_in": _offset(task.due_date, base), "start_in": _offset(task.start_date, base),
        "checklist": list(task.checklist.values_list("text", flat=True)),
        "subtasks": [{"title": s.title, "estimate": s.estimate_minutes, "priority": s.priority, "due_in": _offset(s.due_date, base),
                      "checklist": list(s.checklist.values_list("text", flat=True))}
                     for s in task.subtasks.exclude(status=Status.DONE).order_by("order", "pk")],
    }
    return TaskTemplate.objects.create(owner=task.owner, name=(name or task.title)[:120], data=data)


def _day(base, n):
    return base + timedelta(days=n) if isinstance(n, int) else None


@transaction.atomic
def use_template(tpl, project=None, base=None):
    """A new task (with its checklist and subtasks) from a template. Dates
    count from `base` (today)."""
    base = base or timezone.localdate()
    d, user = tpl.data or {}, tpl.owner
    if project is None and d.get("project"):
        project = Project.objects.filter(owner=user, pk=d["project"], is_archived=False).first()
    task = Task.objects.create(owner=user, title=(d.get("title") or tpl.name)[:300], notes=d.get("notes") or "", priority=d.get("priority") or 0,
                               estimate_minutes=d.get("estimate"), project=project, link=d.get("link") or "",
                               due_date=_day(base, d.get("due_in")), start_date=_day(base, d.get("start_in")),
                               order=services.next_order(user, Status.TODO))
    if d.get("tags"):
        task.tags.set(services.tags_named(user, d["tags"]))
    for i, text in enumerate(d.get("checklist") or []):
        task.checklist.create(text=text[:300], order=i)
    for s in d.get("subtasks") or []:
        sub = Task.objects.create(owner=user, title=(s.get("title") or "")[:300] or "…", parent=task, project=project, priority=s.get("priority") or 0,
                                  estimate_minutes=s.get("estimate"), due_date=_day(base, s.get("due_in")), order=services.next_order(user, Status.TODO))
        for i, text in enumerate(s.get("checklist") or []):
            sub.checklist.create(text=text[:300], order=i)
    return task


# ── A whole project ───────────────────────────────────────────────────────
@transaction.atomic
def duplicate_project(project, keep_dates=False):
    """A copy of a project with its open tasks (and their subtasks and checklists) —
    for work that comes round again: a new client, the next release."""
    name = (_("%(name)s (copy)") % {"name": project.name})[:120]
    n = 2
    while Project.objects.filter(owner=project.owner, name__iexact=name).exists():
        name = (_("%(name)s (copy %(n)s)") % {"name": project.name, "n": n})[:120]
        n += 1
    copy = Project.objects.create(owner=project.owner, name=name, color=project.color, client=project.client, description=project.description,
                                  estimate_hours=project.estimate_hours, hourly_rate=project.hourly_rate, order=project.order + 1)
    dates = {} if keep_dates else {"due_date": None, "start_date": None}
    for t in project.tasks.filter(parent__isnull=True).exclude(status=Status.DONE).order_by("order", "pk"):
        new = _clone(t, project=copy, status=Status.TODO if t.status == Status.DOING else t.status, **dates)
        for sub in t.subtasks.exclude(status=Status.DONE):
            _clone(sub, project=copy, parent=new, status=Status.TODO, **dates)
    return copy

