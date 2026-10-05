from datetime import date
from decimal import Decimal

from django import forms
from django.utils.formats import date_format
from django.utils.translation import gettext_lazy as _

from apps.business.core.crud import BusinessForm, money_field
from apps.business.core.models import Unit
from apps.business.species.models import Species

from .models import CultureCycle, Harvest, LeasePayment, Mortality, Ownership, Pond, PondAlerts, SampleWeighing, Stocking, TimeOfDay, Treatment, TreatmentKind, WaterTest

MAX_PHOTO_MB = 5


class PondForm(BusinessForm):
    tips = {
        "area": _("The water area. It's used to work out profit per decimal, so you can compare ponds of different sizes. 100 decimals = 1 acre."),
        "depth_ft": _("Average water depth in feet. Useful when deciding how many fish to release."),
        "status": _("Changes on its own: starting a cycle sets “Fish in it”, finishing one sets “Empty / dry”. Change it here only to correct it."),
        "ownership": _("Leased? Fill in the lease below so you can see who it's from, what it cost and when it ends."),
    }
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
    tips = {
        "start_date": _("The day you released (or will release) the first fingerlings."),
        "expected_harvest": _("Roughly when you plan to harvest. The cycle page counts down the days to it."),
    }
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
            raise forms.ValidationError(_("This is before the cycle started (%(date)s).") % {"date": date_format(self.cycle.start_date, "j M Y")})
        if d > date.today():
            raise forms.ValidationError(_("This date is in the future."))
        return d


def _units(business, types):
    return Unit.objects.filter(business=business, unit_type__in=types)


class StockingForm(EntryForm):
    tips = {
        "count": _("How many fingerlings (pona) you released."),
        "weight": _("Total weight of all these fingerlings. With the count, it gives the starting size of each fish."),
        "supplier": _("Who sold you the fingerlings. Choose “Own / not bought” if they came from your own nursery."),
        "cost": _("The total price of these fingerlings. It becomes part of this cycle's cost."),
    }
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
    tips = {
        "count": _("Number of dead fish found. It lowers the fish count in the pond."),
        "species": _("Not sure which fish? Leave it as “Mixed / not sure”."),
    }
    layout = [("date", "species"), ("count",), ("cause",), ("notes",)]

    class Meta:
        model = Mortality
        fields = ["date", "species", "count", "cause", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["species"].empty_label = _("Mixed / not sure")


class WeighingForm(EntryForm):
    tips = {
        "fish_count": _("How many fish are in the sample you weighed."),
        "total_weight": _("The weight of all the sampled fish together, not of one fish. The app divides it for you."),
    }
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
    tips = {
        "quantity": _("How much fish came out. A mon is the weight set in Farm setup → Units (usually 40 kg)."),
        "fish_count": _("If you counted the fish, the pond's fish count goes down by this many."),
        "is_final": _("Tick only for the last harvest: the cycle is finished and the pond is marked empty. You can reopen it later."),
    }
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


class WaterTestForm(EntryForm):
    layout = [("date", "time_of_day"), ("oxygen", "ph"), ("temperature", "ammonia"), ("transparency",), ("notes",)]
    tips = {
        "time_of_day": _("Oxygen is lowest just before sunrise, so an early-morning test shows the worst case."),
        "oxygen": _("From a DO meter or test kit, in mg/L. Low oxygen is the most common cause of fish dying suddenly."),
        "ph": _("From a pH kit or paper. It usually rises in the afternoon and falls at night."),
        "temperature": _("Put the thermometer about a foot under the water for a minute."),
        "ammonia": _("From an ammonia test kit, in mg/L. It rises with uneaten feed and waste."),
        "transparency": _("Lower a Secchi disk (a black-and-white plate) until you can't see it, and read the depth in cm."),
    }

    class Meta:
        model = WaterTest
        fields = ["date", "time_of_day", "oxygen", "ph", "temperature", "ammonia", "transparency", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["time_of_day"].choices = [("", _("Not noted"))] + list(TimeOfDay.choices)
        for name in WaterTest.READINGS:
            self.fields[name].widget.attrs["placeholder"] = "—"

    def clean(self):
        data = super().clean()
        if all(data.get(n) is None for n in WaterTest.READINGS):
            raise forms.ValidationError(_("Enter at least one reading."))
        if data.get("ph") is not None and data["ph"] > 14:
            self.add_error("ph", _("pH goes from 0 to 14."))
        return data


class TreatmentForm(EntryForm):
    """Lime, fertilizer, medicine… put into the pond. `dose` is only a helper:
    an amount per decimal of water, multiplied by the pond's size."""

    dose = forms.DecimalField(label=_("Dose per decimal"), required=False, min_value=0, max_digits=10, decimal_places=3,
                              widget=forms.NumberInput(attrs={"placeholder": "—"}),
                              help_text=_("Optional. Type the dose on the bag (e.g. 1 kg lime per decimal) and the amount is worked out from the pond's size."))
    tips = {
        "kind": _("Lime and fertilizer are usually given when preparing the pond and every few weeks; salt, potash and medicine when fish are sick."),
        "withdrawal_days": _("Some medicines stay in the fish for a while. The app warns you if you try to sell fish from this pond before the waiting period is over."),
        "cost": _("What this lot cost. It becomes part of this cycle's cost."),
        "account": _("Leave empty if it was bought earlier or on credit — the cost still counts for the pond, but no money leaves an account today."),
    }
    layout = [("date", "kind"), ("product",), ("dose",), ("quantity", "unit"), ("reason",), ("cost", "account"), ("withdrawal_days",), ("notes",)]

    class Meta:
        model = Treatment
        fields = ["date", "kind", "product", "quantity", "unit", "reason", "cost", "account", "withdrawal_days", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.business.finance.models import Account

        self.fields["unit"].queryset = _units(self.business, ["weight", "volume", "count"])
        self.fields["unit"].empty_label = None
        self.fields["account"].queryset = Account.objects.filter(business=self.business)
        self.fields["account"].empty_label = _("Not paid now")
        self.fields["cost"].required = False
        money_field(self.fields["cost"])
        self.fields["product"].widget.attrs["list"] = f"treatment-products-{self.prefix or 'x'}"
        pond = getattr(self.cycle, "pond", None)
        self.area = pond.area_decimal if pond else None
        if self.area:
            self.fields["dose"].help_text = _("Optional. The pond is %(area)s decimal: the amount is worked out for you.") % {"area": format(self.area.normalize(), "f")}
        if not self.instance.pk:
            self.initial.setdefault("unit", Unit.objects.filter(business=self.business, symbol="kg").first())
            self.initial.setdefault("account", Account.objects.filter(business=self.business, is_default=True).first())
            self.initial["cost"] = None

    is_treatment = True
    suggestions = ("Dolomite lime", "Quick lime (chun)", "Urea", "TSP", "Cow dung", "Salt", "Potash (KMnO₄)",
                   "Zeolite", "Oxytetracycline", "Probiotic")

    def known_products(self):
        """Products used on this farm before, for the suggestions list."""
        return (Treatment.objects.filter(business=self.business).order_by("product").values_list("product", flat=True).distinct()[:60])

    def clean(self):
        data = super().clean()
        data["cost"] = data.get("cost") or 0
        if data.get("dose") and not data.get("quantity") and self.area:
            data["quantity"] = (data["dose"] * self.area).quantize(Decimal("0.001"))
        if data["cost"] and not data.get("account"):
            data["account"] = None
        return data


class PondAlertsForm(BusinessForm):
    unique_name = ()
    layout = [
        ("#", _("Water")), ("oxygen_min",), ("ph_min", "ph_max"), ("temperature_min", "temperature_max"), ("ammonia_max",),
        ("transparency_min", "transparency_max"),
        ("#", _("Deaths")), ("deaths_pct",),
    ]
    tips = {
        "oxygen_min": _("Most pond fish get stressed below about 4 mg/L and can die below 2–3."),
        "deaths_pct": _("E.g. 1 means: warn when more than 1 fish in 100 of those in the pond were recorded dead in the last 3 days."),
    }

    class Meta:
        model = PondAlerts
        exclude = ["business"]

    def clean(self):
        data = super().clean()
        for low, high in (("ph_min", "ph_max"), ("temperature_min", "temperature_max"), ("transparency_min", "transparency_max")):
            if data.get(low) is not None and data.get(high) is not None and data[low] >= data[high]:
                self.add_error(high, _("This has to be more than the lower level."))
        return data


class PondQuickForm(BusinessForm):
    """"+ New pond" from another form: just the name and size."""

    class Meta:
        model = Pond
        fields = ["name", "area"]
        widgets = {"name": forms.TextInput(attrs={"placeholder": _("e.g. Big pond (east)")})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["area"].label = _("Area (decimal)")

    def save(self, commit=True):
        from .models import PondStatus

        self.instance.area_unit = Unit.objects.filter(business=self.business, symbol="dec").first()
        self.instance.status = PondStatus.EMPTY     # no fish until a cycle is started
        return super().save(commit)


class LeasePaymentForm(BusinessForm):
    unique_name = ()
    layout = [("date", "amount"), ("account", "reference"), ("notes",)]

    class Meta:
        model = LeasePayment
        fields = ["date", "amount", "account", "reference", "notes"]
        widgets = {"date": forms.DateInput()}

    def __init__(self, *args, due=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.business.finance.models import Account

        money_field(self.fields["amount"])
        self.fields["account"].queryset = Account.objects.filter(business=self.business)
        self.fields["account"].empty_label = None
        if not self.instance.pk:
            self.initial.setdefault("date", date.today())
            self.initial.setdefault("account", Account.objects.filter(business=self.business, is_default=True).first())
            if due and due > 0:
                self.initial.setdefault("amount", format(due.normalize(), "f"))

    def clean_date(self):
        d = self.cleaned_data["date"]
        if d > date.today():
            raise forms.ValidationError(_("This date is in the future."))
        return d
