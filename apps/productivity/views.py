"""Productivity pages. Every query is limited to the signed-in person
(owner=request.user): nobody sees anyone else's work, admins included."""
import csv
from datetime import timedelta

from django.contrib import messages
from django.db.models import Count, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.translation import gettext as _

from apps.trash.undo import delete_with_undo

from . import services
from .api import entry_json
from .access import work_required
from .forms import EntryForm, HabitForm, ProjectForm, SettingsForm, SnippetForm, TagForm, TaskForm
from .models import (
    Habit, JournalEntry, Language, Note, Priority, Project, Snippet, Status, Tag, Task, TimeEntry, WorkSettings,
)


def _today():
    return timezone.localdate()


def _day(request, name="date", default=None):
    return parse_date(request.GET.get(name, "") or "") or default or _today()


def _urls():
    r = reverse
    return {
        "timerState": r("work:api_timer_state"), "timerStart": r("work:api_timer_start"), "timerStop": r("work:api_timer_stop"),
        "timerUpdate": r("work:api_timer_update"), "taskAdd": r("work:api_task_add"), "taskBase": "/work/api/tasks/",
        "checklist": "/work/api/checklist/", "noteSave": r("work:api_note_save"), "noteBase": "/work/api/notes/",
        "journal": r("work:api_journal_save"), "focus": r("work:api_focus_log"), "search": r("work:api_search"),
        "today": r("work:today"), "tasks": r("work:tasks"), "board": r("work:tasks") + "?view=board", "projects": r("work:projects"),
        "time": r("work:time"), "focus_page": r("work:focus"), "notes": r("work:notes"), "snippets": r("work:snippets"),
        "habits": r("work:habits"), "journal_page": r("work:journal"), "reports": r("work:reports"), "settings": r("work:settings"),
    }


def _texts():
    return {
        "savedOffline": _("Saved on this device — it will sync when you're online."), "synced": _("Synced changes made offline."),
        "undo": _("Undo"), "reminder": _("Reminder"), "stillWorking": _("Still working on this?"), "noDescription": _("No description"),
        "tracked": _("Tracked"), "notSaved": _("Not saved."), "taskAdded": _("Task added"), "noteSaved": _("Note saved"),
        "repeatMade": _("Next one added"), "taskDeleted": _("Task deleted"), "noteDeleted": _("Note deleted"),
        "focusSession": _("Focus session"), "focusDone": _("Focus session done"), "takeBreak": _("Time for a break."),
        "breakOver": _("Break's over"), "backToWork": _("Ready to focus again?"), "myDay": _("My Day"), "noAccess": _("Not allowed."),
    }


def render_work(request, template, ctx=None):
    """Every Productivity page gets the running timer, the settings the page
    scripts need (sounds, focus lengths…) and today's reminders."""
    user = request.user
    s = WorkSettings.for_user(user)
    now = timezone.now()
    reminders = (Task.objects.filter(owner=user, remind_at__isnull=False, remind_at__gte=now - timedelta(hours=1),
                                     remind_at__lte=now + timedelta(hours=24)).exclude(status=Status.DONE).values("pk", "title", "remind_at"))
    running = services.running_entry(user)
    today = _today()
    today_secs = services.totals(user, today, today).seconds
    if running:   # the page adds the running part live
        today_secs -= services.entry_seconds_between(running, *services.day_bounds(today))
    base = {
        "running": running,
        "ws": s,
        "work_config": {
            "running": entry_json(running), "todaySeconds": today_secs, "urls": _urls(), "text": _texts(),
            "focus": s.focus_minutes, "short": s.short_break_minutes, "long": s.long_break_minutes, "every": s.long_break_every,
            "autoBreaks": s.auto_start_breaks, "autoFocus": s.auto_start_focus,
            "sound": s.sound if s.sound_enabled else "", "volume": s.volume, "tick": s.tick_sound,
            "notify": s.notifications, "longTimer": s.long_timer_hours, "target": s.daily_target_minutes,
            "reminders": [{"id": r["pk"], "title": r["title"], "at": r["remind_at"].isoformat(),
                           "url": reverse("work:task", args=[r["pk"]])} for r in reminders],
        },
        "nav_projects": Project.objects.filter(owner=user, is_archived=False)[:12],
    }
    base.update(ctx or {})
    return render(request, template, base)


# ── Today ─────────────────────────────────────────────────────────────────
@work_required
def today_view(request):
    user, today = request.user, _today()
    s = WorkSettings.for_user(user)
    open_tasks, done_today = services.today_tasks(user, today)
    week_start = today - timedelta(days=6)
    week = services.totals(user, week_start, today)
    today_secs = week.by_day.get(today, 0)
    habits, _span = services.habit_rows(user, today, days=7)
    journal = JournalEntry.objects.filter(owner=user, date=today).first()
    hour = timezone.localtime().hour
    greeting = _("Good morning") if hour < 12 else (_("Good afternoon") if hour < 17 else _("Good evening"))
    peak = max(week.by_day.values()) or 1
    return render_work(request, "work/today.html", {
        "today": today, "greeting": greeting,
        "open_tasks": open_tasks, "done_today": done_today,
        "today_seconds": today_secs, "target_seconds": s.daily_target_minutes * 60,
        "target_pct": min(round(100 * today_secs / (s.daily_target_minutes * 60)), 100) if s.daily_target_minutes else 0,
        "week_bars": [{"day": d, "secs": v, "pct": round(100 * v / peak), "today": d == today} for d, v in week.by_day.items()],
        "week_total": week.seconds,
        "streak": services.focus_streak(user, today),
        "habits": [h for h in habits if h["due_today"]],
        "timeline": [e for e in week.entries if timezone.localtime(e.started_at).date() == today or (e.ended_at and timezone.localtime(e.ended_at).date() == today) or e.is_running],
        "notes": Note.objects.filter(owner=user, is_archived=False)[:5],
        "journal": journal,
        "suggest": Task.objects.filter(owner=user, status__in=[Status.TODO, Status.BACKLOG], my_day__isnull=True, due_date__isnull=True).order_by("-priority", "order")[:5],
    })


# ── Tasks ─────────────────────────────────────────────────────────────────
DUE_FILTERS = ("overdue", "today", "week", "none")


@work_required
def tasks_view(request):
    user, today = request.user, _today()
    view = request.GET.get("view") or request.COOKIES.get("work_task_view") or "list"
    view = view if view in ("list", "board") else "list"
    qs = Task.objects.filter(owner=user).select_related("project").prefetch_related("tags", "checklist")
    f = {k: request.GET.get(k, "").strip() for k in ("q", "project", "tag", "priority", "due")}
    if f["q"]:
        qs = qs.filter(Q(title__icontains=f["q"]) | Q(notes__icontains=f["q"]))
    if f["project"] == "none":
        qs = qs.filter(project__isnull=True)
    elif f["project"].isdigit():
        qs = qs.filter(project_id=int(f["project"]))
    if f["tag"]:
        qs = qs.filter(tags__name=f["tag"].lower())
    if f["priority"].isdigit():
        qs = qs.filter(priority__gte=int(f["priority"]))
    if f["due"] == "overdue":
        qs = qs.filter(due_date__lt=today).exclude(status=Status.DONE)
    elif f["due"] == "today":
        qs = qs.filter(due_date=today)
    elif f["due"] == "week":
        qs = qs.filter(due_date__gte=today, due_date__lte=today + timedelta(days=7))
    elif f["due"] == "none":
        qs = qs.filter(due_date__isnull=True)
    qs = qs.distinct()
    show_done = request.GET.get("done") == "1"
    ctx = {"view": view, "f": f, "filtered": any(f.values()), "show_done": show_done, "today": today,
           "projects": Project.objects.filter(owner=user, is_archived=False), "tags": Tag.objects.filter(owner=user),
           "priorities": Priority.choices, "statuses": Status.choices}
    if view == "board":
        columns = []
        for value, label in Status.choices:
            items = qs.filter(status=value)
            if value == Status.DONE:
                items = items.order_by("-completed_at")[:30]
            columns.append({"status": value, "label": label, "tasks": list(items)})
        ctx["columns"] = columns
    else:
        open_ = list(qs.exclude(status=Status.DONE))
        groups = [
            ("doing", _("In progress"), [t for t in open_ if t.status == Status.DOING]),
            ("overdue", _("Late"), [t for t in open_ if t.status != Status.DOING and t.due_date and t.due_date < today]),
            ("today", _("Today"), [t for t in open_ if t.status != Status.DOING and (t.due_date == today or (t.my_day == today and not t.due_date))]),
            ("upcoming", _("Coming up"), sorted([t for t in open_ if t.status != Status.DOING and t.due_date and t.due_date > today], key=lambda t: t.due_date)),
            ("todo", _("To do"), [t for t in open_ if t.status == Status.TODO and not t.due_date and t.my_day != today]),
            ("backlog", _("Backlog"), [t for t in open_ if t.status == Status.BACKLOG and not t.due_date and t.my_day != today]),
        ]
        ctx["groups"] = [(key, label, items) for key, label, items in groups if items]
        ctx["open_count"] = len(open_)
        ctx["done"] = list(qs.filter(status=Status.DONE).order_by("-completed_at")[:50]) if show_done else []
        ctx["done_count"] = qs.filter(status=Status.DONE).count()
    response = render_work(request, "work/tasks.html", ctx)
    if request.GET.get("view"):
        response.set_cookie("work_task_view", view, max_age=365 * 86400, samesite="Lax")
    return response


@work_required
def task_view(request, pk=None):
    user = request.user
    task = get_object_or_404(Task, pk=pk, owner=user) if pk else None
    form = TaskForm(request.POST or None, instance=task, owner=user,
                    initial=None if task else {"project": request.GET.get("project") or None, "due_date": request.GET.get("due") or None})
    if request.method == "POST" and form.is_valid():
        was_done = task.is_done if task else False
        obj = form.save(commit=False)
        obj.owner = user
        if not obj.pk:
            obj.order = services.next_order(user, obj.status)
        if obj.status == Status.DONE and not was_done:
            obj.completed_at = timezone.now()
        elif obj.status != Status.DONE:
            obj.completed_at = None
        obj.save()
        form.save_tags(obj)
        messages.success(request, _("Task saved."))
        return redirect("work:task", pk=obj.pk)
    ctx = {"form": form, "task": task}
    if task:
        entries = list(task.entries.select_related("project").order_by("-started_at")[:30])
        spent = services.task_seconds(task)
        ctx.update({"entries": entries, "spent": spent, "checklist": task.checklist.all(),
                    "estimate_pct": min(round(100 * spent / (task.estimate_minutes * 60)), 999) if task.estimate_minutes else None})
    return render_work(request, "work/task.html", ctx)


# ── Projects ──────────────────────────────────────────────────────────────
@work_required
def projects_view(request):
    user, today = request.user, _today()
    s = WorkSettings.for_user(user)
    first, last = s.week_of(today)
    week = services.totals(user, first, last)
    week_by = {p.pk if p else None: secs for p, secs in week.by_project}
    alltime = services.totals(user, today - timedelta(days=3650), today)
    all_by = {p.pk if p else None: secs for p, secs in alltime.by_project}
    archived = request.GET.get("archived") == "1"
    projects = (Project.objects.filter(owner=user, is_archived=archived)
                .annotate(open_tasks=Count("tasks", filter=~Q(tasks__status=Status.DONE)),
                          done_tasks=Count("tasks", filter=Q(tasks__status=Status.DONE))))
    rows = []
    for p in projects:
        total = all_by.get(p.pk, 0)
        budget = float(p.estimate_hours or 0) * 3600
        rows.append({"p": p, "week": week_by.get(p.pk, 0), "total": total,
                     "budget_pct": round(100 * total / budget) if budget else None,
                     "progress": round(100 * p.done_tasks / (p.open_tasks + p.done_tasks)) if (p.open_tasks + p.done_tasks) else None})
    return render_work(request, "work/projects.html", {"rows": rows, "archived": archived, "week_first": first})


@work_required
def project_form_view(request, pk=None):
    project = get_object_or_404(Project, pk=pk, owner=request.user) if pk else None
    form = ProjectForm(request.POST or None, instance=project, owner=request.user)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.owner = request.user
        obj.save()
        messages.success(request, _("Project saved."))
        return redirect("work:project", pk=obj.pk)
    return render_work(request, "work/project_form.html", {"form": form, "project": project})


@work_required
def project_view(request, pk):
    user, today = request.user, _today()
    project = get_object_or_404(Project, pk=pk, owner=user)
    s = WorkSettings.for_user(user)
    first, last = s.week_of(today)
    week = services.totals(user, first, last)
    alltime = services.totals(user, project.created_at.date() - timedelta(days=1), today)
    total = next((secs for p, secs in alltime.by_project if p and p.pk == project.pk), 0)
    tasks = Task.objects.filter(owner=user, project=project).prefetch_related("tags", "checklist")
    budget = float(project.estimate_hours or 0) * 3600
    return render_work(request, "work/project.html", {
        "project": project, "total": total,
        "week": next((secs for p, secs in week.by_project if p and p.pk == project.pk), 0),
        "budget_pct": round(100 * total / budget) if budget else None,
        "earned": (float(project.hourly_rate) * total / 3600) if project.hourly_rate else None,
        "open_tasks": tasks.exclude(status=Status.DONE), "done_tasks": tasks.filter(status=Status.DONE).order_by("-completed_at")[:15],
        "entries": TimeEntry.objects.filter(owner=user, project=project).select_related("task")[:20],
        "notes": Note.objects.filter(owner=user, project=project, is_archived=False)[:10],
        "today": today,
    })


@work_required
def project_delete_view(request, pk):
    project = get_object_or_404(Project, pk=pk, owner=request.user)
    if request.method != "POST":
        raise Http404
    delete_with_undo(request, project, _("Project deleted: %(name)s. Its tasks, time and notes are kept, without a project.") % {"name": project.name},
                     label=project.name, back_url=reverse("work:project", args=[pk]))
    return redirect("work:projects")


# ── Time ──────────────────────────────────────────────────────────────────
@work_required
def time_view(request):
    user, today = request.user, _today()
    s = WorkSettings.for_user(user)
    first, last = s.week_of(_day(request, "week", today))
    week = services.totals(user, first, last)
    lo, _x = services.day_bounds(first)
    _y, hi = services.day_bounds(last)
    days = []
    for i in range(7):
        d = first + timedelta(days=i)
        items = [e for e in week.entries if timezone.localtime(e.started_at).date() == d]
        days.append({"date": d, "entries": sorted(items, key=lambda e: e.started_at, reverse=True), "secs": week.by_day.get(d, 0), "today": d == today})
    # Timesheet: project × day.
    sheet = {}
    now = timezone.now()
    for e in week.entries:
        row = sheet.setdefault(e.project_id, {"project": e.project, "days": [0] * 7, "total": 0})
        d = (timezone.localtime(e.started_at).date() - first).days
        if 0 <= d < 7:
            secs = services.entry_seconds_between(e, lo, hi, now)
            row["days"][d] += secs
            row["total"] += secs
    sheet_rows = sorted(sheet.values(), key=lambda r: -r["total"])
    return render_work(request, "work/time.html", {
        "first": first, "last": last, "days": list(reversed(days)) if first <= today <= last else list(reversed(days)),
        "week": week, "sheet": sheet_rows, "weekdays": [first + timedelta(days=i) for i in range(7)],
        "prev_week": first - timedelta(days=7), "next_week": first + timedelta(days=7) if last < today else None,
        "target_week": s.daily_target_minutes * 60 * sum(1 for i in range(7) if s.is_work_day(first + timedelta(days=i))),
        "today": today,
    })


@work_required
def entry_form_view(request, pk=None):
    entry = get_object_or_404(TimeEntry, pk=pk, owner=request.user) if pk else None
    initial = {}
    if not entry and request.GET.get("task"):
        task = Task.objects.filter(owner=request.user, pk=request.GET["task"]).first()
        if task:
            initial = {"task": task.pk, "project": task.project_id, "description": ""}
    form = EntryForm(request.POST or None, instance=entry, owner=request.user, initial=initial)
    if request.method == "POST" and form.is_valid():
        e = form.save()
        messages.success(request, _("Time saved: %(time)s.") % {"time": services.hm(e.seconds)})
        return redirect(reverse("work:time") + f"?week={timezone.localtime(e.started_at).date().isoformat()}")
    return render_work(request, "work/entry_form.html", {"form": form, "entry": entry})


# ── Focus (Pomodoro) ──────────────────────────────────────────────────────
@work_required
def focus_view(request):
    user, today = request.user, _today()
    lo, hi = services.day_bounds(today)
    sessions = TimeEntry.objects.filter(owner=user, kind="focus", started_at__gte=lo, started_at__lt=hi)
    open_tasks, _done = services.today_tasks(user, today)
    task = Task.objects.filter(owner=user, pk=request.GET.get("task") or 0).first()
    return render_work(request, "work/focus.html", {
        "sessions": sessions.count(), "focus_seconds": sum(e.seconds for e in sessions),
        "tasks": open_tasks[:30], "task": task,
    })


# ── Notes ─────────────────────────────────────────────────────────────────
@work_required
def notes_view(request, pk=None):
    user = request.user
    q, tag = request.GET.get("q", "").strip(), request.GET.get("tag", "").strip().lower()
    archived = request.GET.get("archived") == "1"
    notes = Note.objects.filter(owner=user, is_archived=archived).prefetch_related("tags")
    if q:
        notes = notes.filter(Q(title__icontains=q) | Q(body__icontains=q))
    if tag:
        notes = notes.filter(tags__name=tag)
    note = get_object_or_404(Note, pk=pk, owner=user) if pk else None
    note_data = {"id": None, "title": "", "body": "", "tags": "", "project": "", "updated": 0, "saved": ""}
    if note:
        note_data = {"id": note.pk, "title": note.title, "body": note.body, "tags": " ".join(note.tags.values_list("name", flat=True)),
                     "project": str(note.project_id or ""), "updated": int(note.updated_at.timestamp() * 1000),
                     "saved": timezone.localtime(note.updated_at).strftime("%H:%M")}
    return render_work(request, "work/notes.html", {
        "note_data": note_data,
        "notes": notes.distinct()[:200], "note": note, "q": q, "tag": tag, "archived": archived,
        "tags": Tag.objects.filter(owner=user, notes__isnull=False).distinct(),
        "projects": Project.objects.filter(owner=user, is_archived=False),
    })


# ── Snippets ──────────────────────────────────────────────────────────────
@work_required
def snippets_view(request):
    user = request.user
    q, lang, tag = request.GET.get("q", "").strip(), request.GET.get("lang", ""), request.GET.get("tag", "").strip().lower()
    snippets = Snippet.objects.filter(owner=user).prefetch_related("tags")
    if q:
        snippets = snippets.filter(Q(title__icontains=q) | Q(code__icontains=q) | Q(description__icontains=q))
    if lang:
        snippets = snippets.filter(language=lang)
    if tag:
        snippets = snippets.filter(tags__name=tag)
    used = set(Snippet.objects.filter(owner=user).values_list("language", flat=True))
    return render_work(request, "work/snippets.html", {
        "snippets": snippets.distinct()[:200], "q": q, "lang": lang, "tag": tag,
        "languages": [(v, l) for v, l in Language.choices if v in used],
        "tags": Tag.objects.filter(owner=user, snippets__isnull=False).distinct(),
    })


@work_required
def snippet_form_view(request, pk=None):
    snippet = get_object_or_404(Snippet, pk=pk, owner=request.user) if pk else None
    form = SnippetForm(request.POST or None, instance=snippet, owner=request.user)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.owner = request.user
        obj.save()
        form.save_tags(obj)
        messages.success(request, _("Snippet saved."))
        return redirect(reverse("work:snippets") + f"#snippet-{obj.pk}")
    return render_work(request, "work/snippet_form.html", {"form": form, "snippet": snippet})


# ── Habits ────────────────────────────────────────────────────────────────
@work_required
def habits_view(request):
    days = 28 if request.GET.get("range") == "28" else 14
    rows, span = services.habit_rows(request.user, _today(), days=days)
    return render_work(request, "work/habits.html", {"rows": rows, "span": span, "days": days, "today": _today()})


@work_required
def habit_form_view(request, pk=None):
    habit = get_object_or_404(Habit, pk=pk, owner=request.user) if pk else None
    form = HabitForm(request.POST or None, instance=habit)
    if request.method == "POST":
        if request.POST.get("action") == "archive" and habit:
            habit.is_archived = not habit.is_archived
            habit.save(update_fields=["is_archived"])
            messages.success(request, _("Habit archived.") if habit.is_archived else _("Habit is back."))
            return redirect("work:habits")
        if request.POST.get("action") == "delete" and habit:
            delete_with_undo(request, habit, _("Habit deleted: %(name)s.") % {"name": habit.name}, label=habit.name, back_url=reverse("work:habits"))
            return redirect("work:habits")
        if form.is_valid():
            obj = form.save(commit=False)
            obj.owner = request.user
            obj.save()
            messages.success(request, _("Habit saved."))
            return redirect("work:habits")
    return render_work(request, "work/habit_form.html", {"form": form, "habit": habit})


# ── Journal & standup ─────────────────────────────────────────────────────
@work_required
def journal_view(request):
    user, today = request.user, _today()
    day = min(_day(request, "date", today), today + timedelta(days=1))
    entry = JournalEntry.objects.filter(owner=user, date=day).first()
    lo, hi = services.day_bounds(day)
    done = Task.objects.filter(owner=user, status=Status.DONE, completed_at__gte=lo, completed_at__lt=hi).select_related("project")
    data = services.standup(user, day)
    return render_work(request, "work/journal.html", {
        "day": day, "entry": entry, "today": today, "done": done,
        "tracked": services.totals(user, day, day),
        "prev": day - timedelta(days=1), "next": day + timedelta(days=1) if day < today else None,
        "recent": JournalEntry.objects.filter(owner=user).exclude(date=day)[:10],
        "standup": data, "standup_md": services.standup_text(data, markdown=True), "standup_plain": services.standup_text(data, markdown=False),
        "moods": range(1, 6),
    })


# ── Reports ───────────────────────────────────────────────────────────────
def _range(request, s, today):
    preset = request.GET.get("range", "week")
    if preset == "custom":
        start, end = parse_date(request.GET.get("from", "") or ""), parse_date(request.GET.get("to", "") or "")
        if start and end:
            return (min(start, end), max(start, end)), preset
        preset = "week"
    if preset == "lastweek":
        first, _last = s.week_of(today)
        return (first - timedelta(days=7), first - timedelta(days=1)), preset
    if preset == "month":
        return (today.replace(day=1), today), preset
    if preset == "lastmonth":
        last = today.replace(day=1) - timedelta(days=1)
        return (last.replace(day=1), last), preset
    if preset == "30":
        return (today - timedelta(days=29), today), preset
    if preset == "year":
        return (today.replace(month=1, day=1), today), preset
    first, last = s.week_of(today)
    return (first, min(last, today)), "week"


@work_required
def reports_view(request):
    user, today = request.user, _today()
    s = WorkSettings.for_user(user)
    (start, end), preset = _range(request, s, today)
    if (end - start).days > 400:
        start = end - timedelta(days=400)
    t = services.totals(user, start, end)
    if request.GET.get("export") == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="time-{start}-{end}.csv"'
        response.write("﻿")
        w = csv.writer(response)
        w.writerow([_("Date"), _("Start"), _("End"), _("Hours"), _("Project"), _("Task"), _("Description"), _("Tags"), _("Billable"), _("Kind")])
        for e in t.entries:
            st, en = timezone.localtime(e.started_at), timezone.localtime(e.ended_at) if e.ended_at else None
            w.writerow([st.date().isoformat(), st.strftime("%H:%M"), en.strftime("%H:%M") if en else "", f"{e.seconds / 3600:.2f}",
                        e.project.name if e.project_id else "", e.task.title if e.task_id else "", e.description,
                        " ".join(tg.name for tg in e.tags.all()), "yes" if e.billable else "", e.kind])
        return response
    peak = max(t.by_day.values(), default=0) or 1
    work_days = sum(1 for i in range(t.days) if s.is_work_day(start + timedelta(days=i)))
    lo, hi = services.day_bounds(start)[0], services.day_bounds(end)[1]
    completed = Task.objects.filter(owner=user, status=Status.DONE, completed_at__gte=lo, completed_at__lt=hi)
    estimated = []
    for task in completed.filter(estimate_minutes__isnull=False).prefetch_related("entries")[:30]:
        spent = services.task_seconds(task)
        estimated.append({"task": task, "estimate": task.estimate_minutes * 60, "spent": spent,
                          "ratio": round(100 * spent / (task.estimate_minutes * 60)) if task.estimate_minutes else 0})
    accuracy = None
    if estimated:
        accuracy = round(100 * sum(min(r["estimate"], r["spent"]) / max(r["estimate"], r["spent"], 1) for r in estimated) / len(estimated))
    hours = [0] * 24
    for e in t.entries:
        st = timezone.localtime(e.started_at)
        hours[st.hour] += e.seconds
    hpeak = max(hours) or 1
    return render_work(request, "work/reports.html", {
        "t": t, "start": start, "end": end, "preset": preset, "today": today,
        "bars": [{"day": d, "secs": v, "pct": round(100 * v / peak), "work": s.is_work_day(d), "weekend": not s.is_work_day(d)} for d, v in t.by_day.items()],
        "target_total": s.daily_target_minutes * 60 * work_days,
        "target_pct": round(100 * t.seconds / (s.daily_target_minutes * 60 * work_days)) if work_days else None,
        "projects": [{"p": p, "secs": secs, "pct": round(100 * secs / t.seconds) if t.seconds else 0} for p, secs in t.by_project],
        "tags": [{"tag": tg, "secs": secs, "pct": round(100 * secs / t.seconds) if t.seconds else 0} for tg, secs in t.by_tag[:12]],
        "tasks": t.by_task, "completed": completed.count(), "created": Task.objects.filter(owner=user, created_at__gte=lo, created_at__lt=hi).count(),
        "estimated": estimated, "accuracy": accuracy,
        "hours": [{"h": h, "secs": v, "pct": round(100 * v / hpeak)} for h, v in enumerate(hours)],
        "presets": [("week", _("This week")), ("lastweek", _("Last week")), ("month", _("This month")), ("lastmonth", _("Last month")),
                    ("30", _("Last 30 days")), ("year", _("This year"))],
    })


# ── Settings ──────────────────────────────────────────────────────────────
@work_required
def settings_view(request):
    s = WorkSettings.for_user(request.user)
    form = SettingsForm(request.POST or None, instance=s, prefix="s")
    tag_form = TagForm(prefix="tag")
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "settings" and form.is_valid():
            form.save()
            messages.success(request, _("Settings saved."))
            return redirect("work:settings")
        if action == "tag":
            tag = get_object_or_404(Tag, pk=request.POST.get("tag"), owner=request.user)
            if request.POST.get("delete"):
                tag.delete()
                messages.success(request, _("Tag removed from everything."))
            else:
                tag_form = TagForm(request.POST, instance=tag, prefix="tag")
                name = (request.POST.get("tag-name") or "").strip().lower()
                if name and not Tag.objects.filter(owner=request.user, name=name).exclude(pk=tag.pk).exists() and tag_form.is_valid():
                    t = tag_form.save(commit=False)
                    t.name = name
                    t.save()
                    messages.success(request, _("Tag saved."))
                else:
                    messages.error(request, _("That tag name is empty or already used."))
            return redirect(reverse("work:settings") + "#tags")
    tags = Tag.objects.filter(owner=request.user).annotate(n_tasks=Count("tasks", distinct=True), n_notes=Count("notes", distinct=True),
                                                           n_entries=Count("entries", distinct=True))
    return render_work(request, "work/settings.html", {"form": form, "tags": tags, "tag_form": tag_form})


@work_required
def help_view(request):
    return render_work(request, "work/help.html", {})

