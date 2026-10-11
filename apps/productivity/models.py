"""Productivity: time tracking, tasks, focus sessions, notes, snippets,
habits and a daily journal. Everything belongs to one person (`owner`) and
nobody else sees it — not even other admins.
"""
from datetime import timedelta

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
    repeat = models.CharField(_("Repeat"), max_length=10, choices=Repeat.choices, default=Repeat.NONE, blank=True)
    tags = models.ManyToManyField(Tag, blank=True, related_name="tasks", verbose_name=_("Tags"))
    order = models.FloatField(default=0, help_text="Position in its column (smaller first).")
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "-priority", "created_at"]
        indexes = [models.Index(fields=["owner", "status"]), models.Index(fields=["owner", "due_date"])]

    def __str__(self):
        return self.title

    @property
    def is_done(self):
        return self.status == Status.DONE

    def is_overdue(self, today=None):
        return bool(self.due_date and not self.is_done and self.due_date < (today or timezone.localdate()))


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
    tags = models.ManyToManyField(Tag, blank=True, related_name="entries", verbose_name=_("Tags"))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
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

    def __str__(self):
        return f"Work settings for {self.owner}"

    @classmethod
    def for_user(cls, user):
        obj, _created = cls.objects.get_or_create(owner=user)
        return obj

    def is_work_day(self, day):
        return str(day.weekday()) in self.work_days

    def week_of(self, day):
        """(first, last) day of the week `day` is in."""
        first = day - timedelta(days=(day.weekday() - self.week_start) % 7)
        return first, first + timedelta(days=6)
