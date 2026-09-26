from django import forms
from django.utils.translation import gettext_lazy as _

from apps.business.core.crud import BusinessForm
from apps.business.core.models import Unit

from .models import COLORS, Species


class SpeciesForm(BusinessForm):
    layout = [("name", "name_bn"), ("default_unit", "scientific_name"), ("color",), ("notes",)]

    class Meta:
        model = Species
        fields = ["name", "name_bn", "default_unit", "scientific_name", "color", "notes"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": _("e.g. Rui")}),
            "name_bn": forms.TextInput(attrs={"placeholder": _("e.g. রুই")}),
            "color": forms.RadioSelect(choices=[(c, c) for c in COLORS], attrs={"class": "color-pick"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["default_unit"].queryset = Unit.objects.filter(business=self.business, unit_type__in=["weight", "count"])
        self.fields["default_unit"].empty_label = _("Choose…")
        if not self.instance.pk:
            self.initial.setdefault("default_unit", Unit.objects.filter(business=self.business, symbol="kg").first())
            used = Species.objects.filter(business=self.business).count()
            self.initial.setdefault("color", COLORS[used % len(COLORS)])


class SpeciesQuickForm(BusinessForm):
    class Meta:
        model = Species
        fields = ["name", "name_bn"]

    def save(self, commit=True):
        self.instance.default_unit = Unit.objects.filter(business=self.business, symbol="kg").first()
        used = Species.objects.filter(business=self.business).count()
        self.instance.color = COLORS[used % len(COLORS)]
        return super().save(commit)
