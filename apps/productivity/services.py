"""The working parts of the productivity module: the timer, the quick-add
parser, time totals for any period, streaks, and the daily standup."""
import calendar
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from django.utils.translation import gettext as _

from .models import (
    EntryKind, Habit, HabitCheck, Priority, Project, Repeat, Status, Tag, Task, TimeEntry, WorkSettings,
)


# ── Time ──────────────────────────────────────────────────────────────────
def day_bounds(day):
    """Aware start of `day` and of the next day, in the site's time zone."""
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(day, time.min), tz)
    return start, start + timedelta(days=1)


def hm(seconds):
    """1h 05m / 45m / 0m."""
    seconds = int(seconds or 0)
    h, m = divmod(seconds // 60, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


def clock(seconds):
    """1:05:09 / 05:09 for a running timer."""
    seconds = int(seconds or 0)
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def running_entry(user):
    return TimeEntry.objects.filter(owner=user, ended_at__isnull=True).select_related("task", "project").first()


def _sane(at, now=None):
    """A time sent by a phone (maybe from its outbox, hours later): kept when
    it's within the last two weeks and not in the future."""
    now = now or timezone.now()
    if at is None:
        return now
    if timezone.is_naive(at):
        at = timezone.make_aware(at, timezone.get_current_timezone())
    return min(max(at, now - timedelta(days=14)), now)


@transaction.atomic
def start_timer(user, *, task=None, project=None, description="", at=None, kind=EntryKind.TIMER, tags=()):
    """Starts tracking now (or at `at`); a timer already running stops there."""
    at = _sane(at)
    stop_timer(user, at=at)
    if task is not None and project is None:
        project = task.project
    if task is not None and task.status in (Status.BACKLOG, Status.TODO):
        task.status = Status.DOING
        task.save(update_fields=["status", "updated_at"])
    entry = TimeEntry.objects.create(owner=user, task=task, project=project, description=description[:300], started_at=at, kind=kind)
    if tags:
        entry.tags.set(tags)
    return entry


def stop_timer(user, at=None):
    entry = TimeEntry.objects.select_for_update().filter(owner=user, ended_at__isnull=True).first()
    if entry is None:
        return None
    entry.ended_at = max(_sane(at), entry.started_at)
    entry.save(update_fields=["ended_at", "updated_at"])
    return entry


def entry_seconds_between(entry, start, end, now=None):
    """The part of an entry that falls inside [start, end)."""
    stop = entry.ended_at or now or timezone.now()
    a, b = max(entry.started_at, start), min(stop, end)
    return max(int((b - a).total_seconds()), 0)


def entries_between(user, start, end):
    """Entries that overlap [start, end) — including one still running."""
    from django.db.models import Q

    return (TimeEntry.objects.filter(owner=user, started_at__lt=end)
            .filter(Q(ended_at__gt=start) | Q(ended_at__isnull=True))
            .select_related("task", "project").prefetch_related("tags").order_by("started_at"))


@dataclass
class Totals:
    start: date
    end: date                                   # inclusive
    seconds: int = 0
    by_day: dict = field(default_factory=dict)  # date → seconds
    by_project: list = field(default_factory=list)   # [(project or None, seconds)]
    by_tag: list = field(default_factory=list)
    by_task: list = field(default_factory=list)
    billable_seconds: int = 0
    focus_sessions: int = 0
    entries: list = field(default_factory=list)

    @property
    def days(self):
        return (self.end - self.start).days + 1

    @property
    def daily_average(self):
        worked = [s for s in self.by_day.values() if s]
        return sum(worked) // len(worked) if worked else 0

    @property
    def best_day(self):
        return max(self.by_day.items(), key=lambda kv: kv[1]) if any(self.by_day.values()) else None


def totals(user, start, end):
    """Tracked time from `start` to `end` (dates, inclusive), split every way."""
    lo, _x = day_bounds(start)
    _y, hi = day_bounds(end)
    now = timezone.now()
    out = Totals(start, end, by_day={start + timedelta(days=i): 0 for i in range((end - start).days + 1)})
    projects, tags, tasks = defaultdict(int), defaultdict(int), defaultdict(int)
    names = {}
    for e in entries_between(user, lo, hi):
        secs = entry_seconds_between(e, lo, hi, now)
        if not secs:
            continue
        out.entries.append(e)
        out.seconds += secs
        if e.billable:
            out.billable_seconds += secs
        if e.kind == EntryKind.FOCUS:
            out.focus_sessions += 1
        # Split across the days it touches (an entry past midnight counts on both).
        cursor = max(e.started_at, lo)
        stop = min(e.ended_at or now, hi)
        while cursor < stop:
            local = timezone.localtime(cursor).date()
            _a, next_day = day_bounds(local)
            part = int((min(next_day, stop) - cursor).total_seconds())
            if local in out.by_day:
                out.by_day[local] += part
            cursor = next_day
        projects[e.project_id] += secs
        names[e.project_id] = e.project
        for t in e.tags.all():
            tags[t] += secs
        if e.task_id:
            tasks[e.task] += secs
    out.by_project = sorted(((names[k], v) for k, v in projects.items()), key=lambda kv: -kv[1])
    out.by_tag = sorted(tags.items(), key=lambda kv: -kv[1])
    out.by_task = sorted(tasks.items(), key=lambda kv: -kv[1])[:10]
    return out


def task_seconds(task):
    now = timezone.now()
    return sum(int(((e.ended_at or now) - e.started_at).total_seconds()) for e in task.entries.all())


def focus_streak(user, today=None):
    """Work days in a row (ending today or yesterday) that reached the daily target."""
    today = today or timezone.localdate()
    s = WorkSettings.for_user(user)
    target = s.daily_target_minutes * 60
    totals_by_day = totals(user, today - timedelta(days=60), today).by_day
    streak, day = 0, today
    if totals_by_day.get(today, 0) < target:
        day -= timedelta(days=1)   # today isn't over yet
    while day in totals_by_day:
        if not s.is_work_day(day):
            day -= timedelta(days=1)
            continue
        if totals_by_day[day] < target:
            break
        streak += 1
        day -= timedelta(days=1)
    return streak


# ── Quick add: "Fix login bug #auth @api !high tomorrow ~45m *" ───────────
PRIORITY_WORDS = {"urgent": Priority.URGENT, "high": Priority.HIGH, "medium": Priority.MEDIUM, "med": Priority.MEDIUM, "low": Priority.LOW,
                  "4": Priority.URGENT, "3": Priority.HIGH, "2": Priority.MEDIUM, "1": Priority.LOW}
WEEKDAYS = {name: i for i, name in enumerate(["mon", "tue", "wed", "thu", "fri", "sat", "sun"])}


@dataclass
class Parsed:
    title: str
    project: str = ""
    tags: list = field(default_factory=list)
    priority: int = Priority.NONE
    due: date | None = None
    estimate: int | None = None
    my_day: bool = False


def parse_due(word, today):
    w = word.lower()
    if w in ("today", "tod", "আজ"):
        return today
    if w in ("tomorrow", "tmr", "tom", "আগামীকাল", "কাল"):
        return today + timedelta(days=1)
    if w in ("nextweek",):
        return today + timedelta(days=7 - today.weekday())
    m = re.fullmatch(r"(?:in)?(\d{1,3})([dw])", w)
    if m:
        n = int(m.group(1))
        return today + timedelta(days=n * (7 if m.group(2) == "w" else 1))
    if w in WEEKDAYS or w in FULL_DAYS:
        ahead = ((WEEKDAYS.get(w) if w in WEEKDAYS else FULL_DAYS[w]) - today.weekday()) % 7 or 7
        return today + timedelta(days=ahead)
    try:
        return date.fromisoformat(w)
    except ValueError:
        pass
    m = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})", w)   # 25/12 = 25 December
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        try:
            due = date(today.year, mo, d)
            return due if due >= today else date(today.year + 1, mo, d)
        except ValueError:
            return None
    return None


FULL_DAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}


def _date_word(low, today):
    """A due date written in the line, or None. Plain words only count when
    unmistakable, so "sun" or "3d" in a title stay part of the title."""
    if low.startswith("due:"):
        return parse_due(low[4:], today)
    if re.fullmatch(r"\+\d{1,3}[dw]", low):
        return parse_due(low[1:], today)
    if low in ("today", "tomorrow", "tmr", "nextweek") or low in FULL_DAYS or re.fullmatch(r"\d{4}-\d{2}-\d{2}", low):
        return parse_due(low, today)
    return None


def parse_quick(text, today=None):
    """Turns one line into a task's parts:
    #tag  @project  !high (or !1–!4)  ~30m / ~2h  *  (My Day)
    and a due date: today, tomorrow, friday, +3d, +2w, 2026-10-20, due:mon, due:25/12."""
    today = today or timezone.localdate()
    p = Parsed(title="")
    words = []
    estimate = re.compile(r"~(\d+(?:\.\d+)?)(m|min|h|hr)?")
    for word in text.split():
        low = word.lower()
        m = estimate.fullmatch(low)
        if len(word) > 1 and word[0] == "#" and word[1].isalpha():   # "#482" stays in the title (an issue number)
            p.tags.append(word[1:40])
        elif len(word) > 1 and word[0] == "@":
            p.project = word[1:].replace("_", " ")
        elif len(word) > 1 and word[0] == "!" and low[1:] in PRIORITY_WORDS:
            p.priority = PRIORITY_WORDS[low[1:]]
        elif m:
            amount = float(m.group(1))
            p.estimate = int(round(amount * 60)) if (m.group(2) or "m").startswith("h") else int(round(amount))
        elif word == "*":
            p.my_day = True
        elif _date_word(low, today) is not None:
            p.due = _date_word(low, today)
        else:
            words.append(word)
    p.title = " ".join(words).strip()
    return p


def find_project(user, name):
    if not name:
        return None
    qs = Project.objects.filter(owner=user, is_archived=False)
    return qs.filter(name__iexact=name).first() or qs.filter(name__istartswith=name).first()


def tags_named(user, names):
    out = []
    for name in dict.fromkeys(n.strip().lower() for n in names if n.strip()):
        tag, _created = Tag.objects.get_or_create(owner=user, name=name[:40])
        out.append(tag)
    return out


def next_order(user, status):
    top = Task.objects.filter(owner=user, status=status).aggregate(m=Max("order"))["m"]
    return (top or 0) + 1


def create_from_quick(user, text, *, status=Status.TODO, project=None, today=None, my_day=False, due=None):
    """A task from one typed line (see parse_quick). Returns the task, or None when no title."""
    today = today or timezone.localdate()
    p = parse_quick(text, today)
    if not p.title:
        return None
    task = Task.objects.create(
        owner=user, title=p.title[:300], status=status, priority=p.priority,
        project=find_project(user, p.project) or project,
        due_date=p.due or due, estimate_minutes=p.estimate,
        my_day=today if (p.my_day or my_day) else None, order=next_order(user, status),
    )
    if p.tags:
        task.tags.set(tags_named(user, p.tags))
    return task


# ── Tasks ─────────────────────────────────────────────────────────────────
def next_due(day, repeat):
    if repeat == Repeat.DAILY:
        return day + timedelta(days=1)
    if repeat == Repeat.WEEKDAYS:
        nxt = day + timedelta(days=1)
        while nxt.weekday() >= 5:   # Saturday, Sunday
            nxt += timedelta(days=1)
        return nxt
    if repeat == Repeat.WEEKLY:
        return day + timedelta(days=7)
    if repeat == Repeat.MONTHLY:
        y, m = (day.year + (day.month // 12), day.month % 12 + 1)
        return date(y, m, min(day.day, calendar.monthrange(y, m)[1]))
    return None


@transaction.atomic
def set_done(task, done=True):
    """Ticks a task off (or back on). A repeating task leaves the next one behind."""
    if done == task.is_done:
        return None
    if done:
        task.status, task.completed_at = Status.DONE, timezone.now()
        task.save(update_fields=["status", "completed_at", "updated_at"])
        running = TimeEntry.objects.filter(owner=task.owner, task=task, ended_at__isnull=True).exists()
        if running:
            stop_timer(task.owner)
        if task.repeat:
            base = task.due_date or timezone.localdate()
            nxt = Task.objects.create(owner=task.owner, project=task.project, title=task.title, notes=task.notes,
                                      priority=task.priority, due_date=next_due(base, task.repeat), repeat=task.repeat,
                                      estimate_minutes=task.estimate_minutes, order=next_order(task.owner, Status.TODO))
            nxt.tags.set(task.tags.all())
            for item in task.checklist.all():
                nxt.checklist.create(text=item.text, order=item.order)
            return nxt
    else:
        task.status, task.completed_at = Status.TODO, None
        task.save(update_fields=["status", "completed_at", "updated_at"])
    return None


def today_tasks(user, today=None):
    """What's on today's list: My Day picks, in progress, due today or late."""
    from django.db.models import Q

    today = today or timezone.localdate()
    open_ = (Task.objects.filter(owner=user).exclude(status=Status.DONE)
             .filter(Q(my_day=today) | Q(status=Status.DOING) | Q(due_date__lte=today))
             .select_related("project").prefetch_related("tags", "checklist"))
    done_today = (Task.objects.filter(owner=user, status=Status.DONE, completed_at__gte=day_bounds(today)[0])
                  .select_related("project"))
    rank = lambda t: (0 if t.status == Status.DOING else 1, -(t.priority or 0), t.due_date or date.max, t.order)  # noqa: E731
    return sorted(open_, key=rank), list(done_today)


# ── Habits ────────────────────────────────────────────────────────────────
def habit_streak(habit, checked, today):
    """Due days in a row that were checked, ending today (or yesterday, if today isn't done yet)."""
    streak, day = 0, today
    if day not in checked:
        day -= timedelta(days=1)
    for _i in range(400):
        if habit.is_due(day):
            if day not in checked:
                break
            streak += 1
        elif day < habit.created_at.date():
            break
        day -= timedelta(days=1)
    return streak


def habit_rows(user, today, days=14):
    habits = list(Habit.objects.filter(owner=user, is_archived=False))
    since = today - timedelta(days=max(days, 400))
    checks = defaultdict(set)
    for hid, d in HabitCheck.objects.filter(habit__in=habits, date__gte=since).values_list("habit_id", "date"):
        checks[hid].add(d)
    span = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    rows = []
    for h in habits:
        done = checks[h.pk]
        due_days = [d for d in span if h.is_due(d)]
        rows.append({
            "habit": h, "done_today": today in done, "due_today": h.is_due(today),
            "streak": habit_streak(h, done, today),
            "cells": [{"date": d, "done": d in done, "due": h.is_due(d), "today": d == today} for d in span],
            "rate": round(100 * sum(1 for d in due_days if d in done) / len(due_days)) if due_days else 0,
        })
    return rows, span


# ── Standup / daily summary ───────────────────────────────────────────────
def standup(user, today=None):
    """Yesterday (the last work day) / Today / Blockers, ready to paste."""
    from .models import JournalEntry

    today = today or timezone.localdate()
    s = WorkSettings.for_user(user)
    prev = today - timedelta(days=1)
    for _i in range(7):
        if s.is_work_day(prev):
            break
        prev -= timedelta(days=1)
    lo, hi = day_bounds(prev)
    done = list(Task.objects.filter(owner=user, status=Status.DONE, completed_at__gte=lo, completed_at__lt=hi).select_related("project"))
    worked = totals(user, prev, prev)
    plan, _done_today = today_tasks(user, today)
    journal = JournalEntry.objects.filter(owner=user, date=today).first()
    blockers = [line.strip("-* ").strip() for line in (journal.blockers if journal else "").splitlines() if line.strip()]

    def line(task):
        return f"{task.title}" + (f" ({task.project.name})" if task.project_id else "")

    yesterday = [line(t) for t in done]
    seen = {t.pk for t in done}
    yesterday += [f"{t.title} — {hm(sec)}" for t, sec in worked.by_task if t.pk not in seen]
    if not yesterday and worked.seconds:
        yesterday = [f"{(p.name if p else _('Other work'))} — {hm(sec)}" for p, sec in worked.by_project]
    today_list = [line(t) for t in plan[:8]]
    return {"since": prev, "yesterday": yesterday, "today": today_list, "blockers": blockers, "seconds": worked.seconds}


def standup_text(data, markdown=True):
    bullet = "- " if markdown else "• "
    head = (lambda t: f"**{t}**") if markdown else (lambda t: t)
    parts = [head(_("Yesterday")) + f" ({data['since']:%a %d %b})"]
    parts += [bullet + x for x in data["yesterday"]] or [bullet + _("Nothing logged")]
    parts += ["", head(_("Today"))] + ([bullet + x for x in data["today"]] or [bullet + _("Planning the day")])
    parts += ["", head(_("Blockers"))] + ([bullet + x for x in data["blockers"]] or [bullet + _("None")])
    return "\n".join(parts)
