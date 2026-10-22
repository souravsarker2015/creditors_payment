"""Productivity: time tracking, tasks, focus sessions, notes, snippets,
habits and a daily journal. Everything belongs to one person (`owner`) and
nobody else sees it — not even other admins.
"""
import os
import re
from datetime import time, timedelta
from urllib.parse import urlparse

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

OWNER = {"to": settings.AUTH_USER_MODEL, "on_delete": models.CASCADE, "related_name": "+"}


class Color(models.TextChoices):
    SLATE = "slate", _("Slate")
    BLUE = "blue", _("Blue")
    TEAL = "teal", _("Teal")
    GREEN = "green", _("Green")
    LIME = "lime", _("Lime")
    AMBER = "amber", _("Amber")
    ORANGE = "orange", _("Orange")
    RED = "red", _("Red")
    PINK = "pink", _("Pink")
    PURPLE = "purple", _("Purple")


class Project(models.Model):
    owner = models.ForeignKey(**OWNER)
    name = models.CharField(_("Name"), max_length=120)
    color = models.CharField(_("Colour"), max_length=10, choices=Color.choices, default=Color.BLUE)
    client = models.CharField(_("Client / team"), max_length=120, blank=True)
    description = models.TextField(_("Description"), blank=True)
    estimate_hours = models.DecimalField(_("Time budget (hours)"), max_digits=7, decimal_places=1, null=True, blank=True,
                                         validators=[MinValueValidator(0)], help_text=_("Optional: how many hours this should take."))
    hourly_rate = models.DecimalField(_("Hourly rate"), max_digits=10, decimal_places=2, null=True, blank=True,
                                      validators=[MinValueValidator(0)], help_text=_("Optional: for billable work."))
    is_archived = models.BooleanField(_("Archived"), default=False)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name, verbose_name_plural = _("Project"), _("Projects")
        ordering = ["is_archived", "order", "name"]
        indexes = [models.Index(fields=["owner", "is_archived"])]

    def __str__(self):
        return self.name


class Tag(models.Model):
    owner = models.ForeignKey(**OWNER)
    name = models.CharField(_("Name"), max_length=40)
    color = models.CharField(_("Colour"), max_length=10, choices=Color.choices, default=Color.SLATE)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["owner", "name"], name="work_tag_unique_name")]

    def __str__(self):
        return self.name


class Status(models.TextChoices):
    BACKLOG = "backlog", _("Backlog")
    TODO = "todo", _("To do")
    DOING = "doing", _("In progress")
    DONE = "done", _("Done")


class Priority(models.IntegerChoices):
    NONE = 0, _("No priority")
    LOW = 1, _("Low")
    MEDIUM = 2, _("Medium")
    HIGH = 3, _("High")
    URGENT = 4, _("Urgent")


class Repeat(models.TextChoices):
    NONE = "", _("Doesn't repeat")
    DAILY = "daily", _("Every day")
    WEEKDAYS = "weekdays", _("Every work day")
    WEEKLY = "weekly", _("Every week")
    MONTHLY = "monthly", _("Every month")
    YEARLY = "yearly", _("Every year")


class Task(models.Model):
    owner = models.ForeignKey(**OWNER)
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="tasks", verbose_name=_("Project"))
    title = models.CharField(_("Title"), max_length=300)
    notes = models.TextField(_("Notes"), blank=True, help_text=_("Markdown works: **bold**, `code`, lists, links."))
    status = models.CharField(_("Status"), max_length=10, choices=Status.choices, default=Status.TODO, db_index=True)
    priority = models.PositiveSmallIntegerField(_("Priority"), choices=Priority.choices, default=Priority.NONE)
    due_date = models.DateField(_("Due"), null=True, blank=True)
    remind_at = models.DateTimeField(_("Remind me"), null=True, blank=True)
    estimate_minutes = models.PositiveIntegerField(_("Estimate (minutes)"), null=True, blank=True)
    my_day = models.DateField(_("In My Day"), null=True, blank=True, help_text="Picked for this day's focus list.")
    scheduled_at = models.DateTimeField(_("Planned for"), null=True, blank=True,
                                        help_text="Start of its block on the day planner (as long as the estimate, else 30 minutes).")
    repeat = models.CharField(_("Repeat"), max_length=10, choices=Repeat.choices, default=Repeat.NONE, blank=True)
    repeat_every = models.PositiveSmallIntegerField(_("Every"), default=1, validators=[MinValueValidator(1)],
                                                    help_text=_("Every 2 weeks, every 3 months…"))
    repeat_days = models.CharField(_("On these days"), max_length=14, blank=True,
                                   help_text="Weekly repeats: the weekdays it falls on, Monday=0 (\"0,3\" = Monday and Thursday).")
    repeat_from_done = models.BooleanField(_("Count from when it's done"), default=False,
                                           help_text=_("The next one is set from the day you finish it, not from its due date — for things like “water the plants”."))
    start_date = models.DateField(_("Starts"), null=True, blank=True, help_text=_("When work on it begins — it's drawn from here to its due date on the timeline."))
    parent = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="subtasks", verbose_name=_("Part of"),
                               help_text=_("Makes this a subtask of a bigger task."))
    blocked_by = models.ManyToManyField("self", symmetrical=False, blank=True, related_name="blocking", verbose_name=_("Blocked by"),
                                        help_text=_("Tasks that must be done before this one can start."))
    tags = models.ManyToManyField(Tag, blank=True, related_name="tasks", verbose_name=_("Tags"))
    link = models.URLField(_("Link"), max_length=500, blank=True,
                           help_text=_("The pull request, issue, ticket or doc this is about."))
    goal = models.ForeignKey("Goal", on_delete=models.SET_NULL, null=True, blank=True, related_name="tasks", verbose_name=_("Goal"))
    from_note = models.ForeignKey("Note", on_delete=models.SET_NULL, null=True, blank=True, related_name="action_tasks",
                                  verbose_name=_("From note"), help_text="Made from a to-do line in this note (ticked there too).")
    waiting_for = models.CharField(_("Waiting on"), max_length=120, blank=True,
                                   help_text=_("Who or what it's stuck on: a code review, Rahim, the client, a deploy…"))
    order = models.FloatField(default=0, help_text="Position in its column (smaller first).")
    reminder_sent_at = models.DateTimeField(null=True, blank=True, help_text="When its reminder was emailed (once per remind_at).")
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name, verbose_name_plural = _("Task"), _("Tasks")
        ordering = ["order", "-priority", "created_at"]
        indexes = [models.Index(fields=["owner", "status"]), models.Index(fields=["owner", "due_date"]),
                   models.Index(fields=["owner", "scheduled_at"])]

    def __str__(self):
        return self.title

    @property
    def block_minutes(self):
        """How long its block on the day planner is."""
        return self.estimate_minutes or 30

    @property
    def is_done(self):
        return self.status == Status.DONE

    def is_overdue(self, today=None):
        return bool(self.due_date and not self.is_done and self.due_date < (today or timezone.localdate()))


    @property
    def link_label(self):
        return link_label(self.link)

    @property
    def open_blockers(self):
        """The unfinished tasks in this one's way (uses prefetched blocked_by when there)."""
        return [b for b in self.blocked_by.all() if b.status != Status.DONE]

    @property
    def subtask_counts(self):
        """"2/5" for a task with subtasks (uses prefetched subtasks when there), else ""."""
        subs = list(self.subtasks.all())
        return f"{sum(1 for s in subs if s.status == Status.DONE)}/{len(subs)}" if subs else ""

    @property
    def is_blocked(self):
        return not self.is_done and bool(self.open_blockers)

    @property
    def repeat_label(self):
        from .services import repeat_text

        return repeat_text(self)


def link_label(url):
    """A short name for a link: "PR #482", "#91", "ABC-123", or the site's name."""
    if not url:
        return ""
    u = urlparse(url)
    path = u.path.rstrip("/")
    m = re.search(r"/(pull|pulls|merge_requests)/(\d+)", path)
    if m:
        return f"PR #{m.group(2)}" if m.group(1) != "merge_requests" else f"MR !{m.group(2)}"
    m = re.search(r"/issues/(\d+)", path)
    if m:
        return f"#{m.group(1)}"
    m = re.search(r"\b([A-Z][A-Z0-9]{1,9}-\d+)\b", url)   # Jira / Linear keys
    if m:
        return m.group(1)
    host = (u.hostname or "").removeprefix("www.")
    return host or url[:30]


class TaskActivity(models.Model):
    """A task's history: what changed and when, and comments written on it."""

    class Kind(models.TextChoices):
        COMMENT = "comment", _("Comment")
        CHANGE = "change", _("Change")

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="activity")
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.CHANGE)
    text = models.TextField(blank=True)                    # a comment's words
    data = models.JSONField(default=dict, blank=True)      # a change: {"field": "status", "old": "todo", "new": "doing"} — worded when shown
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name, verbose_name_plural = _("Task activity"), _("Task activity")
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["task", "created_at"])]

    def __str__(self):
        return self.text[:60] or str(self.data)[:60]

    @property
    def words(self):
        """A change, put into words in the reader's language."""
        from .activity import describe

        return describe(self)


class TaskTemplate(models.Model):
    """A task kept to make again: its notes, checklist and subtasks — "Release
    checklist", "New client onboarding"."""

    owner = models.ForeignKey(**OWNER)
    name = models.CharField(_("Name"), max_length=120)
    data = models.JSONField(default=dict, help_text="title, notes, priority, estimate, tags, project, due_in (days), checklist [..], subtasks [{title, estimate, due_in}]")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name, verbose_name_plural = _("Task template"), _("Task templates")
        ordering = ["name"]

    def __str__(self):
        return self.name


class SavedView(models.Model):
    """A task filter kept under a name — "Urgent at work", "Waiting on others"."""

    owner = models.ForeignKey(**OWNER)
    name = models.CharField(_("Name"), max_length=60)
    query = models.CharField(max_length=500, help_text="The task list's query string: view=board&project=3&priority=3…")
    order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name, verbose_name_plural = _("Saved view"), _("Saved views")
        ordering = ["order", "created_at"]

    def __str__(self):
        return self.name


class ChecklistItem(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="checklist")
    text = models.CharField(max_length=300)
    done = models.BooleanField(default=False)
    order = models.FloatField(default=0)

    class Meta:
        ordering = ["order", "pk"]

    def __str__(self):
        return self.text


class EntryKind(models.TextChoices):
    TIMER = "timer", _("Timer")
    MANUAL = "manual", _("Added by hand")
    FOCUS = "focus", _("Focus session")


class TimeEntry(models.Model):
    owner = models.ForeignKey(**OWNER)
    task = models.ForeignKey(Task, on_delete=models.SET_NULL, null=True, blank=True, related_name="entries", verbose_name=_("Task"))
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="entries", verbose_name=_("Project"))
    description = models.CharField(_("What you worked on"), max_length=300, blank=True)
    started_at = models.DateTimeField(_("Start"), db_index=True)
    ended_at = models.DateTimeField(_("End"), null=True, blank=True, help_text="Empty while the timer runs.")
    kind = models.CharField(max_length=10, choices=EntryKind.choices, default=EntryKind.TIMER)
    billable = models.BooleanField(_("Billable"), default=False)
    invoiced_at = models.DateTimeField(_("Billed"), null=True, blank=True, help_text="Put on an invoice (so it isn't billed twice).")
    tags = models.ManyToManyField(Tag, blank=True, related_name="entries", verbose_name=_("Tags"))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name, verbose_name_plural = _("Time entry"), _("Time entries")
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["owner", "started_at"])]
        constraints = [models.UniqueConstraint(fields=["owner"], condition=Q(ended_at__isnull=True), name="work_one_running_timer")]

    def __str__(self):
        return self.label

    @property
    def is_running(self):
        return self.ended_at is None

    @property
    def seconds(self):
        end = self.ended_at or timezone.now()
        return max(int((end - self.started_at).total_seconds()), 0)

    @property
    def label(self):
        return self.description or (self.task.title if self.task_id else "") or (self.project.name if self.project_id else "") or str(_("No description"))


class Note(models.Model):
    owner = models.ForeignKey(**OWNER)
    title = models.CharField(_("Title"), max_length=200, blank=True)
    body = models.TextField(_("Note"), blank=True)
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="notes", verbose_name=_("Project"))
    tags = models.ManyToManyField(Tag, blank=True, related_name="notes", verbose_name=_("Tags"))
    is_pinned = models.BooleanField(_("Pinned"), default=False)
    is_archived = models.BooleanField(_("Archived"), default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        verbose_name, verbose_name_plural = _("Note"), _("Notes")
        ordering = ["-is_pinned", "-updated_at"]

    def __str__(self):
        return self.display_title

    @property
    def display_title(self):
        if self.title:
            return self.title
        first = next((line.strip("# ").strip() for line in self.body.splitlines() if line.strip()), "")
        return first[:80] or str(_("Untitled note"))


class Language(models.TextChoices):
    TEXT = "plaintext", "Plain text"
    BASH = "bash", "Bash / shell"
    C = "c", "C"
    CPP = "cpp", "C++"
    CSHARP = "csharp", "C#"
    CSS = "css", "CSS"
    DART = "dart", "Dart"
    DOCKER = "dockerfile", "Dockerfile"
    GO = "go", "Go"
    HTML = "xml", "HTML / XML"
    JAVA = "java", "Java"
    JS = "javascript", "JavaScript"
    JSON = "json", "JSON"
    KOTLIN = "kotlin", "Kotlin"
    MARKDOWN = "markdown", "Markdown"
    PHP = "php", "PHP"
    PYTHON = "python", "Python"
    RUBY = "ruby", "Ruby"
    RUST = "rust", "Rust"
    SQL = "sql", "SQL"
    SWIFT = "swift", "Swift"
    TS = "typescript", "TypeScript"
    YAML = "yaml", "YAML"


class Snippet(models.Model):
    owner = models.ForeignKey(**OWNER)
    title = models.CharField(_("Title"), max_length=200)
    language = models.CharField(_("Language"), max_length=20, choices=Language.choices, default=Language.PYTHON)
    code = models.TextField(_("Code"))
    description = models.TextField(_("When to use it"), blank=True)
    tags = models.ManyToManyField(Tag, blank=True, related_name="snippets", verbose_name=_("Tags"))
    is_favorite = models.BooleanField(_("Favourite"), default=False)
    uses = models.PositiveIntegerField(default=0, help_text="Times copied.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name, verbose_name_plural = _("Snippet"), _("Snippets")
        ordering = ["-is_favorite", "-uses", "title"]

    def __str__(self):
        return self.title


class Habit(models.Model):
    owner = models.ForeignKey(**OWNER)
    name = models.CharField(_("Habit"), max_length=120)
    emoji = models.CharField(_("Emoji"), max_length=8, blank=True, default="✅")
    color = models.CharField(_("Colour"), max_length=10, choices=Color.choices, default=Color.GREEN)
    days = models.CharField(_("Days"), max_length=7, default="0123456",
                            help_text="Weekdays it's for: 0 = Monday … 6 = Sunday.")
    is_archived = models.BooleanField(_("Archived"), default=False)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name, verbose_name_plural = _("Habit"), _("Habits")
        ordering = ["is_archived", "order", "created_at"]

    def __str__(self):
        return self.name

    def is_due(self, day):
        return str(day.weekday()) in self.days


class HabitCheck(models.Model):
    habit = models.ForeignKey(Habit, on_delete=models.CASCADE, related_name="checks")
    date = models.DateField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["habit", "date"], name="work_habit_once_a_day")]


class JournalEntry(models.Model):
    """A day's log: the plan, what got done or learnt, blockers, and how it felt."""

    owner = models.ForeignKey(**OWNER)
    date = models.DateField(_("Date"))
    plan = models.TextField(_("Plan for the day"), blank=True)
    wins = models.TextField(_("Done & learnt"), blank=True)
    blockers = models.TextField(_("Blockers"), blank=True)
    notes = models.TextField(_("Notes"), blank=True)
    mood = models.PositiveSmallIntegerField(_("Mood"), null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)])
    energy = models.PositiveSmallIntegerField(_("Energy"), null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)])
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date"]
        constraints = [models.UniqueConstraint(fields=["owner", "date"], name="work_journal_one_a_day")]

    def __str__(self):
        return f"Journal {self.date}"


class WeekStart(models.IntegerChoices):
    MONDAY = 0, _("Monday")
    SATURDAY = 5, _("Saturday")
    SUNDAY = 6, _("Sunday")


class Sound(models.TextChoices):
    CHIME = "chime", _("Chime")
    BELL = "bell", _("Bell")
    DIGITAL = "digital", _("Digital")
    SOFT = "soft", _("Soft")


class WorkSettings(models.Model):
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="work_settings")
    daily_target_minutes = models.PositiveIntegerField(_("Daily target (minutes)"), default=360,
                                                       validators=[MinValueValidator(15), MaxValueValidator(1440)])
    work_days = models.CharField(_("Work days"), max_length=7, default="60123",
                                 help_text="Weekdays you work: 0 = Monday … 6 = Sunday.")
    week_start = models.PositiveSmallIntegerField(_("Week starts on"), choices=WeekStart.choices, default=WeekStart.SUNDAY)
    focus_minutes = models.PositiveSmallIntegerField(_("Focus length (minutes)"), default=25, validators=[MinValueValidator(1), MaxValueValidator(180)])
    short_break_minutes = models.PositiveSmallIntegerField(_("Short break (minutes)"), default=5, validators=[MinValueValidator(1), MaxValueValidator(60)])
    long_break_minutes = models.PositiveSmallIntegerField(_("Long break (minutes)"), default=15, validators=[MinValueValidator(1), MaxValueValidator(120)])
    long_break_every = models.PositiveSmallIntegerField(_("Long break after every"), default=4, validators=[MinValueValidator(2), MaxValueValidator(12)],
                                                        help_text=_("Focus sessions."))
    auto_start_breaks = models.BooleanField(_("Start breaks by themselves"), default=False)
    auto_start_focus = models.BooleanField(_("Start the next focus by itself"), default=False)
    sound_enabled = models.BooleanField(_("Sounds"), default=True)
    sound = models.CharField(_("Sound"), max_length=10, choices=Sound.choices, default=Sound.CHIME)
    volume = models.PositiveSmallIntegerField(_("Volume"), default=70, validators=[MaxValueValidator(100)])
    tick_sound = models.BooleanField(_("Ticking during focus"), default=False)
    notifications = models.BooleanField(_("Notifications"), default=True,
                                        help_text=_("When a focus session or break ends, a reminder is due, or a timer runs very long."))
    long_timer_hours = models.PositiveSmallIntegerField(_("Remind me when a timer runs over (hours)"), default=3,
                                                        validators=[MinValueValidator(1), MaxValueValidator(24)])
    default_project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name=_("Default project"))
    idle_minutes = models.PositiveSmallIntegerField(_("Ask about idle time after (minutes)"), default=15,
                                                    validators=[MinValueValidator(0), MaxValueValidator(240)],
                                                    help_text=_("When you come back to a running timer after this long away. 0 = never ask."))
    feed_token = models.CharField(max_length=40, blank=True, help_text="Secret part of the calendar feed address.")
    day_start = models.TimeField(_("Work day starts"), default=time(9, 0),
                                 help_text=_("The day planner opens here, and “Fill my day” plans from here."))
    day_end = models.TimeField(_("Work day ends"), default=time(18, 0))
    wip_limit = models.PositiveSmallIntegerField(_("Most tasks in progress at once"), null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(50)],
                                                 help_text=_("Optional. The board warns when “In progress” holds more — finishing beats starting."))
    invoice_from = models.TextField(_("Your details on invoices"), blank=True,
                                    help_text=_("Your name, address, phone and how to pay you (bank, bKash…). Printed at the top of an invoice."))
    currency = models.CharField(_("Currency"), max_length=8, default="৳", help_text=_("Shown on invoices and earnings: ৳, $, €…"))
    daily_email = models.BooleanField(_("Email me my day each morning"), default=False,
                                      help_text=_("When your work day starts: what's late and due, your plan, reminders, habits and flashcards."))
    reminder_emails = models.BooleanField(_("Email my task reminders too"), default=False,
                                          help_text=_("So a reminder reaches you even when the app is closed."))
    daily_email_sent_on = models.DateField(null=True, blank=True)
    cards_remind_at = models.TimeField(_("Remind me to review flashcards at"), null=True, blank=True,
                                       help_text=_("A notification when cards are waiting. Leave empty for none."))

    def __str__(self):
        return f"Work settings for {self.owner}"

    @classmethod
    def for_user(cls, user):
        """The person's settings (made on first use), kept on the user for the rest of the request."""
        cached = getattr(user, "_work_settings", None)
        if cached is not None and cached.owner_id == user.pk:
            return cached
        obj, _created = cls.objects.get_or_create(owner=user)
        user._work_settings = obj
        return obj

    def is_work_day(self, day):
        return str(day.weekday()) in self.work_days

    def new_feed_token(self):
        import secrets

        self.feed_token = secrets.token_urlsafe(24)
        self.save(update_fields=["feed_token"])
        return self.feed_token

    def week_of(self, day):
        """(first, last) day of the week `day` is in."""
        first = day - timedelta(days=(day.weekday() - self.week_start) % 7)
        return first, first + timedelta(days=6)


# ── Goals: where all this work is heading ─────────────────────────────────
class GoalArea(models.TextChoices):
    CAREER = "career", _("Career")
    LEARNING = "learning", _("Learning")
    PROJECT = "project", _("Project")
    HEALTH = "health", _("Health")
    MONEY = "money", _("Money")
    PERSONAL = "personal", _("Personal")


class GoalStatus(models.TextChoices):
    ACTIVE = "active", _("Active")
    DONE = "done", _("Reached")
    DROPPED = "dropped", _("Dropped")


class Goal(models.Model):
    """Something bigger than a task: "Become a senior engineer", "Ship v2",
    "Read 12 books". Progress comes from a number (12 books), its milestones,
    or the tasks linked to it — whichever it has."""

    owner = models.ForeignKey(**OWNER)
    title = models.CharField(_("Goal"), max_length=200)
    why = models.TextField(_("Why it matters"), blank=True, help_text=_("Markdown works. Read it when motivation dips."))
    area = models.CharField(_("Area"), max_length=10, choices=GoalArea.choices, default=GoalArea.CAREER)
    color = models.CharField(_("Colour"), max_length=10, choices=Color.choices, default=Color.PURPLE)
    status = models.CharField(_("Status"), max_length=10, choices=GoalStatus.choices, default=GoalStatus.ACTIVE, db_index=True)
    target_date = models.DateField(_("By when"), null=True, blank=True)
    unit = models.CharField(_("Measured in"), max_length=30, blank=True,
                            help_text=_("Optional: books, users, LeetCode problems, kg… Leave empty to track by milestones."))
    start_value = models.DecimalField(_("Starting from"), max_digits=12, decimal_places=2, default=0)
    current_value = models.DecimalField(_("Now at"), max_digits=12, decimal_places=2, null=True, blank=True)
    target_value = models.DecimalField(_("Target"), max_digits=12, decimal_places=2, null=True, blank=True)
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="goals", verbose_name=_("Project"))
    completed_at = models.DateTimeField(null=True, blank=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name, verbose_name_plural = _("Goal"), _("Goals")
        ordering = ["order", "target_date", "-created_at"]
        indexes = [models.Index(fields=["owner", "status"])]

    def __str__(self):
        return self.title

    @property
    def has_number(self):
        return self.target_value is not None and self.target_value != self.start_value

    def progress(self, steps=None, tasks=None):
        """0–100. `steps` / `tasks` are (done, total), when already counted."""
        if self.status == GoalStatus.DONE:
            return 100
        if self.has_number:
            now = self.current_value if self.current_value is not None else self.start_value
            pct = float((now - self.start_value) / (self.target_value - self.start_value) * 100)
            return max(0, min(100, round(pct)))
        for done, total in (steps, tasks):
            if total:
                return round(100 * done / total)
        return 0

    def days_left(self, today=None):
        if not self.target_date:
            return None
        return (self.target_date - (today or timezone.localdate())).days


class GoalStep(models.Model):
    """A milestone on the way to a goal."""

    goal = models.ForeignKey(Goal, on_delete=models.CASCADE, related_name="steps")
    text = models.CharField(max_length=300)
    done = models.BooleanField(default=False)
    done_at = models.DateTimeField(null=True, blank=True)
    order = models.FloatField(default=0)

    class Meta:
        ordering = ["order", "pk"]

    def __str__(self):
        return self.text


# ── Learning: books, courses, talks and docs ──────────────────────────────
class LearningKind(models.TextChoices):
    BOOK = "book", _("Book")
    COURSE = "course", _("Course")
    VIDEO = "video", _("Video / talk")
    ARTICLE = "article", _("Article / blog")
    DOCS = "docs", _("Docs / tutorial")
    PODCAST = "podcast", _("Podcast")
    PAPER = "paper", _("Paper")
    OTHER = "other", _("Other")


class LearningStatus(models.TextChoices):
    QUEUED = "queued", _("Want to")
    ACTIVE = "active", _("In progress")
    DONE = "done", _("Finished")
    DROPPED = "dropped", _("Dropped")


class LearningUnit(models.TextChoices):
    PAGES = "pages", _("pages")
    CHAPTERS = "chapters", _("chapters")
    LESSONS = "lessons", _("lessons")
    VIDEOS = "videos", _("videos")
    MINUTES = "minutes", _("minutes")
    PERCENT = "percent", _("%")


class LearningItem(models.Model):
    owner = models.ForeignKey(**OWNER)
    title = models.CharField(_("Title"), max_length=250)
    kind = models.CharField(_("Kind"), max_length=10, choices=LearningKind.choices, default=LearningKind.BOOK)
    url = models.URLField(_("Link"), max_length=500, blank=True)
    author = models.CharField(_("Author / source"), max_length=150, blank=True)
    status = models.CharField(_("Status"), max_length=10, choices=LearningStatus.choices, default=LearningStatus.QUEUED, db_index=True)
    unit = models.CharField(_("Progress in"), max_length=10, choices=LearningUnit.choices, default=LearningUnit.PAGES)
    progress = models.PositiveIntegerField(_("Done so far"), default=0)
    total = models.PositiveIntegerField(_("Out of"), null=True, blank=True, help_text=_("Pages in the book, lessons in the course…"))
    rating = models.PositiveSmallIntegerField(_("Rating"), null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)])
    takeaways = models.TextField(_("Takeaways"), blank=True, help_text=_("What you learnt, in your own words. Markdown works."))
    tags = models.ManyToManyField(Tag, blank=True, related_name="learning", verbose_name=_("Tags"))
    goal = models.ForeignKey(Goal, on_delete=models.SET_NULL, null=True, blank=True, related_name="learning", verbose_name=_("Goal"))
    started_on = models.DateField(_("Started"), null=True, blank=True)
    finished_on = models.DateField(_("Finished"), null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name, verbose_name_plural = _("Learning item"), _("Learning")
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["owner", "status"])]

    def __str__(self):
        return self.title

    @property
    def percent(self):
        if self.status == LearningStatus.DONE:
            return 100
        if self.unit == LearningUnit.PERCENT:
            return min(self.progress, 100)
        return min(round(100 * self.progress / self.total), 100) if self.total else 0

    @property
    def link_label(self):
        return link_label(self.url)


# ── Diagrams: mind maps, system design boards and text diagrams ─────────────
class DiagramKind(models.TextChoices):
    MINDMAP = "mindmap", _("Mind map")
    SYSTEM = "system", _("System design")
    FLOWCHART = "flowchart", _("Flowchart")
    SEQUENCE = "sequence", _("Sequence diagram")
    ER = "er", _("Database (ER) diagram")
    CLASS = "class", _("Class diagram")
    STATE = "state", _("State diagram")
    GANTT = "gantt", _("Gantt chart")
    TIMELINE = "timeline", _("Timeline")
    JOURNEY = "journey", _("User journey")
    C4 = "c4", _("C4 context")
    ARCHITECTURE = "architecture", _("Cloud architecture")
    BLOCK = "block", _("Block diagram")
    GITGRAPH = "gitgraph", _("Git branches")
    PIE = "pie", _("Pie chart")
    QUADRANT = "quadrant", _("Priority matrix")
    XYCHART = "xychart", _("Bar & line chart")
    SANKEY = "sankey", _("Sankey (flows)")


# Drawn with the mouse or a finger (their shapes are kept in `data`); every
# other kind is written as Mermaid text (`source`) and drawn by the browser.
VISUAL_KINDS = (DiagramKind.MINDMAP, DiagramKind.SYSTEM)


class Diagram(models.Model):
    owner = models.ForeignKey(**OWNER)
    title = models.CharField(_("Title"), max_length=200)
    kind = models.CharField(_("Kind"), max_length=12, choices=DiagramKind.choices, default=DiagramKind.MINDMAP)
    source = models.TextField(_("Diagram text"), blank=True, help_text="Mermaid text, for the written kinds.")
    data = models.JSONField(default=dict, blank=True, help_text="Nodes and links, for mind maps and system design boards.")
    notes = models.TextField(_("Notes"), blank=True, help_text=_("Requirements, decisions, trade-offs… Markdown works."))
    preview = models.TextField(blank=True, help_text="An SVG picture of the diagram, drawn by the browser on save, for the list.")
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="diagrams", verbose_name=_("Project"))
    is_pinned = models.BooleanField(_("Pinned"), default=False)
    is_archived = models.BooleanField(_("Archived"), default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        verbose_name, verbose_name_plural = _("Diagram"), _("Diagrams")
        ordering = ["-is_pinned", "-updated_at"]
        indexes = [models.Index(fields=["owner", "is_archived", "kind"])]

    def __str__(self):
        return self.title

    @property
    def is_visual(self):
        return self.kind in VISUAL_KINDS


class DiagramVersion(models.Model):
    """An earlier state of a diagram, kept so it can be brought back: taken
    by itself before a new round of editing, or on purpose with a name."""
    diagram = models.ForeignKey(Diagram, on_delete=models.CASCADE, related_name="versions")
    name = models.CharField(_("Name"), max_length=120, blank=True, help_text="Given by hand; empty for automatic copies.")
    title = models.CharField(max_length=200)
    source = models.TextField(blank=True)
    data = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)
    preview = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return self.name or f"{self.title} @ {self.created_at:%Y-%m-%d %H:%M}"


def note_image_path(instance, filename):
    import uuid
    ext = os.path.splitext(filename)[1].lower()[:6] or ".png"
    return f"work/images/{instance.owner_id}/{uuid.uuid4().hex}{ext}"


class NoteImage(models.Model):
    """A picture pasted or dropped into a note. Served only to its owner
    (views.note_image_view), never as a public media address."""
    owner = models.ForeignKey(**OWNER)
    note = models.ForeignKey(Note, on_delete=models.SET_NULL, null=True, blank=True, related_name="images")
    file = models.FileField(upload_to=note_image_path)
    name = models.CharField(max_length=200, blank=True)
    size = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name or self.file.name


class NoteVersion(models.Model):
    """An earlier state of a note, kept before each new round of editing (see services.remember_note)."""
    note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name="versions")
    title = models.CharField(max_length=200, blank=True)
    body = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"{self.title or self.note_id} @ {self.created_at:%Y-%m-%d %H:%M}"


# ── Flashcards: remember what you learn (spaced repetition) ─────────────────
class Deck(models.Model):
    owner = models.ForeignKey(**OWNER)
    name = models.CharField(_("Name"), max_length=120)
    color = models.CharField(_("Colour"), max_length=10, choices=Color.choices, default=Color.TEAL)
    description = models.TextField(_("About this deck"), blank=True)
    learning = models.ForeignKey(LearningItem, on_delete=models.SET_NULL, null=True, blank=True, related_name="decks",
                                 verbose_name=_("From what you're learning"))
    new_per_day = models.PositiveSmallIntegerField(_("New cards a day"), default=20, validators=[MaxValueValidator(500)],
                                                   help_text=_("How many cards you haven't seen yet come up each day."))
    is_archived = models.BooleanField(_("Archived"), default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name, verbose_name_plural = _("Deck"), _("Decks")
        ordering = ["is_archived", "name"]

    def __str__(self):
        return self.name


class Card(models.Model):
    """One question and its answer. `due`, `interval` (days) and `ease` say
    when it comes up next: sooner when it was hard, later when it was easy."""
    owner = models.ForeignKey(**OWNER)
    deck = models.ForeignKey(Deck, on_delete=models.CASCADE, related_name="cards", verbose_name=_("Deck"))
    front = models.TextField(_("Question"))
    back = models.TextField(_("Answer"), blank=True)
    due = models.DateField(_("Next review"), default=timezone.localdate, db_index=True)
    interval = models.PositiveIntegerField(default=0, help_text="Days until the next review.")
    ease = models.FloatField(default=2.5)
    reps = models.PositiveIntegerField(default=0, help_text="Times answered right in a row.")
    lapses = models.PositiveIntegerField(default=0, help_text="Times forgotten.")
    last_reviewed = models.DateTimeField(null=True, blank=True)
    is_suspended = models.BooleanField(_("Paused"), default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name, verbose_name_plural = _("Flashcard"), _("Flashcards")
        ordering = ["due", "pk"]
        indexes = [models.Index(fields=["owner", "is_suspended", "due"])]

    def __str__(self):
        return self.front[:60]

    @property
    def is_new(self):
        return self.last_reviewed is None


class CardReview(models.Model):
    """One answer in a review: kept for the streak and the "how am I doing" numbers."""
    owner = models.ForeignKey(**OWNER)
    card = models.ForeignKey(Card, on_delete=models.CASCADE, related_name="reviews")
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(4)])
    interval = models.PositiveIntegerField(default=0)
    before = models.JSONField(default=dict, blank=True, help_text="The card's schedule before this answer, so it can be undone.")
    reviewed_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-reviewed_at"]
