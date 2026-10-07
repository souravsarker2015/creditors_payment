"""Starts on / Ends on for the repeating schedules (recurring expense and
income, goal auto-save).

`next_run_date` stays the schedule's own "next one" pointer. A new schedule
simply starts on its start date (the pointer is filled in for you); when
editing, the next date is shown and can still be moved. Older forms that send
only `next_run_date` keep working: it's taken as the start.
"""
from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

DATE_ATTRS = {"class": "form-input datepicker", "autocomplete": "off"}


class ScheduleDatesMixin:
    def setup_schedule_dates(self):
        f = self.fields
        f["start_date"].widget = forms.DateInput(attrs={**DATE_ATTRS, "placeholder": _("Select Date")}, format="%Y-%m-%d")
        f["end_date"].widget = forms.DateInput(attrs={**DATE_ATTRS, "placeholder": _("No end date")}, format="%Y-%m-%d")
        f["next_run_date"].required = False
        f["start_date"].required = True
        f["start_date"].label = _("Starts on")
        f["end_date"].label = _("Ends on")
        start, nxt = self.add_prefix("start_date"), self.add_prefix("next_run_date")
        if self.is_bound and not self.data.get(start) and self.data.get(nxt):
            # An older form (or app) that only knows the next date: that's where it starts.
            self.data = self.data.copy()
            self.data[start] = self.data[nxt]
        f["end_date"].help_text = _("Leave empty if it goes on. Nothing is created after this date.")
        if not self.instance.pk:
            f["next_run_date"].widget = forms.HiddenInput()
            if not self.is_bound:
                self.initial.setdefault("start_date", self.initial.get("next_run_date") or timezone.localdate())
        else:
            f["next_run_date"].label = _("Next date")
            f["next_run_date"].help_text = _("The next one is created on this date. You rarely need to change it.")
            if self.instance.start_date is None and not self.is_bound:
                self.initial["start_date"] = self.instance.next_run_date

    def clean_schedule_dates(self, data):
        start = data.get("start_date") or data.get("next_run_date") or getattr(self.instance, "start_date", None) or timezone.localdate()
        data["start_date"] = start
        if not self.instance.pk:
            data["next_run_date"] = start               # a new schedule begins on its start date
        else:
            nxt = data.get("next_run_date") or self.instance.next_run_date
            data["next_run_date"] = max(nxt, start)     # never before the start
        end = data.get("end_date")
        if end and end < start:
            self.add_error("end_date", _("The end date is before the start date."))
        return data
