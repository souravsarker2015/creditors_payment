from datetime import date

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.business.core.crud import BusinessForm, money_field
from apps.business.core.models import Unit

from .models import SupplyItem, SupplyPurchase

UNIT_TYPES = ["weight", "volume", "count"]


class SupplyItemForm(BusinessForm):
    tips = {
        "unit": _("Stock is shown in this unit. You can still buy or use it in another unit of the same kind (mon, gram, ml…)."),
        "low_stock": _("The farm's to-do list tells you when the stock falls to this."),
    }
    layout = [("name", "kind"), ("unit", "low_stock"), ("dose_per_decimal", "withdrawal_days"), ("notes",)]

    class Meta:
        model = SupplyItem
        fields = ["name", "kind", "unit", "low_stock", "dose_per_decimal", "withdrawal_days", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["unit"].queryset = Unit.objects.filter(business=self.business, unit_type__in=UNIT_TYPES)
        self.fields["unit"].empty_label = None
        if not self.instance.pk:
            self.initial.setdefault("unit", Unit.objects.filter(business=self.business, symbol="kg").first())
        elif self.instance.purchases.exists() or self.instance.uses.exists():
            # Stock already counted in this kind of unit: kg can become mon, not litres.
            self.fields["unit"].queryset = self.fields["unit"].queryset.filter(unit_type=self.instance.unit.unit_type)


class SupplyPurchaseForm(BusinessForm):
    unique_name = ()
    tips = {
        "supplier": _("Choose the shop if you still owe them something: the rest goes into their baki."),
        "paid_now": _("Paid today, from the account below. Without a shop, it's taken as fully paid."),
    }
    layout = [("date",), ("quantity", "unit"), ("supplier",), ("cost", "paid_now"), ("account",), ("notes",)]

    class Meta:
        model = SupplyPurchase
        fields = ["date", "quantity", "unit", "supplier", "cost", "paid_now", "account", "notes"]
        widgets = {"date": forms.DateInput()}

    def __init__(self, *args, item, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.business.finance.models import Account
        from apps.business.parties.models import Party

        self.item = item
        self.fields["unit"].queryset = Unit.objects.filter(business=self.business, unit_type=item.unit.unit_type)
        self.fields["unit"].empty_label = None
        self.fields["supplier"].queryset = Party.objects.filter(business=self.business, is_supplier=True)
        self.fields["supplier"].empty_label = _("Paid in full / no shop")
        self.fields["supplier"].biz_quick_add = "supplier"
        self.fields["account"].queryset = Account.objects.filter(business=self.business)
        self.fields["account"].empty_label = _("Not paid from an account")
        for name in ("cost", "paid_now"):
            money_field(self.fields[name])
            self.fields[name].required = False
        if not self.instance.pk:
            self.initial.setdefault("date", date.today())
            self.initial.setdefault("unit", item.unit)
            self.initial.setdefault("account", Account.objects.filter(business=self.business, is_default=True).first())

    def clean(self):
        data = super().clean()
        data["cost"] = data.get("cost") or 0
        data["paid_now"] = data.get("paid_now") or 0
        if data.get("date") and data["date"] > date.today():
            self.add_error("date", _("This date is in the future."))
        if not data.get("supplier"):  # nobody to owe
            data["paid_now"] = data["cost"]
        if data["paid_now"] > data["cost"]:
            self.add_error("paid_now", _("That's more than the cost."))
        if data["paid_now"] and not data.get("account"):
            self.add_error("account", _("Which account was it paid from?"))
        if not data["paid_now"]:
            data["account"] = None
        return data
