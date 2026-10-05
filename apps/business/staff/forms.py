from datetime import date
from decimal import Decimal

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.business.core.crud import BusinessForm, money_field

from .models import Earning, EarningKind, Worker, WorkerPayment


def _running_cycles(form, field="cycle"):
    from apps.business.ponds.models import CultureCycle, CycleStatus

    cycles = CultureCycle.objects.filter(business=form.business, status=CycleStatus.RUNNING)
    current = getattr(form.instance, f"{field}_id", None)
    if current:
        cycles = cycles | CultureCycle.objects.filter(pk=current)
    form.fields[field].queryset = cycles.distinct().select_related("pond")
    form.fields[field].empty_label = _("Whole farm")


class WorkerForm(BusinessForm):
    tips = {
        "pay_type": _("Monthly: a fixed salary each month. Daily: paid for the days they work (mark them on the work sheet)."),
        "opening_balance": _("Only when you start using the app: wages you already owed them (+), or an advance they already had (− in front)."),
    }
    layout = [("name", "phone"), ("job",), ("pay_type", "rate"), ("started_on", "left_on"), ("address",), ("opening_balance",), ("notes",)]

    class Meta:
        model = Worker
        fields = ["name", "phone", "job", "pay_type", "rate", "started_on", "left_on", "address", "opening_balance", "notes"]
        widgets = {"started_on": forms.DateInput(), "left_on": forms.DateInput(),
                   "name": forms.TextInput(attrs={"placeholder": _("e.g. Rahim Mia")})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        money_field(self.fields["rate"])
        money_field(self.fields["opening_balance"])
        self.fields["opening_balance"].required = False

    def clean(self):
        data = super().clean()
        data["opening_balance"] = data.get("opening_balance") or 0
        if data.get("left_on") and data.get("started_on") and data["left_on"] < data["started_on"]:
            self.add_error("left_on", _("This is before they started."))
        return data


class EarningForm(BusinessForm):
    """Days worked, a month's salary, a bonus, or a deduction."""

    unique_name = ()
    tips = {
        "kind": _("Days worked: for daily workers (the work sheet does this for everyone at once). Monthly salary: one per month. Bonus: Eid bonus, overtime. Deduction: a fine or damage taken off their pay."),
        "cycle": _("Work for one pond? Pick its cycle, and the wage counts towards that pond's cost."),
    }
    layout = [("date", "kind"), ("days", "rate"), ("amount",), ("cycle",), ("notes",)]

    class Meta:
        model = Earning
        fields = ["date", "kind", "days", "rate", "amount", "cycle", "notes"]
        widgets = {"date": forms.DateInput()}

    def __init__(self, *args, worker, **kwargs):
        super().__init__(*args, **kwargs)
        self.worker = worker
        _running_cycles(self)
        money_field(self.fields["rate"])
        money_field(self.fields["amount"])
        for name in ("days", "rate", "amount"):
            self.fields[name].required = False
        self.fields["rate"].help_text = _("Per day. Filled with their usual wage.")
        self.fields["amount"].help_text = _("For days worked it's days × rate, worked out for you.")
        if not self.instance.pk:
            self.initial.setdefault("date", date.today())
            if worker.is_monthly:
                self.initial.setdefault("kind", EarningKind.SALARY)
                self.initial.setdefault("amount", format(worker.salary_for(date.today()).normalize(), "f"))
            else:
                self.initial.setdefault("kind", EarningKind.WORK)
                self.initial.setdefault("days", 1)
            self.initial.setdefault("rate", format(worker.rate.normalize(), "f"))

    def clean(self):
        data = super().clean()
        kind = data.get("kind")
        if kind == EarningKind.WORK:
            if not data.get("days"):
                self.add_error("days", _("How many days?"))
            data["rate"] = data.get("rate") if data.get("rate") is not None else self.worker.rate
            if data.get("days"):
                data["amount"] = (data["days"] * data["rate"]).quantize(Decimal("0.01"))
        else:
            data["days"] = data["rate"] = None
            if not data.get("amount"):
                self.add_error("amount", _("Enter the amount."))
        if kind == EarningKind.SALARY and data.get("date"):
            clash = Earning.objects.filter(worker=self.worker, kind=EarningKind.SALARY, month=data["date"].replace(day=1)).exclude(pk=self.instance.pk)
            if clash.exists():
                self.add_error("date", _("This month's salary is already written. Edit that one instead."))
        return data


class PaymentForm(BusinessForm):
    unique_name = ()
    tips = {
        "kind": _("Wages / salary: paying what they've earned. Advance: money given before the work is done — it's taken off later pay automatically."),
    }
    layout = [("date", "kind"), ("amount", "account"), ("notes",)]

    class Meta:
        model = WorkerPayment
        fields = ["date", "kind", "amount", "account", "notes"]
        widgets = {"date": forms.DateInput()}

    def __init__(self, *args, worker, owed=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.business.finance.models import Account

        self.worker = worker
        money_field(self.fields["amount"])
        self.fields["account"].queryset = Account.objects.filter(business=self.business)
        self.fields["account"].empty_label = None
        if not self.instance.pk:
            self.initial.setdefault("date", date.today())
            self.initial.setdefault("account", Account.objects.filter(business=self.business, is_default=True).first())
            if owed and owed > 0:
                self.initial.setdefault("amount", format(owed.normalize(), "f"))
            else:
                self.initial.setdefault("kind", "advance")


class WorkSheetDayForm(forms.Form):
    """The date and pond on top of the daily work sheet."""

    date = forms.DateField(label=_("Date"), widget=forms.DateInput(attrs={"class": "form-input datepicker", "autocomplete": "off"}, format="%Y-%m-%d"))

    def clean_date(self):
        d = self.cleaned_data["date"]
        if d > date.today():
            raise forms.ValidationError(_("This date is in the future."))
        return d

