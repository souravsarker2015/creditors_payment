from datetime import date

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.business.core.crud import BusinessForm, money_field

from .models import Equipment, Service


def _accounts(form, field="account"):
    from apps.business.finance.models import Account

    form.fields[field].queryset = Account.objects.filter(business=form.business)
    form.fields[field].empty_label = _("Not paid now")


class EquipmentForm(BusinessForm):
    tips = {
        "condition": _("Mark it “Needs repair” when it breaks; it shows on the farm's to-do list until it's fixed."),
        "account": _("Leave empty for something you already owned or haven't paid for yet — no money leaves an account."),
        "service_every_days": _("The app reminds you when a service is due, counting from the last one."),
    }
    layout = [("name", "kind"), ("pond", "condition"), ("#", _("Purchase (optional)")), ("bought_on", "cost"), ("account",),
              ("#", _("Servicing")), ("service_every_days",), ("notes",)]

    class Meta:
        model = Equipment
        fields = ["name", "kind", "pond", "condition", "bought_on", "cost", "account", "service_every_days", "notes"]
        widgets = {"bought_on": forms.DateInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _accounts(self)
        money_field(self.fields["cost"])
        self.fields["cost"].required = False
        self.fields["pond"].empty_label = _("Whole farm / moves around")

    def clean(self):
        data = super().clean()
        data["cost"] = data.get("cost") or 0
        if data.get("account") and not data.get("bought_on"):
            self.add_error("bought_on", _("When was it bought? The money leaves the account on that day."))
        if data.get("bought_on") and data["bought_on"] > date.today():
            self.add_error("bought_on", _("This date is in the future."))
        return data


class ServiceForm(BusinessForm):
    unique_name = ()
    tips = {
        "cost": _("Parts and labour together. It's a farm cost."),
    }
    layout = [("date", "kind"), ("description",), ("cost", "account"), ("notes",)]

    class Meta:
        model = Service
        fields = ["date", "kind", "description", "cost", "account", "notes"]
        widgets = {"date": forms.DateInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.business.finance.models import Account

        _accounts(self)
        money_field(self.fields["cost"])
        self.fields["cost"].required = False
        if not self.instance.pk:
            self.initial.setdefault("date", date.today())
            self.initial.setdefault("account", Account.objects.filter(business=self.business, is_default=True).first())

    def clean(self):
        data = super().clean()
        data["cost"] = data.get("cost") or 0
        if data.get("date") and data["date"] > date.today():
            self.add_error("date", _("This date is in the future."))
        return data
