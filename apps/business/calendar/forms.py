from django import forms
from django.utils.translation import gettext_lazy as _

from apps.business.core.crud import BusinessForm

from .models import CalendarEvent, Repeat


class EventForm(BusinessForm):
    unique_name = ()
    layout = [("title",), ("date", "time"), ("category", "pond"), ("#", _("Longer or repeating")), ("end_date",),
              ("repeat", "repeat_until"), ("#", _("Notes")), ("notes",)]
    tips = {
        "end_date": _("For something that lasts several days, like drying a pond. Leave empty for one day."),
        "repeat": _("“Bangla date” repeats keep the same Bangla day, e.g. every 1 Boishakh, or the 1st of every Bangla month."),
        "repeat_until": _("Leave empty to repeat for ever."),
        "category": _("Sets the colour. “To do” items get a tick box and stay on the home page until they're done."),
    }

    class Meta:
        model = CalendarEvent
        fields = ["title", "date", "time", "category", "pond", "end_date", "repeat", "repeat_until", "notes"]
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": _("e.g. Lime the east pond, Pay pond lease, Eid-ul-Adha")}),
            "date": forms.DateInput(), "end_date": forms.DateInput(), "repeat_until": forms.DateInput(),
            "time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.business.ponds.models import Pond

        self.fields["pond"].queryset = Pond.objects.filter(business=self.business)
        self.fields["pond"].empty_label = _("Not for one pond")
        self.fields["pond"].biz_quick_add = "pond"
        self.fields["repeat"].choices = Repeat.choices
        self.fields["time"].widget.attrs["class"] = "form-input"

    def clean(self):
        data = super().clean()
        start, end = data.get("date"), data.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", _("This has to be on or after the start date."))
        if data.get("repeat") and end:
            self.add_error("end_date", _("A repeating event can only be one day long."))
        if data.get("repeat_until") and start and data["repeat_until"] < start:
            self.add_error("repeat_until", _("This has to be after the first date."))
        if not data.get("repeat"):
            data["repeat_until"] = None
        return data
