from datetime import date

from django import forms
from django.forms import inlineformset_factory
from django.utils.translation import gettext_lazy as _

from apps.business.core.crud import BusinessForm, money_field
from apps.business.core.models import Unit
from apps.business.finance.models import Account
from apps.business.parties.models import Party
from apps.business.ponds.forms import EntryForm
from apps.business.ponds.models import CultureCycle, CycleStatus

from .models import FeedProduct, FeedPurchase, FeedPurchaseLine, FeedUsage


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


# ── Purchases and feeding ───────────────────────────────────────────────────


def _bag_or_weight(field, business):
    """Unit dropdown for feed: empty choice = bags, then weight units."""
    field.queryset = Unit.objects.filter(business=business, unit_type="weight")
    field.empty_label = _("bags")
    field.required = False


class FeedPurchaseForm(BusinessForm):
    unique_name = ()

    class Meta:
        model = FeedPurchase
        fields = ["supplier", "date", "invoice_no", "transport", "discount", "paid_now", "account", "notes"]
        widgets = {"date": forms.DateInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supplier"].queryset = Party.objects.filter(business=self.business, is_supplier=True)
        self.fields["supplier"].empty_label = _("Choose supplier…")
        self.fields["supplier"].biz_quick_add = "supplier"
        self.fields["account"].queryset = Account.objects.filter(business=self.business)
        self.fields["account"].empty_label = _("Not recorded")
        for name in ("transport", "discount", "paid_now"):
            money_field(self.fields[name])
            self.fields[name].required = False
        if not self.instance.pk:
            self.initial.setdefault("date", date.today())
            self.initial.setdefault("account", Account.objects.filter(business=self.business, is_default=True).first())
            last = FeedPurchase.objects.filter(business=self.business).order_by("-date", "-id").first()
            if last:  # quick entry: same supplier as last time
                self.initial.setdefault("supplier", last.supplier_id)
            for name in ("transport", "discount", "paid_now"):
                self.initial[name] = None

    def clean(self):
        data = super().clean()
        for name in ("transport", "discount", "paid_now"):
            data[name] = data.get(name) or 0
        return data


class FeedLineForm(BusinessForm):
    unique_name = ()

    class Meta:
        model = FeedPurchaseLine
        fields = ("product", "quantity", "unit", "rate")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].empty_label = _("Choose feed…")
        _bag_or_weight(self.fields["unit"], self.business)

    def has_changed(self):
        if not self.instance.pk and not (self.data.get(self.add_prefix("product")) or self.data.get(self.add_prefix("quantity"))):
            return False
        return super().has_changed()


class _RequireOne(forms.BaseInlineFormSet):
    message = _("Add at least one line.")

    def clean(self):
        super().clean()
        alive = [f for f in self.forms if f.has_changed() and not (self.can_delete and self._should_delete_form(f))]
        kept = [f for f in self.forms if f.instance.pk and not self._should_delete_form(f)]
        if not alive and not kept:
            raise forms.ValidationError(self.message)


FeedLineFormSet = inlineformset_factory(FeedPurchase, FeedPurchaseLine, form=FeedLineForm, formset=_RequireOne, extra=0, can_delete=True)


class FeedUsageForm(EntryForm):
    layout = [("date",), ("product",), ("quantity", "unit"), ("notes",)]

    class Meta:
        model = FeedUsage
        fields = ["date", "product", "quantity", "unit", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bag_or_weight(self.fields["unit"], self.business)
        self.fields["product"].empty_label = _("Choose feed…")
        if not self.instance.pk:
            last = FeedUsage.objects.filter(business=self.business).order_by("-date", "-id").first()
            if last:
                self.initial.setdefault("product", last.product_id)
                self.initial.setdefault("unit", last.unit_id)


class BulkFeedingForm(forms.Form):
    """Feed several ponds in one go: one date and feed, a quantity per pond."""

    date = forms.DateField(label=_("Date"), widget=forms.DateInput(attrs={"class": "form-input datepicker"}, format="%Y-%m-%d"))
    product = forms.ModelChoiceField(label=_("Feed"), queryset=FeedProduct.objects.none(), empty_label=_("Choose feed…"),
                                     widget=forms.Select(attrs={"class": "form-input"}))
    unit = forms.ModelChoiceField(label=_("Unit"), queryset=Unit.objects.none(), required=False,
                                  widget=forms.Select(attrs={"class": "form-input"}))

    def __init__(self, *args, business, **kwargs):
        super().__init__(*args, **kwargs)
        self.business = business
        self.fields["product"].queryset = FeedProduct.objects.filter(business=business)
        _bag_or_weight(self.fields["unit"], business)
        self.cycles = list(CultureCycle.objects.filter(business=business, status=CycleStatus.RUNNING).select_related("pond").order_by("pond__order", "pond__name"))
        for c in self.cycles:
            self.fields[f"c{c.pk}"] = forms.DecimalField(label=str(c.pond), required=False, min_value=0, max_digits=12, decimal_places=3,
                                                         widget=forms.NumberInput(attrs={"class": "form-input", "inputmode": "decimal", "step": "any", "placeholder": "0", "data-pond": "1"}))
        if not self.is_bound:
            self.initial.setdefault("date", date.today())
            last = FeedUsage.objects.filter(business=business).order_by("-date", "-id").first()
            if last:
                self.initial.setdefault("product", last.product_id)
                self.initial.setdefault("unit", last.unit_id)
                # Pre-fill each pond with its last amount of this feed: most days are the same.
                for c in self.cycles:
                    prev = FeedUsage.objects.filter(cycle=c, product_id=last.product_id).order_by("-date", "-id").first()
                    if prev and prev.unit_id == last.unit_id:
                        self.initial[f"c{c.pk}"] = format(prev.quantity.normalize(), "f")

    def pond_fields(self):
        return [(c, self[f"c{c.pk}"]) for c in self.cycles]

    def clean(self):
        data = super().clean()
        entries = [(c, data.get(f"c{c.pk}")) for c in self.cycles if data.get(f"c{c.pk}")]
        if not entries:
            raise forms.ValidationError(_("Enter the feed given to at least one pond."))
        d = data.get("date")
        if d and d > date.today():
            self.add_error("date", _("This date is in the future."))
        data["entries"] = [(c, q, data.get("unit")) for c, q in entries]
        return data
