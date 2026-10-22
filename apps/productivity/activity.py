"""A task's history, like an issue tracker's: every change to the fields that
matter is noted (from the task page, the board, a quick menu or a bulk action),
and comments can be written alongside. Changes are stored as plain values and
put into words when shown, so they read in whichever language you use."""
from datetime import date

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils.formats import date_format
from django.utils.translation import gettext as _

from .models import Goal, Priority, Project, Status, Task, TaskActivity

TRACKED = ("title", "status", "priority", "due_date", "start_date", "project_id", "goal_id", "estimate_minutes", "waiting_for")
NAMED = {"project_id": Project, "goal_id": Goal}     # kept with their name, in case they're deleted later


def _plain(field, value):
    if isinstance(value, date):
        return value.isoformat()
    return value


def _label(field, pk):
    if not pk:
        return ""
    model = NAMED[field]
    obj = model.objects.filter(pk=pk).values_list("name" if model is Project else "title", flat=True).first()
    return obj or ""


@receiver(pre_save, sender=Task)
def _before(sender, instance, raw=False, **kwargs):
    instance._activity = []
    if raw or not instance.pk or getattr(instance, "_no_activity", False):
        return
    old = Task.objects.filter(pk=instance.pk).values(*TRACKED).first()
    if old is None:
        return
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
    instance._activity = []


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
    return ""
