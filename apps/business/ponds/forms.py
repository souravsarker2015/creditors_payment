from django import forms
from django.utils.translation import gettext_lazy as _

from apps.business.core.crud import BusinessForm, money_field
from apps.business.core.models import Unit

from .models import Ownership, Pond

MAX_PHOTO_MB = 5


class PondForm(BusinessForm):
    layout = [
        ("name", "code"), ("location",), ("area", "area_unit"), ("depth_ft", "status"),
        ("#", _("Ownership")), ("ownership",), ("lease_from", "lease_amount"), ("lease_start", "lease_end"),
        ("#", _("Photo and notes")), ("photo",), ("notes",),
    ]

    class Meta:
        model = Pond
        fields = ["name", "code", "location", "area", "area_unit", "depth_ft", "status", "ownership",
                  "lease_from", "lease_amount", "lease_start", "lease_end", "photo", "notes"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": _("e.g. Big pond (east)")}),
            "location": forms.TextInput(attrs={"placeholder": _("Village / mouza, landmark")}),
            "lease_start": forms.DateInput(), "lease_end": forms.DateInput(),
            "ownership": forms.RadioSelect,
            "photo": forms.ClearableFileInput(attrs={"accept": "image/*", "class": "form-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["area_unit"].queryset = Unit.objects.filter(business=self.business, unit_type="area")
        self.fields["area_unit"].empty_label = None
        if not self.instance.pk:
            self.initial.setdefault("area_unit", Unit.objects.filter(business=self.business, symbol="dec").first())
        money_field(self.fields["lease_amount"])
        self.fields["lease_amount"].help_text = _("For the whole lease period.")

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if photo and hasattr(photo, "size") and photo.size > MAX_PHOTO_MB * 1024 * 1024:
            raise forms.ValidationError(_("Please use a photo under %(mb)s MB.") % {"mb": MAX_PHOTO_MB})
        return photo

    def clean(self):
        data = super().clean()
        if data.get("ownership") != Ownership.LEASED:
            data["lease_from"], data["lease_amount"], data["lease_start"], data["lease_end"] = "", None, None, None
        elif data.get("lease_start") and data.get("lease_end") and data["lease_end"] <= data["lease_start"]:
            self.add_error("lease_end", _("The lease has to end after it starts."))
        return data
