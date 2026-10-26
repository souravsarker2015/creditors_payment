import json
from datetime import datetime, timedelta

from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from . import services
from .models import Deck, ExamSubject, Goal, GoalStatus, Habit, LearningItem, LearningStatus, PrepSection, PrepTopic, Project, Question, QuestionKind, Snippet, Sprint, Tag, Task, TaskKind, TimeEntry, WorkSettings

DATE = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
SWATCHES = forms.RadioSelect   # colours are picked from swatches (templates: .w-swatches)
WEEKDAY_CHOICES = [("0", _("Mon")), ("1", _("Tue")), ("2", _("Wed")), ("3", _("Thu")), ("4", _("Fri")), ("5", _("Sat")), ("6", _("Sun"))]


class TagsField(forms.CharField):
    """Tags typed as words: "backend, urgent review" → three tags."""

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("label", _("Tags"))
        kwargs.setdefault("help_text", _("Separate with commas or spaces."))
        super().__init__(**kwargs)

    def to_python(self, value):
        value = super().to_python(value) or ""
        return [w.strip().lstrip("#").lower()[:40] for w in value.replace(",", " ").split() if w.strip().lstrip("#")]


class OwnedForm(forms.ModelForm):
    """A form whose pickers only offer the person's own projects and tasks."""

    def __init__(self, *args, owner=None, **kwargs):
        self.owner = owner
        super().__init__(*args, **kwargs)
        if "project" in self.fields:
            self.fields["project"].queryset = Project.objects.filter(owner=owner, is_archived=False)
        if "task" in self.fields:
            self.fields["task"].queryset = Task.objects.filter(owner=owner).exclude(status="done").order_by("-updated_at")
        if "goal" in self.fields:
            goals = Goal.objects.filter(owner=owner)
            self.fields["goal"].queryset = goals.filter(status=GoalStatus.ACTIVE) | goals.filter(pk=getattr(self.instance, "goal_id", None) or 0)
        if "sprint" in self.fields:
            sprints = Sprint.objects.filter(owner=owner)
            self.fields["sprint"].queryset = (sprints.filter(completed_at__isnull=True) | sprints.filter(pk=getattr(self.instance, "sprint_id", None) or 0)).order_by("start_date")
            self.fields["sprint"].empty_label = _("— Not in a sprint —")
        if "tags_text" in self.fields and self.instance.pk:
            self.fields["tags_text"].initial = " ".join(self.instance.tags.values_list("name", flat=True))

    def save_tags(self, obj):
        if "tags_text" in self.cleaned_data:
            obj.tags.set(services.tags_named(self.owner, self.cleaned_data["tags_text"]))


class TaskForm(OwnedForm):
    tags_text = TagsField()
    repeat_on = forms.MultipleChoiceField(label=_("On these days"), choices=WEEKDAY_CHOICES, required=False, widget=forms.CheckboxSelectMultiple,
                                          help_text=_("Leave empty to repeat on the same weekday as the due date."))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["scheduled_at"].help_text = _("A block on your day planner, as long as the estimate (else 30 minutes).")
        self.fields["repeat_every"].required = False      # left out: once each day / week / month
        self.fields["kind"].required = False              # left out: kept as it was (a plain task when new)
        parents = Task.objects.filter(owner=self.owner, parent__isnull=True).exclude(status="done")
        if self.instance.pk:
            parents = parents.exclude(pk=self.instance.pk)
        self.fields["parent"].queryset = parents.order_by("-updated_at") | Task.objects.filter(pk=getattr(self.instance, "parent_id", None) or 0)
        self.fields["parent"].empty_label = _("— Not a subtask —")
        if self.instance.pk and self.instance.repeat_days:
            self.fields["repeat_on"].initial = [x for x in self.instance.repeat_days.split(",") if x]

    class Meta:
        model = Task
        fields = ("title", "parent", "project", "sprint", "status", "kind", "points", "priority", "start_date", "due_date", "estimate_minutes", "repeat", "repeat_every", "repeat_from_done",
                  "remind_at", "scheduled_at", "link", "goal", "waiting_for", "notes")
        widgets = {
            "link": forms.URLInput(attrs={"placeholder": "https://github.com/…/pull/482", "inputmode": "url"}),
            "start_date": DATE,
            "repeat_every": forms.NumberInput(attrs={"inputmode": "numeric", "min": 1, "max": 99}),
            "due_date": DATE,
            "remind_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "scheduled_at": forms.DateTimeInput(attrs={"type": "datetime-local", "step": 900}, format="%Y-%m-%dT%H:%M"),
            "notes": forms.Textarea(attrs={"rows": 8, "data-markdown": "1"}),
            "estimate_minutes": forms.NumberInput(attrs={"inputmode": "numeric", "min": 0, "step": 5}),
            "points": forms.NumberInput(attrs={"inputmode": "numeric", "min": 0, "max": 100, "list": "story-points"}),
        }

    def clean(self):
        data = super().clean()
        start, due = data.get("start_date"), data.get("due_date")
        if start and due and start > due:
            self.add_error("start_date", _("The start can't be after the due date."))
        if not data.get("repeat_every"):
            data["repeat_every"] = 1
        if not data.get("kind"):
            data["kind"] = self.instance.kind or TaskKind.TASK
        parent = data.get("parent")
        if parent and not services.can_be_parent(self.instance, parent):
            self.add_error("parent", _("Subtasks go one level deep: pick a task that isn't a subtask, and this one can't have subtasks of its own."))
        return data

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.repeat_days = ",".join(sorted(self.cleaned_data.get("repeat_on") or [])) if obj.repeat == "weekly" else ""
        obj.repeat_every = obj.repeat_every or 1
        if commit:
            obj.save()
        return obj


class SprintForm(forms.ModelForm):
    class Meta:
        model = Sprint
        fields = ("name", "goal", "start_date", "end_date")
        widgets = {"start_date": DATE, "end_date": DATE}

    def clean(self):
        data = super().clean()
        start, end = data.get("start_date"), data.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", _("The sprint has to end after it starts."))
        elif start and end and (end - start).days > 90:
            self.add_error("end_date", _("Keep a sprint to three months at most — a few weeks works best."))
        return data


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ("name", "color", "client", "repo_url", "estimate_hours", "hourly_rate", "description", "is_archived")
        widgets = {"description": forms.Textarea(attrs={"rows": 3}), "color": SWATCHES,
                   "repo_url": forms.URLInput(attrs={"placeholder": "https://github.com/acme/web", "spellcheck": "false", "autocapitalize": "off"})}

    def __init__(self, *args, owner=None, **kwargs):
        self.owner = owner
        super().__init__(*args, **kwargs)

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if Project.objects.filter(owner=self.owner, name__iexact=name).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(_("You already have a project with this name."))
        return name


class EntryForm(OwnedForm):
    """A time entry added or fixed by hand: date, start and end (or a length)."""

    tags_text = TagsField()
    day = forms.DateField(label=_("Date"), widget=DATE)
    start = forms.TimeField(label=_("Start"), widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))
    end = forms.TimeField(label=_("End"), required=False, widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
                          help_text=_("Or leave empty and give the length."))
    minutes = forms.IntegerField(label=_("Length (minutes)"), required=False, min_value=1, max_value=24 * 60)

    class Meta:
        model = TimeEntry
        fields = ("description", "task", "project", "billable")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        e = self.instance
        if e.pk:
            start = timezone.localtime(e.started_at)
            self.fields["day"].initial, self.fields["start"].initial = start.date(), start.time().replace(second=0, microsecond=0)
            if e.ended_at:
                self.fields["end"].initial = timezone.localtime(e.ended_at).time().replace(second=0, microsecond=0)
                self.fields["minutes"].initial = max(e.seconds // 60, 1)
        else:
            now = timezone.localtime()
            self.fields["day"].initial = now.date()
            self.fields["start"].initial = (now - timedelta(hours=1)).time().replace(second=0, microsecond=0)
            self.fields["end"].initial = now.time().replace(second=0, microsecond=0)
        self.order_fields(["description", "task", "project", "day", "start", "end", "minutes", "tags_text", "billable"])

    def clean(self):
        data = super().clean()
        day, start, end, minutes = data.get("day"), data.get("start"), data.get("end"), data.get("minutes")
        if not (day and start):
            return data
        tz = timezone.get_current_timezone()
        begin = timezone.make_aware(datetime.combine(day, start), tz)
        if end:
            finish = timezone.make_aware(datetime.combine(day, end), tz)
            if finish <= begin:          # past midnight
                finish += timedelta(days=1)
        elif minutes:
            finish = begin + timedelta(minutes=minutes)
        elif self.instance.pk and self.instance.is_running:
            finish = None
        else:
            raise forms.ValidationError(_("Give an end time or how many minutes."))
        if finish and finish - begin > timedelta(hours=24):
            raise forms.ValidationError(_("One entry can't be longer than 24 hours."))
        if begin > timezone.now() + timedelta(minutes=1):
            raise forms.ValidationError(_("That start time is in the future."))
        data["started_at"], data["ended_at"] = begin, finish
        return data

    def save(self, commit=True):
        entry = super().save(commit=False)
        entry.owner = self.owner
        entry.started_at, entry.ended_at = self.cleaned_data["started_at"], self.cleaned_data["ended_at"]
        if entry.task_id and not entry.project_id:
            entry.project_id = entry.task.project_id
        if not entry.pk:
            entry.kind = "manual"
        if commit:
            entry.save()
            self.save_tags(entry)
        return entry


class SnippetForm(OwnedForm):
    tags_text = TagsField()

    class Meta:
        model = Snippet
        fields = ("title", "language", "code", "description", "is_favorite")
        widgets = {
            "code": forms.Textarea(attrs={"rows": 14, "spellcheck": "false", "class": "code-input", "autocapitalize": "off", "autocomplete": "off"}),
            "description": forms.Textarea(attrs={"rows": 2}),
        }


class HabitForm(forms.ModelForm):
    day_list = forms.MultipleChoiceField(label=_("On these days"), choices=WEEKDAY_CHOICES, widget=forms.CheckboxSelectMultiple,
                                         initial=[c for c, _l in WEEKDAY_CHOICES])

    class Meta:
        model = Habit
        fields = ("name", "emoji", "color")
        widgets = {"color": SWATCHES}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["day_list"].initial = list(self.instance.days)

    def save(self, commit=True):
        habit = super().save(commit=False)
        habit.days = "".join(sorted(self.cleaned_data["day_list"]))
        if commit:
            habit.save()
        return habit


class SettingsForm(forms.ModelForm):
    work_day_list = forms.MultipleChoiceField(label=_("Work days"), choices=WEEKDAY_CHOICES, widget=forms.CheckboxSelectMultiple)
    daily_target_hours = forms.DecimalField(label=_("Daily target (hours)"), min_value=0.25, max_value=24, decimal_places=2,
                                            help_text=_("Tracked time you aim for on a work day."))

    class Meta:
        model = WorkSettings
        fields = ("week_start", "focus_minutes", "short_break_minutes", "long_break_minutes", "long_break_every",
                  "auto_start_breaks", "auto_start_focus", "sound_enabled", "sound", "volume", "tick_sound",
                  "notifications", "long_timer_hours", "idle_minutes", "default_project", "day_start", "day_end", "cards_remind_at",
                  "daily_email", "reminder_emails", "wip_limit", "invoice_from", "currency", "key_prefix", "branch_format")
        widgets = {"invoice_from": forms.Textarea(attrs={"rows": 4, "placeholder": _("Your name\nAddress\nPhone\nPay to: bank account or bKash number")}),
                   "volume": forms.NumberInput(attrs={"type": "range", "min": 0, "max": 100, "step": 5}),
                   "day_start": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
                   "cards_remind_at": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
                   "day_end": forms.TimeInput(attrs={"type": "time"}, format="%H:%M")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("day_start", "day_end", "currency", "key_prefix", "branch_format"):      # left empty: keep what it was
            self.fields[name].required = False
        self.fields["default_project"].queryset = Project.objects.filter(owner=self.instance.owner, is_archived=False)
        self.fields["work_day_list"].initial = list(self.instance.work_days)
        self.fields["daily_target_hours"].initial = round(self.instance.daily_target_minutes / 60, 2)

    def clean(self):
        data = super().clean()
        start = data.get("day_start") or self.instance.day_start
        end = data.get("day_end") or self.instance.day_end
        data["day_start"], data["day_end"] = start, end
        data["currency"] = (data.get("currency") or "").strip() or self.instance.currency or "৳"
        data["key_prefix"] = (data.get("key_prefix") or self.instance.key_prefix or "T").upper()
        data["branch_format"] = (data.get("branch_format") or "").strip() or self.instance.branch_format or "{type}/{key}-{slug}"
        if "{key}" not in data["branch_format"] and "{id}" not in data["branch_format"]:
            self.add_error("branch_format", _("Put {key} or {id} in it, so the branch can be traced back to its task."))
        if start and end and end <= start:
            self.add_error("day_end", _("The day has to end after it starts."))
        return data

    def save(self, commit=True):
        s = super().save(commit=False)
        s.work_days = "".join(sorted(self.cleaned_data["work_day_list"]))
        s.daily_target_minutes = int(round(float(self.cleaned_data["daily_target_hours"]) * 60))
        if commit:
            s.save()
        return s


class TagForm(forms.ModelForm):
    class Meta:
        model = Tag
        fields = ("name", "color")


class GoalForm(OwnedForm):
    class Meta:
        model = Goal
        fields = ("title", "area", "color", "target_date", "project", "unit", "start_value", "target_value", "current_value", "why")
        widgets = {
            "color": SWATCHES,
            "target_date": DATE,
            "why": forms.Textarea(attrs={"rows": 4}),
            "title": forms.TextInput(attrs={"placeholder": _("Become a senior engineer by next June")}),
            "unit": forms.TextInput(attrs={"placeholder": _("books, problems solved, users…")}),
        }

    def clean(self):
        data = super().clean()
        if data.get("target_value") is not None and data.get("target_value") == data.get("start_value"):
            self.add_error("target_value", _("The target has to be different from where you start."))
        return data


class LearningForm(OwnedForm):
    tags_text = TagsField()

    class Meta:
        model = LearningItem
        fields = ("title", "kind", "author", "url", "status", "unit", "progress", "total", "rating", "goal", "started_on", "finished_on", "takeaways")
        widgets = {
            "started_on": DATE, "finished_on": DATE,
            "takeaways": forms.Textarea(attrs={"rows": 8}),
            "url": forms.URLInput(attrs={"inputmode": "url", "placeholder": "https://"}),
            "progress": forms.NumberInput(attrs={"inputmode": "numeric", "min": 0}),
            "total": forms.NumberInput(attrs={"inputmode": "numeric", "min": 1}),
            "rating": forms.Select(choices=[("", "—"), (1, "★"), (2, "★★"), (3, "★★★"), (4, "★★★★"), (5, "★★★★★")]),
        }

    def clean(self):
        data = super().clean()
        today = timezone.localdate()
        if data.get("status") == LearningStatus.DONE and not data.get("finished_on"):
            data["finished_on"] = today
        if data.get("status") in (LearningStatus.ACTIVE, LearningStatus.DONE) and not data.get("started_on"):
            data["started_on"] = data.get("finished_on") or today
        if data.get("status") == LearningStatus.DONE and data.get("total"):
            data["progress"] = max(data.get("progress") or 0, data["total"])
        return data


class DeckForm(OwnedForm):
    class Meta:
        model = Deck
        fields = ("name", "color", "description", "learning", "new_per_day")
        widgets = {
            "color": SWATCHES,
            "name": forms.TextInput(attrs={"placeholder": _("System design, Spanish words, AWS exam…")}),
            "description": forms.Textarea(attrs={"rows": 2}),
            "new_per_day": forms.NumberInput(attrs={"inputmode": "numeric", "min": 0, "max": 500}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["learning"].queryset = LearningItem.objects.filter(owner=self.owner).order_by("-updated_at")


# ── Interview prep ────────────────────────────────────────────────────────
class PrepTopicForm(forms.ModelForm):
    class Meta:
        model = PrepTopic
        fields = ("name", "code", "color", "description")
        widgets = {"color": SWATCHES}

    def __init__(self, *args, owner=None, **kwargs):
        self.owner = owner
        super().__init__(*args, **kwargs)

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if PrepTopic.objects.filter(owner=self.owner, name__iexact=name).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(_("You already have a topic with this name."))
        return name


class ExamSubjectForm(forms.ModelForm):
    class Meta:
        model = ExamSubject
        fields = ("name", "exam_date", "color")
        widgets = {"exam_date": DATE, "color": SWATCHES}

    def __init__(self, *args, owner=None, **kwargs):
        self.owner = owner
        super().__init__(*args, **kwargs)

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if ExamSubject.objects.filter(owner=self.owner, name__iexact=name).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(_("You already have a subject with this name."))
        return name


class QuestionForm(forms.ModelForm):
    """A question. Choices come from the page's editor as JSON; a new topic can be typed in place."""
    tags_text = TagsField()
    new_topic = forms.CharField(label=_("…or a new topic"), max_length=80, required=False)
    new_section = forms.CharField(label=_("…or a new section"), max_length=120, required=False)
    options_json = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = Question
        fields = ("topic", "section", "kind", "difficulty", "level", "prompt", "hints", "answer", "key_points", "explanation", "language", "starter", "tests",
                  "companies", "source", "notes", "is_starred")
        widgets = {
            "prompt": forms.Textarea(attrs={"rows": 5, "data-paste-images": "1"}),
            "answer": forms.Textarea(attrs={"rows": 8, "data-paste-images": "1"}),
            "key_points": forms.Textarea(attrs={"rows": 4, "placeholder": _("Mentions the trade-off\nGives the complexity\nNames an example")}),
            "explanation": forms.Textarea(attrs={"rows": 3}),
            "starter": forms.Textarea(attrs={"rows": 4, "spellcheck": "false"}),
            "tests": forms.Textarea(attrs={"rows": 4, "spellcheck": "false", "placeholder": "assert two_sum([2, 7, 11, 15], 9) == [0, 1]"}),
            "hints": forms.Textarea(attrs={"rows": 3, "placeholder": _("Think about a hash map\nWhat do you need to remember as you go?")}),
            "notes": forms.Textarea(attrs={"rows": 3}),
            "language": forms.TextInput(attrs={"list": "prep-languages", "placeholder": "python"}),
            "companies": forms.TextInput(attrs={"placeholder": "Google, Amazon"}),
            "source": forms.URLInput(attrs={"placeholder": "https://leetcode.com/problems/…", "inputmode": "url"}),
        }

    def __init__(self, *args, owner=None, **kwargs):
        self.owner = owner
        super().__init__(*args, **kwargs)
        self.fields["topic"].queryset = PrepTopic.objects.filter(owner=owner)
        self.fields["topic"].required = False
        self.fields["topic"].empty_label = _("— Pick a topic —")
        self.fields["section"].queryset = PrepSection.objects.filter(owner=owner).select_related("topic").order_by("topic__order", "topic__name", "order", "pk")
        self.fields["section"].empty_label = _("— Not in a section —")
        self.fields["section"].label_from_instance = lambda s: f"{s.topic.name} › {s.name}"
        self.fields["level"].required = False
        if self.instance.pk:
            self.fields["tags_text"].initial = " ".join(self.instance.tags.values_list("name", flat=True))
        self.fields["options_json"].initial = json.dumps(self.instance.options or [], ensure_ascii=False)

    def clean(self):
        data = super().clean()
        if not data.get("topic") and not (data.get("new_topic") or "").strip():
            self.add_error("new_topic", _("Pick a topic, or type a new one."))
        if data.get("section") and data.get("topic") and data["section"].topic_id != data["topic"].pk:
            data["section"] = None            # a section of another topic: the question goes outside the sections
        try:
            raw = json.loads(data.get("options_json") or "[]")
        except ValueError:
            raw = []
        options = [{"text": str(o.get("text", "")).strip()[:500], "correct": bool(o.get("correct"))}
                   for o in raw if isinstance(o, dict) and str(o.get("text", "")).strip()][:12]
        if data.get("kind") == QuestionKind.CHOICE:
            if len(options) < 2:
                self.add_error("kind", _("A multiple-choice question needs at least two choices."))
            elif not any(o["correct"] for o in options):
                self.add_error("kind", _("Tick the right choice (or choices)."))
        data["options"] = options if data.get("kind") == QuestionKind.CHOICE else []
        return data

    def save(self, commit=True):
        q = super().save(commit=False)
        q.owner = self.owner
        q.options = self.cleaned_data["options"]
        if not self.cleaned_data.get("topic"):
            name = self.cleaned_data["new_topic"].strip()[:80]
            q.topic = (PrepTopic.objects.filter(owner=self.owner, name__iexact=name).first()
                       or PrepTopic.objects.create(owner=self.owner, name=name, order=PrepTopic.objects.filter(owner=self.owner).count()))
        if (self.cleaned_data.get("new_section") or "").strip():
            from .prep import section_named

            q.section = section_named(q.topic, self.cleaned_data["new_section"])
        if q.section_id and q.section.topic_id != q.topic_id:
            q.section = None
        before = (self.initial.get("topic"), self.initial.get("section")) if self.instance.pk else None
        if before != (q.topic_id, q.section_id):          # new, or moved: to the end of its section
            from .prep import next_position

            q.order = next_position(q.topic, q.section)
        q.level = q.level or ""
        if commit:
            q.save()
            q.tags.set(services.tags_named(self.owner, self.cleaned_data.get("tags_text") or []))
        return q


class PrepGoalForm(forms.ModelForm):
    class Meta:
        model = WorkSettings
        fields = ("prep_exam", "prep_exam_date", "prep_new_per_day")
        widgets = {"prep_exam_date": DATE}
