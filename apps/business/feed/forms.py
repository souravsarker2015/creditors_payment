from collections import Counter
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
from apps.core.receipts import memo_field

from .models import FeedProduct, FeedPurchase, FeedPurchaseLine, FeedUsage


class FeedProductForm(BusinessForm):
    tips = {
        "form": _("Floating feed stays on top, so you can see the fish eat it. Sinking feed goes to the bottom."),
        "stage": _("Which size of fish it's made for: starter for small fish, grower in the middle, finisher before harvest."),
        "protein_pct": _("Printed on the bag. Feed for small fish usually has more protein than feed for big fish."),
        "bag_size": _("How much one bag holds, e.g. 25 kg. Used to turn bags into kg for stock and cost."),
        "default_price": _("The usual price of one bag. Filled in as the rate when you buy this feed; you can change it on each purchase."),
        "low_stock_bags": _("When fewer bags than this are left, the dashboard and the Feed page warn you."),
    }
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
        self.fields["suppliers"].help_text = _("Pick one or more.")
        self.fields["suppliers"].biz_quick_add = "supplier"
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
    tips = {
        "invoice_no": _("The number on the dealer's memo, so you can match it later."),
        "transport": _("Van fare or labour to bring the feed. It is added to the bill total."),
        "discount": _("Money the dealer took off the bill."),
        "paid_now": _("What you paid at the time of buying. The rest is added to this supplier's Baki."),
        "account": _("Which account you paid from: cash, bank or bKash/Nagad."),
    }

    class Meta:
        model = FeedPurchase
        fields = ["supplier", "date", "invoice_no", "transport", "discount", "paid_now", "account", "receipt", "notes"]
        widgets = {"date": forms.DateInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supplier"].queryset = Party.objects.filter(business=self.business, is_supplier=True)
        self.fields["supplier"].empty_label = _("Choose supplier…")
        self.fields["supplier"].biz_quick_add = "supplier"
        self.fields["account"].queryset = Account.objects.filter(business=self.business)
        memo_field(self, "feed")
        self.fields["account"].empty_label = _("Not recorded")
        self.fields["account"].biz_quick_add = "account"
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
    tips = {
        "quantity": _("How much this pond ate. Leave the unit on “bags”, or pick kg if you weighed it out."),
    }
    layout = [("date",), ("product",), ("quantity", "unit"), ("notes",)]

    class Meta:
        model = FeedUsage
        fields = ["date", "product", "quantity", "unit", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bag_or_weight(self.fields["unit"], self.business)
        self.fields["product"].empty_label = _("Choose feed…")
        self.fields["product"].biz_quick_add = "feed"
        if not self.instance.pk:
            last = FeedUsage.objects.filter(business=self.business).order_by("-date", "-id").first()
            if last:
                self.initial.setdefault("product", last.product_id)
                self.initial.setdefault("unit", last.unit_id)


class BulkFeedingForm(forms.Form):
    """Feed several ponds in one go: one date, a quantity per pond. The feed
    chosen at the top is for every pond, unless a pond has its own (a nursery
    on starter feed while the big ponds get grower)."""

    tips = {
        "unit": _("“bags” uses the feed's bag size. Choose kg if you weighed it out."),
    }

    date = forms.DateField(label=_("Date"), widget=forms.DateInput(attrs={"class": "form-input datepicker"}, format="%Y-%m-%d"))
    product = forms.ModelChoiceField(label=_("Feed"), queryset=FeedProduct.objects.none(), empty_label=_("Choose feed…"), required=False,
                                     help_text=_("For every pond, unless you choose another feed for a pond below."),
                                     widget=forms.Select(attrs={"class": "form-input"}))
    unit = forms.ModelChoiceField(label=_("Unit"), queryset=Unit.objects.none(), required=False,
                                  widget=forms.Select(attrs={"class": "form-input"}))

    def __init__(self, *args, business, **kwargs):
        super().__init__(*args, **kwargs)
        self.business = business
        self.fields["product"].queryset = FeedProduct.objects.filter(business=business)
        self.fields["product"].biz_quick_add = "feed"
        _bag_or_weight(self.fields["unit"], business)
        self.cycles = list(CultureCycle.objects.filter(business=business, status=CycleStatus.RUNNING).select_related("pond").order_by("pond__order", "pond__name"))
        products = self.fields["product"].queryset
        for c in self.cycles:
            self.fields[f"c{c.pk}"] = forms.DecimalField(label=str(c.pond), required=False, min_value=0, max_digits=12, decimal_places=3,
                                                         widget=forms.NumberInput(attrs={"class": "form-input", "inputmode": "decimal", "step": "any", "placeholder": "0", "data-pond": "1"}))
            self.fields[f"f{c.pk}"] = forms.ModelChoiceField(label=_("Feed for %(pond)s") % {"pond": c.pond}, queryset=products, required=False,
                                                             empty_label=_("Same as above"),
                                                             widget=forms.Select(attrs={"class": "form-input input-compact", "data-pond-feed": "1"}))
        if not self.is_bound:
            self.initial.setdefault("date", date.today())
            last = FeedUsage.objects.filter(business=business).order_by("-date", "-id").first()
            if last:
                prevs = {c.pk: FeedUsage.objects.filter(cycle=c).order_by("-date", "-id").first() for c in self.cycles}
                # The feed at the top: the one most ponds ate last time, so most rows say "Same as above".
                counts = Counter(p.product_id for p in prevs.values() if p)
                usual = max(counts, key=lambda pk: (counts[pk], pk == last.product_id)) if counts else last.product_id
                self.initial.setdefault("product", usual)
                self.initial.setdefault("unit", last.unit_id)
                # Pre-fill each pond with what it ate last time: most days are the same.
                # A pond on another feed (a nursery on starter) keeps its own feed.
                for c in self.cycles:
                    prev = prevs[c.pk]
                    if prev is None:
                        continue
                    if prev.product_id != self.initial["product"]:
                        self.initial[f"f{c.pk}"] = prev.product_id
                    if prev.unit_id == self.initial["unit"]:
                        self.initial[f"c{c.pk}"] = format(prev.quantity.normalize(), "f")

    def pond_fields(self):
        return [(c, self[f"c{c.pk}"], self[f"f{c.pk}"]) for c in self.cycles]

    def clean(self):
        data = super().clean()
        entries = [(c, data.get(f"c{c.pk}")) for c in self.cycles if data.get(f"c{c.pk}")]
        if not entries:
            raise forms.ValidationError(_("Enter the feed given to at least one pond."))
        d = data.get("date")
        if d and d > date.today():
            self.add_error("date", _("This date is in the future."))
        default = data.get("product")
        out = []
        for c, q in entries:
            feed = data.get(f"f{c.pk}") or default
            if feed is None:
                self.add_error(f"f{c.pk}", _("Choose the feed this pond ate."))
            out.append((c, q, data.get("unit"), feed))
        data["entries"] = out
        return data


class FeedProductQuickForm(BusinessForm):
    """"+ New feed" from a purchase or a feeding: the name and the bag, the rest later."""

    class Meta:
        model = FeedProduct
        fields = ["name", "brand", "bag_size", "default_price"]
        widgets = {"name": forms.TextInput(attrs={"placeholder": _("e.g. Floating grower 28%")})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["bag_size"].label = _("Bag size (kg)")
        money_field(self.fields["default_price"])

    def save(self, commit=True):
        self.instance.bag_unit = Unit.objects.filter(business=self.business, symbol="kg").first()
        return super().save(commit)

    def page_data(self, obj):
        """What a purchase form needs to work out this feed's kg and price."""
        return {"bag_kg": str(obj.bag_kg), "price": str(obj.default_price or ""), "bag": str(obj.bag_size.normalize())}


class StoreCountForm(forms.Form):
    """Count the bags in the store, feed by feed. A feed left empty wasn't counted."""

    date = forms.DateField(label=_("Date counted"), widget=forms.DateInput(attrs={"class": "form-input datepicker"}, format="%Y-%m-%d"))

    def __init__(self, *args, business, **kwargs):
        from .services import stock

        super().__init__(*args, **kwargs)
        self.business = business
        self.rows = []
        for row in sorted(stock(business), key=lambda r: (not (r.bought_kg or r.used_kg or r.counted_kg), r.product.name.lower())):
            p = row.product
            if not p.bag_kg:
                continue
            self.fields[f"n{p.pk}"] = forms.DecimalField(
                label=str(p), required=False, min_value=0, max_digits=12, decimal_places=2,
                widget=forms.NumberInput(attrs={"class": "form-input", "inputmode": "decimal", "step": "any", "placeholder": _("bags"), "x-model": "v"}))
            new = not (row.bought_kg or row.used_kg or row.counted_kg)
            if new:   # feed you already had: what is it worth?
                self.fields[f"p{p.pk}"] = money_field(forms.DecimalField(
                    label=_("Price per bag"), required=False, min_value=0, max_digits=14, decimal_places=2,
                    widget=forms.NumberInput(attrs={"class": "form-input", "inputmode": "decimal", "step": "any"})))
                if p.default_price:
                    self.initial.setdefault(f"p{p.pk}", p.default_price)
            self.rows.append(row)
        if not self.is_bound:
            self.initial.setdefault("date", date.today())

    def count_fields(self):
        return [(r, self[f"n{r.product.pk}"], self[f"p{r.product.pk}"] if f"p{r.product.pk}" in self.fields else None) for r in self.rows]

    def clean(self):
        data = super().clean()
        d = data.get("date")
        if d and d > date.today():
            self.add_error("date", _("This date is in the future."))
        entries = []
        for r in self.rows:
            bags = data.get(f"n{r.product.pk}")
            if bags is None:
                continue
            price = data.get(f"p{r.product.pk}")
            entries.append((r.product, bags * r.product.bag_kg, (price / r.product.bag_kg) if price is not None else None))
        if not entries:
            raise forms.ValidationError(_("Type the bags you counted for at least one feed."))
        data["entries"] = entries
        return data
