from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import AutoSave, GoalEntry, SavingsGoal


class GoalForm(forms.ModelForm):
    class Meta:
        model = SavingsGoal
        fields = ["name", "target_amount", "target_date", "color", "note"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-input", "placeholder": _("e.g. Emergency fund, Eid shopping, New laptop")}),
            "target_amount": forms.NumberInput(attrs={"class": "form-input", "placeholder": "0", "min": "1", "step": "1"}),
            "target_date": forms.DateInput(attrs={"class": "form-input datepicker", "placeholder": _("No deadline")}),
            "color": forms.RadioSelect,
            "note": forms.Textarea(attrs={"class": "form-input", "rows": 2, "placeholder": _("Why this matters, where the money is kept…")}),
        }

    def clean_target_date(self):
        d = self.cleaned_data.get("target_date")
        # Allowed when editing an existing goal (the date may already be past),
        # not when setting up a new one.
        if d and not self.instance.pk and d < timezone.localdate():
            raise forms.ValidationError(_("Pick a date in the future."))
        return d


class EntryForm(forms.ModelForm):
    class Meta:
        model = GoalEntry
        fields = ["kind", "amount", "date", "note"]
        widgets = {
            "kind": forms.RadioSelect,
            "amount": forms.NumberInput(attrs={"class": "form-input", "placeholder": "0", "min": "1", "step": "any"}),
            "date": forms.DateInput(attrs={"class": "form-input datepicker"}),
            "note": forms.TextInput(attrs={"class": "form-input", "placeholder": _("Optional note")}),
        }

    def __init__(self, *args, goal=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.goal = goal
        if not self.is_bound and not self.instance.pk:
            self.initial.setdefault("date", timezone.localdate())
            self.initial.setdefault("kind", GoalEntry.DEPOSIT)

    def clean(self):
        data = super().clean()
        # Can't take out more than is in the pot.
        if self.goal and data.get("kind") == GoalEntry.WITHDRAW and data.get("amount"):
            from .services import progress
            available = progress(self.goal)["saved"]
            if self.instance.pk and self.instance.kind == GoalEntry.WITHDRAW:
                available += self.instance.amount
            elif self.instance.pk:
                available -= self.instance.amount
            if data["amount"] > available:
                self.add_error("amount", _("Only %(amount)s is in this goal.") % {"amount": f"৳{available:,.0f}"})
        return data


class AutoSaveForm(forms.ModelForm):
    class Meta:
        model = AutoSave
        fields = ["amount", "frequency", "next_run_date", "skip_weekend"]
        labels = {"next_run_date": _("First deposit on")}
        widgets = {
            "amount": forms.NumberInput(attrs={"class": "form-input", "placeholder": "0", "min": "1", "step": "1"}),
            "frequency": forms.Select(attrs={"class": "form-input"}),
            "next_run_date": forms.DateInput(attrs={"class": "form-input datepicker"}),
        }
        help_texts = {"skip_weekend": _("Handy when it matches a salary paid before the weekend.")}

    def __init__(self, *args, plan=None, **kwargs):
        super().__init__(*args, **kwargs)
        if plan:
            from apps.core.templatetags.ui import money
            self.fields["amount"].help_text = _("Your monthly plan is %(plan)s.") % {"plan": money(plan)}
        if self.instance.pk:
            self.fields["next_run_date"].label = _("Next deposit on")
            a = self.instance.amount
            if not self.is_bound and a == a.to_integral_value():
                self.initial["amount"] = int(a)  # "18000", not "18000.00"
        elif not self.is_bound:
            # Sensible defaults: the goal's monthly plan, starting on the 1st of next month.
            from .services import month_start
            self.initial.setdefault("amount", plan)
            self.initial.setdefault("next_run_date", month_start(timezone.localdate(), 1))

    def clean_next_run_date(self):
        d = self.cleaned_data["next_run_date"]
        if d < timezone.localdate():
            raise forms.ValidationError(_("Pick today or a later date. Past deposits can be added by hand."))
        return d
