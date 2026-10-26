"""Productivity pages. Every query is limited to the signed-in person
(owner=request.user): nobody sees anyone else's work, admins included."""
import csv
from datetime import date, timedelta
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import BooleanField, Count, ExpressionWrapper, F, Q, prefetch_related_objects
from django.http import Http404, HttpResponse, HttpResponseNotModified
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.formats import date_format
from django.utils.http import http_date, parse_http_date_safe
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.trash.undo import delete_with_undo

from . import cards, dev, diagrams, services
from .api import card_json, entry_json
from .access import can_use, work_required
from .forms import DeckForm, EntryForm, GoalForm, HabitForm, LearningForm, ProjectForm, SettingsForm, SnippetForm, SprintForm, TagForm, TaskForm
from .models import (
    Card, Color, Deck, Diagram, DiagramKind, DiagramVersion, Goal, GoalStatus, Habit, JournalEntry, Language, LearningItem, LearningKind, LearningStatus, LearningUnit, KIND_ICONS, Note, Priority, Project, SavedView, Snippet, Sprint, TaskKind, TaskTemplate,
    Status, Tag, Task, TimeEntry, WorkSettings, DRAG_KINDS, VISUAL_KINDS,
)

ROW_RELATED = ("tags", "checklist", "blocked_by", "subtasks")   # what a task row shows; fetched only for the rows on screen


def _today():
    return timezone.localdate()


def _day(request, name="date", default=None):
    return parse_date(request.GET.get(name, "") or "") or default or _today()


def _urls():
    r = reverse
    return {
        "timerState": r("work:api_timer_state"), "timerStart": r("work:api_timer_start"), "timerStop": r("work:api_timer_stop"),
        "timerUpdate": r("work:api_timer_update"), "taskAdd": r("work:api_task_add"), "taskBase": "/work/api/tasks/", "commentBase": "/work/api/comments/", "fileBase": "/work/api/files/",
        "viewSave": r("work:api_view_save"), "viewBase": "/work/api/views/",
        "taskBulk": r("work:api_task_bulk"), "wrapup": r("work:wrapup"),
        "checklist": "/work/api/checklist/", "noteSave": r("work:api_note_save"), "noteBase": "/work/api/notes/",
        "journal": r("work:api_journal_save"), "focus": r("work:api_focus_log"), "search": r("work:api_search"),
        "today": r("work:today"), "tasks": r("work:tasks"), "board": r("work:tasks") + "?view=board", "projects": r("work:projects"),
        "time": r("work:time"), "focus_page": r("work:focus"), "notes": r("work:notes"), "snippets": r("work:snippets"),
        "habits": r("work:habits"), "journal_page": r("work:journal"), "reports": r("work:reports"), "settings": r("work:settings"),
        "goals": r("work:goals"), "learning": r("work:learning"), "review": r("work:review"), "calendar": r("work:calendar"),
        "help": r("work:help"), "entry_new": r("work:entry_new"), "task_new": r("work:task_new"), "goal_new": r("work:goal_new"),
        "learning_new": r("work:learning_new"), "snippet_new": r("work:snippet_new"), "export": r("work:export"),
        "learningBase": "/work/api/learning/", "goalBase": "/work/api/goals/",
        "plan": r("work:plan"), "planAction": r("work:api_plan"), "week": r("work:week"), "noteGo": r("work:note_go"),
        "diagrams": r("work:diagrams"), "diagramBase": "/work/api/diagrams/", "diagramList": r("work:api_diagram_list"),
        "cardsDue": r("work:api_cards_due"), "cardReview": r("work:card_review"), "imageUpload": r("work:api_image_upload"),
        "cards": r("work:cards"), "cardBase": "/work/api/cards/", "cardAdd": r("work:api_card_add"),
        "prep": r("work:prep"), "prepBase": "/work/api/prep/questions/", "exam": r("work:exam"),
    }


def _texts():
    return {
        "savedOffline": _("Saved on this device — it will sync when you're online."), "synced": _("Synced changes made offline."),
        "undo": _("Undo"), "reminder": _("Reminder"), "stillWorking": _("Still working on this?"), "noDescription": _("No description"),
        "tracked": _("Tracked"), "notSaved": _("Not saved."), "taskAdded": _("Task added"), "noteSaved": _("Note saved"), "noteArchived": _("Archived"), "noteUnarchived": _("Back from the archive"),
        "repeatMade": _("Next one added"), "taskDeleted": _("Task deleted"), "noteDeleted": _("Note deleted"),
        "focusSession": _("Focus session"), "focusDone": _("Focus session done"), "takeBreak": _("Time for a break."),
        "focusSavedLate": _("A focus session finished while you were away — it's in your timesheet."),
        "unblocked": _("Ready to start now:"), "deleteComment": _("Delete this comment?"),
        "removeFile": _("Remove this file? It can't be brought back."), "fileOffline": _("Files need a connection — try again when you're online."),
        "duplicated": _("Copy made"), "open": _("Open"), "wipOver": _("“In progress” is over your limit of %(n)s — finish one before starting another?"),
        "viewName": _("Name this view (e.g. “Urgent at work”):"), "viewDelete": _("Remove this saved view?"), "viewSaved": _("View saved"),
        "breakOver": _("Break's over"), "backToWork": _("Ready to focus again?"), "myDay": _("My Day"), "noAccess": _("Not allowed."),
        "link": _("Link"), "copied": _("Copied"), "copyCode": _("Copy code"),
        "slash": {      # "/" in a Markdown box (static/js/writing.js)
            "h1": _("Heading 1"), "h2": _("Heading 2"), "h3": _("Heading 3"), "todo": _("To-do"), "bullet": _("Bulleted list"),
            "numbered": _("Numbered list"), "quote": _("Quote"), "callout": _("Callout"), "code": _("Code block"), "python": _("Python code"),
            "js": _("JavaScript code"), "sql": _("SQL"), "bash": _("Shell command"), "json": _("JSON"), "mermaid": _("Diagram (Mermaid)"),
            "table": _("Table"), "details": _("Collapsible section"), "divider": _("Divider"), "math": _("Formula"), "link": _("Link to a note"),
            "card": _("Flashcard (question :: answer)"), "date": _("Today’s date"), "time": _("Time now"),
        },
        "units": {k: str(v) for k, v in LearningUnit.choices},
        "kindCommand": _("Command"), "kindRecent": _("Recent"), "kindCreate": _("Create"),
        "addTask": _("Add task"), "addNote": _("Save as a note"), "trackThis": _("Start the timer for"),
        "selected": _("Selected"), "changed": _("Updated"), "confirmBulkDelete": _("Delete the selected tasks? You can bring them back from Recently deleted."),
        "pickSome": _("Select some tasks first."),
        "clearPlan": _("Take every open task off the timeline? They stay on the day's list."), "planned": _("Planned"),
        "noRoom": _("no room for"), "dayFull": _("No free time left in your work day."), "nothingToPlan": _("Nothing left to plan."), "planTomorrow": _("Plan tomorrow"),
        "tasksMade": _("Tasks made"), "openTasks": _("See them"), "tomorrow": _("Tomorrow"),
        "error": _("Couldn't save. Try again."), "later": _("Moved to"),
        "kinds": {"task": _("Task"), "note": _("Note"), "project": _("Project"), "goal": _("Goal"), "learning": _("Learning"),
                  "snippet": _("Snippet"), "diagram": _("Diagram"), "card": _("Flashcard"), "question": _("Question"),
                  "exam": _("Exam notes")},
        "restoreNote": _("Bring back this version? What's there now is kept as a version too."),
        "uploading": _("Uploading…"), "imageFailed": _("The picture couldn't be uploaded."),
        "imageOffline": _("Pictures need a connection — try again when you're online."),
        "cardsWaiting": _("Flashcards waiting"), "cardsToReview": _("%(n)s cards to review — about %(n)s minutes."), "review": _("Review"),
        "cardsMade": _("Flashcards made"), "seeCards": _("See them"), "noPairs": _("Write cards as “question :: answer”, one a line."),
    }


def _commands():
    """What the command palette (Ctrl+K) can do, besides finding things."""
    r = reverse
    go = [
        ("today", _("Today"), "sun", "work:today", "g h", "home my day"),
        ("plan", _("Plan my day"), "clock", "work:plan", "g d", "time blocking schedule timeline day planner calendar hours"),
        ("week", _("Plan the week"), "calendar", "work:week", "g w", "weekly planning schedule days"),
        ("tasks", _("Tasks"), "check", "work:tasks", "g t", "todo list"),
        ("board", _("Board"), "board", None, "g b", "kanban"),
        ("calendar", _("Calendar"), "calendar", "work:calendar", "g c", "month due"),
        ("projects", _("Projects"), "folder", "work:projects", "g p", "clients"),
        ("goals", _("Goals"), "flag", "work:goals", "g o", "okr career future"),
        ("learning", _("Learning"), "book", "work:learning", "g l", "books courses reading list"),
        ("focus", _("Focus timer"), "bolt", "work:focus", "g f", "pomodoro"),
        ("time", _("Time"), "timer", "work:time", "g i", "timesheet hours"),
        ("habits", _("Habits"), "flame", "work:habits", "g a", "streak"),
        ("journal", _("Journal & standup"), "journal", "work:journal", "g j", "daily log standup"),
        ("review", _("Review & brag document"), "trophy", "work:review", "g v", "weekly review performance achievements"),
        ("reports", _("Reports"), "chart", "work:reports", "g r", "stats charts"),
        ("notes", _("Notes"), "note", "work:notes", "g n", ""),
        ("snippets", _("Snippets"), "code", "work:snippets", "g s", "code"),
        ("cards", _("Flashcards"), "cards", "work:cards", "g k", "flashcards spaced repetition anki memorise memorize study quiz revise"),
        ("prep", _("Interview prep"), "target", "work:prep", "g q", "interview exam questions answers quiz practice mock test leetcode prepare dsa system design"),
        ("diagrams", _("Diagrams"), "diagram", "work:diagrams", "g m", "mind map mindmap system design architecture flowchart sequence er uml whiteboard"),
        ("settings", _("Timer, focus & sounds"), "key", "work:settings", "g ,", "settings preferences tags"),
    ]
    out = [{"id": "go-" + key, "title": title, "icon": icon, "url": r(name) if name else r("work:tasks") + "?view=board",
            "hint": hint, "words": words, "kind": "page"} for key, title, icon, name, hint, words in go]
    out += [
        {"id": "go-matrix", "title": _("Tasks: urgent × important matrix"), "icon": "quadrant", "url": r("work:tasks") + "?view=matrix",
         "words": "eisenhower priority prioritise prioritize quadrant", "kind": "page"},
        {"id": "go-timeline", "title": _("Tasks: timeline"), "icon": "gantt", "url": r("work:tasks") + "?view=timeline",
         "words": "gantt roadmap schedule weeks start due", "kind": "page"},
        {"id": "go-blocked", "title": _("Tasks: blocked"), "icon": "lock", "url": r("work:tasks") + "?view=list&blocked=yes",
         "words": "dependencies waiting depends on", "kind": "page"},
        {"id": "go-sprints", "title": _("Sprints"), "icon": "repeat", "url": r("work:sprints"), "words": "sprint scrum jira iteration cycle burndown velocity backlog", "kind": "page"},
        {"id": "go-templates", "title": _("Task templates"), "icon": "insert", "url": r("work:templates"), "words": "template checklist reuse repeat", "kind": "page"},
        {"id": "go-invoice", "title": _("Invoice & timesheet"), "icon": "note", "url": r("work:invoice"), "words": "bill client billing hours rate money", "kind": "page"},
        {"id": "go-import", "title": _("Import tasks"), "icon": "upload", "url": r("work:import"), "words": "csv todoist trello jira asana clickup move migrate", "kind": "page"},
        {"id": "new-task", "title": _("New task"), "icon": "plus", "action": "capture:task", "hint": "c", "words": "add create"},
        {"id": "new-note", "title": _("New note"), "icon": "note", "action": "capture:note", "hint": "n", "words": "add create write"},
        {"id": "new-mindmap", "title": _("New mind map"), "icon": "mindmap", "url": r("work:diagrams") + "?start=mindmap", "words": "add create brainstorm diagram"},
        {"id": "review-cards", "title": _("Review flashcards"), "icon": "cards", "url": r("work:card_review"), "words": "study quiz spaced repetition anki"},
        {"id": "new-deck", "title": _("New flashcard deck"), "icon": "cards", "url": r("work:cards") + "?new=1", "words": "add create flashcards study"},
        {"id": "new-diagram", "title": _("New diagram"), "icon": "diagram", "url": r("work:diagrams") + "#new", "words": "add create chart drawing c4 architecture pie git"},
        {"id": "new-flowchart", "title": _("New flowchart"), "icon": "diagram", "url": r("work:diagrams") + "?start=flowchart", "words": "add create diagram process"},
        {"id": "new-sequence", "title": _("New sequence diagram"), "icon": "diagram", "url": r("work:diagrams") + "?start=sequence", "words": "add create diagram api calls"},
        {"id": "new-system", "title": _("New system design"), "icon": "server", "url": r("work:diagrams") + "?start=system", "words": "add create architecture diagram board"},
        {"id": "start", "title": _("Start the timer"), "icon": "play", "action": "capture:time", "hint": "s", "words": "track", "when": "idle"},
        {"id": "stop", "title": _("Stop the timer"), "icon": "stop", "action": "timer:stop", "hint": "s", "words": "track", "when": "running"},
        {"id": "wrapup", "title": _("Wrap up the day"), "icon": "sun", "url": r("work:wrapup"), "words": "shutdown end of day evening plan tomorrow"},
        {"id": "note-today", "title": _("Today's note"), "icon": "sun", "url": r("work:note_today"), "words": "daily journal log scratch"},
        {"id": "note-meeting", "title": _("New meeting notes"), "icon": "note", "url": r("work:notes") + "?new=1&template=meeting", "words": "template"},
        {"id": "note-adr", "title": _("New decision record (ADR)"), "icon": "note", "url": r("work:notes") + "?new=1&template=adr", "words": "template architecture"},
        {"id": "note-study", "title": _("New study notes"), "icon": "note", "url": r("work:notes") + "?new=1&template=study", "words": "template learning flashcards revise"},
        {"id": "note-bug", "title": _("New bug report"), "icon": "note", "url": r("work:notes") + "?new=1&template=bug", "words": "template issue"},
        {"id": "add-time", "title": _("Add time by hand"), "icon": "clock", "url": r("work:entry_new"), "words": "manual entry log"},
        {"id": "new-goal", "title": _("New goal"), "icon": "flag", "url": r("work:goal_new"), "words": "add create"},
        {"id": "new-learning", "title": _("Add a book, course or article"), "icon": "book", "url": r("work:learning_new"), "words": "learning read"},
        {"id": "new-snippet", "title": _("New snippet"), "icon": "code", "url": r("work:snippet_new"), "words": "code add"},
        {"id": "standup", "title": _("Copy my standup"), "icon": "copy", "url": r("work:journal") + "#standup", "words": "daily slack teams"},
        {"id": "export", "title": _("Download all my data"), "icon": "download", "url": r("work:export"), "words": "export backup zip json"},
        {"id": "shortcuts", "title": _("Keyboard shortcuts"), "icon": "keyboard", "action": "help", "hint": "?", "words": "keys help"},
    ]
    return out


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
            "dev": {"prefix": s.key_prefix or "T", "branch": s.branch_format or "{type}/{key}-{slug}"},
            "commands": _commands() + [{"id": f"view-{v.pk}", "title": _("View: %(name)s") % {"name": v.name}, "icon": "filter", "kind": "page",
                                        "url": reverse("work:tasks") + "?" + v.query + ("&" if v.query else "") + f"sv={v.pk}", "words": "saved view filter"}
                                       for v in SavedView.objects.filter(owner=user)],
            "wip": s.wip_limit, "focus": s.focus_minutes, "short": s.short_break_minutes, "long": s.long_break_minutes, "every": s.long_break_every,
            "autoBreaks": s.auto_start_breaks, "autoFocus": s.auto_start_focus,
            "sound": s.sound if s.sound_enabled else "", "volume": s.volume, "tick": s.tick_sound,
            "notify": s.notifications, "longTimer": s.long_timer_hours, "target": s.daily_target_minutes, "idle": s.idle_minutes,
            "cardsRemind": s.cards_remind_at.strftime("%H:%M") if s.cards_remind_at else "",
            "reminders": [{"id": r["pk"], "title": r["title"], "at": r["remind_at"].isoformat(),
                           "url": reverse("work:task", args=[r["pk"]])} for r in reminders],
        },
        "nav_projects": Project.objects.filter(owner=user, is_archived=False)[:12],
    }
    base.update(ctx or {})
    return render(request, template, base)


# ── Today ─────────────────────────────────────────────────────────────────
TODAY_LIMIT = 40


@work_required
def today_view(request):
    user, today = request.user, _today()
    s = WorkSettings.for_user(user)
    open_tasks, done_today = services.today_tasks(user, today)
    cap = services.capacity(open_tasks, user, today)
    more = max(len(open_tasks) - TODAY_LIMIT, 0)
    open_tasks = open_tasks[:TODAY_LIMIT]
    prefetch_related_objects(open_tasks, *ROW_RELATED)
    prefetch_related_objects(done_today, *ROW_RELATED)
    week_start = today - timedelta(days=6)
    week = services.totals(user, week_start, today)
    today_secs = week.by_day.get(today, 0)
    habits, _span = services.habit_rows(user, today, days=7)
    journal = JournalEntry.objects.filter(owner=user, date=today).first()
    hour = timezone.localtime().hour
    greeting = _("Good morning") if hour < 12 else (_("Good afternoon") if hour < 17 else _("Good evening"))
    peak = max(week.by_day.values()) or 1
    from .sprints import current

    sprint = current(user, today)
    if sprint:
        counts = sprint.tasks.aggregate(total=Count("pk"), done=Count("pk", filter=Q(status=Status.DONE)))
        sprint.counts, sprint.days_left = counts, (sprint.end_date - today).days
    from .models import Question

    prep_due = 0
    if Question.objects.filter(owner=user).exists():
        from .prep import new_left

        due = Question.objects.filter(owner=user, last_reviewed__isnull=False, due__lte=today).count()
        prep_due = due + min(new_left(user, today), Question.objects.filter(owner=user, last_reviewed__isnull=True).count())
    from .models import ExamSubject

    exam_soon = (ExamSubject.objects.filter(owner=user, exam_date__gte=today, exam_date__lte=today + timedelta(days=14))
                 .annotate(n=Count("notes"), left=Count("notes", filter=Q(notes__is_known=False))).filter(n__gt=0).order_by("exam_date").first())
    return render_work(request, "work/today.html", {
        "today": today, "greeting": greeting, "hour_late": hour >= 16, "sprint": sprint, "prep_due": prep_due, "exam_soon": exam_soon,
        "open_tasks": open_tasks, "done_today": done_today, "more_tasks": more, "cap": cap,
        "next_block": services.next_block(user), "now": timezone.now(),
        "leftovers": services.leftovers(user, today), "waiting": services.waiting_tasks(user)[:6],
        "goals": services.with_progress(Goal.objects.filter(owner=user, status=GoalStatus.ACTIVE)[:3]),
        "reading": LearningItem.objects.filter(owner=user, status=LearningStatus.ACTIVE)[:3],
        "today_seconds": today_secs, "target_seconds": s.daily_target_minutes * 60,
        "target_pct": min(round(100 * today_secs / (s.daily_target_minutes * 60)), 100) if s.daily_target_minutes else 0,
        "week_bars": [{"day": d, "secs": v, "pct": round(100 * v / peak), "today": d == today, "hrs": _hours(v)} for d, v in week.by_day.items()],
        "week_total": week.seconds,
        "streak": services.focus_streak(user, today),
        "habits": [h for h in habits if h["due_today"]],
        "timeline": [e for e in week.entries if timezone.localtime(e.started_at).date() == today or (e.ended_at and timezone.localtime(e.ended_at).date() == today) or e.is_running],
        "notes": Note.objects.filter(owner=user, is_archived=False)[:5],
        "journal": journal,
        "suggest": Task.objects.filter(owner=user, status__in=[Status.TODO, Status.BACKLOG], my_day__isnull=True, due_date__isnull=True).order_by("-priority", "order")[:5],
        "cards_due": cards.due_count(user, today) if Deck.objects.filter(owner=user, is_archived=False).exists() else 0,
    })


# ── Tasks ─────────────────────────────────────────────────────────────────
DUE_FILTERS = ("overdue", "today", "week", "none")
GROUP_LIMIT = 40     # rows per group on the list; "Show all" opens one group
GROUP_PAGE = 100
BOARD_LIMIT = 80
BOARD_DONE = 30


TASK_VIEWS = ("list", "board", "matrix", "timeline")
GROUP_BY = ("project", "priority", "status", "kind")        # the list's other groupings ("" = by when it's due)
SORTS = {
    "due": lambda t: (t.due_date is None, t.due_date or date.max, -t.priority),
    "priority": lambda t: (-t.priority, t.due_date is None, t.due_date or date.max),
    "title": lambda t: t.title.lower(),
    "new": lambda t: -t.created_at.timestamp(),
}


def _grouped(tasks, by):
    """Open tasks as (key, label, items) by project, priority or status."""
    if by == "project":
        groups = {}
        for t in tasks:
            groups.setdefault(t.project_id, []).append(t)
        named = sorted((k for k in groups if k), key=lambda k: (groups[k][0].project.order, groups[k][0].project.name.lower()))
        out = [(f"p{k}", groups[k][0].project.name, groups[k]) for k in named]
        return out + ([("p-none", _("No project"), groups[None])] if None in groups else [])
    if by == "priority":
        return [(f"pr{value}", label, [t for t in tasks if t.priority == value]) for value, label in reversed(Priority.choices)]
    if by == "kind":
        return [(f"k-{value}", label, [t for t in tasks if t.kind == value]) for value, label in TaskKind.choices]
    return [(value, Status(value).label, [t for t in tasks if t.status == value]) for value in (Status.DOING, Status.REVIEW, Status.TODO, Status.BACKLOG)]


def _with_rows(tasks):
    prefetch_related_objects(tasks, *ROW_RELATED)
    return tasks
URGENT_DAYS = 2       # the matrix: due within this many days (or late) counts as urgent
TIMELINE_DAYS = 42    # six weeks


def _matrix(tasks, today):
    """Urgent × important (the Eisenhower matrix). Important: high or urgent
    priority, or tied to a goal. Urgent: late, due within two days, or marked urgent."""
    soon = today + timedelta(days=URGENT_DAYS)
    q = {"do": [], "plan": [], "quick": [], "drop": []}
    for t in tasks:
        important = (t.priority or 0) >= Priority.HIGH or bool(t.goal_id)
        urgent = (t.priority or 0) >= Priority.URGENT or bool(t.due_date and t.due_date <= soon) or t.status == Status.DOING
        q["do" if important and urgent else "plan" if important else "quick" if urgent else "drop"].append(t)
    for items in q.values():
        items.sort(key=lambda t: (t.due_date or date.max, -(t.priority or 0), t.order))
    return [
        ("do", _("Do first"), _("Important and urgent"), q["do"]),
        ("plan", _("Plan it"), _("Important, not urgent — give it a day"), q["plan"]),
        ("quick", _("Get it off your plate"), _("Urgent, not important — do it fast, or hand it over"), q["quick"]),
        ("drop", _("Later, or never"), _("Neither — question whether it's needed"), q["drop"]),
    ]


def _timeline(request, qs, today):
    """Tasks drawn from their start to their due date over six weeks, by project."""
    first = parse_date(request.GET.get("from") or "") or (today - timedelta(days=today.weekday() + 7))
    last = first + timedelta(days=TIMELINE_DAYS - 1)
    dated = (qs.filter(Q(due_date__isnull=False) | Q(start_date__isnull=False))
             .filter(Q(due_date__gte=first) | Q(due_date__isnull=True, start_date__gte=first))
             .filter(Q(start_date__lte=last) | Q(start_date__isnull=True, due_date__lte=last))
             .select_related("project").prefetch_related("blocked_by").order_by("project__name", "start_date", "due_date"))
    rows = {}
    for t in dated:
        a, b = t.start_date or t.due_date, t.due_date or t.start_date
        a2, b2 = max(a, first), min(b, last)
        rows.setdefault(t.project, []).append({
            "t": t, "left": (a2 - first).days * 100 / TIMELINE_DAYS, "width": ((b2 - a2).days + 1) * 100 / TIMELINE_DAYS,
            "cut_start": a < first, "cut_end": b > last, "late": t.is_overdue(today), "days": (b - a).days + 1,
        })
    days = [first + timedelta(days=i) for i in range(TIMELINE_DAYS)]
    weeks = [d for d in days if d.weekday() == first.weekday()]
    return {
        "tl_rows": sorted(rows.items(), key=lambda kv: (kv[0] is None, kv[0].name.lower() if kv[0] else "")),
        "tl_first": first, "tl_last": last, "tl_weeks": weeks, "tl_days": days,
        "tl_today": (today - first).days * 100 / TIMELINE_DAYS if first <= today <= last else None,
        "tl_prev": first - timedelta(days=28), "tl_next": first + timedelta(days=28),
        "tl_undated": qs.exclude(status=Status.DONE).filter(due_date__isnull=True, start_date__isnull=True).count(),
    }


@work_required
def tasks_view(request):
    user, today = request.user, _today()
    view = request.GET.get("view") or request.COOKIES.get("work_task_view") or "list"
    view = view if view in TASK_VIEWS else "list"
    qs = Task.objects.filter(owner=user).select_related("project")
    f = {k: request.GET.get(k, "").strip() for k in ("q", "project", "tag", "priority", "due", "goal", "blocked", "sprint", "kind")}
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
    if f["goal"].isdigit():
        qs = qs.filter(goal_id=int(f["goal"]))
    if f["kind"] in TaskKind.values:
        qs = qs.filter(kind=f["kind"])
    if f["sprint"] == "current":
        from .sprints import current
        qs = qs.filter(sprint=current(user, today))
    elif f["sprint"] == "none":
        qs = qs.filter(sprint__isnull=True)
    elif f["sprint"].isdigit():
        qs = qs.filter(sprint_id=int(f["sprint"]))
    if f["due"] == "overdue":
        qs = qs.filter(due_date__lt=today).exclude(status=Status.DONE)
    elif f["due"] == "today":
        qs = qs.filter(due_date=today)
    elif f["due"] == "week":
        qs = qs.filter(due_date__gte=today, due_date__lte=today + timedelta(days=7))
    elif f["due"] == "none":
        qs = qs.filter(due_date__isnull=True)
    open_blocker = Q(blocked_by__isnull=False) & ~Q(blocked_by__status=Status.DONE)
    if f["blocked"] == "yes":
        qs = qs.filter(open_blocker).exclude(status=Status.DONE)
    elif f["blocked"] == "no":
        qs = qs.exclude(pk__in=Task.objects.filter(owner=user).filter(open_blocker).values("pk"))
    qs = qs.distinct()
    show_subs = request.GET.get("sub") == "1" or bool(f["q"])
    if view in ("list", "board") and not show_subs:
        qs = qs.filter(parent__isnull=True)      # subtasks show under their task (and on Today, the matrix and the timeline)
    qs = qs.select_related("parent")
    show_done = request.GET.get("done") == "1"
    one = request.GET.get("group", "")
    by = request.GET.get("by", "") if request.GET.get("by", "") in GROUP_BY else ""
    sort = request.GET.get("sort", "") if request.GET.get("sort", "") in SORTS else ""
    ctx = {"view": view, "f": f, "filtered": any(f.values()), "show_done": show_done, "today": today, "one_group": one,
           "by": by, "sort": sort, "custom": any(f.values()) or bool(by or sort),
           "projects": Project.objects.filter(owner=user, is_archived=False), "tags": Tag.objects.filter(owner=user),
           "goals": Goal.objects.filter(owner=user, status=GoalStatus.ACTIVE),
           "priorities": Priority.choices, "statuses": Status.choices, "kinds": TaskKind.choices,
           "saved_views": SavedView.objects.filter(owner=user), "sv": request.GET.get("sv", ""), "show_subs": show_subs,
           "has_subs": Task.objects.filter(owner=user, parent__isnull=False).exclude(status=Status.DONE).exists(),
           "templates": TaskTemplate.objects.filter(owner=user).only("pk", "name"),
           "sprints": Sprint.objects.filter(owner=user, completed_at__isnull=True).order_by("start_date", "pk"),
           "query": request.GET.urlencode()}
    if view == "matrix":
        ctx["quadrants"] = _matrix(list(qs.exclude(status=Status.DONE).prefetch_related(*ROW_RELATED)), today)
    elif view == "timeline":
        ctx.update(_timeline(request, qs, today))
    elif view == "board":
        columns = []
        for value, label in Status.choices:
            items = qs.filter(status=value)
            total = items.count()
            items = list((items.order_by("-completed_at") if value == Status.DONE else items)[:BOARD_DONE if value == Status.DONE else BOARD_LIMIT])
            prefetch_related_objects(items, *ROW_RELATED)
            columns.append({"status": value, "label": label, "tasks": items, "total": total, "hidden": total - len(items)})
        ctx["columns"] = columns
    else:
        open_ = all_open = list(qs.exclude(status=Status.DONE).prefetch_related("blocked_by"))
        ctx["open_count"] = len(open_)
        waiting = [t for t in open_ if t.waiting_for]
        open_ = [t for t in open_ if not t.waiting_for]
        active = (Status.DOING, Status.REVIEW)        # started: in their own groups, whatever their dates
        blocked = [t for t in open_ if t.is_blocked and t.status not in active]
        blocked_ids = {t.pk for t in blocked}
        open_ = [t for t in open_ if t.pk not in blocked_ids]
        later = sorted([t for t in open_ if t.my_day and t.my_day > today and t.status not in active
                        and not (t.due_date and t.due_date <= t.my_day)], key=lambda t: t.my_day)
        later_ids = {t.pk for t in later}
        open_ = [t for t in open_ if t.pk not in later_ids]
        groups = [
            ("doing", _("In progress"), [t for t in open_ if t.status == Status.DOING]),
            ("review", _("In review"), [t for t in open_ if t.status == Status.REVIEW]),
            ("waiting", _("Waiting on others"), waiting),
            ("blocked", _("Blocked by other tasks"), blocked),
            ("overdue", _("Late"), [t for t in open_ if t.status not in active and t.due_date and t.due_date < today]),
            ("today", _("Today"), [t for t in open_ if t.status not in active and (t.due_date == today or (t.my_day == today and not t.due_date))]),
            ("upcoming", _("Coming up"), sorted([t for t in open_ if t.status not in active and t.due_date and t.due_date > today], key=lambda t: t.due_date)),
            ("todo", _("To do"), [t for t in open_ if t.status == Status.TODO and not t.due_date and t.my_day != today]),
            ("backlog", _("Backlog"), [t for t in open_ if t.status == Status.BACKLOG and not t.due_date and t.my_day != today]),
            ("later", _("Later"), later),
        ]
        if by:
            groups = _grouped(all_open, by)
        if sort:
            groups = [(key, label, sorted(items, key=SORTS[sort])) for key, label, items in groups]
        groups = [(key, label, items) for key, label, items in groups if items and (not one or key == one)]
        shown, page = [], None
        for i, (key, label, items) in enumerate(groups):
            if one:
                page = Paginator(items, GROUP_PAGE).get_page(request.GET.get("page"))
                groups[i] = (key, label, list(page.object_list), len(items))
            else:
                groups[i] = (key, label, items[:GROUP_LIMIT], len(items))
            shown += groups[i][2]
        ctx["groups"], ctx["page"] = groups, page
        if page:
            from apps.accounts.views import _page_window

            base = request.GET.copy()
            base.pop("page", None)
            ctx.update({"base_query_string": base.urlencode(), "pagination_window": _page_window(page)})
        ctx["done"] = list(qs.filter(status=Status.DONE).order_by("-completed_at")[:50]) if show_done and not one else []
        ctx["done_count"] = qs.filter(status=Status.DONE).count()
        prefetch_related_objects(shown + ctx["done"], *ROW_RELATED)
    response = render_work(request, "work/tasks.html", ctx)
    if request.GET.get("view"):
        response.set_cookie("work_task_view", view, max_age=365 * 86400, samesite="Lax")
    return response


@work_required
def task_view(request, pk=None):
    user = request.user
    task = get_object_or_404(Task, pk=pk, owner=user) if pk else None
    form = TaskForm(request.POST or None, instance=task, owner=user,
                    initial=None if task else {"project": request.GET.get("project") or None, "due_date": request.GET.get("due") or None,
                                               "goal": request.GET.get("goal") or None, "title": request.GET.get("title", ""),
                                               "sprint": request.GET.get("sprint") or None,
                                               "link": request.GET.get("link", "")})
    old_status = task.status if task else None      # the form writes the new one onto the task as it checks it
    if request.method == "POST" and form.is_valid():
        was_done = old_status == Status.DONE
        obj = form.save(commit=False)
        obj.owner = user
        wanted = obj.status
        tick = bool(task) and (wanted == Status.DONE) != was_done
        if tick:                          # ticked off (or back on) the one way: the next repeat, its subtasks, a running timer
            obj.status = old_status
        if not obj.pk:
            obj.order = services.next_order(user, obj.status)
            obj.completed_at = timezone.now() if obj.status == Status.DONE else None
        if obj.scheduled_at:              # planned for a day: it's on that day's list too
            day = timezone.localtime(obj.scheduled_at).date()
            if obj.my_day != day and obj.due_date != day:
                obj.my_day = day
        obj.save()
        form.save_tags(obj)
        if tick:
            services.set_done(obj, wanted == Status.DONE)
            if obj.status != wanted:      # reopened straight into "In progress" or the backlog
                obj.status = wanted
                obj.save(update_fields=["status", "updated_at"])
        messages.success(request, _("Task saved."))
        return redirect("work:task", pk=obj.pk)
    ctx = {"form": form, "task": task, "bug_template": dev.bug_template()}
    if task:
        s = WorkSettings.for_user(user)
        ctx["dev"] = {"key": task.key(s.key_prefix), "branch": dev.branch_name(task, s), "commit": dev.commit_message(task, s),
                      "pr": dev.pr_description(task, s)}
        entries = list(task.entries.select_related("project").order_by("-started_at")[:30])
        spent = services.task_seconds(task)
        subs = list(task.subtasks.all())
        ctx["with_subs"] = {"spent": spent + sum(services.task_seconds(t) for t in subs),
                            "estimate": (task.estimate_minutes or 0) + sum(t.estimate_minutes or 0 for t in subs)} if subs else None
        ctx.update({"entries": entries, "spent": spent, "checklist": task.checklist.all(), "files": list(task.files.all()),
                    "estimate_pct": min(round(100 * spent / (task.estimate_minutes * 60)), 999) if task.estimate_minutes else None,
                    "activity": list(task.activity.all()[:60]),
                    "subtasks": _with_rows(sorted(task.subtasks.select_related("project"), key=lambda t: (t.is_done, t.order, t.pk))),
                    "blocker_options": list(Task.objects.filter(owner=user).exclude(status=Status.DONE).exclude(pk=task.pk)
                                            .exclude(pk__in=task.blocked_by.values("pk")).order_by("-updated_at").only("pk", "title")[:300])})
    return render_work(request, "work/task.html", ctx)


# ── Projects ──────────────────────────────────────────────────────────────
@work_required
def projects_view(request):
    user, today = request.user, _today()
    s = WorkSettings.for_user(user)
    first, last = s.week_of(today)
    week = services.totals(user, first, last)
    week_by = {p.pk if p else None: secs for p, secs in week.by_project}
    all_by = services.tracked_by(user, "project_id")
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
    total = services.tracked_by(user, "project_id", ids=[project.pk]).get(project.pk, 0)
    tasks = Task.objects.filter(owner=user, project=project).select_related("project")
    open_tasks = list(tasks.exclude(status=Status.DONE)[:100])
    done_tasks = list(tasks.filter(status=Status.DONE).order_by("-completed_at")[:15])
    prefetch_related_objects(open_tasks + done_tasks, *ROW_RELATED)
    budget = float(project.estimate_hours or 0) * 3600
    return render_work(request, "work/project.html", {
        "project": project, "total": total,
        "week": next((secs for p, secs in week.by_project if p and p.pk == project.pk), 0),
        "budget_pct": round(100 * total / budget) if budget else None,
        "earned": (float(project.hourly_rate) * total / 3600) if project.hourly_rate else None,
        "open_tasks": open_tasks, "done_tasks": done_tasks,
        "entries": TimeEntry.objects.filter(owner=user, project=project).select_related("task", "project").prefetch_related("tags")[:20],
        "goals": services.with_progress(project.goals.filter(status=GoalStatus.ACTIVE)),
        "notes": Note.objects.filter(owner=user, project=project, is_archived=False)[:10],
        "diagrams": Diagram.objects.filter(owner=user, project=project, is_archived=False).only("pk", "title", "kind", "updated_at")[:8],
        "today": today, "burnup": _burnup(project, today),
        "unbilled": TimeEntry.objects.filter(owner=user, project=project, billable=True, invoiced_at__isnull=True, ended_at__isnull=False).exists(),
    })


@work_required
def project_delete_view(request, pk):
    project = get_object_or_404(Project, pk=pk, owner=request.user)
    if request.method != "POST":
        raise Http404
    delete_with_undo(request, project, _("Project deleted: %(name)s. Its tasks, time and notes are kept, without a project.") % {"name": project.name},
                     label=project.name, back_url=reverse("work:project", args=[pk]))
    return redirect("work:projects")


def _hours(secs):
    """A short label for a bar: "3.5h", "45m", "" for nothing."""
    if not secs:
        return ""
    if secs < 3600:
        return f"{round(secs / 60)}m"
    return f"{secs / 3600:.1f}".rstrip("0").rstrip(".") + "h"


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
    # The week as stacked bars: one per day, a slice per project, against the daily target.
    target = s.daily_target_minutes * 60
    top = max([sum(r["days"][i] for r in sheet_rows) for i in range(7)] + [target, 1])
    chart = []
    for i in range(7):
        d = first + timedelta(days=i)
        total = sum(r["days"][i] for r in sheet_rows)
        segs = [{"project": r["project"], "secs": r["days"][i], "pct": round(100 * r["days"][i] / top, 2)} for r in sheet_rows if r["days"][i]]
        chart.append({"date": d, "secs": total, "pct": round(100 * total / top, 2), "segs": segs, "today": d == today,
                      "off": not s.is_work_day(d), "hrs": _hours(total)})
    return render_work(request, "work/time.html", {
        "chart": chart, "target_pct": round(100 * target / top, 2) if target else None, "target": target,
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
NOTE_TEMPLATES = {   # key: (title, Markdown body, tags)
    "meeting": (gettext_lazy("Meeting notes"), gettext_lazy("**Who:** \n**Goal of the meeting:** \n\n## Notes\n- \n\n## Decisions\n- \n\n## Action items\n- [ ] "), "meeting"),
    "one_on_one": (gettext_lazy("1:1"), gettext_lazy("## Wins since last time\n- \n\n## Blockers / need help with\n- \n\n## Feedback (both ways)\n- \n\n## Career & growth\n- \n\n## Follow-ups\n- [ ] "), "1on1"),
    "adr": (gettext_lazy("Decision record (ADR)"), gettext_lazy("## Status\nProposed\n\n## Context\nWhat is the problem, and why now?\n\n## Options\n1. \n2. \n\n## Decision\nWe will …\n\n## Consequences\n- Good: \n- Bad: \n- Follow-up: "), "adr"),
    "bug": (gettext_lazy("Bug report"), gettext_lazy("## What happens\n\n## What should happen\n\n## Steps to reproduce\n1. \n2. \n\n## Environment\n- Version / commit: \n- Browser / device: \n\n## Logs\n```\n\n```\n\n## Cause & fix\n"), "bug"),
    "postmortem": (gettext_lazy("Post-mortem"), gettext_lazy("## Summary\n\n## Impact\nWho was affected, for how long?\n\n## Timeline\n- 00:00 — \n\n## Root cause\n\n## What went well\n- \n\n## What went badly\n- \n\n## Action items\n- [ ] "), "postmortem"),
    "daily": (gettext_lazy("Daily note"), gettext_lazy("## Top 3 today\n1. \n2. \n3. \n\n## Notes\n- \n\n## Learnt today\n- "), "daily"),
    "study": (gettext_lazy("Study notes"), gettext_lazy("## In one sentence\n\n## Key ideas\n- \n- \n\n## How it fits together\n```mermaid\nflowchart LR\n    A[Idea] --> B[Another idea]\n```\n\n## Flashcards\nQuestion :: Answer\n\n## Questions I still have\n- "), "study"),
    "design": (gettext_lazy("Design doc"), gettext_lazy("## Problem\n\n## Goals / non-goals\n- \n\n## Proposal\n\n## Alternatives considered\n\n## Rollout & risks\n\n## Open questions\n- "), "design"),
}


@work_required
def notes_view(request, pk=None):
    user = request.user
    q, tag = request.GET.get("q", "").strip(), request.GET.get("tag", "").strip().lower()
    archived = request.GET.get("archived") == "1"
    notes = Note.objects.filter(owner=user, is_archived=archived).select_related("project").prefetch_related("tags")
    if q:
        notes = notes.filter(Q(title__icontains=q) | Q(body__icontains=q))
    if tag:
        notes = notes.filter(tags__name=tag)
    note = get_object_or_404(Note, pk=pk, owner=user) if pk else None
    note_data = {"id": None, "title": "", "body": "", "tags": "", "project": "", "updated": 0, "saved": ""}
    template = NOTE_TEMPLATES.get(request.GET.get("template", "")) if not note else None
    if template:
        stamp = date_format(_today(), "j M Y")
        note_data.update({"title": f"{template[0]} — {stamp}", "body": str(template[1]), "tags": template[2]})
    elif not note and request.GET.get("title"):        # a [[link]] to a note that isn't written yet
        note_data["title"] = request.GET["title"].strip()[:200]
    if note:
        note_data = {"id": note.pk, "title": note.title, "body": note.body, "tags": " ".join(note.tags.values_list("name", flat=True)),
                     "project": str(note.project_id or ""), "updated": int(note.updated_at.timestamp() * 1000),
                     "saved": timezone.localtime(note.updated_at).strftime("%H:%M")}
    from django.core.paginator import Paginator

    # Nothing open: the notes as a board of cards (like Keep), unless the list was asked for.
    board = not note and not request.GET.get("new") and request.GET.get("view") != "list"
    page = Paginator(notes.distinct(), 40).get_page(request.GET.get("page"))
    keep = request.GET.copy()
    keep.pop("page", None)
    return render_work(request, "work/notes.html", {
        "note_data": note_data, "board": board, "page_obj": page, "base_query_string": keep.urlencode(),
        "pagination_window": [], "colors": Color.choices,
        "notes": page.object_list, "total": page.paginator.count, "note": note, "q": q, "tag": tag, "archived": archived,
        "tags": Tag.objects.filter(owner=user, notes__isnull=False).distinct(),
        "projects": Project.objects.filter(owner=user, is_archived=False),
        "templates": [(key, t[0]) for key, t in NOTE_TEMPLATES.items()],
        "backlinks": services.backlinks(note) if note else [],
        "titles": list(Note.objects.filter(owner=user, is_archived=False).exclude(title="").order_by("-updated_at")
                       .values_list("title", flat=True)[:500]),
    })


@work_required
def note_today_view(request):
    """Today's note (like Obsidian's or Bear's daily note): opened if it's there, made from the
    "Daily note" template if not — one click from the notes board, the palette or the Today page."""
    today = _today()
    note = (Note.objects.filter(owner=request.user, is_archived=False, tags__name="daily", created_at__date=today).order_by("pk").first())
    if note is None:
        title, body, tags = NOTE_TEMPLATES["daily"]
        note = Note.objects.create(owner=request.user, title=f"{title} — {date_format(today, 'j M Y')}", body=str(body))
        note.tags.set(services.tags_named(request.user, [tags]))
    return redirect("work:note", pk=note.pk)


@work_required
def note_go_view(request):
    """Where a [[Note title]] link goes: that note, or a new one with that title."""
    title = request.GET.get("title", "").strip()[:200]
    notes = Note.objects.filter(owner=request.user, title__iexact=title).order_by("is_archived", "-updated_at")
    note = notes.first() if title else None
    if note:
        return redirect("work:note", pk=note.pk)
    return redirect(reverse("work:notes") + "?" + urlencode({"new": "1", "title": title}))


# ── Diagrams ──────────────────────────────────────────────────────────────
# What each kind is for, shown on the "start something new" tiles.
DIAGRAM_KINDS = [
    (DiagramKind.MINDMAP, "mindmap", gettext_lazy("Ideas around one centre. Tab adds a branch, Enter a sibling.")),
    (DiagramKind.SYSTEM, "server", gettext_lazy("Services, databases, caches and queues, linked up — with the numbers.")),
    (DiagramKind.DRAWING, "shapes", gettext_lazy("Any shapes, dragged and linked — like draw.io.")),
    (DiagramKind.FLOWCHART, "flow", gettext_lazy("Steps and decisions.")),
    (DiagramKind.SEQUENCE, "sequence", gettext_lazy("Who calls whom, in order.")),
    (DiagramKind.ER, "database", gettext_lazy("Tables, keys and how they relate.")),
    (DiagramKind.CLASS, "class", gettext_lazy("Classes, fields and methods.")),
    (DiagramKind.STATE, "state", gettext_lazy("The states something moves through.")),
    (DiagramKind.GANTT, "gantt", gettext_lazy("Tasks on a calendar.")),
    (DiagramKind.TIMELINE, "timeline", gettext_lazy("Events in time.")),
    (DiagramKind.JOURNEY, "journey", gettext_lazy("A person's steps and how each feels.")),
    (DiagramKind.C4, "c4", gettext_lazy("People, systems and what talks to what.")),
    (DiagramKind.ARCHITECTURE, "cloud", gettext_lazy("Cloud services in groups, with icons.")),
    (DiagramKind.BLOCK, "block", gettext_lazy("Boxes laid out in rows and columns.")),
    (DiagramKind.GITGRAPH, "git", gettext_lazy("Branches, commits and merges.")),
    (DiagramKind.PIE, "pie", gettext_lazy("Parts of a whole.")),
    (DiagramKind.QUADRANT, "quadrant", gettext_lazy("Effort against impact: what to do first.")),
    (DiagramKind.XYCHART, "chart", gettext_lazy("Numbers over time as bars and lines.")),
    (DiagramKind.SANKEY, "sankey", gettext_lazy("Where amounts flow, like money or traffic.")),
]
DIAGRAM_ICON = {k: icon for k, icon, _h in DIAGRAM_KINDS}
K = DiagramKind
DIAGRAM_GROUPS = [
    (gettext_lazy("Draw by hand"), [K.DRAWING, K.MINDMAP, K.SYSTEM]),
    (gettext_lazy("Software and systems"), [K.FLOWCHART, K.SEQUENCE, K.ER, K.CLASS, K.STATE, K.C4, K.ARCHITECTURE, K.BLOCK, K.GITGRAPH]),
    (gettext_lazy("Plans and time"), [K.GANTT, K.TIMELINE, K.JOURNEY]),
    (gettext_lazy("Charts"), [K.PIE, K.QUADRANT, K.XYCHART, K.SANKEY]),
]


@work_required
def diagrams_view(request):
    user = request.user
    kind, q = request.GET.get("kind", ""), request.GET.get("q", "").strip()
    archived = request.GET.get("archived") == "1"
    mine = Diagram.objects.filter(owner=user)
    qs = (mine.filter(is_archived=archived).select_related("project").defer("source", "data", "notes", "preview")
          .annotate(has_preview=ExpressionWrapper(~Q(preview=""), output_field=BooleanField())))
    if kind in DiagramKind.values:
        qs = qs.filter(kind=kind)
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(notes__icontains=q) | Q(source__icontains=q))
    project = request.GET.get("project", "")
    if project.isdigit():
        qs = qs.filter(project_id=int(project))
    counts = dict(mine.filter(is_archived=False).values_list("kind").annotate(n=Count("id")))
    starts = diagrams.templates()
    tiles = [{"kind": k, "label": k.label, "icon": icon, "hint": hint, "templates": starts.get(k, []), "count": counts.get(k, 0)}
             for k, icon, hint in DIAGRAM_KINDS]
    by_kind = {t["kind"]: t for t in tiles}
    groups = [{"label": label, "tiles": [by_kind[k] for k in kinds]} for label, kinds in DIAGRAM_GROUPS]
    return render_work(request, "work/diagrams.html", {
        "diagrams": qs[:300], "tiles": tiles, "groups": groups, "kind": kind, "q": q, "archived": archived, "project": project,
        "total": sum(counts.values()), "icons": DIAGRAM_ICON,
        "projects": Project.objects.filter(owner=user, is_archived=False),
    })


@work_required
@require_POST
def diagram_new_view(request):
    kind = request.POST.get("kind", "")
    if kind not in DiagramKind.values:
        raise Http404
    title, source, data, notes = diagrams.start(kind, request.POST.get("template", "blank"))
    project = Project.objects.filter(owner=request.user, pk=request.POST.get("project") or 0).first()
    d = Diagram.objects.create(owner=request.user, kind=kind, title=title[:200], source=source, data=data, notes=notes, project=project)
    return redirect("work:diagram", pk=d.pk)


# The parts a system design board is built from: (type, name). Their pictures are in static/js/diagrams.js.
BOARD_PARTS = [
    ("client", gettext_lazy("Users")), ("mobile", gettext_lazy("Phone app")), ("web", gettext_lazy("Web app")),
    ("dns", gettext_lazy("DNS")), ("cdn", gettext_lazy("CDN")), ("lb", gettext_lazy("Load balancer")),
    ("gateway", gettext_lazy("API gateway")), ("service", gettext_lazy("Service")), ("worker", gettext_lazy("Worker")),
    ("function", gettext_lazy("Function")), ("auth", gettext_lazy("Auth")), ("db", gettext_lazy("SQL database")),
    ("nosql", gettext_lazy("NoSQL store")), ("cache", gettext_lazy("Cache")), ("queue", gettext_lazy("Queue")),
    ("stream", gettext_lazy("Event stream")), ("storage", gettext_lazy("File storage")), ("search", gettext_lazy("Search")),
    ("analytics", gettext_lazy("Analytics")), ("external", gettext_lazy("Outside service")), ("monitor", gettext_lazy("Monitoring")),
    ("note", gettext_lazy("Sticky note")), ("zone", gettext_lazy("Zone / group")),
]


def _snippets(kind):
    """Buttons above a text diagram that put in a piece of Mermaid: (label, text)."""
    k = DiagramKind
    table = {
        k.FLOWCHART: [(_("Box"), "\n    id[Text]"), (_("Rounded"), "\n    id([Text])"), (_("Question"), "\n    id{Question?}"),
                      (_("Arrow"), " --> "), (_("Arrow with words"), " -- words --> "), (_("Dotted arrow"), " -.-> "),
                      (_("Group"), "\n    subgraph Name\n        \n    end")],
        k.SEQUENCE: [(_("Person"), "\n    actor P as Person"), (_("Part"), "\n    participant S as Service"), (_("Call"), "\n    A->>B: Request"),
                     (_("Answer"), "\n    B-->>A: Response"), (_("Note"), "\n    Note over A,B: Text"), (_("Loop"), "\n    loop Every minute\n        A->>B: Ping\n    end"),
                     (_("Either / or"), "\n    alt Success\n        B-->>A: OK\n    else Failure\n        B-->>A: Error\n    end")],
        k.ER: [(_("Table"), "\n    TABLE {\n        int id PK\n        string name\n    }"), (_("One to many"), "\n    A ||--o{ B : has"),
               (_("One to one"), "\n    A ||--|| B : is"), (_("Many to many"), "\n    A }o--o{ B : links")],
        k.CLASS: [(_("Class"), "\n    class Name {\n        +field\n        +method()\n    }"), (_("Inherits"), "\n    Parent <|-- Child"),
                  (_("Contains"), "\n    Whole *-- Part"), (_("Uses"), "\n    A --> B")],
        k.STATE: [(_("State"), "\n    Name"), (_("Change"), "\n    A --> B: why"), (_("Start"), "\n    [*] --> A"), (_("End"), "\n    A --> [*]"),
                  (_("Group"), "\n    state Name {\n        [*] --> Inner\n    }")],
        k.GANTT: [(_("Section"), "\n    section Name"), (_("Task"), "\n    Task name :t1, after a1, 3d"), (_("Milestone"), "\n    Milestone :milestone, after t1, 0d")],
        k.TIMELINE: [(_("Period"), "\n    2026 : What happened"), (_("Section"), "\n    section Name")],
        k.JOURNEY: [(_("Section"), "\n    section Name"), (_("Step"), "\n      Step: 3: Person")],
        k.C4: [(_("Person"), '\n    Person(id, "Name", "What they do")'), (_("System"), '\n    System(id, "Name", "What it does")'),
               (_("Outside system"), '\n    System_Ext(id, "Name")'), (_("Database"), '\n    SystemDb(id, "Name")'),
               (_("Link"), '\n    Rel(from, to, "Uses", "HTTPS")'), (_("Boundary"), '\n    System_Boundary(b1, "Name") {\n        \n    }')],
        k.ARCHITECTURE: [(_("Group"), "\n    group name(cloud)[Name]"), (_("Server"), "\n    service id(server)[Name]"),
                         (_("Database"), "\n    service id(database)[Name]"), (_("Storage"), "\n    service id(disk)[Name]"),
                         (_("Internet"), "\n    service id(internet)[Name]"), (_("Link"), "\n    a:R --> L:b")],
        k.BLOCK: [(_("Columns"), "\n    columns 3"), (_("Box"), '\n    id["Text"]'), (_("Wide box"), '\n    id["Text"]:2'),
                  (_("Database"), '\n    id[("Text")]'), (_("Gap"), "\n    space"), (_("Arrow"), "\n    a --> b")],
        k.GITGRAPH: [(_("Commit"), '\n    commit id: "message"'), (_("Branch"), "\n    branch name"), (_("Switch"), "\n    checkout main"),
                     (_("Merge"), "\n    merge name"), (_("Tag"), '\n    commit id: "release" tag: "v1.0"')],
        k.PIE: [(_("Slice"), '\n    "Name" : 10')],
        k.QUADRANT: [(_("Point"), "\n    Item: [0.5, 0.5]"), (_("Quadrant names"), "\n    quadrant-1 Top right\n    quadrant-2 Top left\n    quadrant-3 Bottom left\n    quadrant-4 Bottom right")],
        k.XYCHART: [(_("Bars"), "\n    bar [1, 2, 3]"), (_("Line"), "\n    line [1, 2, 3]"), (_("Labels"), "\n    x-axis [A, B, C]")],
        k.SANKEY: [(_("Flow"), "\nFrom,To,10")],
    }
    return table.get(kind, [])


def _diagram_texts(kind=""):
    return {
        "kindLabel": str(DiagramKind(kind).label) if kind in DiagramKind.values else "",
        "snips": _snippets(kind),
        "saving": _("Saving…"), "saved": _("Saved"), "editing": _("Editing…"), "offline": _("Saved on this device"), "error": _("Not saved"),
        "newIdea": _("New idea"), "copied": _("Copied"), "exported": _("Downloaded"),
        "deleted": _("Diagram deleted"), "tasksMade": _("Tasks made"), "seeTasks": _("See them"),
        "pickIdea": _("Pick an idea first."), "importEmpty": _("Paste a list first: one idea per line, indent to go deeper."),
        "connectPick": _("Now tap the part to connect to."), "nothing": _("There is nothing to export yet."),
        "badSyntax": _("There is a mistake in the text"), "noMermaid": _("The diagram drawing tool could not load. Check the internet connection."),
        "replaceMap": _("Replace this mind map with the pasted list? You can undo it."),
        "parts": {k: str(v) for k, v in BOARD_PARTS},
        "cardsMade": _("Flashcards made"), "seeCards": _("See them"), "noCards": _("Add ideas under an idea to make a card from it."),
        "versionSaved": _("Version saved"), "restored": _("Earlier version brought back"), "restoreConfirm": _("Bring back this version? What's there now is kept as a version too."),
        "noMatch": _("Nothing matches"), "copiedParts": _("Copied"), "pasted": _("Pasted"),
        "auto": _("Kept by itself"), "now": _("Now"),
        **(_drawing_texts() if kind == DiagramKind.DRAWING or kind in DRAG_KINDS else {}),
    }


def _drawing_texts():
    """Names for the drag-and-drop editor (static/js/drawing.js): its shapes, link ends and kinds of class link."""
    return {
        "shapes": {
            "terminal": _("Start / end"), "process": _("Step"), "decision": _("Decision"), "io": _("Input / output"), "subroutine": _("Sub-process"),
            "database": _("Database"), "document": _("Document"), "circle": _("Circle"), "dcircle": _("Double circle"), "hexagon": _("Preparation"),
            "manual": _("Manual step"), "flag": _("Flag"), "rounded": _("Rounded box"), "note": _("Note"), "text": _("Text"), "container": _("Group"),
            "start": _("Start"), "state": _("State"), "choice": _("Choice"), "fork": _("Fork / join"), "end": _("End"),
            "class": _("Class"), "interface": _("Interface"), "abstract": _("Abstract class"), "enum": _("Enumeration"), "entity": _("Table"),
            "rect": _("Box"), "ellipse": _("Ellipse"), "triangle": _("Triangle"), "trapezoid": _("Trapezoid"), "cloud": _("Cloud"), "actor": _("Person"),
            "picture": _("Picture"),
        },
        "uploading": _("Uploading…"), "imageFailed": _("The picture couldn't be uploaded."), "drawioEmpty": _("No shapes found in that file."),
        "drawioOpened": _("Shapes brought in"), "drawioBad": _("That file couldn't be read as a draw.io drawing."),
        "starts": {"terminal": _("Start"), "io": _("Input"), "subroutine": _("Sub-process"), "manual": _("Manual step")},
        "shapeGroups": {"basic": _("Shapes"), "uml": _("UML and data")},
        "marks": {
            "none": _("None"), "arrow": _("Arrow"), "open": _("Open arrow"), "triangle": _("Triangle (inherits)"), "diamond": _("Filled diamond (owns)"),
            "odiamond": _("Hollow diamond (has)"), "circle": _("Circle"), "cross": _("Cross"),
            "one": _("Exactly one"), "zone": _("Zero or one"), "many": _("One or more"), "zmany": _("Zero or more"),
        },
        "classLinks": {
            "association": _("Uses (association)"), "inheritance": _("Inherits"), "realization": _("Implements"), "composition": _("Is made of (composition)"),
            "aggregation": _("Has (aggregation)"), "dependency": _("Depends on"), "link": _("Line"), "dashedLink": _("Dashed line"),
        },
        "addLinked": _("Click: add a linked shape. Drag: link to another shape."), "linkLabel": _("Label"),
    }


@work_required
def diagram_view(request, pk):
    d = get_object_or_404(Diagram.objects.select_related("project"), pk=pk, owner=request.user)
    payload = {"id": d.pk, "title": d.title, "kind": d.kind, "source": d.source, "data": d.data, "notes": d.notes,
               "project": str(d.project_id or ""), "saved": timezone.localtime(d.updated_at).strftime("%H:%M"),
               "updated": int(d.updated_at.timestamp() * 1000), "pinned": d.is_pinned,
               "hasPreview": bool(d.preview), "look": (d.data or {}).get("look", "") if not d.is_visual else "",
               "mode": ((d.data or {}).get("mode") or "draw") if d.kind in DRAG_KINDS else ""}
    return render_work(request, "work/diagram.html", {
        "diagram": d, "payload": payload, "sketchable": d.kind in diagrams.SKETCH_KINDS, "draggable": d.kind in DRAG_KINDS, "icon": DIAGRAM_ICON.get(d.kind, "diagram"), "texts": _diagram_texts(d.kind), "parts": BOARD_PARTS,
        "projects": Project.objects.filter(owner=request.user, is_archived=False),
        "kinds": [(k, k.label) for k in DiagramKind if k not in VISUAL_KINDS],
    })


def _svg_picture(svg, request, modified=None, fixed=False):
    """A picture a page drew, sent as an image with scripts, links and
    anything outside it switched off."""
    response = HttpResponse(svg, content_type="image/svg+xml; charset=utf-8")
    response["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; sandbox"
    response["X-Content-Type-Options"] = "nosniff"
    if fixed or request.GET.get("v"):     # the address names the version, so a copy can be kept until it changes
        response["Cache-Control"] = "private, max-age=31536000, immutable"
    else:
        response["Cache-Control"] = "private, no-cache"
        if modified:
            response["Last-Modified"] = http_date(modified.timestamp())
    return response


@work_required
def diagram_preview_view(request, pk):
    """The list's picture of a diagram (also what a note shows when a diagram is put in it)."""
    d = get_object_or_404(Diagram.objects.only("preview", "owner_id", "updated_at"), pk=pk, owner=request.user)
    if not d.preview:
        raise Http404
    since = parse_http_date_safe(request.headers.get("If-Modified-Since", ""))
    if since and not request.GET.get("v") and int(d.updated_at.timestamp()) <= since:
        return HttpResponseNotModified()
    return _svg_picture(d.preview, request, d.updated_at)


@work_required
def note_image_view(request, pk):
    """A picture in a note — only ever to the person it belongs to."""
    import mimetypes
    import os

    from django.http import FileResponse

    from .models import NoteImage

    img = get_object_or_404(NoteImage, pk=pk, owner=request.user)
    try:
        handle = img.file.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404
    response = FileResponse(handle, content_type=mimetypes.guess_type(img.file.name)[0] or "application/octet-stream")
    response["Content-Disposition"] = f'inline; filename="{os.path.basename(img.file.name)}"'
    response["Cache-Control"] = "private, max-age=31536000, immutable"     # a picture never changes
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return response


@csrf_exempt
@require_POST
def git_hook_view(request, token):
    """GitHub / GitLab webhooks (no sign-in: the secret address, and the body signed
    with the same secret). See dev.handle for what a delivery does."""
    import json

    from django.http import JsonResponse

    s = WorkSettings.objects.filter(git_token=token).exclude(git_token="").select_related("owner").first()
    if s is None or len(token) < 20 or not s.owner.is_active or not can_use(s.owner):
        raise Http404
    if not dev.signed(request, s.git_token):
        return JsonResponse({"ok": False, "error": "The signature doesn't match: use the secret from Settings."}, status=403)
    event = request.headers.get("X-GitHub-Event") or request.headers.get("X-Gitlab-Event") or ""
    if event == "ping":
        return JsonResponse({"ok": True, "pong": True})
    try:
        raw = request.POST.get("payload") if request.content_type == "application/x-www-form-urlencoded" else request.body
        data = json.loads(raw or b"{}")
    except ValueError:
        return JsonResponse({"ok": False, "error": "Send JSON."}, status=400)
    return JsonResponse({"ok": True, **dev.handle(s.owner, s, event, data)})


@work_required
def task_file_view(request, pk):
    """A file kept with a task — only ever to the person it belongs to. Pictures
    open in the browser; everything else is downloaded, under its own name."""
    import mimetypes

    from django.http import FileResponse

    from .models import TaskFile

    tf = get_object_or_404(TaskFile, pk=pk, owner=request.user)
    try:
        handle = tf.file.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404
    inline = tf.is_image and request.GET.get("download") != "1"
    kind = mimetypes.guess_type(tf.file.name)[0] if inline else "application/octet-stream"
    response = FileResponse(handle, content_type=kind or "application/octet-stream", as_attachment=not inline, filename=tf.name)
    response["Cache-Control"] = "private, max-age=31536000, immutable"     # a kept file never changes
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return response


@work_required
def diagram_version_preview_view(request, pk, vid):
    v = get_object_or_404(DiagramVersion.objects.only("preview"), pk=vid, diagram_id=pk, diagram__owner=request.user)
    if not v.preview:
        raise Http404
    return _svg_picture(v.preview, request, fixed=True)     # a version never changes


# ── Flashcards ────────────────────────────────────────────────────────────
def _with_counts(decks, counts):
    for dk in decks:
        c = counts.get(dk.pk, {})
        dk.n_due, dk.n_new, dk.n_total, dk.n_learnt = c.get("due", 0), c.get("new", 0), c.get("total", 0), c.get("learnt", 0)
        dk.n_today = dk.n_due + dk.n_new
        dk.pct = round(100 * dk.n_learnt / dk.n_total) if dk.n_total else 0
    return decks


@work_required
def cards_view(request):
    user, today = request.user, _today()
    counts = cards.deck_counts(user, today)
    decks = _with_counts(list(Deck.objects.filter(owner=user, is_archived=False).select_related("learning")), counts)
    stats = cards.stats(user, today)
    pad = stats["heat"][0]["date"].weekday()            # the heatmap's rows run Monday to Sunday
    return render_work(request, "work/cards.html", {
        "decks": decks, "archived": _with_counts(list(Deck.objects.filter(owner=user, is_archived=True)), counts),
        "due": sum(dk.n_today for dk in decks), "stats": stats, "forecast": cards.forecast(user, today),
        "pad": range(pad), "weeks": -(-(pad + len(stats["heat"])) // 7),
        "form": DeckForm(owner=user, initial={"new_per_day": 20}),
    })


@work_required
@require_POST
def deck_new_view(request):
    user = request.user
    learning = LearningItem.objects.filter(owner=user, pk=request.POST.get("learning") or 0).first()
    if learning and request.POST.get("from_learning"):      # "Flashcards" on something you're learning: its deck
        deck = Deck.objects.filter(owner=user, learning=learning).first() or Deck.objects.create(
            owner=user, name=learning.title[:120], learning=learning, color=Color.PURPLE)
        return redirect("work:deck", pk=deck.pk)
    form = DeckForm(request.POST, owner=user)
    if form.is_valid():
        deck = form.save(commit=False)
        deck.owner = user
        deck.save()
        return redirect("work:deck", pk=deck.pk)
    messages.error(request, " ".join(e for errs in form.errors.values() for e in errs))
    return redirect("work:cards")


DECK_SHOW = ("all", "due", "new", "learnt", "paused")


@work_required
def deck_view(request, pk):
    user, today = request.user, _today()
    deck = get_object_or_404(Deck.objects.select_related("learning"), pk=pk, owner=user)
    form = DeckForm(request.POST or None, instance=deck, owner=user)
    if request.method == "POST":
        if form.is_valid():
            form.save()
            messages.success(request, _("Deck saved."))
            return redirect("work:deck", pk=deck.pk)
    show, q = request.GET.get("show", "all"), request.GET.get("q", "").strip()
    show = show if show in DECK_SHOW else "all"
    qs = deck.cards.all()
    if show == "due":
        qs = qs.filter(is_suspended=False, last_reviewed__isnull=False, due__lte=today)
    elif show == "new":
        qs = qs.filter(last_reviewed__isnull=True)
    elif show == "learnt":
        qs = qs.filter(interval__gte=cards.MATURE)
    elif show == "paused":
        qs = qs.filter(is_suspended=True)
    if q:
        qs = qs.filter(Q(front__icontains=q) | Q(back__icontains=q))
    _with_counts([deck], cards.deck_counts(user, today))
    page = Paginator(qs.order_by("-created_at", "-pk"), 100).get_page(request.GET.get("page"))
    return render_work(request, "work/deck.html", {
        "deck": deck, "form": form, "page": page, "cards": [card_json(c) for c in page], "show": show, "q": q,
        "paused": deck.cards.filter(is_suspended=True).count(), "decks": Deck.objects.filter(owner=user, is_archived=False).exclude(pk=deck.pk),
        "texts": _card_texts(),
    })


@work_required
def deck_export_view(request, pk):
    """One deck as a tab-separated file: Anki, Quizlet and spreadsheets open it."""
    deck = get_object_or_404(Deck, pk=pk, owner=request.user)
    lines = ["\t".join(t.replace("\t", " ").replace("\r", "").replace("\n", "<br>") for t in (c.front, c.back)) for c in deck.cards.order_by("pk")]
    response = HttpResponse("\n".join(lines) + "\n", content_type="text/tab-separated-values; charset=utf-8")
    name = "".join(ch if ch.isalnum() or ch in "-_ " else "-" for ch in deck.name).strip().replace(" ", "-")[:60] or "deck"
    response["Content-Disposition"] = f'attachment; filename="{name}.tsv"'
    return response


def _card_texts():
    return {
        "again": _("Again"), "hard": _("Hard"), "good": _("Good"), "easy": _("Easy"), "show": _("Show the answer"),
        "deleted": _("Card deleted"), "added": _("Card added"), "addedMany": _("Cards added"), "skipped": _("already in the deck"),
        "saved": _("Saved"), "paused": _("Paused: it won't come up until you start it again"), "resumed": _("It will come up again"),
        "reset": _("It will come up as new"), "resetConfirm": _("Forget how well you know this card and start it again as new?"),
        "deleteDeck": _("Delete this deck and all its cards? You can bring it back from Recently deleted."),
        "noAnswer": _("(no answer written)"), "moved": _("Moved"), "undone": _("Answer taken back"),
    }


@work_required
def card_review_view(request):
    """A review session: the cards due today (or, to practise, every card in a deck)."""
    user = request.user
    deck = Deck.objects.filter(owner=user, pk=request.GET.get("deck") or 0).first()
    practice = request.GET.get("practice") == "1" and deck is not None
    if practice:
        session = list(deck.cards.filter(is_suspended=False).order_by("?")[:cards.SESSION_MAX])
    else:
        session = cards.due_cards(user, deck)
    return render_work(request, "work/cards_review.html", {
        "deck": deck, "practice": practice, "texts": _card_texts(),
        "review": {"cards": [card_json(c, deck_info=True) for c in session], "practice": practice,
                    "back": reverse("work:deck", args=[deck.pk]) if deck else reverse("work:cards")},
        "stats": cards.stats(user, days=1),
    })


# ── Snippets ──────────────────────────────────────────────────────────────
@work_required
def snippets_view(request):
    user = request.user
    q, lang, tag = request.GET.get("q", "").strip(), request.GET.get("lang", ""), request.GET.get("tag", "").strip().lower()
    snippets = Snippet.objects.filter(owner=user).prefetch_related("tags")
    if q:
        snippets = snippets.filter(Q(title__icontains=q) | Q(code__icontains=q) | Q(description__icontains=q) | Q(tags__name__icontains=q))
    if lang:
        snippets = snippets.filter(language=lang)
    if tag:
        snippets = snippets.filter(tags__name=tag)
    used = set(Snippet.objects.filter(owner=user).values_list("language", flat=True))
    from apps.accounts.views import _page_window as page_window

    page = Paginator(snippets.distinct(), 30).get_page(request.GET.get("page"))
    keep = request.GET.copy()
    keep.pop("page", None)
    return render_work(request, "work/snippets.html", {
        "snippets": page.object_list, "page_obj": page, "base_query_string": keep.urlencode(), "pagination_window": page_window(page),
        "q": q, "lang": lang, "tag": tag,
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


def _earned(by_project):
    """Time × hourly rate over the projects that have a rate (None when none has one)."""
    rated = [(p, secs) for p, secs in by_project if p and p.hourly_rate]
    return sum(float(p.hourly_rate) * secs / 3600 for p, secs in rated) if rated else None


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
    est = services.estimate_accuracy(user, start, end)
    hours = t.by_hour
    hpeak = max(hours) or 1
    year = services.daily_seconds(user, today - timedelta(days=364), today)
    return render_work(request, "work/reports.html", {
        "t": t, "start": start, "end": end, "preset": preset, "today": today,
        "bars": [{"day": d, "secs": v, "pct": round(100 * v / peak), "work": s.is_work_day(d), "weekend": not s.is_work_day(d), "hrs": _hours(v)}
                 for d, v in t.by_day.items()],
        "avg_pct": round(100 * t.daily_average / peak, 1) if t.daily_average else None,
        "target_total": s.daily_target_minutes * 60 * work_days,
        "target_pct": round(100 * t.seconds / (s.daily_target_minutes * 60 * work_days)) if work_days else None,
        "projects": [{"p": p, "secs": secs, "pct": round(100 * secs / t.seconds) if t.seconds else 0,
                      "earned": float(p.hourly_rate) * secs / 3600 if p and p.hourly_rate else None} for p, secs in t.by_project],
        "earned": _earned(t.by_project),
        "kinds": [{"k": k, "icon": KIND_ICONS.get(k, "check"), "secs": secs, "pct": round(100 * secs / t.seconds) if t.seconds else 0} for k, secs in t.by_kind]
        if any(k != TaskKind.TASK for k, _secs in t.by_kind) else [],
        "tags": [{"tag": tg, "secs": secs, "pct": round(100 * secs / t.seconds) if t.seconds else 0} for tg, secs in t.by_tag[:12]],
        "tasks": t.by_task, "completed": completed.count(), "created": Task.objects.filter(owner=user, created_at__gte=lo, created_at__lt=hi).count(),
        "est": est, "delivery": services.delivery(user, start, end),
        "hours": [{"h": h, "secs": v, "pct": round(100 * v / hpeak), "level": 0 if not v else min(4, 1 + int(3.999 * v / hpeak))} for h, v in enumerate(hours)],
        "heat": services.heatmap(year, today, s.week_start), "year_total": sum(year.values()),
        "year_days": sum(1 for v in year.values() if v),
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
        if action == "feed":
            s.new_feed_token()
            messages.success(request, _("New calendar link made. The old one no longer works."))
            return redirect(reverse("work:settings") + "#feed")
        if action == "test_brief":
            from . import emails

            result = emails.send_brief(request.user, request=request, force=True)
            if result == "sent":
                messages.success(request, _("Sent to %(email)s.") % {"email": request.user.email})
            else:
                messages.error(request, _("The email couldn't be sent. Try again later."))
            return redirect(reverse("work:settings") + "#emails")
        if action == "git":
            s.new_git_token()
            messages.success(request, _("Webhook address made. Add it to your repository (the steps are below)."))
            return redirect(reverse("work:settings") + "#git")
        if action == "git_off":
            s.git_token = ""
            s.save(update_fields=["git_token"])
            messages.success(request, _("Git connection turned off."))
            return redirect(reverse("work:settings") + "#git")
        if action == "feed_off":
            s.feed_token = ""
            s.save(update_fields=["feed_token"])
            messages.success(request, _("Calendar link turned off."))
            return redirect(reverse("work:settings") + "#feed")
        if action == "restore":
            return _restore(request)
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
    feed = request.build_absolute_uri(reverse("work:feed", args=[s.feed_token])) if s.feed_token else ""
    sample = Task(pk=42, title=_("Fix the login redirect"), kind=TaskKind.BUG)
    return render_work(request, "work/settings.html", {
        "form": form, "tags": tags, "tag_form": tag_form, "feed": feed,
        "git_hook": request.build_absolute_uri(reverse("work:git_hook", args=[s.git_token])) if s.git_token else "",
        "branch_example": dev.branch_name(sample, s), "key_example": sample.key(s.key_prefix),
    })


BACKUP_LIMIT = 30 * 1024 * 1024


def _restore(request):
    """Adds what's in a backup (.zip from "Download everything", or its data.json)."""
    import json
    import zipfile

    upload = request.FILES.get("backup")
    back = redirect(reverse("work:settings") + "#data")
    if not upload or upload.size > BACKUP_LIMIT:
        messages.error(request, _("Choose the .zip (or data.json) you downloaded, up to 30 MB."))
        return back
    try:
        if zipfile.is_zipfile(upload):
            with zipfile.ZipFile(upload) as z:
                names = set(z.namelist())     # this page's download, or "My data & backup"'s
                base = "" if "data.json" in names else "backup/"
                rows = json.loads(z.read(base + "data.json").decode("utf-8"))
                if not isinstance(rows, list):
                    raise ValueError

                def media(name):              # an uploaded file kept in the backup
                    member = base + "media/" + name
                    return z.read(member) if member in names and ".." not in name.split("/") else None

                counts = services.restore(request.user, rows, media=media)
        else:
            upload.seek(0)
            rows = json.loads(upload.read().decode("utf-8"))
            if not isinstance(rows, list):
                raise ValueError
            counts = services.restore(request.user, rows)
    except (KeyError, ValueError, UnicodeDecodeError, zipfile.BadZipFile):
        messages.error(request, _("That file isn't a Productivity backup."))
        return back
    except Exception:   # a damaged file: nothing was added (it all runs in one transaction)
        import logging

        logging.getLogger(__name__).exception("work backup restore failed")
        messages.error(request, _("The backup couldn't be read, so nothing was added."))
        return back
    messages.success(request, _("Backup restored: %(tasks)s tasks, %(time)s time entries, %(notes)s notes and %(other)s other items added.") % {
        "tasks": counts.get("task", 0), "time": counts.get("timeentry", 0), "notes": counts.get("note", 0),
        "other": sum(v for k, v in counts.items() if k not in ("task", "timeentry", "note"))})
    return back


@work_required
def help_view(request):
    return render_work(request, "work/help.html", {})



# ── Goals ─────────────────────────────────────────────────────────────────
@work_required
def goals_view(request):
    user, today = request.user, _today()
    show = request.GET.get("show", "active")
    show = show if show in ("active", "done", "dropped") else "active"
    goals = services.with_progress(Goal.objects.filter(owner=user, status=show).select_related("project"))
    counts = dict(Goal.objects.filter(owner=user).values_list("status").annotate(n=Count("id")).values_list("status", "n"))
    return render_work(request, "work/goals.html", {"goals": goals, "show": show, "counts": counts, "today": today})


@work_required
def goal_form_view(request, pk=None):
    goal = get_object_or_404(Goal, pk=pk, owner=request.user) if pk else None
    initial = None if goal else {"project": request.GET.get("project") or None, "area": request.GET.get("area") or None}
    form = GoalForm(request.POST or None, instance=goal, owner=request.user, initial=initial)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.owner = request.user
        obj.save()
        messages.success(request, _("Goal saved."))
        return redirect("work:goal", pk=obj.pk)
    return render_work(request, "work/goal_form.html", {"form": form, "goal": goal})


@work_required
def goal_view(request, pk):
    user, today = request.user, _today()
    goal = get_object_or_404(Goal.objects.select_related("project"), pk=pk, owner=user)
    if request.method == "POST":
        action = request.POST.get("action")
        if action in GoalStatus.values:
            services.set_goal_status(goal, action)
            messages.success(request, {GoalStatus.DONE: _("Goal reached. Well done!"), GoalStatus.DROPPED: _("Goal dropped."),
                                       GoalStatus.ACTIVE: _("Goal is active again.")}[action])
        elif action == "delete":
            delete_with_undo(request, goal, _("Goal deleted: %(title)s. Its tasks are kept.") % {"title": goal.title},
                             label=goal.title, back_url=reverse("work:goal", args=[pk]))
            return redirect("work:goals")
        return redirect("work:goal", pk=pk)
    goal = services.with_progress([goal])[0]
    tasks = Task.objects.filter(owner=user, goal=goal).select_related("project")
    open_tasks = list(tasks.exclude(status=Status.DONE))
    done_tasks = list(tasks.filter(status=Status.DONE).order_by("-completed_at")[:20])
    prefetch_related_objects(open_tasks + done_tasks, *ROW_RELATED)
    spent = sum(services.tracked_by(user, "task__goal_id", ids=[goal.pk]).values())
    return render_work(request, "work/goal.html", {
        "goal": goal, "steps": goal.steps.all(), "open_tasks": open_tasks, "done_tasks": done_tasks, "today": today,
        "spent": spent, "days_left": goal.days_left(today),
        "learning": goal.learning.all()[:10],
    })


# ── Learning ──────────────────────────────────────────────────────────────
@work_required
def learning_view(request):
    user, today = request.user, _today()
    show = request.GET.get("show", "active")
    show = show if show in (*LearningStatus.values, "all") else "active"
    kind = request.GET.get("kind", "")
    items = LearningItem.objects.filter(owner=user).prefetch_related("tags")
    counts = dict(items.values_list("status").annotate(n=Count("id")).values_list("status", "n"))
    if show != "all":
        items = items.filter(status=show)
    if kind in LearningKind.values:
        items = items.filter(kind=kind)
    if show == LearningStatus.DONE:
        items = items.order_by("-finished_on", "-updated_at")
    return render_work(request, "work/learning.html", {
        "items": items.annotate(n_cards=Count("decks__cards", distinct=True))[:300], "show": show, "kind": kind, "counts": counts, "kinds": LearningKind.choices,
        "finished_this_year": LearningItem.objects.filter(owner=user, status=LearningStatus.DONE, finished_on__year=today.year).count(),
        "statuses": LearningStatus.choices,
    })


@work_required
def learning_form_view(request, pk=None):
    item = get_object_or_404(LearningItem, pk=pk, owner=request.user) if pk else None
    initial = None
    if not item:
        initial = {k: request.GET.get(k) for k in ("title", "url", "kind", "goal") if request.GET.get(k)}
    form = LearningForm(request.POST or None, instance=item, owner=request.user, initial=initial)
    if request.method == "POST":
        if item and request.POST.get("action") == "delete":
            delete_with_undo(request, item, _("Removed from your learning list: %(title)s.") % {"title": item.title},
                             label=item.title, back_url=reverse("work:learning"))
            return redirect("work:learning")
        if form.is_valid():
            obj = form.save(commit=False)
            obj.owner = request.user
            obj.save()
            form.save_tags(obj)
            messages.success(request, _("Saved."))
            return redirect(reverse("work:learning") + f"?show={obj.status}#learn-{obj.pk}")
    return render_work(request, "work/learning_form.html", {"form": form, "item": item})


# ── Review & brag document ────────────────────────────────────────────────
def _review_range(request, s, today):
    preset = request.GET.get("range", "week")
    if preset == "quarter":
        q = (today.month - 1) // 3 * 3 + 1
        return (today.replace(month=q, day=1), today), preset
    if preset == "half":
        return (today.replace(month=1 if today.month <= 6 else 7, day=1), today), preset
    return _range(request, s, today)


@work_required
def review_view(request):
    user, today = request.user, _today()
    s = WorkSettings.for_user(user)
    (start, end), preset = _review_range(request, s, today)
    if (end - start).days > 400:
        start = end - timedelta(days=400)
    data = services.review(user, start, end)
    md = services.review_markdown(data)
    if request.GET.get("export") == "md":
        response = HttpResponse(md, content_type="text/markdown; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="review-{start}-{end}.md"'
        return response
    lo = services.day_bounds(today)[0]
    return render_work(request, "work/review.html", {
        "d": data, "md": md, "start": start, "end": end, "preset": preset, "today": today,
        "presets": [("week", _("This week")), ("lastweek", _("Last week")), ("month", _("This month")), ("lastmonth", _("Last month")),
                    ("quarter", _("This quarter")), ("half", _("Half year")), ("year", _("This year"))],
        "late": Task.objects.filter(owner=user, due_date__lt=today).exclude(status=Status.DONE).count(),
        "coming": Task.objects.filter(owner=user, due_date__gte=today, due_date__lte=today + timedelta(days=7)).exclude(status=Status.DONE)
                  .select_related("project").order_by("due_date")[:12],
        "stale": Task.objects.filter(owner=user, status__in=[Status.DOING, Status.REVIEW], updated_at__lt=lo - timedelta(days=7)).count(),
        "waiting": Task.objects.filter(owner=user).exclude(waiting_for="").exclude(status=Status.DONE).count(),
    })


# ── Calendar ──────────────────────────────────────────────────────────────
@work_required
def calendar_view(request):
    import calendar as cal

    user, today = request.user, _today()
    s = WorkSettings.for_user(user)
    month = parse_date((request.GET.get("month") or "") + "-01") if request.GET.get("month") else None
    month = (month or today).replace(day=1)
    last = month.replace(day=cal.monthrange(month.year, month.month)[1])
    first_cell = month - timedelta(days=(month.weekday() - s.week_start) % 7)
    last_cell = last + timedelta(days=(s.week_start - last.weekday() - 1) % 7)
    secs = services.daily_seconds(user, first_cell, last_cell)
    due = {}
    for t in (Task.objects.filter(owner=user, due_date__gte=first_cell, due_date__lte=last_cell)
              .select_related("project").order_by("status", "-priority", "order")):
        due.setdefault(t.due_date, []).append(t)
    lo, hi = services.day_bounds(first_cell)[0], services.day_bounds(last_cell)[1]
    done = {}
    for when in Task.objects.filter(owner=user, status=Status.DONE, completed_at__gte=lo, completed_at__lt=hi).values_list("completed_at", flat=True):
        day = timezone.localtime(when).date()
        done[day] = done.get(day, 0) + 1
    moods = dict(JournalEntry.objects.filter(owner=user, date__gte=first_cell, date__lte=last_cell, mood__isnull=False).values_list("date", "mood"))
    peak = max(secs.values(), default=0) or 1
    days, day = [], first_cell
    while day <= last_cell:
        v = secs.get(day, 0)
        days.append({"date": day, "secs": v, "level": 0 if not v else min(4, 1 + int(4 * v / (peak + 1))),
                     "tasks": due.get(day, []), "done": done.get(day, 0), "mood": moods.get(day),
                     "in_month": day.month == month.month, "today": day == today, "work": s.is_work_day(day)})
        day += timedelta(days=1)
    prev = (month - timedelta(days=1)).replace(day=1)
    return render_work(request, "work/calendar.html", {
        "month": month, "days": days, "weeks": [days[i:i + 7] for i in range(0, len(days), 7)],
        "weekdays": [d["date"] for d in days[:7]], "prev": prev, "next": last + timedelta(days=1), "today": today,
        "month_secs": sum(v for d, v in secs.items() if d.month == month.month),
        "month_due": sum(len(v) for d, v in due.items() if d.month == month.month),
        "moods": {1: "😞", 2: "😕", 3: "😐", 4: "🙂", 5: "😄"},
    })


# ── Day planner ───────────────────────────────────────────────────────────
PLAN_PPM = 1.2     # pixels per minute on the timeline (the same in work.js)


def _minute(when, day):
    """Minutes from the start of `day` (local time), clamped to the day."""
    local = timezone.localtime(when)
    if local.date() < day:
        return 0
    if local.date() > day:
        return 24 * 60
    return local.hour * 60 + local.minute


def plan_data(user, day):
    """Everything the planner draws, as plain data (also sent back after "Fill my day")."""
    blocks, unplanned, entries = services.plan_day(user, day)
    now = timezone.now()

    def task_dict(t):
        return {"id": t.pk, "title": t.title, "url": reverse("work:task", args=[t.pk]), "priority": t.priority,
                "done": t.is_done, "estimate": t.estimate_minutes or 0, "length": t.block_minutes,
                "project": t.project.name if t.project else "", "color": t.project.color if t.project else "",
                "waiting": t.waiting_for, "link": t.link}

    return {
        "date": day.isoformat(),
        "blocks": [{**task_dict(t), "start": _minute(t.scheduled_at, day)} for t in blocks],
        "unplanned": [task_dict(t) for t in unplanned],
        "entries": [{"start": _minute(e.started_at, day), "end": _minute(e.ended_at or now, day), "running": e.is_running,
                     "title": (e.task.title if e.task else e.description) or (e.project.name if e.project else ""),
                     "color": e.project.color if e.project else ""} for e in entries],
    }


@work_required
def plan_view(request):
    """Time blocking: drag the day's tasks onto its hours."""
    user, today = request.user, _today()
    day = _day(request, default=today)
    s = WorkSettings.for_user(user)
    data = plan_data(user, day)
    planned = sum(b["length"] for b in data["blocks"] if not b["done"])
    window = (s.day_end.hour * 60 + s.day_end.minute) - (s.day_start.hour * 60 + s.day_start.minute)
    return render_work(request, "work/plan.html", {
        "day": day, "today": today, "is_today": day == today, "prev": day - timedelta(days=1), "next": day + timedelta(days=1),
        "plan": data, "planned_minutes": planned, "window_minutes": max(window, 0),
        "day_start": s.day_start.hour * 60 + s.day_start.minute, "day_end": s.day_end.hour * 60 + s.day_end.minute,
        "start_label": s.day_start.strftime("%H:%M"), "end_label": s.day_end.strftime("%H:%M"),
        "grid_px": round(24 * 60 * PLAN_PPM), "work_top": round((s.day_start.hour * 60 + s.day_start.minute) * PLAN_PPM),
        "work_px": round(max(window, 0) * PLAN_PPM), "work_day": s.is_work_day(day),
    })


@work_required
def week_view(request):
    """Plan the week: drag tasks between the days (My Day), see each day's load."""
    user, today = request.user, _today()
    s = WorkSettings.for_user(user)
    start = services.week_start(_day(request, "start", today), s.week_start)
    days, backlog, backlog_total = services.plan_week(user, start, today)
    prefetch_related_objects([t for d in days for t in d["tasks"]] + backlog, "tags", "checklist")
    planned = sum(d["planned"] for d in days if not d["past"])
    return render_work(request, "work/week.html", {
        "start": start, "end": start + timedelta(days=6), "today": today, "days": days, "backlog": backlog,
        "backlog_more": max(backlog_total - len(backlog), 0), "prev": start - timedelta(days=7), "next": start + timedelta(days=7),
        "is_this_week": start <= today <= start + timedelta(days=6), "planned": planned,
        "target": sum(d["target"] for d in days if not d["past"]),
    })


# ── Your data ─────────────────────────────────────────────────────────────
@work_required
def export_view(request):
    """Everything in the tracker as one .zip: data.json and media/ (what
    "Add from a backup" reads), plus notes, snippets, diagrams and flashcards
    as plain files you can open anywhere."""
    import io
    import json
    import os
    import re
    import zipfile

    from django.core.files.storage import default_storage

    user = request.user
    rows, media = services.backup_rows(user)       # every table of the tracker (a new feature's too), and its uploaded files
    ext = {"python": "py", "javascript": "js", "typescript": "ts", "bash": "sh", "plaintext": "txt", "markdown": "md", "xml": "html",
           "csharp": "cs", "cpp": "cpp", "dockerfile": "Dockerfile", "kotlin": "kt", "ruby": "rb", "rust": "rs", "yaml": "yml"}

    def slug(text, pk):
        return f"{pk}-" + (re.sub(r"[^\w-]+", "-", text.lower()).strip("-")[:60] or "untitled")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("data.json", json.dumps(rows, ensure_ascii=False, indent=1))
        for name in sorted(set(media)):              # read back by "Add from a backup"
            try:
                with default_storage.open(name, "rb") as fh:
                    z.writestr("media/" + name, fh.read())
            except (FileNotFoundError, OSError):
                pass
        for n in Note.objects.filter(owner=user):
            z.writestr(f"notes/{slug(n.display_title, n.pk)}.md", (f"# {n.title}\n\n" if n.title else "") + n.body)
        for sn in Snippet.objects.filter(owner=user):
            z.writestr(f"snippets/{slug(sn.title, sn.pk)}.{ext.get(sn.language, sn.language)}", sn.code)
        for j in JournalEntry.objects.filter(owner=user):
            z.writestr(f"journal/{j.date}.md", f"# {j.date}\n\n## Plan\n{j.plan}\n\n## Done & learnt\n{j.wins}\n\n## Blockers\n{j.blockers}\n\n## Notes\n{j.notes}\n")
        for dg in Diagram.objects.filter(owner=user):
            name = f"diagrams/{slug(dg.title, dg.pk)}"
            if dg.preview:
                z.writestr(f"{name}.svg", dg.preview)
            if dg.kind == DiagramKind.MINDMAP:
                z.writestr(f"{name}.md", diagrams.outline_text(dg.data))
            elif not dg.is_visual:
                z.writestr(f"{name}.mmd", dg.source)
        from .models import NoteImage

        for img in NoteImage.objects.filter(owner=user):
            try:
                with img.file.open("rb") as fh:
                    z.writestr(f"notes/images/{img.pk}{os.path.splitext(img.file.name)[1]}", fh.read())
            except (FileNotFoundError, OSError):
                pass
        from .models import TaskFile

        for tf in TaskFile.objects.filter(owner=user).select_related("task"):
            try:
                with tf.file.open("rb") as fh:
                    z.writestr(f"tasks/files/{slug(tf.task.title, tf.task_id)}/{tf.pk}-{tf.name}", fh.read())
            except (FileNotFoundError, OSError):
                pass
        for dk in Deck.objects.filter(owner=user):    # tab-separated: Anki and spreadsheets open these
            lines = ["\t".join(" ".join(t.split()) for t in (c.front, c.back)) for c in dk.cards.all()]
            z.writestr(f"flashcards/{slug(dk.name, dk.pk)}.tsv", "\n".join(lines) + "\n")
    response = HttpResponse(buf.getvalue(), content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="productivity-{_today()}.zip"'
    return response


# ── Shared from another app (phone share sheet) ───────────────────────────
@login_required
def share_view(request):
    """What another app shared (a link, some text): keep it as a task, a note
    or something to read — one tap. (The app's share target, so someone
    without Productivity is just taken home.)"""
    if not can_use(request.user):
        messages.info(request, _("Shared items are kept in Productivity, which isn't turned on for you."))
        return redirect("home")
    title, text, url = (request.GET.get(k, "").strip() for k in ("title", "text", "url"))
    if not url:   # many apps put the link in the text
        import re

        m = re.search(r"https?://\S+", text)
        if m:
            url, text = m.group(0), (text[:m.start()] + text[m.end():]).strip()
    return render_work(request, "work/share.html", {"title": title or text[:200], "text": text, "url": url})



# ── End of the day ────────────────────────────────────────────────────────
@work_required
def wrapup_view(request):
    """Shut the day down: what got done, what's left (move it on), wins and
    blockers for the journal, and tomorrow's plan — so you can stop thinking about work."""
    user, today = request.user, _today()
    tomorrow = today + timedelta(days=1)
    open_tasks, done_today = services.today_tasks(user, today)
    prefetch_related_objects(done_today, *ROW_RELATED)
    t = services.totals(user, today, today)
    journal = JournalEntry.objects.filter(owner=user, date=today).first()
    next_plan = JournalEntry.objects.filter(owner=user, date=tomorrow).values_list("plan", flat=True).first() or ""
    s = WorkSettings.for_user(user)
    return render_work(request, "work/wrapup.html", {
        "today": today, "tomorrow": tomorrow, "left": [x for x in open_tasks if x.status not in (Status.DOING, Status.REVIEW) or x.my_day == today][:30],
        "doing": [x for x in open_tasks if x.status == Status.DOING], "done_today": done_today, "t": t, "journal": journal,
        "next_plan": next_plan, "done_lines": "\n".join(f"- {x.title}" for x in done_today),
        "target": s.daily_target_minutes * 60, "moods": range(1, 6),
        "cards_due": cards.due_count(user, today) if Deck.objects.filter(owner=user, is_archived=False).exists() else 0,
    })


# ── Calendar feed for Google / Apple / Outlook ────────────────────────────
def feed_view(request, token):
    """No sign-in (calendar apps can't sign in): the long secret in the address is the key."""
    s = WorkSettings.objects.filter(feed_token=token).exclude(feed_token="").select_related("owner").first()
    if s is None or len(token) < 20 or not s.owner.is_active or not can_use(s.owner):
        raise Http404
    body = services.calendar_feed(s.owner, base_url=request.build_absolute_uri("/").rstrip("/"))
    response = HttpResponse(body, content_type="text/calendar; charset=utf-8")
    response["Content-Disposition"] = 'inline; filename="work.ics"'
    response["Cache-Control"] = "private, max-age=900"
    return response


# ── Sprints ───────────────────────────────────────────────────────────────
@work_required
def sprints_view(request):
    """Sprints: the running one, the ones planned, the closed ones and how many
    tasks each finished (velocity) — and a new one."""
    from . import sprints
    from .models import Sprint

    user, today = request.user, _today()
    form = SprintForm(request.POST or None, initial=sprints.suggest(user, today))
    if request.method == "POST" and form.is_valid():
        sp = form.save(commit=False)
        sp.owner = user
        sp.save()
        messages.success(request, _("Sprint added. Now pick the tasks for it."))
        return redirect("work:sprint", pk=sp.pk)
    rows = []
    for sp in Sprint.objects.filter(owner=user, completed_at__isnull=True).order_by("start_date", "pk"):
        counts = sp.tasks.aggregate(total=Count("pk"), done=Count("pk", filter=Q(status=Status.DONE)))
        rows.append({"s": sp, "state": sp.state(today), **counts, "pct": round(100 * counts["done"] / counts["total"]) if counts["total"] else 0,
                     "days_left": (sp.end_date - today).days})
    velocity, unit = sprints.velocity(user)
    top = max([d + left for _s, d, left in velocity] + [1])
    return render_work(request, "work/sprints.html", {
        "form": form, "rows": rows, "today": today,
        "closed": Sprint.objects.filter(owner=user, completed_at__isnull=False).order_by("-end_date", "-pk")[:30],
        "velocity": [{"s": s, "done": d, "left": left, "h": round(100 * d / top), "lh": round(100 * left / top)} for s, d, left in velocity],
        "average": round(sum(d for _s, d, _l in velocity) / len(velocity), 1) if velocity else None, "unit": unit,
    })


@work_required
def sprint_view(request, pk):
    """One sprint: its tasks by status, the burndown, adding tasks from the backlog, closing it."""
    from . import sprints
    from .models import Sprint

    user, today = request.user, _today()
    sp = get_object_or_404(Sprint, pk=pk, owner=user)
    form = SprintForm(instance=sp)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "edit":
            form = SprintForm(request.POST, instance=sp)
            if form.is_valid():
                form.save()
                messages.success(request, _("Sprint saved."))
                return redirect("work:sprint", pk=sp.pk)
        elif action == "add":
            n = sprints.add_tasks(sp, [int(x) for x in request.POST.getlist("task") if x.isdigit()])
            messages.success(request, ngettext("%(n)s task added to the sprint.", "%(n)s tasks added to the sprint.", n) % {"n": n})
            return redirect("work:sprint", pk=sp.pk)
        elif action == "close" and not sp.completed_at:
            target = request.POST.get("move_to", "")
            move_to = None
            if target == "new":
                move_to = Sprint.objects.create(owner=user, **sprints.suggest(user, today))
            elif target.isdigit():
                move_to = Sprint.objects.filter(owner=user, completed_at__isnull=True, pk=int(target)).exclude(pk=sp.pk).first()
            n = sprints.close(sp, move_to)
            if move_to:
                messages.success(request, ngettext("Sprint closed. %(n)s open task moved to %(name)s.", "Sprint closed. %(n)s open tasks moved to %(name)s.", n)
                                 % {"n": n, "name": move_to.name})
                return redirect("work:sprint", pk=move_to.pk)
            messages.success(request, ngettext("Sprint closed. %(n)s open task went back to the backlog.", "Sprint closed. %(n)s open tasks went back to the backlog.", n) % {"n": n})
            return redirect("work:sprints")
        elif action == "delete":
            sp.delete()
            messages.success(request, _("Sprint deleted. Its tasks are kept."))
            return redirect("work:sprints")
    tasks = _with_rows(list(sp.tasks.select_related("project", "parent").order_by("order", "-priority", "pk")))
    columns = [(value, Status(value).label, [t for t in tasks if t.status == value]) for value in (Status.DOING, Status.REVIEW, Status.TODO, Status.BACKLOG, Status.DONE)]
    done = [t for t in tasks if t.is_done]
    backlog = []
    if not sp.completed_at:
        backlog = list(Task.objects.filter(owner=user, sprint__isnull=True, parent__isnull=True).exclude(status=Status.DONE)
                       .select_related("project").order_by("-priority", F("due_date").asc(nulls_last=True), "order")[:200])
    est_total = sum(t.estimate_minutes or 0 for t in tasks)
    est_done = sum(t.estimate_minutes or 0 for t in done)
    ws = WorkSettings.for_user(user)
    notes = dev.release_notes(tasks, f"{sp.name} ({date_format(sp.start_date, 'j M')} – {date_format(sp.end_date, 'j M Y')})", ws)
    if request.GET.get("notes") == "md":
        response = HttpResponse(notes, content_type="text/markdown; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="release-notes-{dev.slug(sp.name) or sp.pk}.md"'
        return response
    return render_work(request, "work/sprint.html", {
        "sp": sp, "form": form, "state": sp.state(today), "today": today, "columns": [c for c in columns if c[2] or c[0] in (Status.TODO, Status.DOING)],
        "total": len(tasks), "done": len(done), "pct": round(100 * len(done) / len(tasks)) if tasks else 0,
        "est_total": est_total, "est_done": est_done, "chart": sprints.chart(sp, today), "backlog": backlog, "release_notes": notes,
        "pts_total": sum(t.points or 0 for t in tasks), "pts_done": sum(t.points or 0 for t in done),
        "days_left": (sp.end_date - today).days, "day_no": min(max((today - sp.start_date).days + 1, 0), sp.length),
        "others": sprints.open_sprints(user).exclude(pk=sp.pk),
    })


# ── Templates, copying a project, importing, invoices ──────────────────────
@work_required
def templates_view(request):
    """Task templates: make a task from one, rename or remove it."""
    from .copying import use_template

    user = request.user
    if request.method == "POST":
        tpl = get_object_or_404(TaskTemplate, pk=request.POST.get("template") or 0, owner=user)
        if request.POST.get("action") == "delete":
            tpl.delete()
            messages.success(request, _("Template removed."))
            return redirect("work:templates")
        project = Project.objects.filter(owner=user, pk=request.POST.get("project") or 0).first()
        task = use_template(tpl, project=project)
        messages.success(request, _("Made “%(title)s” from the template.") % {"title": task.title})
        return redirect("work:task", pk=task.pk)
    return render_work(request, "work/templates.html", {
        "templates": TaskTemplate.objects.filter(owner=user), "projects": Project.objects.filter(owner=user, is_archived=False),
    })


@work_required
@require_POST
def project_duplicate_view(request, pk):
    from .copying import duplicate_project

    project = get_object_or_404(Project, pk=pk, owner=request.user)
    copy = duplicate_project(project, keep_dates=request.POST.get("dates") == "1")
    messages.success(request, _("Copied as “%(name)s”, with its open tasks.") % {"name": copy.name})
    return redirect("work:project", pk=copy.pk)


IMPORT_KEY = "work_import_rows"


@work_required
def import_view(request):
    """Tasks from a CSV: upload → preview → add."""
    from . import importer

    user = request.user
    if request.method == "POST" and request.POST.get("action") == "confirm":
        rows = request.session.pop(IMPORT_KEY, None)
        if not rows:
            messages.error(request, _("The preview has expired. Choose the file again."))
            return redirect("work:import")
        project = Project.objects.filter(owner=user, pk=request.POST.get("project") or 0).first()
        made = importer.save(user, rows, project=project)
        messages.success(request, _("%(n)s tasks added.") % {"n": made})
        return redirect(reverse("work:tasks") + "?view=list")
    ctx = {"projects": Project.objects.filter(owner=user, is_archived=False)}
    if request.method == "POST" and request.FILES.get("file"):
        f = request.FILES["file"]
        if f.size > 5 * 1024 * 1024:
            ctx["error"] = _("That file is over 5 MB. Split it, or export fewer tasks.")
        else:
            parsed = importer.read(f.read())
            if parsed.error:
                ctx["error"] = parsed.error
            elif not parsed.rows:
                ctx["error"] = _("No tasks found in that file.")
            else:
                request.session[IMPORT_KEY] = importer.to_session(parsed)
                preview = [{**r, "priority_label": Priority(r["priority"]).label if r["priority"] else "", "status_label": Status(r["status"]).label,
                            "kind_label": TaskKind(r["kind"]).label if r.get("kind") and r["kind"] != TaskKind.TASK else ""}
                           for r in parsed.rows[:30]]
                ctx.update({"parsed": parsed, "preview": preview, "file_name": f.name})
    return render_work(request, "work/import.html", ctx)


@work_required
def invoice_view(request):
    """An invoice or a timesheet from tracked time, for a project or a client."""
    from . import invoices

    user, today = request.user, _today()
    s = WorkSettings.for_user(user)
    start = parse_date(request.GET.get("from") or "") or today.replace(day=1)
    end = parse_date(request.GET.get("to") or "") or today
    if end < start:
        start, end = end, start
    project = Project.objects.filter(owner=user, pk=request.GET.get("project") or 0).first()
    client = "" if project else request.GET.get("client", "").strip()
    billable_only = request.GET.get("all") != "1"
    include_billed = request.GET.get("billed") == "1"
    inv = invoices.build(user, start, end, project=project, client=client, billable_only=billable_only, include_billed=include_billed)
    if request.method == "POST" and request.POST.get("action") == "billed":
        n = invoices.mark_billed(user, inv.entry_ids)
        messages.success(request, _("%(n)s time entries marked as billed — they won't go on another invoice.") % {"n": n})
        return redirect(request.get_full_path())
    if request.GET.get("export") == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="invoice-{start}-{end}.csv"'
        response.write("﻿")
        w = csv.writer(response)
        w.writerow([_("Project"), _("Work"), _("Hours"), _("Rate"), _("Amount")])
        for line in inv.lines:
            w.writerow([line.project.name if line.project else "", line.label, line.hours, line.rate or "", line.amount if line.amount is not None else ""])
        w.writerow(["", _("Total"), inv.hours, "", inv.total])
        return response
    number = f"INV-{end:%Y%m%d}-{(project.pk if project else 0):03d}"
    return render_work(request, "work/invoice.html", {
        "inv": inv, "start": start, "end": end, "project": project, "client": client or (project.client if project else ""),
        "billable_only": billable_only, "include_billed": include_billed, "ws": s, "number": number, "today": today,
        "projects": Project.objects.filter(owner=user), "clients": invoices.clients(user),
        "query": request.GET.urlencode(),
    })


def _burnup(project, today, weeks=12):
    """Week by week: all the tasks the project has had, and how many are done —
    with a guess at when the rest will be done, at the recent pace."""
    tasks = list(Task.objects.filter(project=project).values_list("created_at", "completed_at", "status"))
    if len(tasks) < 2:
        return None
    age = (today - min(timezone.localtime(c).date() for c, _d, _s in tasks)).days // 7 + 1
    weeks = min(max(age, 4), weeks)          # a young project: its own few weeks, not twelve empty ones
    ends = [today - timedelta(days=7 * i) for i in range(weeks - 1, -1, -1)]
    points = []
    for end in ends:
        cut = end + timedelta(days=1)
        added = sum(1 for c, _d, _s in tasks if timezone.localtime(c).date() < cut)
        done = sum(1 for _c, d, s in tasks if s == Status.DONE and d and timezone.localtime(d).date() < cut)
        points.append({"day": end, "added": added, "done": done})
    top = max(p["added"] for p in points) or 1
    W, H = 600, 160
    step = W / (len(points) - 1)

    def line(key):
        return " ".join(f"{i * step:.1f},{H - p[key] * H / top:.1f}" for i, p in enumerate(points))
    recent = points[-1]["done"] - points[-5]["done"] if len(points) >= 5 else 0      # the last four weeks
    left = points[-1]["added"] - points[-1]["done"]
    eta = today + timedelta(weeks=left / (recent / 4)) if (recent > 0 and left > 0) else None
    return {"points": points, "added": line("added"), "done": line("done"), "top": top, "w": W, "h": H,
            "left": left, "pace": round(recent / 4, 1), "eta": eta, "first": points[0]["day"], "weeks": weeks}
