from datetime import datetime, timedelta

from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from . import services
from .models import Habit, Project, Snippet, Tag, Task, TimeEntry, WorkSettings

DATE = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
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
        if "tags_text" in self.fields and self.instance.pk:
            self.fields["tags_text"].initial = " ".join(self.instance.tags.values_list("name", flat=True))

    def save_tags(self, obj):
        if "tags_text" in self.cleaned_data:
            obj.tags.set(services.tags_named(self.owner, self.cleaned_data["tags_text"]))


class TaskForm(OwnedForm):
    tags_text = TagsField()

    class Meta:
        model = Task
        fields = ("title", "project", "status", "priority", "due_date", "estimate_minutes", "repeat", "remind_at", "notes")
        widgets = {
            "due_date": DATE,
            "remind_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "notes": forms.Textarea(attrs={"rows": 8, "data-markdown": "1"}),
            "estimate_minutes": forms.NumberInput(attrs={"inputmode": "numeric", "min": 0, "step": 5}),
        }


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ("name", "color", "client", "estimate_hours", "hourly_rate", "description", "is_archived")
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

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
                  "notifications", "long_timer_hours", "default_project")
        widgets = {"volume": forms.NumberInput(attrs={"type": "range", "min": 0, "max": 100, "step": 5})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["default_project"].queryset = Project.objects.filter(owner=self.instance.owner, is_archived=False)
        self.fields["work_day_list"].initial = list(self.instance.work_days)
        self.fields["daily_target_hours"].initial = round(self.instance.daily_target_minutes / 60, 2)

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
