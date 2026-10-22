"""Bring tasks in from another app: a CSV exported from Todoist, Trello, Jira,
Asana, ClickUp — or any spreadsheet with a title column.

The columns are recognised by their names (Content / Card Name / Summary /
Name / Title…), shown in a preview, and only then added. Projects and tags
named in the file are made when they don't exist yet.
"""
import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from . import services
from .models import Priority, Project, Status, Task, TaskKind

MAX_ROWS = 2000

# Column names each app uses, lower-cased; the first one found wins.
COLUMNS = {
    "title": ["content", "card name", "summary", "name", "title", "task", "task name", "subject", "to do", "todo"],
    "notes": ["description", "card description", "notes", "note", "details", "body"],
    "due": ["due date", "due", "date", "deadline", "due on", "end date"],
    "start": ["start date", "start", "start on"],
    "priority": ["priority", "importance"],
    "project": ["project", "projects", "project name", "board name", "list"],
    "status": ["status", "list name", "section/column", "section", "column", "state", "completed"],
    "tags": ["labels", "label", "tags", "tag"],
    "estimate": ["estimate", "time estimate", "original estimate", "estimate (minutes)"],
    "type": ["type"],          # Todoist: task / section / note rows
    "kind": ["issue type", "work type", "task type"],
    "points": ["story points", "story point estimate", "custom field (story points)", "custom field (story point estimate)", "points", "estimate (points)"],
}
KIND_WORDS = {"bug": TaskKind.BUG, "defect": TaskKind.BUG, "incident": TaskKind.BUG, "story": TaskKind.FEATURE, "feature": TaskKind.FEATURE,
              "new feature": TaskKind.FEATURE, "improvement": TaskKind.FEATURE, "epic": TaskKind.FEATURE, "enhancement": TaskKind.FEATURE,
              "spike": TaskKind.RESEARCH, "research": TaskKind.RESEARCH, "chore": TaskKind.CHORE, "tech debt": TaskKind.CHORE,
              "maintenance": TaskKind.CHORE, "documentation": TaskKind.DOCS, "docs": TaskKind.DOCS}
DONE_WORDS = {"done", "complete", "completed", "closed", "resolved", "finished", "true", "yes", "1"}
DOING_WORDS = {"in progress", "doing", "in review", "review", "started", "active", "ongoing"}
BACKLOG_WORDS = {"backlog", "someday", "icebox", "later", "ideas"}
PRIORITY_WORDS = {"urgent": Priority.URGENT, "highest": Priority.URGENT, "critical": Priority.URGENT, "blocker": Priority.URGENT, "p1": Priority.URGENT,
                  "high": Priority.HIGH, "p2": Priority.HIGH, "major": Priority.HIGH,
                  "medium": Priority.MEDIUM, "normal": Priority.MEDIUM, "p3": Priority.MEDIUM,
                  "low": Priority.LOW, "lowest": Priority.LOW, "minor": Priority.LOW, "trivial": Priority.LOW, "p4": Priority.NONE}
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_date(value, today=None):
    """Most ways apps write a date: 2026-10-22, 22/10/2026, 10/22/2026, 22 Oct 2026,
    Oct 22, 2026, 22/Oct/26 10:00 AM (Jira), today, tomorrow. Day first when unsure."""
    v = (value or "").strip().lower()
    if not v:
        return None
    today = today or timezone.localdate()
    if v in ("today", "tod"):
        return today
    if v in ("tomorrow", "tmr"):
        return today + timedelta(days=1)
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", v)
    if m:
        return _safe(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.match(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})", v)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y = y + 2000 if y < 100 else y
        day, month = (b, a) if (b > 12 and a <= 12) else (a, b)     # 10/22/2026 is month first; else day first
        return _safe(y, month, day)
    m = re.match(r"(\d{1,2})[\s/.-]+([a-z]{3})[a-z]*[\s/.,-]+(\d{2,4})", v)              # 22 Oct 2026, 22/Oct/26
    if m and m.group(2) in MONTHS:
        y = int(m.group(3))
        return _safe(y + 2000 if y < 100 else y, MONTHS[m.group(2)], int(m.group(1)))
    m = re.match(r"([a-z]{3})[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s*(\d{4})?", v)    # Oct 22, 2026 / Oct 22
    if m and m.group(1) in MONTHS:
        return _safe(int(m.group(3) or today.year), MONTHS[m.group(1)], int(m.group(2)))
    return None


def _safe(y, m, d):
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _priority(value, source):
    v = (value or "").strip().lower()
    if not v:
        return Priority.NONE
    if v.isdigit():
        n = int(v)
        if source == "todoist":          # Todoist: 4 is the highest (p1)
            return {4: Priority.URGENT, 3: Priority.HIGH, 2: Priority.MEDIUM}.get(n, Priority.NONE)
        return {1: Priority.URGENT, 2: Priority.HIGH, 3: Priority.MEDIUM, 4: Priority.LOW}.get(n, Priority.NONE)
    return PRIORITY_WORDS.get(v, Priority.NONE)


def _status(value):
    v = (value or "").strip().lower()
    if v in DONE_WORDS:
        return Status.DONE
    if v in DOING_WORDS:
        return Status.DOING
    if v in BACKLOG_WORDS:
        return Status.BACKLOG
    return Status.TODO


def _minutes(value):
    v = (value or "").strip().lower()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(h|hr|hrs|hours?|m|min|mins|minutes?)?", v)
    if not m:
        return None
    n = float(m.group(1))
    unit = m.group(2) or "m"
    if unit.startswith("h"):
        return int(round(n * 60))
    if n > 600 and not m.group(2):        # Jira gives seconds
        return int(round(n / 60))
    return int(round(n))


def _points(value):
    try:
        n = round(float((value or "").strip()))
    except ValueError:
        return None
    return n if 0 < n <= 100 else None


@dataclass
class Parsed:
    source: str = "csv"
    columns: dict = field(default_factory=dict)    # our field → their column name
    rows: list = field(default_factory=list)       # [{title, notes, due, start, priority, project, status, tags, estimate}]
    skipped: int = 0
    error: str = ""


def read(data, today=None):
    """Parsed rows from CSV bytes (any of the common encodings, comma or semicolon)."""
    from django.utils.translation import gettext as _

    out = Parsed()
    text = None
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            text = data.decode(enc)
            break
        except (UnicodeDecodeError, AttributeError):
            continue
    if not text:
        out.error = _("This file couldn't be read. Save it as CSV (UTF-8) and try again.")
        return out
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    names = {(h or "").strip().lower(): h for h in (reader.fieldnames or [])}
    for key, options in COLUMNS.items():
        hit = next((names[o] for o in options if o in names), None)
        if hit:
            out.columns[key] = hit
    if "title" not in out.columns:
        out.error = _("No title column found. Name one of the columns “Title”, “Name”, “Task” or “Summary”.")
        return out
    heads = set(names)
    out.source = ("todoist" if {"type", "content"} <= heads else "trello" if "card name" in heads else
                  "jira" if "summary" in heads and ("issue key" in heads or "issue type" in heads) else "asana" if "section/column" in heads else "csv")
    get = lambda row, key: (row.get(out.columns[key]) or "").strip() if key in out.columns else ""  # noqa: E731
    for row in reader:
        if len(out.rows) >= MAX_ROWS:
            out.skipped += 1
            continue
        if out.source == "todoist" and get(row, "type").lower() not in ("task", ""):
            out.skipped += 1          # Todoist's section and note rows
            continue
        title = re.sub(r"\s+", " ", get(row, "title"))[:300]
        if not title:
            out.skipped += 1
            continue
        split = r"[,;\s]+" if out.source == "jira" else r"[,;]|\s(?=#)"      # Jira separates labels with spaces
        tags = [t for t in re.split(split, get(row, "tags")) if t.strip()]
        out.rows.append({
            "title": title, "notes": get(row, "notes")[:10000], "due": parse_date(get(row, "due"), today), "start": parse_date(get(row, "start"), today),
            "priority": _priority(get(row, "priority"), out.source), "project": get(row, "project")[:120],
            "status": _status(get(row, "status")), "tags": [t.strip().lstrip("#@")[:40] for t in tags][:10], "estimate": _minutes(get(row, "estimate")),
            "kind": KIND_WORDS.get(get(row, "kind").lower(), TaskKind.TASK), "points": _points(get(row, "points")),
        })
    return out


@transaction.atomic
def save(user, rows, project=None):
    """Adds the rows as tasks. `project`, when given, is used for rows without one."""
    made, projects = 0, {}
    for r in rows:
        p = project
        if r.get("project"):
            key = r["project"].lower()
            if key not in projects:
                projects[key] = (Project.objects.filter(owner=user, name__iexact=r["project"]).first()
                                 or Project.objects.create(owner=user, name=r["project"][:120]))
            p = projects[key]
        due, start = r.get("due"), r.get("start")
        due = date.fromisoformat(due) if isinstance(due, str) else due
        start = date.fromisoformat(start) if isinstance(start, str) else start
        status = r.get("status") or Status.TODO
        t = Task.objects.create(owner=user, title=r["title"], notes=r.get("notes") or "", due_date=due,
                                start_date=start if (start and (not due or start <= due)) else None,
                                priority=r.get("priority") or 0, project=p, status=status, estimate_minutes=r.get("estimate"),
                                kind=r.get("kind") or TaskKind.TASK, points=r.get("points"),
                                completed_at=timezone.now() if status == Status.DONE else None,
                                order=services.next_order(user, status))
        if r.get("tags"):
            t.tags.set(services.tags_named(user, r["tags"]))
        made += 1
    return made


def to_session(parsed):
    """Rows as plain JSON for the preview → confirm step."""
    return [{**r, "due": r["due"].isoformat() if r["due"] else None, "start": r["start"].isoformat() if r["start"] else None} for r in parsed.rows]

