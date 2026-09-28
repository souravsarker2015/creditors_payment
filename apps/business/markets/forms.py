from django import forms
from django.forms import inlineformset_factory
from django.utils.translation import gettext_lazy as _

from apps.business.core.crud import BusinessForm
from apps.business.core.models import Unit

from .models import DeductionMethod, DeductionType, Market, MarketDeduction


class MarketForm(BusinessForm):
    tips = {
        "market_days": _("Which days the market runs, for your own reference."),
    }
    layout = [("name",), ("location", "phone"), ("market_days", "distance_km"), ("notes",)]

    class Meta:
        model = Market
        fields = ["name", "location", "phone", "market_days", "distance_km", "notes"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": _("e.g. Jatrabari fish aarot")}),
            "phone": forms.TextInput(attrs={"inputmode": "tel"}),
        }


class MarketQuickForm(MarketForm):
    class Meta(MarketForm.Meta):
        fields = ["name", "location"]


class DeductionTypeForm(BusinessForm):
    tips = {
        "method": _("“% of the sale”: e.g. 3% commission. “Per unit sold”: e.g. ৳20 per mon for labour. “Fixed per sale”: the same amount on every sale, e.g. ৳100 khajna. This is only the usual way; each market can set its own."),
        "name_bn": _("Shown instead of the English name when the app is in Bangla."),
    }
    layout = [("name", "name_bn"), ("method",), ("notes",)]

    class Meta:
        model = DeductionType
        fields = ["name", "name_bn", "method", "notes"]
        widgets = {"name": forms.TextInput(attrs={"placeholder": _("e.g. Ice")})}


class DeductionTypeQuickForm(DeductionTypeForm):
    class Meta(DeductionTypeForm.Meta):
        fields = ["name", "method"]


class MarketDeductionForm(BusinessForm):
    unique_name = ()
    tips = {
        "value": _("The percentage, or the taka amount, depending on how it's charged."),
    }

    class Meta:
        model = MarketDeduction
        fields = ("deduction_type", "method", "value", "unit")  # a tuple: inline formsets append their FK to a list in place

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["deduction_type"].empty_label = _("Choose…")
        self.fields["unit"].queryset = Unit.objects.filter(business=self.business, unit_type__in=["weight", "count"])
        self.fields["unit"].empty_label = "—"
        self.fields["value"].widget.attrs["placeholder"] = "0"

    def has_changed(self):
        # A blank row (added then left empty or removed on the page) is skipped;
        # "How" always has a value, so only the deduction and rate count.
        if not self.instance.pk and not (self.data.get(self.add_prefix("deduction_type")) or self.data.get(self.add_prefix("value"))):
            return False
        return super().has_changed()

    def clean(self):
        data = super().clean()
        if data.get("method") == DeductionMethod.PER_UNIT and not data.get("unit"):
            self.add_error("unit", _("Per which unit?"))
        if data.get("method") != DeductionMethod.PER_UNIT:
            data["unit"] = None
        return data


MarketDeductionFormSet = inlineformset_factory(Market, MarketDeduction, form=MarketDeductionForm, extra=0, can_delete=True)
