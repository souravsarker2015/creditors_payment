from datetime import date

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.business.core.crud import BusinessForm, money_field
from apps.business.core.models import Unit
from apps.business.species.models import Species

from .models import CultureCycle, Harvest, Mortality, Ownership, Pond, SampleWeighing, Stocking

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


# ── Cycles and pond entries ─────────────────────────────────────────────────


class CycleForm(BusinessForm):
    unique_name = ()
    layout = [("start_date", "expected_harvest"), ("name",), ("notes",)]

    class Meta:
        model = CultureCycle
        fields = ["start_date", "expected_harvest", "name", "notes"]
        widgets = {"start_date": forms.DateInput(), "expected_harvest": forms.DateInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.initial.setdefault("start_date", date.today())

    def clean(self):
        data = super().clean()
        if data.get("start_date") and data.get("expected_harvest") and data["expected_harvest"] <= data["start_date"]:
            self.add_error("expected_harvest", _("Harvest has to come after the start."))
        return data


class EntryForm(BusinessForm):
    """A record inside one cycle (stocking, deaths, weighing, harvest, feeding)."""

    unique_name = ()

    def __init__(self, *args, cycle=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.cycle = cycle or getattr(self.instance, "cycle", None)
        if "date" in self.fields:
            self.fields["date"].widget = forms.DateInput(attrs={"class": "form-input datepicker", "autocomplete": "off"}, format="%Y-%m-%d")
            if not self.instance.pk:
                self.initial.setdefault("date", date.today())
        if "species" in self.fields:
            self.fields["species"].queryset = Species.objects.filter(business=self.business)
            self.fields["species"].empty_label = _("Choose fish…")
            self.fields["species"].biz_quick_add = "species"
            stocked = list(Stocking.objects.filter(cycle=self.cycle).values_list("species_id", flat=True).distinct()) if self.cycle else []
            if len(set(stocked)) == 1 and not self.instance.pk:
                self.initial.setdefault("species", stocked[0])

    def clean_date(self):
        d = self.cleaned_data["date"]
        if self.cycle and d < self.cycle.start_date:
            raise forms.ValidationError(_("This is before the cycle started (%(date)s).") % {"date": self.cycle.start_date.strftime("%d %b %Y")})
        if d > date.today():
            raise forms.ValidationError(_("This date is in the future."))
        return d


def _units(business, types):
    return Unit.objects.filter(business=business, unit_type__in=types)


class StockingForm(EntryForm):
    layout = [("date", "species"), ("count", "size"), ("weight", "weight_unit"), ("supplier",), ("cost", "paid_now"), ("notes",)]

    class Meta:
        model = Stocking
        fields = ["date", "species", "count", "size", "weight", "weight_unit", "supplier", "cost", "paid_now", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.business.parties.models import Party

        self.fields["weight_unit"].queryset = _units(self.business, ["weight"])
        self.fields["weight_unit"].empty_label = None
        self.fields["supplier"].queryset = Party.objects.filter(business=self.business, is_supplier=True)
        self.fields["supplier"].empty_label = _("Own / not bought")
        self.fields["supplier"].biz_quick_add = "supplier"
        money_field(self.fields["cost"])
        money_field(self.fields["paid_now"])
        self.fields["cost"].required = self.fields["paid_now"].required = False
        self.fields["paid_now"].help_text = _("The rest is recorded as owed to the supplier.")
        if not self.instance.pk:
            self.initial.setdefault("weight_unit", Unit.objects.filter(business=self.business, symbol="kg").first())
            self.initial["cost"] = self.initial["paid_now"] = None

    def clean(self):
        data = super().clean()
        if not data.get("count") and not data.get("weight"):
            raise forms.ValidationError(_("Enter the number of fish, their weight, or both."))
        data["cost"] = data.get("cost") or 0
        data["paid_now"] = data.get("paid_now") or 0
        if data["paid_now"] > data["cost"]:
            self.add_error("paid_now", _("That's more than the cost."))
        if not data.get("supplier"):  # nobody to owe: own fingerlings or paid on the spot
            data["paid_now"] = data["cost"]
        return data


class MortalityForm(EntryForm):
    layout = [("date", "species"), ("count",), ("cause",), ("notes",)]

    class Meta:
        model = Mortality
        fields = ["date", "species", "count", "cause", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["species"].empty_label = _("Mixed / not sure")


class WeighingForm(EntryForm):
    layout = [("date", "species"), ("fish_count",), ("total_weight", "unit"), ("notes",)]

    class Meta:
        model = SampleWeighing
        fields = ["date", "species", "fish_count", "total_weight", "unit", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["unit"].queryset = _units(self.business, ["weight"])
        self.fields["unit"].empty_label = None
        self.fields["fish_count"].help_text = _("Catch 10–20 fish with a net and weigh them together.")
        if not self.instance.pk:
            self.initial.setdefault("unit", Unit.objects.filter(business=self.business, symbol="kg").first())


class HarvestForm(EntryForm):
    layout = [("date", "species"), ("quantity", "unit"), ("fish_count",), ("is_final",), ("notes",)]

    class Meta:
        model = Harvest
        fields = ["date", "species", "quantity", "unit", "fish_count", "is_final", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["unit"].queryset = _units(self.business, ["weight", "count"])
        self.fields["unit"].empty_label = None
        if not self.instance.pk:
            self.initial.setdefault("unit", Unit.objects.filter(business=self.business, symbol="mon").first()
                                    or Unit.objects.filter(business=self.business, symbol="kg").first())
