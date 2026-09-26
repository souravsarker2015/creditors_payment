from django import forms
from django.utils.translation import gettext_lazy as _

from apps.business.core.crud import BusinessForm, money_field
from apps.business.core.models import Unit
from apps.business.parties.models import Party

from .models import FeedProduct


class FeedProductForm(BusinessForm):
    layout = [("name", "brand"), ("form", "stage"), ("bag_size", "bag_unit"), ("default_price", "protein_pct"),
              ("suppliers",), ("low_stock_bags",), ("notes",)]

    class Meta:
        model = FeedProduct
        fields = ["name", "brand", "form", "stage", "protein_pct", "bag_size", "bag_unit", "default_price", "suppliers", "low_stock_bags", "notes"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": _("e.g. Floating grower 28%")}),
            "brand": forms.TextInput(attrs={"placeholder": _("e.g. Nourish, Quality, Mega")}),
            "suppliers": forms.SelectMultiple(attrs={"data-multi": "1"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["bag_unit"].queryset = Unit.objects.filter(business=self.business, unit_type="weight")
        self.fields["bag_unit"].empty_label = None
        self.fields["suppliers"].queryset = Party.objects.filter(business=self.business, is_supplier=True)
        self.fields["suppliers"].help_text = _("Pick one or more. Add new suppliers under Suppliers.")
        self.fields["stage"].choices = [("", _("Any / not sure"))] + list(self.fields["stage"].choices)[1:]
        money_field(self.fields["default_price"])
        money_field(self.fields["protein_pct"], "%")
        if not self.instance.pk:
            self.initial.setdefault("bag_unit", Unit.objects.filter(business=self.business, symbol="kg").first())
