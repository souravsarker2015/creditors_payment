from datetime import date
from decimal import Decimal

from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Lender, Loan, LoanRateChange, LoanTransaction, Repayment


def plain(value):
    return format(value.normalize(), "f") if value is not None else value


def _date_input():
    return forms.DateInput(attrs={"class": "form-input datepicker", "autocomplete": "off"}, format="%Y-%m-%d")


def _money_input(**attrs):
    return forms.NumberInput(attrs={"class": "form-input", "step": "any", "min": "0", "inputmode": "decimal", "placeholder": "0", **attrs})


class LenderForm(forms.ModelForm):
    class Meta:
        model = Lender
        fields = ["name", "kind", "phone", "address", "notes"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-input", "placeholder": _("e.g. Sonali Bank, BRAC, Karim bhai")}),
            "kind": forms.Select(attrs={"class": "form-input"}),
            "phone": forms.TextInput(attrs={"class": "form-input", "inputmode": "tel", "placeholder": "01XXXXXXXXX"}),
            "address": forms.TextInput(attrs={"class": "form-input", "placeholder": _("e.g. Jessore branch")}),
            "notes": forms.Textarea(attrs={"class": "form-input", "rows": 2}),
        }

    def __init__(self, *args, business, **kwargs):
        super().__init__(*args, **kwargs)
        self.business = business

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        clash = Lender.objects.filter(business=self.business, name__iexact=name).exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError(_("“%(name)s” is already in your lenders.") % {"name": name})
        return name


class LenderQuickForm(LenderForm):
    class Meta(LenderForm.Meta):
        fields = ["name", "kind", "phone"]


class LoanForm(forms.ModelForm):
    class Meta:
        model = Loan
        fields = ["lender", "name", "account_no", "principal", "taken_on", "account", "rate", "rate_period", "method",
                  "every", "every_unit", "repayment", "first_due", "maturity", "notes"]
        widgets = {
            "lender": forms.Select(attrs={"class": "form-input"}),
            "name": forms.TextInput(attrs={"class": "form-input", "placeholder": _("e.g. New pond digging")}),
            "account_no": forms.TextInput(attrs={"class": "form-input"}),
            "principal": _money_input(min="1"),
            "taken_on": _date_input(),
            "rate": forms.NumberInput(attrs={"class": "form-input", "step": "any", "min": "0", "max": "100", "inputmode": "decimal", "placeholder": "0"}),
            "rate_period": forms.RadioSelect,
            "method": forms.RadioSelect,
            "every": forms.NumberInput(attrs={"class": "form-input", "min": "1", "max": "60", "inputmode": "numeric"}),
            "every_unit": forms.Select(attrs={"class": "form-input"}),
            "repayment": forms.RadioSelect,
            "first_due": _date_input(),
            "maturity": _date_input(),
            "notes": forms.Textarea(attrs={"class": "form-input", "rows": 2}),
        }

    def __init__(self, *args, business, **kwargs):
        super().__init__(*args, **kwargs)
        self.business = business
        qs = Lender.objects.filter(business=business)
        if self.instance.pk:  # keep the current lender even if it was archived
            qs = qs | Lender.all_objects.filter(pk=self.instance.lender_id)
        self.fields["lender"].queryset = qs.distinct().order_by("name")
        self.fields["lender"].empty_label = _("Choose who lent the money…")
        # The page starts a relative's loan as interest-free with no fixed end (see INFORMAL_KINDS).
        self.lender_kinds = {str(pk): kind for pk, kind in self.fields["lender"].queryset.values_list("pk", "kind")}
        _account_field(self.fields["account"], business, _("Not recorded"))
        self.fields["account"].help_text = _("Where the borrowed money went: cash, bank or bKash. It's added to that account's balance on the date received.")
        if not self.instance.pk:
            self.initial.setdefault("taken_on", date.today())
            self.initial.setdefault("account", _default_account(business))
        else:  # "12" and "500000" rather than "12.0000" and "500000.00"
            self.initial["rate"] = plain(self.instance.rate)
            self.initial["principal"] = plain(self.instance.principal)

    def clean(self):
        data = super().clean()
        taken, first, end = data.get("taken_on"), data.get("first_due"), data.get("maturity")
        if taken and end and end <= taken:
            self.add_error("maturity", _("The end date has to be after the date you received the money."))
        if taken and first and first <= taken:
            self.add_error("first_due", _("The first payment has to be after the date you received the money."))
        if first and end and first > end:
            self.add_error("first_due", _("The first payment can't be after the end date."))
        if data.get("repayment") in (Repayment.EQUAL, Repayment.EMI) and not end:
            self.add_error("maturity", _("Pick an end date so the loan can be split into payments."))
        if not data.get("rate"):
            data["rate"] = Decimal("0")
        account = data.get("account")
        self.already_in_balance = None
        if account and taken and account.opening_date and taken < account.opening_date:
            # Received before the account's starting balance: that money is already
            # inside it, so it isn't added again (an old loan entered at setup).
            self.already_in_balance = account
            data["account"] = None
        return data


def _account_field(field, business, empty_label):
    """Which account the money went out of (or came into). Only when the
    finance app is there — loans work on their own too."""
    from apps.business.finance.models import Account

    field.queryset = Account.objects.filter(business=business)
    field.empty_label = empty_label
    field.widget.attrs.setdefault("class", "form-input")


def _default_account(business):
    from apps.business.finance.models import Account

    return Account.objects.filter(business=business, is_default=True).first()


class PaymentForm(forms.ModelForm):
    class Meta:
        model = LoanTransaction
        fields = ["date", "interest", "principal", "charges", "paid_via", "account", "reference", "notes"]
        widgets = {
            "date": _date_input(),
            "interest": _money_input(), "principal": _money_input(), "charges": _money_input(),
            "paid_via": forms.Select(attrs={"class": "form-input"}),
            "reference": forms.TextInput(attrs={"class": "form-input"}),
            "notes": forms.Textarea(attrs={"class": "form-input", "rows": 2}),
        }

    def __init__(self, *args, loan, **kwargs):
        super().__init__(*args, **kwargs)
        self.loan = loan
        for name in ("interest", "principal", "charges"):
            self.fields[name].required = False
        _account_field(self.fields["account"], loan.business, _("Not recorded"))
        if not self.instance.pk:
            self.initial.setdefault("date", date.today())
            self.initial.setdefault("account", _default_account(loan.business))

    def clean(self):
        data = super().clean()
        for name in ("interest", "principal", "charges"):
            data[name] = data.get(name) or Decimal("0")
        if not (data["interest"] + data["principal"] + data["charges"]):
            raise forms.ValidationError(_("Enter how much you paid."))
        if data.get("date") and data["date"] < self.loan.taken_on:
            self.add_error("date", _("This is before the loan was taken."))
        return data


class TopUpForm(forms.ModelForm):
    class Meta:
        model = LoanTransaction
        fields = ["date", "principal", "paid_via", "account", "reference", "notes"]
        labels = {"principal": _("Extra amount received"), "paid_via": _("Received by")}
        widgets = {
            "date": _date_input(), "principal": _money_input(min="1"),
            "paid_via": forms.Select(attrs={"class": "form-input"}),
            "reference": forms.TextInput(attrs={"class": "form-input"}),
            "notes": forms.Textarea(attrs={"class": "form-input", "rows": 2}),
        }

    def __init__(self, *args, loan, **kwargs):
        super().__init__(*args, **kwargs)
        self.loan = loan
        _account_field(self.fields["account"], loan.business, _("Not recorded"))
        if not self.instance.pk:
            self.initial.setdefault("date", date.today())
            self.initial.setdefault("account", _default_account(loan.business))

    def clean(self):
        data = super().clean()
        if not data.get("principal"):
            self.add_error("principal", _("Enter the amount."))
        if data.get("date") and data["date"] < self.loan.taken_on:
            self.add_error("date", _("This is before the loan was taken."))
        return data


class RateChangeForm(forms.ModelForm):
    class Meta:
        model = LoanRateChange
        fields = ["effective_from", "rate"]
        widgets = {
            "effective_from": _date_input(),
            "rate": forms.NumberInput(attrs={"class": "form-input", "step": "any", "min": "0", "max": "100", "inputmode": "decimal"}),
        }

    def __init__(self, *args, loan, **kwargs):
        super().__init__(*args, **kwargs)
        self.loan = loan

    def clean_effective_from(self):
        d = self.cleaned_data["effective_from"]
        if d <= self.loan.taken_on:
            raise forms.ValidationError(_("Pick a date after the loan was taken. To change the starting rate, edit the loan."))
        if self.loan.rate_changes.filter(effective_from=d).exists():
            raise forms.ValidationError(_("There's already a rate change on this date."))
        return d


class CloseForm(forms.Form):
    closed_on = forms.DateField(label=_("Closed on"), widget=_date_input())
