"""The working parts of the productivity module: the timer, the quick-add
parser, time totals for any period, streaks, and the daily standup."""
import calendar
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from datetime import timezone as dt_timezone
from functools import cached_property

from django.db import transaction
from django.db.models import DurationField, ExpressionWrapper, F, Max, Q, Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from .models import (
    EntryKind, Goal, GoalStatus, GoalStep, Habit, HabitCheck, JournalEntry, LearningItem, LearningStatus, Note, Priority, Project,
    Repeat, Status, Tag, Task, TaskKind, TimeEntry, WorkSettings, link_label,
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
    return (TimeEntry.objects.filter(owner=user, started_at__lt=end)
            .filter(Q(ended_at__gt=start) | Q(ended_at__isnull=True))
            .select_related("task", "project").prefetch_related("tags").order_by("started_at"))


class Totals:
    """Tracked time from `start` to `end` (dates, inclusive), split by day,
    project, tag, task and hour. Sums are made from plain rows (no model
    objects), so a year of entries is still quick; `entries` (the full
    objects, for lists and CSV) is only loaded when a page asks for it."""

    def __init__(self, user, start, end):
        self.user, self.start, self.end = user, start, end
        self.seconds = self.billable_seconds = self.focus_sessions = 0
        self.by_day = {start + timedelta(days=i): 0 for i in range((end - start).days + 1)}
        self.by_project, self.by_tag, self.by_task, self.by_kind = [], [], [], []
        self.by_hour = [0] * 24
        self._lo, self._hi = day_bounds(start)[0], day_bounds(end)[1]

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

    @cached_property
    def entries(self):
        now = timezone.now()
        return [e for e in entries_between(self.user, self._lo, self._hi) if entry_seconds_between(e, self._lo, self._hi, now)]


def _overlapping(qs, lo, hi, prefix=""):
    return qs.filter(**{f"{prefix}started_at__lt": hi}).filter(Q(**{f"{prefix}ended_at__gt": lo}) | Q(**{f"{prefix}ended_at__isnull": True}))


def totals(user, start, end):
    """Tracked time from `start` to `end` (dates, inclusive), split every way."""
    out = Totals(user, start, end)
    lo, hi, now = out._lo, out._hi, timezone.now()
    tz = timezone.get_current_timezone()
    rows = _overlapping(TimeEntry.objects.filter(owner=user), lo, hi).values_list(
        "pk", "started_at", "ended_at", "project_id", "task_id", "billable", "kind")
    tags_of = defaultdict(list)
    through = TimeEntry.tags.through.objects.filter(timeentry__owner=user)
    for entry_id, tag_id in _overlapping(through, lo, hi, "timeentry__").values_list("timeentry_id", "tag_id"):
        tags_of[entry_id].append(tag_id)
    projects, tags, tasks = defaultdict(int), defaultdict(int), defaultdict(int)
    for pk, started, ended, project_id, task_id, billable, kind in rows:
        a, b = max(started, lo), min(ended or now, hi)
        secs = int((b - a).total_seconds())
        if secs <= 0:
            continue
        out.seconds += secs
        if billable:
            out.billable_seconds += secs
        if kind == EntryKind.FOCUS:
            out.focus_sessions += 1
        out.by_hour[started.astimezone(tz).hour] += secs
        # Split across the days it touches (an entry past midnight counts on both).
        cursor, left = a, secs
        while left > 0:
            local = cursor.astimezone(tz).date()
            next_day = day_bounds(local)[1]
            part = left if next_day >= b else min(int((next_day - cursor).total_seconds()), left)
            if local in out.by_day:
                out.by_day[local] += part
            left -= part
            cursor = next_day
        projects[project_id] += secs
        for tag_id in tags_of.get(pk, ()):
            tags[tag_id] += secs
        if task_id:
            tasks[task_id] += secs
    found = Project.objects.in_bulk([k for k in projects if k])
    out.by_project = sorted(((found.get(k), v) for k, v in projects.items()), key=lambda kv: -kv[1])
    found = Tag.objects.in_bulk(list(tags))
    out.by_tag = sorted(((found[k], v) for k, v in tags.items() if k in found), key=lambda kv: -kv[1])
    top = sorted(tasks.items(), key=lambda kv: -kv[1])[:10]
    found = Task.objects.select_related("project").in_bulk([k for k, _v in top])
    out.by_task = [(found[k], v) for k, v in top if k in found]
    kinds = defaultdict(int)          # features, bugs, chores… (time not on a task counts as "task")
    kind_of = dict(Task.objects.filter(pk__in=list(tasks)).values_list("pk", "kind"))
    for task_id, secs in tasks.items():
        kinds[kind_of.get(task_id, TaskKind.TASK)] += secs
    kinds[TaskKind.TASK] += out.seconds - sum(tasks.values())
    out.by_kind = sorted(((TaskKind(k), v) for k, v in kinds.items() if v > 0), key=lambda kv: -kv[1])
    return out


def daily_seconds(user, start, end):
    """date → tracked seconds, summed by the database (by the day each entry
    started — close enough for a year at a glance)."""
    from django.db.models.functions import TruncDate

    duration = ExpressionWrapper(F("ended_at") - F("started_at"), output_field=DurationField())
    lo, hi = day_bounds(start)[0], day_bounds(end)[1]
    rows = (TimeEntry.objects.filter(owner=user, started_at__gte=lo, started_at__lt=hi, ended_at__isnull=False)
            .annotate(day=TruncDate("started_at")).values("day").annotate(d=Sum(duration)).values_list("day", "d"))
    out = {start + timedelta(days=i): 0 for i in range((end - start).days + 1)}
    for day, total in rows:
        if day in out and total:
            out[day] += int(total.total_seconds())
    running = running_entry(user)
    if running and running.started_at < hi:       # the timer that's going now, split by day
        tz, now = timezone.get_current_timezone(), timezone.now()
        cursor = max(running.started_at, lo)
        while cursor < now:
            day = cursor.astimezone(tz).date()
            nxt = day_bounds(day)[1]
            if day in out:
                out[day] += int((min(nxt, now) - cursor).total_seconds())
            cursor = nxt
    return out


def tracked_by(user, field, ids=None):
    """All-time tracked seconds per project (or task…), summed by the database."""
    duration = ExpressionWrapper(F("ended_at") - F("started_at"), output_field=DurationField())
    qs = TimeEntry.objects.filter(owner=user)
    if ids is not None:
        qs = qs.filter(**{f"{field}__in": ids})
    out = defaultdict(int)
    for key, total in qs.filter(ended_at__isnull=False).values(field).annotate(d=Sum(duration)).values_list(field, "d"):
        out[key] += int(total.total_seconds()) if total else 0
    running = qs.filter(ended_at__isnull=True).values_list(field, "started_at").first()
    if running:
        out[running[0]] += max(int((timezone.now() - running[1]).total_seconds()), 0)
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
    link: str = ""
    at: time | None = None          # "at 3pm": a reminder at that time
    repeat: str = ""                # "every monday", "every day"…
    repeat_every: int = 1           # "every 2 weeks"
    repeat_days: str = ""           # "every mon, thu" → "0,3"
    repeat_from_done: bool = False  # "every! week": counted from the day it's done
    later: date | None = None       # "snooze:fri": out of sight until then
    kind: str = ""                  # "fix: …" → a bug, "feat(api): …" → a feature (dev.take_prefix)
    points: int | None = None       # "3pt", "5sp": story points


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


TIME_WORD = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?")
DAY_NAME = r"(?:monday|mon|tuesday|tues|tue|wednesday|wed|thursday|thurs|thu|friday|fri|saturday|sat|sunday|sun)"
EVERY = re.compile(r"\bevery(!?)\s+(?:(\d{1,2})\s+)?(days?|weekday|workday|work\s+day|weeks?|months?|years?|"
                   + DAY_NAME + r"(?:\s*(?:,|&|\band\b)\s*" + DAY_NAME + r")*)\b", re.I)
REPEAT_WORDS = {"day": Repeat.DAILY, "days": Repeat.DAILY, "weekday": Repeat.WEEKDAYS, "workday": Repeat.WEEKDAYS, "week": Repeat.WEEKLY,
                "weeks": Repeat.WEEKLY, "month": Repeat.MONTHLY, "months": Repeat.MONTHLY, "year": Repeat.YEARLY, "years": Repeat.YEARLY}


def _time_word(word):
    """3pm, 3:30pm, 15:30 → a time; anything else → None."""
    m = TIME_WORD.fullmatch(word.lower())
    if not m or (not m.group(2) and not m.group(3)):      # a bare "3" is a number, not a time
        return None
    h, mins = int(m.group(1)), int(m.group(2) or 0)
    if m.group(3):
        if not 1 <= h <= 12:
            return None
        h = h % 12 + (12 if m.group(3) == "pm" else 0)
    if h > 23 or mins > 59:
        return None
    return time(h, mins)


def parse_quick(text, today=None):
    """Turns one line into a task's parts:
    #tag  @project  !high (or !1–!4)  ~30m / ~2h  *  (My Day)
    a due date: today, tomorrow, friday, +3d, +2w, 2026-10-20, due:mon, due:25/12
    a reminder: at 3pm, at 15:30   ·   a repeat: every day / weekday / week / month / monday
    a type, conventional-commit style: "fix(auth): …" (bug, tag auth), "feat: …", "chore: …", "docs: …"
    story points: 3pt, 5sp
    out of sight until a day: snooze:fri, snooze:+3d.
    A pasted link (a PR, an issue…) is kept as the task's link."""
    from .dev import take_prefix

    today = today or timezone.localdate()
    p = Parsed(title="")
    kind, scope, text = take_prefix(text)
    if kind:
        p.kind = kind
        if scope:
            p.tags.append(scope)
    m = EVERY.search(text)
    if m:
        p.repeat_from_done = m.group(1) == "!"
        p.repeat_every = max(int(m.group(2) or 1), 1)
        word = re.sub(r"\s+", "", m.group(3).lower())
        if word in REPEAT_WORDS:
            p.repeat = REPEAT_WORDS[word]
        else:                     # "every mon", "every mon, thu", "every tue and fri"
            p.repeat = Repeat.WEEKLY
            picked = sorted({FULL_DAYS[next(k for k in FULL_DAYS if k.startswith(d[:3]))] for d in re.findall(DAY_NAME, m.group(3).lower())})
            if len(picked) > 1 or p.repeat_every > 1:
                p.repeat_days = ",".join(str(w) for w in picked)
            p.due = min(today + timedelta(days=(w - today.weekday()) % 7) for w in picked)   # the first of them, today included
        text = (text[:m.start()] + " " + text[m.end():]).strip()
    words = []
    estimate = re.compile(r"~(\d+(?:\.\d+)?)(m|min|h|hr)?")
    tokens = text.split()
    i = 0
    while i < len(tokens):
        word = tokens[i]
        low = word.lower()
        m = estimate.fullmatch(low)
        if low == "at" and i + 1 < len(tokens) and _time_word(tokens[i + 1]) is not None:
            p.at = _time_word(tokens[i + 1])
            i += 2
            continue
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
        elif re.fullmatch(r"\d{1,3}(pts?|sp)", low):
            p.points = int(re.match(r"\d+", low).group())
        elif re.match(r"https?://\S+\.\S+", word) and not p.link:
            p.link = word[:500]
        elif low.startswith("snooze:") and parse_due(low[7:].lstrip("+"), today):
            p.later = parse_due(low[7:].lstrip("+"), today)
        elif _date_word(low, today) is not None:
            p.due = _date_word(low, today)
        elif re.fullmatch(r"\d{1,2}(:\d{2})?(am|pm)|\d{1,2}:\d{2}", low) and _time_word(low) is not None:
            p.at = _time_word(low)
        else:
            words.append(word)
        i += 1
    p.title = " ".join(words).strip() or link_label(p.link)
    if p.kind and p.title:
        p.title = p.title[0].upper() + p.title[1:]      # "fix: login loop" → "Login loop"
    return p


def reminder_time(p, today):
    """When "at 3pm" fires: on the due (or snooze) day, else today — or
    tomorrow, if that time has already gone today."""
    if p.at is None:
        return None
    tz = timezone.get_current_timezone()
    day = p.due or p.later or today
    when = timezone.make_aware(datetime.combine(day, p.at), tz)
    if when <= timezone.now() and not (p.due or p.later):
        when += timedelta(days=1)
    return when


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


def create_from_quick(user, text, *, status=Status.TODO, project=None, today=None, my_day=False, due=None, goal=None):
    """A task from one typed line (see parse_quick). Returns the task, or None when no title.
    my_day: True for today, or a day."""
    today = today or timezone.localdate()
    p = parse_quick(text, today)
    if not p.title:
        return None
    task = Task.objects.create(
        owner=user, title=p.title[:300], status=status, priority=p.priority,
        project=find_project(user, p.project) or project,
        due_date=p.due or due or (today if p.repeat else None), estimate_minutes=p.estimate,
        my_day=p.later or (today if p.my_day else (my_day if isinstance(my_day, date) else (today if my_day else None))),
        order=next_order(user, status),
        link=p.link, goal=goal, repeat=p.repeat, remind_at=reminder_time(p, today), kind=p.kind or TaskKind.TASK, points=p.points,
        repeat_every=p.repeat_every, repeat_days=p.repeat_days, repeat_from_done=p.repeat_from_done,
    )
    if p.tags:
        task.tags.set(tags_named(user, p.tags))
    return task


# ── Tasks ─────────────────────────────────────────────────────────────────
def _add_months(day, n):
    y, m = divmod(day.month - 1 + n, 12)
    y, m = day.year + y, m + 1
    return date(y, m, min(day.day, calendar.monthrange(y, m)[1]))


def next_due(day, repeat, work_days="01234", every=1, days=""):
    """The next date after `day`: every N days / weeks / months / years, or on
    chosen weekdays ("0,3" = Monday and Thursday) every N weeks."""
    every = max(int(every or 1), 1)
    if repeat == Repeat.DAILY:
        return day + timedelta(days=every)
    if repeat == Repeat.WEEKDAYS:      # the person's own work days (Sunday–Thursday by default here)
        nxt = day + timedelta(days=1)
        for _i in range(7):
            if str(nxt.weekday()) in (work_days or "01234"):
                break
            nxt += timedelta(days=1)
        return nxt
    if repeat == Repeat.WEEKLY:
        picked = sorted({int(x) for x in (days or "").split(",") if x.strip().isdigit() and int(x) < 7})
        if not picked:
            return day + timedelta(days=7 * every)
        later = [w for w in picked if w > day.weekday()]
        if later:                                   # later this same week
            return day + timedelta(days=later[0] - day.weekday())
        monday = day - timedelta(days=day.weekday())   # else the first chosen day, `every` weeks on
        return monday + timedelta(days=7 * every + picked[0])
    if repeat == Repeat.MONTHLY:
        return _add_months(day, every)
    if repeat == Repeat.YEARLY:
        return _add_months(day, 12 * every)
    return None


def repeat_text(task):
    """"Every 2 weeks on Mon, Thu", "Every month (from when it's done)"… for a task row or page."""
    from django.utils.dates import WEEKDAYS_ABBR

    if not task.repeat:
        return ""
    n = task.repeat_every or 1
    if task.repeat == Repeat.WEEKDAYS:
        text = _("Every work day")
    elif task.repeat == Repeat.DAILY:
        text = (_("Every day") if n == 1 else _("Every %(n)s days") % {"n": n})
    elif task.repeat == Repeat.WEEKLY:
        text = (_("Every week") if n == 1 else _("Every %(n)s weeks") % {"n": n})
        picked = [int(x) for x in (task.repeat_days or "").split(",") if x.strip().isdigit() and int(x) < 7]
        if picked:
            text += " · " + ", ".join(str(WEEKDAYS_ABBR[w]) for w in sorted(set(picked)))
    elif task.repeat == Repeat.MONTHLY:
        text = (_("Every month") if n == 1 else _("Every %(n)s months") % {"n": n})
    else:
        text = (_("Every year") if n == 1 else _("Every %(n)s years") % {"n": n})
    if task.repeat_from_done:
        text += " · " + _("from when it's done")
    return text


@transaction.atomic
def set_done(task, done=True):
    """Ticks a task off (or back on). A repeating task leaves the next one behind."""
    if done == task.is_done:
        return None
    if task.from_note_id:
        tick_note_line(task, done)
    if done:
        task.status, task.completed_at = Status.DONE, timezone.now()
        task.save(update_fields=["status", "completed_at", "updated_at"])
        for sub in task.subtasks.exclude(status=Status.DONE):    # a finished task's open subtasks are finished with it
            sub.status, sub.completed_at = Status.DONE, task.completed_at
            sub.save(update_fields=["status", "completed_at", "updated_at"])
        running = TimeEntry.objects.filter(owner=task.owner, task=task, ended_at__isnull=True).exists()
        if running:
            stop_timer(task.owner)
        if task.repeat:
            base = timezone.localdate() if (task.repeat_from_done or not task.due_date) else task.due_date
            due = next_due(base, task.repeat, WorkSettings.for_user(task.owner).work_days, task.repeat_every, task.repeat_days)
            start = due - (task.due_date - task.start_date) if (task.start_date and task.due_date and due) else None
            nxt = Task.objects.create(owner=task.owner, project=task.project, title=task.title, notes=task.notes,
                                      priority=task.priority, due_date=due, start_date=start, goal=task.goal, link=task.link,
                                      repeat=task.repeat, repeat_every=task.repeat_every, repeat_days=task.repeat_days,
                                      repeat_from_done=task.repeat_from_done,
                                      estimate_minutes=task.estimate_minutes, remind_at=_next_reminder(task, due),
                                      order=next_order(task.owner, Status.TODO))
            nxt.tags.set(task.tags.all())
            for item in task.checklist.all():
                nxt.checklist.create(text=item.text, order=item.order)
            return nxt
    else:
        task.status, task.completed_at = Status.TODO, None
        task.save(update_fields=["status", "completed_at", "updated_at"])
    return None


def _next_reminder(task, due):
    """The next repeat's reminder: as many days before its due date as this one's was
    (at the same time of day) — or none, when there's nothing to count from."""
    if not task.remind_at or not due:
        return None
    local = timezone.localtime(task.remind_at)
    gap = max((task.due_date - local.date()).days, 0) if task.due_date else 0       # never after its due day
    return timezone.make_aware(datetime.combine(due - timedelta(days=gap), local.time().replace(tzinfo=None)), timezone.get_current_timezone())


def can_be_parent(task, parent):
    """Subtasks go one level deep: a subtask can't have subtasks, and a task
    with subtasks can't become one."""
    if parent is None:
        return True
    return (parent.pk != task.pk and parent.owner_id == task.owner_id and parent.parent_id is None
            and not (task.pk and task.subtasks.exists()))


def add_subtask(parent, text):
    """A subtask from one typed line (quick-add words work), in the parent's project."""
    sub = create_from_quick(parent.owner, text, project=parent.project, goal=parent.goal)
    if sub is None:
        return None
    sub.parent = parent
    if not sub.project_id:
        sub.project = parent.project
    sub.save(update_fields=["parent", "project", "updated_at"])
    return sub


def unblocked_by(task):
    """Open tasks that were waiting on `task` and now have nothing left in their way."""
    out = []
    for t in task.blocking.exclude(status=Status.DONE).prefetch_related("blocked_by"):
        if all(b.status == Status.DONE for b in t.blocked_by.all()):
            out.append(t)
    return out


def can_block(task, other):
    """Whether `other` may be set as blocking `task`: not itself, and not
    something that (through others) already waits on `task` — no circles."""
    if other.pk == task.pk or other.owner_id != task.owner_id:
        return False
    seen, todo = set(), [other.pk]
    while todo:
        pk = todo.pop()
        if pk == task.pk:
            return False
        if pk in seen:
            continue
        seen.add(pk)
        todo.extend(Task.blocked_by.through.objects.filter(from_task_id=pk).values_list("to_task_id", flat=True))
    return True


def today_tasks(user, today=None):
    """What's on today's list: My Day picks, in progress, due today or late."""
    today = today or timezone.localdate()
    open_ = (Task.objects.filter(owner=user).exclude(status=Status.DONE)
             .filter(Q(my_day=today) | Q(status=Status.DOING) | Q(due_date__lte=today))
             .select_related("project"))
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
    blockers += [_("Waiting on %(who)s: %(task)s") % {"who": t.waiting_for, "task": t.title} for t in waiting_tasks(user)[:8]]

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



# ── Goals ─────────────────────────────────────────────────────────────────
def with_progress(goals):
    """Goals with .steps_count / .tasks_count (done, total) and .pct, counted in two queries."""
    from django.db.models import Count

    goals = list(goals)
    ids = [g.pk for g in goals]
    steps = {r["goal_id"]: (r["done"], r["total"]) for r in GoalStep.objects.filter(goal_id__in=ids).values("goal_id")
             .annotate(total=Count("id"), done=Count("id", filter=Q(done=True)))}
    tasks = {r["goal_id"]: (r["done"], r["total"]) for r in Task.objects.filter(goal_id__in=ids).values("goal_id")
             .annotate(total=Count("id"), done=Count("id", filter=Q(status=Status.DONE)))}
    for g in goals:
        g.steps_count, g.tasks_count = steps.get(g.pk, (0, 0)), tasks.get(g.pk, (0, 0))
        g.pct = g.progress(g.steps_count, g.tasks_count)
    return goals


def set_goal_status(goal, status):
    goal.status = status
    goal.completed_at = timezone.now() if status == GoalStatus.DONE else None
    goal.save(update_fields=["status", "completed_at", "updated_at"])


# ── Year heatmap (like GitHub's) ──────────────────────────────────────────
def heatmap(by_day, last, week_start=0):
    """Weeks (columns) of 7 days ending with the week of `last`; each cell has
    a level 0–4 against the busiest day. `by_day` is date → seconds."""
    if not by_day:
        return {"weeks": [], "months": []}
    first = min(by_day)
    first -= timedelta(days=(first.weekday() - week_start) % 7)
    peak = max(by_day.values()) or 1
    weeks, months, day, seen = [], [], first, None
    while day <= last:
        week = []
        for _i in range(7):
            secs = by_day.get(day)
            level = 0 if not secs else min(4, 1 + int(4 * secs / (peak + 1)))
            week.append({"date": day, "secs": secs or 0, "level": level, "out": secs is None or day > last})
            day += timedelta(days=1)
        top = week[0]["date"]
        if top.month != seen:
            months.append({"col": len(weeks), "date": top})
            seen = top.month
        weeks.append(week)
    return {"weeks": weeks, "months": months}


# ── Review & brag document ────────────────────────────────────────────────
def review(user, start, end):
    """Everything worth remembering from a period: time, what got done (by
    project), wins from the journal, goals reached, learning finished,
    habits kept, mood and energy."""
    from django.db.models import Avg

    lo, hi = day_bounds(start)[0], day_bounds(end)[1]
    today = timezone.localdate()
    t = totals(user, start, end)
    done = list(Task.objects.filter(owner=user, status=Status.DONE, completed_at__gte=lo, completed_at__lt=hi)
                .select_related("project").order_by("project__name", "completed_at"))
    by_project = defaultdict(list)
    for task in done:
        by_project[task.project].append(task)
    journals = list(JournalEntry.objects.filter(owner=user, date__gte=start, date__lte=end).order_by("date"))
    wins = [(j.date, line.strip("-*• ").strip()) for j in journals for line in j.wins.splitlines() if line.strip("-*• ").strip()]
    blockers = [(j.date, line.strip("-*• ").strip()) for j in journals for line in j.blockers.splitlines() if line.strip("-*• ").strip()]
    feel = JournalEntry.objects.filter(owner=user, date__gte=start, date__lte=end).aggregate(mood=Avg("mood"), energy=Avg("energy"))
    goals_done = list(Goal.objects.filter(owner=user, status=GoalStatus.DONE, completed_at__gte=lo, completed_at__lt=hi))
    goals_active = with_progress(Goal.objects.filter(owner=user, status=GoalStatus.ACTIVE))
    learnt = list(LearningItem.objects.filter(owner=user, status=LearningStatus.DONE, finished_on__gte=start, finished_on__lte=end))
    from .models import CardReview, Diagram

    answers = CardReview.objects.filter(owner=user, reviewed_at__gte=lo, reviewed_at__lt=hi)
    n_answers = answers.count()
    practice = {"answers": n_answers, "cards": answers.values("card").distinct().count(),
                "remembered": round(100 * answers.filter(rating__gt=1).count() / n_answers) if n_answers else None,
                "days": len({timezone.localdate(r) for r in answers.values_list("reviewed_at", flat=True)})}
    drawn = list(Diagram.objects.filter(owner=user, is_archived=False, updated_at__gte=lo, updated_at__lt=hi)
                 .only("pk", "title", "kind", "created_at", "updated_at").order_by("-updated_at")[:20])
    for dg in drawn:
        dg.is_new = dg.created_at >= lo
    habits = []
    for h in Habit.objects.filter(owner=user, is_archived=False):
        due = [start + timedelta(days=i) for i in range((end - start).days + 1) if h.is_due(start + timedelta(days=i))]
        checked = set(h.checks.filter(date__gte=start, date__lte=end).values_list("date", flat=True))
        due = [d for d in due if d >= h.created_at.date() and (d < today or d in checked)]   # today isn't missed yet
        if due:
            habits.append({"habit": h, "pct": round(100 * sum(1 for d in due if d in checked) / len(due))})
    return {
        "start": start, "end": end, "totals": t, "done": done,
        "done_by_project": sorted(by_project.items(), key=lambda kv: (kv[0] is None, kv[0].name if kv[0] else "")),
        "wins": wins, "blockers": blockers, "mood": feel["mood"], "energy": feel["energy"],
        "goals_done": goals_done, "goals_active": goals_active, "learnt": learnt, "habits": habits,
        "practice": practice, "diagrams": drawn,
        "created": Task.objects.filter(owner=user, created_at__gte=lo, created_at__lt=hi).count(),
    }


def review_markdown(data):
    """The review as Markdown — a brag document to paste into a 1:1 or a performance review."""
    t = data["totals"]
    lines = [f"# {_('Work review')}: {data['start']:%d %b %Y} – {data['end']:%d %b %Y}", ""]
    lines += [f"- **{_('Time tracked')}:** {hm(t.seconds)}", f"- **{_('Tasks done')}:** {len(data['done'])}"]
    if t.focus_sessions:
        lines.append(f"- **{_('Focus sessions')}:** {t.focus_sessions}")
    if data["goals_done"]:
        lines += ["", f"## {_('Goals reached')}"] + [f"- {g.title}" for g in data["goals_done"]]
    if data["wins"]:
        lines += ["", f"## {_('Highlights')}"] + [f"- {text} ({day:%d %b})" for day, text in data["wins"]]
    if data["done_by_project"]:
        lines += ["", f"## {_('What I shipped')}"]
        for project, tasks in data["done_by_project"]:
            lines += ["", f"### {project.name if project else _('Other work')}"]
            lines += [f"- {task.title}" + (f" ({task.link})" if task.link else "") for task in tasks]
    if t.by_project:
        lines += ["", f"## {_('Where the time went')}"]
        lines += [f"- {(p.name if p else _('No project'))}: {hm(secs)} ({round(100 * secs / t.seconds)}%)" for p, secs in t.by_project]
    if data["learnt"]:
        lines += ["", f"## {_('Learning')}"] + [f"- {item.title}" + (f" — {item.author}" if item.author else "") for item in data["learnt"]]
    pr = data.get("practice") or {}
    if pr.get("answers"):
        lines += ["", f"## {_('Practice')}",
                  "- " + _("Flashcards: %(answers)s answers on %(cards)s cards over %(days)s days, %(pct)s%% remembered") % {
                      "answers": pr["answers"], "cards": pr["cards"], "days": pr["days"], "pct": pr["remembered"]}]
    if data.get("diagrams"):
        lines += ["", f"## {_('Diagrams')}"] + [f"- {dg.title} ({dg.get_kind_display()})" for dg in data["diagrams"]]
    active = [g for g in data["goals_active"]]
    if active:
        lines += ["", f"## {_('Goals in progress')}"] + [f"- {g.title}: {g.pct}%" for g in active]
    return "\n".join(lines) + "\n"



# ── Waiting on others, leftovers, capacity ────────────────────────────────
def waiting_tasks(user):
    return list(Task.objects.filter(owner=user).exclude(waiting_for="").exclude(status=Status.DONE).select_related("project").order_by("updated_at"))


def leftovers(user, today=None):
    """Picked for an earlier day (this past week), not done, and not already on today's list."""
    today = today or timezone.localdate()
    return list(Task.objects.filter(owner=user, my_day__lt=today, my_day__gte=today - timedelta(days=7))
                .exclude(status__in=[Status.DONE, Status.DOING]).exclude(due_date__lte=today).select_related("project"))


def capacity(tasks, user, today=None):
    """What's planned for today against the time that's left of the daily target."""
    s = WorkSettings.for_user(user)
    planned = sum((t.estimate_minutes or 0) for t in tasks if not t.is_done) * 60
    unestimated = sum(1 for t in tasks if not t.is_done and not t.estimate_minutes)
    target = s.daily_target_minutes * 60 if s.is_work_day(today or timezone.localdate()) else 0
    return {"planned": planned, "unestimated": unestimated, "target": target, "over": bool(target) and planned > target,
            "pct": min(round(100 * planned / target), 100) if target else 0}


# ── Many tasks at once ────────────────────────────────────────────────────
BULK_ACTIONS = ("done", "myday", "notmyday", "tomorrow", "due", "project", "priority", "status", "sprint", "delete")


@transaction.atomic
def bulk(user, ids, action, value=""):
    """Applies one change to many tasks; returns how many changed."""
    tasks = list(Task.objects.filter(owner=user, pk__in=ids))
    today = timezone.localdate()
    if action == "delete":
        from apps.trash.services import trash

        picked = {t.pk for t in tasks}
        for t in tasks:
            if t.parent_id in picked:      # goes to the trash with its task
                continue
            trash(user, t, _("Task: %(title)s") % {"title": t.title}, "")
        return len(tasks)
    for t in tasks:
        if action == "done":
            set_done(t, True)
            continue
        if action == "myday":
            t.my_day = today
        elif action == "notmyday":
            t.my_day = None
        elif action == "tomorrow":     # on to tomorrow's list (and its due date, if it was due by today)
            t.my_day = today + timedelta(days=1)
            if t.due_date and t.due_date <= today:
                t.due_date = t.my_day
        elif action == "due":
            t.due_date = date.fromisoformat(value) if value else None
        elif action == "project":
            t.project = Project.objects.filter(owner=user, pk=value or 0).first()
        elif action == "sprint":
            from .models import Sprint
            t.sprint = Sprint.objects.filter(owner=user, pk=value or 0, completed_at__isnull=True).first()
        elif action == "priority" and value.isdigit() and int(value) in Priority.values:
            t.priority = int(value)
        elif action == "status" and value in Status.values and value != Status.DONE:
            if t.is_done:
                set_done(t, False)
            t.status = value
        t.save()
    return len(tasks)


# ── Note history ──────────────────────────────────────────────────────────
NOTE_EVERY = timedelta(minutes=10)    # a new copy at most this often while writing
NOTE_KEEP = 40


def remember_note(note, force=False):
    """Keep the note as it is now, before a new round of edits (or on purpose with `force`)."""
    from .models import NoteVersion

    if not (note.title.strip() or note.body.strip()):
        return None
    last = note.versions.only("created_at", "body", "title").first()
    now = timezone.now()
    if last and not force and now - last.created_at < NOTE_EVERY:
        return None
    if last and last.body == note.body and last.title == note.title:
        return None
    v = NoteVersion.objects.create(note=note, title=note.title, body=note.body, created_at=now)
    old = list(note.versions.values_list("pk", flat=True)[NOTE_KEEP:])
    if old:
        NoteVersion.objects.filter(pk__in=old).delete()
    return v


# ── Restore from a backup (the export .zip / data.json) ───────────────────
BACKUP_ORDER = ["project", "tag", "goal", "goalstep", "note", "sprint", "task", "checklistitem", "taskactivity", "timeentry", "snippet",
                "habit", "habitcheck", "journalentry", "learningitem", "diagram", "deck", "card", "savedview", "tasktemplate", "preptopic", "prepsection", "question",
                "examsubject", "examnote"]


@transaction.atomic
def restore(user, rows):
    """Adds everything in a backup to this person's tracker, with new ids.
    Only Productivity records are read; anything else in the file is ignored.
    Tags and journal days that already exist are kept as they are."""
    import json

    from django.apps import apps as django_apps
    from django.core import serializers

    rows = [r for r in rows if isinstance(r, dict) and str(r.get("model", "")).startswith("productivity.")
            and r["model"].split(".", 1)[1] in BACKUP_ORDER]
    rows.sort(key=lambda r: (BACKUP_ORDER.index(r["model"].split(".", 1)[1]), bool((r.get("fields") or {}).get("parent"))))   # a subtask after the task it's part of
    ids, counts = defaultdict(dict), defaultdict(int)
    later = []      # tasks blocked by other tasks: linked once every task exists
    running = TimeEntry.objects.filter(owner=user, ended_at__isnull=True).exists()
    for row in rows:
        name = row["model"].split(".", 1)[1]
        model = django_apps.get_model("productivity", name)
        fields = dict(row.get("fields") or {})
        if "owner" in fields:
            fields["owner"] = user.pk
        old_pk = row.get("pk")
        m2m = {}
        for f in model._meta.get_fields():
            if not getattr(f, "concrete", False) or f.name not in fields:
                continue
            if f.many_to_many and f.related_model is model:     # task → task (blocked by): after all tasks are in
                later.append((name, old_pk, f.name, fields.pop(f.name) or []))
            elif f.many_to_many:
                m2m[f.name] = [ids[f.related_model._meta.model_name].get(v) for v in fields.pop(f.name) or []]
            elif f.is_relation and f.name != "owner" and fields[f.name] is not None:
                fields[f.name] = ids[f.related_model._meta.model_name].get(fields[f.name])
                if fields[f.name] is None and not f.null:
                    fields = None
                    break
        if fields is None:
            continue
        if name == "tag":
            tag, _created = Tag.objects.get_or_create(owner=user, name=fields["name"], defaults={"color": fields.get("color", "slate")})
            ids["tag"][old_pk] = tag.pk
            continue
        if name == "tasktemplate" and isinstance(fields.get("data"), dict) and fields["data"].get("project"):
            fields["data"] = {**fields["data"], "project": ids["project"].get(fields["data"]["project"])}   # its project, by its new id
        if name == "journalentry" and JournalEntry.objects.filter(owner=user, date=fields.get("date")).exists():
            continue
        if name == "habitcheck" and HabitCheck.objects.filter(habit_id=fields.get("habit"), date=fields.get("date")).exists():
            continue
        if name == "timeentry" and fields.get("ended_at") is None:
            if running:
                fields["ended_at"] = fields.get("started_at")
            running = True
        obj = next(serializers.deserialize("json", json.dumps([{"model": row["model"], "fields": fields}])))
        obj.object.pk = None
        obj.object._no_activity = True     # its history comes from the backup, not from being added now
        obj.object.save()
        ids[name][old_pk] = obj.object.pk
        for fname, values in m2m.items():
            getattr(obj.object, fname).set([v for v in values if v])
        counts[name] += 1
    for name, old_pk, fname, values in later:
        new_pk = ids[name].get(old_pk)
        if new_pk:
            model = django_apps.get_model("productivity", name)
            getattr(model.objects.get(pk=new_pk), fname).set([ids[name][v] for v in values if ids[name].get(v)])
    return dict(counts)


# ── Calendar feed (.ics) ──────────────────────────────────────────────────
def _ics(value):
    return str(value).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line):
    out, part = [], ""
    for ch in line:
        if len((part + ch).encode()) > 73:
            out.append(part)
            part = " "
        part += ch
    out.append(part)
    return "\r\n".join(out)


def calendar_feed(user, base_url=""):
    """Open tasks with a due date (all-day), reminders and day-planner blocks
    (timed, with an alarm) and goal deadlines, for Google / Apple / Outlook calendars."""
    from django.urls import reverse

    now = timezone.now()
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//FinTrack//Productivity//EN", "CALSCALE:GREGORIAN",
             "X-WR-CALNAME:" + _ics(_("Work tasks")), "REFRESH-INTERVAL;VALUE=DURATION:PT1H", "X-PUBLISHED-TTL:PT1H"]

    def event(uid, summary, url, start_lines, alarm=False, description=""):
        nonlocal lines
        lines += ["BEGIN:VEVENT", f"UID:{uid}@fintrack-work", f"DTSTAMP:{stamp}", *start_lines, _fold("SUMMARY:" + _ics(summary))]
        if url:
            lines.append(_fold("URL:" + base_url + url))
        if description or url:
            lines.append(_fold("DESCRIPTION:" + _ics("\n".join(x for x in (description, base_url + url if url else "") if x))))
        if alarm:
            lines += ["BEGIN:VALARM", "ACTION:DISPLAY", _fold("DESCRIPTION:" + _ics(summary)), "TRIGGER:PT0M", "END:VALARM"]
        lines.append("END:VEVENT")

    open_tasks = Task.objects.filter(owner=user).exclude(status=Status.DONE).select_related("project")
    for t in open_tasks.filter(due_date__gte=timezone.localdate() - timedelta(days=30)):
        nxt = t.due_date + timedelta(days=1)
        event(f"task-{t.pk}", t.title, reverse("work:task", args=[t.pk]),
              [f"DTSTART;VALUE=DATE:{t.due_date:%Y%m%d}", f"DTEND;VALUE=DATE:{nxt:%Y%m%d}"],
              description=" · ".join(x for x in (t.project.name if t.project_id else "", t.link) if x))
    for t in open_tasks.filter(remind_at__gte=now - timedelta(days=7)):
        at = t.remind_at.astimezone(dt_timezone.utc)
        end = at + timedelta(minutes=15)
        event(f"remind-{t.pk}", "⏰ " + t.title, reverse("work:task", args=[t.pk]),
              [f"DTSTART:{at:%Y%m%dT%H%M%SZ}", f"DTEND:{end:%Y%m%dT%H%M%SZ}"], alarm=True)
    for t in open_tasks.filter(scheduled_at__gte=now - timedelta(days=7)):     # the day planner's blocks
        at = t.scheduled_at.astimezone(dt_timezone.utc)
        end = at + timedelta(minutes=t.block_minutes)
        event(f"block-{t.pk}", t.title, reverse("work:task", args=[t.pk]),
              [f"DTSTART:{at:%Y%m%dT%H%M%SZ}", f"DTEND:{end:%Y%m%dT%H%M%SZ}"], alarm=True,
              description=" · ".join(x for x in (t.project.name if t.project_id else "", t.link) if x))
    for g in Goal.objects.filter(owner=user, status=GoalStatus.ACTIVE, target_date__isnull=False):
        event(f"goal-{g.pk}", "🎯 " + g.title, reverse("work:goal", args=[g.pk]),
              [f"DTSTART;VALUE=DATE:{g.target_date:%Y%m%d}", f"DTEND;VALUE=DATE:{g.target_date + timedelta(days=1):%Y%m%d}"])
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


# ── Day planner (time blocking) ───────────────────────────────────────────
SLOT_MINUTES = 15


def _at(day, t):
    return timezone.make_aware(datetime.combine(day, t), timezone.get_current_timezone())


def plan_day(user, day):
    """(blocks, unplanned, entries) for the planner: tasks with a time on
    `day`, the day's other open tasks, and the time actually tracked."""
    lo, hi = day_bounds(day)
    blocks = list(Task.objects.filter(owner=user, scheduled_at__gte=lo, scheduled_at__lt=hi)
                  .select_related("project").order_by("scheduled_at"))
    if day == timezone.localdate():
        candidates = today_tasks(user, day)[0]
    else:
        candidates = list(Task.objects.filter(owner=user).exclude(status=Status.DONE)
                          .filter(Q(my_day=day) | Q(due_date=day)).select_related("project")
                          .order_by("-priority", "order"))
    planned = {t.pk for t in blocks}
    unplanned = [t for t in candidates if t.pk not in planned]
    entries = list(TimeEntry.objects.filter(owner=user, started_at__lt=hi)
                   .filter(Q(ended_at__gt=lo) | Q(ended_at__isnull=True))
                   .select_related("task", "project").order_by("started_at"))
    return blocks, unplanned, entries


def fill_day(user, day, now=None):
    """"Fill my day": gives each unplanned task (most important first) the
    first free time that fits it, from now (or the start of the work day) to
    its end. Waiting tasks are left out. Returns (placed, did_not_fit)."""
    s = WorkSettings.for_user(user)
    now = now or timezone.now()
    start, end = _at(day, s.day_start), _at(day, s.day_end)
    if timezone.localtime(now).date() == day:
        local = timezone.localtime(now)
        rounded = local.replace(second=0, microsecond=0) + timedelta(minutes=(-local.minute) % SLOT_MINUTES)
        start = max(start, rounded)
    blocks, unplanned, _entries = plan_day(user, day)
    busy = sorted((b.scheduled_at, b.scheduled_at + timedelta(minutes=b.block_minutes)) for b in blocks)
    placed, left = [], []
    for task in unplanned:
        if task.waiting_for:
            continue
        length = timedelta(minutes=task.block_minutes)
        at = start
        for b_start, b_end in busy:
            if b_start < at + length and at < b_end:
                at = max(at, b_end)
        if at + length > end:
            left.append(task)
            continue
        task.scheduled_at = at
        fields = ["scheduled_at", "updated_at"]
        if task.my_day != day and task.due_date != day:
            task.my_day = day
            fields.append("my_day")
        task.save(update_fields=fields)
        busy = sorted(busy + [(at, at + length)])
        placed.append(task)
    return placed, left


def clear_plan(user, day):
    """Takes the day's open tasks off the timeline (they stay on the day's list)."""
    lo, hi = day_bounds(day)
    return Task.objects.filter(owner=user, scheduled_at__gte=lo, scheduled_at__lt=hi).exclude(status=Status.DONE).update(scheduled_at=None)


def next_block(user, now=None):
    """The planned task now running or coming next today, for the Today page."""
    now = now or timezone.now()
    lo, hi = day_bounds(timezone.localtime(now).date())
    for t in (Task.objects.filter(owner=user, scheduled_at__gte=lo, scheduled_at__lt=hi).exclude(status=Status.DONE)
              .select_related("project").order_by("scheduled_at")):
        if t.scheduled_at + timedelta(minutes=t.block_minutes) > now:
            return t
    return None


# ── Estimates vs. what it really took ─────────────────────────────────────
def estimate_accuracy(user, start, end):
    """For tasks finished between start and end that had an estimate and
    tracked time: totals, the ratio (1.0 = spot on), and the biggest misses."""
    lo, hi = day_bounds(start)[0], day_bounds(end)[1]
    tasks = list(Task.objects.filter(owner=user, status=Status.DONE, completed_at__gte=lo, completed_at__lt=hi,
                                     estimate_minutes__gt=0))
    tracked = tracked_by(user, "task", [t.pk for t in tasks]) if tasks else {}
    rows = []
    for t in tasks:
        actual = tracked.get(t.pk, 0)
        if actual < 60:
            continue
        est = t.estimate_minutes * 60
        rows.append({"task": t, "estimate": est, "actual": actual, "ratio": actual / est, "over": actual - est})
    if not rows:
        return None
    est_total, actual_total = sum(r["estimate"] for r in rows), sum(r["actual"] for r in rows)
    ratio = actual_total / est_total
    on_target = sum(1 for r in rows if 0.8 <= r["ratio"] <= 1.25)
    return {"count": len(rows), "estimate": est_total, "actual": actual_total, "ratio": ratio,
            "pct_off": round(abs(ratio - 1) * 100), "under": ratio > 1.05, "over": ratio < 0.95,
            "on_target": on_target, "on_target_pct": round(100 * on_target / len(rows)),
            "misses": sorted(rows, key=lambda r: -abs(r["over"]))[:5]}


# ── Notes: to-dos into tasks, and links between notes ─────────────────────
TODO_LINE = re.compile(r"^([ \t]*[-*+][ \t]+)\[ \][ \t]+(\S.*?)[ \t]*$", re.M)
TASK_URL = re.compile(r"/work/tasks/(\d+)/")


def open_todos(body):
    """The note's unticked "- [ ] …" lines that aren't tasks yet."""
    return [m.group(2) for m in TODO_LINE.finditer(body or "") if not TASK_URL.search(m.group(2))]


@transaction.atomic
def note_todos_to_tasks(user, note, today=None):
    """Each open to-do line becomes a task (quick-add words work: "#tag
    tomorrow ~30m @api"), and the line becomes a link to it — so doing it again
    skips those lines, and ticking the task ticks the line. Returns the new tasks."""
    from django.urls import reverse

    made = []

    def swap(m):
        text = m.group(2)
        if TASK_URL.search(text):
            return m.group(0)
        task = create_from_quick(user, text, project=note.project, today=today)
        if task is None:
            return m.group(0)
        task.from_note = note
        task.save(update_fields=["from_note"])
        made.append(task)
        label = task.title.replace("[", "(").replace("]", ")")
        return f"{m.group(1)}[ ] [{label}]({reverse('work:task', args=[task.pk])})"

    body = TODO_LINE.sub(swap, note.body)
    if made:
        note.body = body
        note.save(update_fields=["body", "updated_at"])
    return made


def tick_note_line(task, done):
    """Ticks (or unticks) the note line a task was made from."""
    note = Note.objects.filter(pk=task.from_note_id).first()
    if note is None:
        return
    url = f"/work/tasks/{task.pk}/"
    lines, changed = note.body.split("\n"), False
    for i, line in enumerate(lines):
        if url in line:
            new = re.sub(r"\[( |x|X)\]", "[x]" if done else "[ ]", line, count=1)
            changed, lines[i] = changed or new != line, new
    if changed:
        note.body = "\n".join(lines)
        note.save(update_fields=["body", "updated_at"])


def backlinks(note):
    """Other notes that link here with [[Title]]."""
    if not note.title.strip():
        return []
    return list(Note.objects.filter(owner=note.owner, body__icontains=f"[[{note.title.strip()}]]").exclude(pk=note.pk)
                .order_by("-updated_at")[:30])


# ── Week planner ──────────────────────────────────────────────────────────
WEEK_BACKLOG = 60


def week_start(day, starts_on):
    """The first day of day's week, for a week starting on `starts_on` (0 = Monday)."""
    return day - timedelta(days=(day.weekday() - starts_on) % 7)


def plan_week(user, start, today=None):
    """Seven days of tasks (by My Day, or by due date when not picked for a
    day), each with its planned and tracked time, plus what isn't planned."""
    today = today or timezone.localdate()
    s = WorkSettings.for_user(user)
    end = start + timedelta(days=6)
    tasks = list(Task.objects.filter(owner=user)
                 .filter(Q(my_day__gte=start, my_day__lte=end) | Q(my_day__isnull=True, due_date__gte=start, due_date__lte=end))
                 .exclude(Q(status=Status.DONE) & ~Q(completed_at__gte=day_bounds(start)[0], completed_at__lt=day_bounds(end)[1]))
                 .select_related("project").order_by("status", "-priority", "order"))
    tracked = daily_seconds(user, start, end)
    days = []
    for i in range(7):
        day = start + timedelta(days=i)
        items = [t for t in tasks if (t.my_day or t.due_date) == day]
        if day == today:     # late tasks and work in progress show up today
            seen = {t.pk for t in items}
            items += [t for t in today_tasks(user, today)[0] if t.pk not in seen and (t.my_day or t.due_date or today) < start]
        open_items = [t for t in items if not t.is_done]
        planned = sum((t.estimate_minutes or 0) for t in open_items) * 60
        target = s.daily_target_minutes * 60 if s.is_work_day(day) else 0
        days.append({"date": day, "tasks": items, "planned": planned, "target": target, "over": bool(target) and planned > target,
                     "pct": min(round(100 * planned / target), 100) if target else 0, "tracked": tracked.get(day, 0),
                     "past": day < today, "today": day == today, "work": s.is_work_day(day),
                     "unestimated": sum(1 for t in open_items if not t.estimate_minutes)})
    backlog_qs = (Task.objects.filter(owner=user, my_day__isnull=True).exclude(status=Status.DONE).exclude(waiting_for__gt="")
                  .filter(Q(due_date__isnull=True) | Q(due_date__gt=end)).select_related("project")
                  .order_by("-priority", "due_date", "order"))
    return days, list(backlog_qs[:WEEK_BACKLOG]), backlog_qs.count()
