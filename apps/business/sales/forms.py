from datetime import date, timedelta

from django import forms
from django.forms import inlineformset_factory
from django.utils.translation import gettext_lazy as _

from apps.business.core.crud import BusinessForm, money_field
from apps.business.core.models import Unit
from apps.business.feed.forms import _RequireOne
from apps.business.finance.models import Account
from apps.business.markets.forms import MarketDeductionForm
from apps.business.parties.models import Party
from apps.business.ponds.models import CultureCycle, CycleStatus
from apps.business.species.models import Species

from .models import FishSale, FishSaleLine, SaleDeduction


class FishSaleForm(BusinessForm):
    unique_name = ()

    class Meta:
        model = FishSale
        fields = ["date", "market", "buyer", "cycle", "memo_no", "received_now", "account", "notes"]
        widgets = {"date": forms.DateInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        b = self.business
        self.fields["market"].empty_label = _("Not at a market / direct")
        self.fields["market"].biz_quick_add = "market"
        self.fields["buyer"].queryset = Party.objects.filter(business=b, is_buyer=True)
        self.fields["buyer"].empty_label = _("Cash buyer / not recorded")
        self.fields["buyer"].biz_quick_add = "buyer"
        recent = date.today() - timedelta(days=120)
        cycles = CultureCycle.objects.filter(business=b).filter(status=CycleStatus.RUNNING) | CultureCycle.objects.filter(business=b, ended_on__gte=recent)
        if self.instance.cycle_id:
            cycles = cycles | CultureCycle.objects.filter(pk=self.instance.cycle_id)
        self.fields["cycle"].queryset = cycles.distinct().select_related("pond")
        self.fields["cycle"].empty_label = _("Not from a particular pond")
        self.fields["account"].queryset = Account.objects.filter(business=b)
        self.fields["account"].empty_label = _("Not recorded")
        money_field(self.fields["received_now"])
        self.fields["received_now"].required = False
        if not self.instance.pk:
            self.initial.setdefault("date", date.today())
            self.initial.setdefault("account", Account.objects.filter(business=b, is_default=True).first())
            self.initial["received_now"] = None
            last = FishSale.objects.filter(business=b).order_by("-date", "-id").first()
            if last:  # quick entry: same market and buyer as last time
                self.initial.setdefault("market", last.market_id)
                self.initial.setdefault("buyer", last.buyer_id)
            running = list(CultureCycle.objects.filter(business=b, status=CycleStatus.RUNNING)[:2])
            if len(running) == 1:
                self.initial.setdefault("cycle", running[0].pk)

    def clean(self):
        data = super().clean()
        data["received_now"] = data.get("received_now") or 0
        return data


class SaleLineForm(BusinessForm):
    unique_name = ()

    class Meta:
        model = FishSaleLine
        fields = ("species", "quantity", "unit", "rate")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["species"].queryset = Species.objects.filter(business=self.business)
        self.fields["species"].empty_label = _("Choose fish…")
        self.fields["unit"].queryset = Unit.objects.filter(business=self.business, unit_type__in=["weight", "count"])
        self.fields["unit"].empty_label = None

    def has_changed(self):
        if not self.instance.pk and not (self.data.get(self.add_prefix("species")) or self.data.get(self.add_prefix("quantity"))):
            return False
        return super().has_changed()


class SaleDeductionForm(MarketDeductionForm):
    class Meta(MarketDeductionForm.Meta):
        model = SaleDeduction
        fields = ("deduction_type", "method", "value", "unit")


class _SaleLines(_RequireOne):
    message = _("Add at least one fish.")


SaleLineFormSet = inlineformset_factory(FishSale, FishSaleLine, form=SaleLineForm, formset=_SaleLines, extra=0, can_delete=True)
SaleDeductionFormSet = inlineformset_factory(FishSale, SaleDeduction, form=SaleDeductionForm, extra=0, can_delete=True)
