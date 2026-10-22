"""A task's history, like an issue tracker's: every change to the fields that
matter is noted (from the task page, the board, a quick menu or a bulk action),
and comments can be written alongside. Changes are stored as plain values and
put into words when shown, so they read in whichever language you use."""
from datetime import date, timedelta

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import gettext as _

from .models import Goal, Priority, Project, Sprint, Status, Task, TaskActivity, TaskKind

TRACKED = ("title", "status", "kind", "priority", "points", "due_date", "start_date", "project_id", "goal_id", "sprint_id", "estimate_minutes", "waiting_for")
NAMED = {"project_id": Project, "goal_id": Goal, "sprint_id": Sprint}     # kept with their name, in case they're deleted later


def _plain(field, value):
    if isinstance(value, date):
        return value.isoformat()
    return value


def _label(field, pk):
    if not pk:
        return ""
    model = NAMED[field]
    obj = model.objects.filter(pk=pk).values_list("title" if model is Goal else "name", flat=True).first()
    return obj or ""


@receiver(pre_save, sender=Task)
def _before(sender, instance, raw=False, **kwargs):
    instance._activity = []
    if raw or not instance.pk or getattr(instance, "_no_activity", False):
        return
    old = Task.objects.filter(pk=instance.pk).values(*TRACKED, "remind_at").first()
    if old is None:
        return
    _reminder_follows_due(instance, old)
    for f in TRACKED:
        a, b = old[f], getattr(instance, f)
        if (a or None) != (b or None):
            change = {"field": f, "old": _plain(f, a), "new": _plain(f, b)}
            if f in NAMED:
                change.update(old_label=_label(f, a), new_label=_label(f, b))
            instance._activity.append(change)


@receiver(post_save, sender=Task)
def _after(sender, instance, created, raw=False, **kwargs):
    if raw or getattr(instance, "_no_activity", False):
        return
    if created:
        TaskActivity.objects.create(task=instance, data={"field": "created"})
        return
    for change in getattr(instance, "_activity", []):
        TaskActivity.objects.create(task=instance, data=change)
        if change["field"] == "project_id" and instance.parent_id is None:
            _subtasks_follow(instance, change["old"])
    instance._activity = []


def _reminder_follows_due(task, old):
    """A due date moved (dragged on the calendar, pushed to tomorrow…) takes a
    reminder that was counted from it along — unless the reminder was changed too."""
    before, after = old["due_date"], task.due_date
    if not (before and after and before != after and task.remind_at and task.remind_at == old["remind_at"]):
        return
    if timezone.localtime(task.remind_at).date() <= before:
        task.remind_at += timedelta(days=(after - before).days)


def _subtasks_follow(task, old_project):
    """A task moved to another project takes the subtasks that were in its old one along."""
    for sub in task.subtasks.filter(project_id=old_project):
        sub.project_id = task.project_id
        sub.save(update_fields=["project", "updated_at"])


def note(task, **data):
    """Something the save hook can't see (a blocker added or removed)."""
    TaskActivity.objects.create(task=task, data=data)


def _day(value):
    if not value:
        return "—"
    try:
        return date_format(date.fromisoformat(value), "j M Y")
    except (TypeError, ValueError):
        return str(value)


def _mins(value):
    if not value:
        return "—"
    h, m = divmod(int(value), 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


def describe(a):
    """One line, in the reader's language, for a change."""
    d = a.data or {}
    f = d.get("field")
    old, new = d.get("old"), d.get("new")
    if f == "created":
        return _("Created this task")
    if f == "status":
        if new == Status.DONE:
            return _("Marked done")
        return _("Status: %(old)s → %(new)s") % {"old": Status(old).label if old in Status.values else "—", "new": Status(new).label if new in Status.values else "—"}
    if f == "priority":
        label = lambda v: Priority(v).label if v in Priority.values else "—"  # noqa: E731
        return _("Priority: %(old)s → %(new)s") % {"old": label(old or 0), "new": label(new or 0)}
    if f == "due_date":
        return _("Due date: %(old)s → %(new)s") % {"old": _day(old), "new": _day(new)}
    if f == "start_date":
        return _("Start date: %(old)s → %(new)s") % {"old": _day(old), "new": _day(new)}
    if f == "project_id":
        return _("Project: %(old)s → %(new)s") % {"old": d.get("old_label") or "—", "new": d.get("new_label") or "—"}
    if f == "kind":
        label = lambda v: TaskKind(v).label if v in TaskKind.values else "—"  # noqa: E731
        return _("Type: %(old)s → %(new)s") % {"old": label(old), "new": label(new)}
    if f == "points":
        return _("Story points: %(old)s → %(new)s") % {"old": old or "—", "new": new or "—"}
    if f == "sprint_id":
        return _("Sprint: %(old)s → %(new)s") % {"old": d.get("old_label") or "—", "new": d.get("new_label") or "—"}
    if f == "goal_id":
        return _("Goal: %(old)s → %(new)s") % {"old": d.get("old_label") or "—", "new": d.get("new_label") or "—"}
    if f == "estimate_minutes":
        return _("Estimate: %(old)s → %(new)s") % {"old": _mins(old), "new": _mins(new)}
    if f == "title":
        return _("Renamed from “%(old)s”") % {"old": old or ""}
    if f == "waiting_for":
        return _("Waiting on: %(new)s") % {"new": new} if new else _("No longer waiting on %(old)s") % {"old": old}
    if f == "blocked_by":
        return (_("Now blocked by “%(title)s”") if d.get("added") else _("No longer blocked by “%(title)s”")) % {"title": d.get("title", "")}
    if f == "unblocked":
        return _("Ready: “%(title)s” is done") % {"title": d.get("title", "")}
    if f == "file":
        return (_("Attached “%(name)s”") if d.get("added") else _("Removed the file “%(name)s”")) % {"name": d.get("name", "")}
    return ""
