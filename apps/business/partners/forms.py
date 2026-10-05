from datetime import date

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.business.core.crud import BusinessForm, money_field
from apps.business.core.templatetags.business import num

from . import services
from .models import EntryKind, Partner, PartnerEntry


class PartnerForm(BusinessForm):
    tips = {
        "share_pct": _("Their part of the farm's profit (and loss). All partners' shares together should make 100."),
        "opening_capital": _("Only when you start using the app: the money they had already put into the farm."),
    }
    layout = [("name", "phone"), ("share_pct", "joined_on"), ("opening_capital",), ("notes",)]

    class Meta:
        model = Partner
        fields = ["name", "phone", "share_pct", "joined_on", "opening_capital", "notes"]
        widgets = {"joined_on": forms.DateInput(), "name": forms.TextInput(attrs={"placeholder": _("e.g. Karim Uddin")})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        money_field(self.fields["opening_capital"])
        money_field(self.fields["share_pct"], "%")
        self.fields["opening_capital"].required = False
        self.others = services.other_shares(self.business, self.instance.pk)
        if self.others:
            self.fields["share_pct"].help_text = _("Other partners have %(n)s%% between them.") % {"n": num(self.others)}
        if not self.instance.pk and self.others < 100:
            self.initial.setdefault("share_pct", format((100 - self.others).normalize(), "f"))

    def clean(self):
        data = super().clean()
        data["opening_capital"] = data.get("opening_capital") or 0
        pct = data.get("share_pct")
        if pct is not None and self.others + pct > 100:
            self.add_error("share_pct", _("All shares together can't be more than 100. %(n)s is left.") % {"n": num(max(100 - self.others, 0))})
        return data


class EntryForm(BusinessForm):
    unique_name = ()
    tips = {
        "kind": _("Put money in: capital for the farm. Took money out: their share of profit, or capital taken back."),
    }
    layout = [("date", "kind"), ("amount", "account"), ("notes",)]

    class Meta:
        model = PartnerEntry
        fields = ["date", "kind", "amount", "account", "notes"]
        widgets = {"date": forms.DateInput(), "kind": forms.RadioSelect}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.business.finance.models import Account

        money_field(self.fields["amount"])
        self.fields["account"].queryset = Account.objects.filter(business=self.business)
        self.fields["account"].empty_label = None
        if not self.instance.pk:
            self.initial.setdefault("date", date.today())
            self.initial.setdefault("account", Account.objects.filter(business=self.business, is_default=True).first())

    def clean_date(self):
        d = self.cleaned_data["date"]
        if d > date.today():
            raise forms.ValidationError(_("This date is in the future."))
        return d


__all__ = ["PartnerForm", "EntryForm", "EntryKind"]
