from datetime import date

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.business.core.crud import BusinessForm, money_field
from apps.business.feed.models import FeedPurchase
from apps.business.finance.models import Account
from apps.business.parties.models import Party
from apps.business.ponds.models import Stocking
from apps.business.sales.models import FishSale

from .models import Direction, PartyPayment

BILL_MODELS = {"sale": (FishSale, "sale", "buyer_id"), "feed": (FeedPurchase, "feed_purchase", "supplier_id"),
               "stocking": (Stocking, "stocking", "supplier_id")}


class PaymentForm(BusinessForm):
    """One payment. `against` is an optional bill ("sale:12"); the page fills
    its choices per party from the ledger, so it's validated here by hand."""

    unique_name = ()
    against = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = PartyPayment
        fields = ["party", "direction", "date", "amount", "discount", "account", "reference", "notes"]
        widgets = {"date": forms.DateInput(), "direction": forms.RadioSelect}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        b = self.business
        self.fields["party"].queryset = Party.objects.filter(business=b)
        self.fields["party"].empty_label = _("Choose a person or firm…")
        self.fields["account"].queryset = Account.objects.filter(business=b)
        self.fields["account"].empty_label = _("Not recorded")
        money_field(self.fields["amount"])
        money_field(self.fields["discount"])
        self.fields["discount"].required = False
        self.fields["amount"].required = False
        if self.instance.pk:
            bill = self.instance.bill
            if bill is not None:
                kind = next(k for k, (_m, attr, _f) in BILL_MODELS.items() if getattr(self.instance, f"{attr}_id"))
                self.initial["against"] = f"{kind}:{bill.pk}"
        else:
            self.initial.setdefault("date", date.today())
            for name in ("amount", "discount"):  # empty boxes rather than "0"
                if not self.initial.get(name):
                    self.initial[name] = None
            self.initial.setdefault("account", Account.objects.filter(business=b, is_default=True).first())

    def clean_date(self):
        d = self.cleaned_data["date"]
        if d and d > date.today():
            raise forms.ValidationError(_("That date is in the future."))
        return d

    def clean(self):
        data = super().clean()
        data["amount"] = data.get("amount") or 0
        data["discount"] = data.get("discount") or 0
        if not (data["amount"] or data["discount"]):
            self.add_error("amount", _("Enter the amount."))
        self.bill_attr, self.bill = None, None
        raw = (data.get("against") or "").strip()
        party = data.get("party")
        if raw and party:
            kind, _sep, pk = raw.partition(":")
            spec = BILL_MODELS.get(kind)
            bill = spec[0].objects.filter(business=self.business, pk=pk).first() if (spec and pk.isdigit()) else None
            if bill is None or getattr(bill, spec[2]) != party.pk:
                self.add_error(None, _("That bill isn't one of %(name)s's.") % {"name": party})
            else:
                self.bill_attr, self.bill = spec[1], bill
        return data

    def save(self, commit=True):
        obj = super().save(commit=False)
        for attr in ("sale", "feed_purchase", "stocking"):
            setattr(obj, attr, self.bill if attr == self.bill_attr else None)
        if commit:
            obj.save()
        return obj


class FollowUpForm(forms.ModelForm):
    class Meta:
        model = Party
        fields = ["follow_up_on", "follow_up_note"]
        widgets = {"follow_up_on": forms.DateInput(attrs={"class": "form-input datepicker", "autocomplete": "off"}, format="%Y-%m-%d"),
                   "follow_up_note": forms.TextInput(attrs={"class": "form-input", "placeholder": _("e.g. Said he'll pay after Friday's market")})}


__all__ = ["PaymentForm", "FollowUpForm", "Direction"]
