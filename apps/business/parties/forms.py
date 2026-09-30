from datetime import date

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.business.core.crud import BusinessForm, money_field

from .models import OpeningType, Party


class PartyForm(BusinessForm):
    role = None   # "supplier" | "buyer": the page it's added from
    tips = {
        "opening_balance": _("Money owed between you from before you started using this app, e.g. an old feed bill. It becomes the first line of their Baki statement."),
        "opening_type": _("“They owe me”: money you'll collect from them. “I owe them”: money you still have to pay."),
        "opening_date": _("When that old balance was due from. Used to show how old the Baki is."),
        "market": _("Their usual market. On a new sale with no market chosen yet, picking this buyer fills it in."),
        "phone": _("Used for the WhatsApp reminder button on their Baki statement."),
    }

    class Meta:
        model = Party
        fields = ["name", "phone", "contact_person", "address", "is_supplier", "is_buyer", "buyer_type", "market",
                  "opening_balance", "opening_type", "opening_date", "notes"]
        widgets = {
            "phone": forms.TextInput(attrs={"inputmode": "tel", "placeholder": "01XXXXXXXXX"}),
            "opening_type": forms.RadioSelect, "opening_date": forms.DateInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        money_field(self.fields["opening_balance"])
        self.fields["opening_balance"].required = False
        self.fields["opening_balance"].help_text = _("Leave empty if you start with nothing owed either way.")
        self.fields["market"].empty_label = _("None / various")
        self.fields["market"].biz_quick_add = "market"
        self.fields["buyer_type"].choices = [("", _("Choose…"))] + list(self.fields["buyer_type"].choices)[1:]
        self.fields["opening_balance"].label = _("Amount")
        self.fields["is_buyer"].label = _("Also a buyer")
        self.fields["is_supplier"].label = _("Also a supplier")
        if not self.instance.pk:
            self.initial["opening_balance"] = None
            self.initial.setdefault(f"is_{self.role}", True)
            self.initial.setdefault("opening_type", OpeningType.PAYABLE if self.role == "supplier" else OpeningType.RECEIVABLE)
            self.initial.setdefault("opening_date", date.today())

    def clean(self):
        data = super().clean()
        data["opening_balance"] = data.get("opening_balance") or 0
        data[f"is_{self.role}"] = True   # saved from the Suppliers/Buyers page, so it is one
        if not data.get("is_buyer"):
            data["buyer_type"], data["market"] = "", None
        return data


class SupplierForm(PartyForm):
    role = "supplier"
    layout = [("name", "phone"), ("contact_person", "address"), ("is_buyer",),
              ("#", _("Balance before using this app")), ("opening_balance", "opening_date"), ("opening_type",), ("notes",)]


class BuyerForm(PartyForm):
    role = "buyer"
    layout = [("name", "phone"), ("buyer_type", "market"), ("contact_person", "address"), ("is_supplier",),
              ("#", _("Balance before using this app")), ("opening_balance", "opening_date"), ("opening_type",), ("notes",)]


class _PartyQuickForm(BusinessForm):
    flag = None

    class Meta:
        model = Party
        fields = ["name", "phone"]
        widgets = {"phone": forms.TextInput(attrs={"inputmode": "tel", "placeholder": "01XXXXXXXXX"})}

    def save(self, commit=True):
        setattr(self.instance, self.flag, True)
        return super().save(commit)


class SupplierQuickForm(_PartyQuickForm):
    flag = "is_supplier"


class BuyerQuickForm(_PartyQuickForm):
    flag = "is_buyer"


class PartyQuickForm(BusinessForm):
    """"+ New person" on dropdowns that take anyone: a supplier, a buyer, or both."""

    role = forms.ChoiceField(label=_("They are a"), choices=[("supplier", _("Supplier")), ("buyer", _("Buyer")), ("both", _("Both"))],
                             initial="supplier")

    class Meta:
        model = Party
        fields = ["name", "phone"]
        widgets = {"phone": forms.TextInput(attrs={"inputmode": "tel", "placeholder": "01XXXXXXXXX"})}

    def save(self, commit=True):
        role = self.cleaned_data.get("role") or "supplier"
        self.instance.is_supplier = role in ("supplier", "both")
        self.instance.is_buyer = role in ("buyer", "both")
        return super().save(commit)
