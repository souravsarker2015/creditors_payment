from datetime import date
from decimal import Decimal

from django import forms
from django.core.validators import MaxLengthValidator
from django.utils.translation import gettext_lazy as _

from .models import Card, CardBank, CardEntry, CardNetwork, EmiPlan, EntryKind, MfsFees, PayRoute
from .services import q

MONEY = {"inputmode": "decimal", "step": "0.01", "placeholder": "0.00"}
RATE = {"inputmode": "decimal", "step": "0.01", "placeholder": "0"}
DATE = {"class": "form-input datepicker", "autocomplete": "off"}


def _input(**attrs):
    return forms.TextInput(attrs={"class": "form-input", **attrs})


def _num(**attrs):
    return forms.NumberInput(attrs={"class": "form-input", **attrs})


class CardForm(forms.ModelForm):
    GROUPS = (       # (title, fields, help, folded) — the folded ones are optional, under "More details"
        (_("The card"), ("name", "bank"),
         _("Only what helps you tell your cards apart. Never type the full card number, the CVV or the PIN — the app doesn't need them."), False),
        (_("Bill and pay-by dates"), ("statement_day", "due_day"),
         _("Printed on your card bill (statement). Everything until the bill day lands on that bill; pay it in full by the pay-by day and there's no interest."), False),
        (_("Limit and fee"), ("limit", "transfer_fee_rate"), "", False),
        (_("What you owe today"), ("opening_balance", "opening_date"),
         _("What you already owe on the card today (0 for a new card). Everything you record from then on adds to it or takes it down."), False),
        (_("Look and number"), ("network", "color", "last4", "expiry"), _("For the picture of the card and a reminder before it runs out."), True),
        (_("Interest and other fees"), ("interest_rate", "min_due_rate", "min_due_floor", "late_fee", "annual_fee", "annual_fee_month", "cash_limit"),
         _("For the minimum payment, the interest warning and the annual fee reminder. Left empty, the usual values are used."), True),
        (_("Note"), ("note",), "", True),
    )

    class Meta:
        model = Card
        fields = ["name", "bank", "network", "color", "last4", "expiry", "limit", "cash_limit", "statement_day", "due_day",
                  "transfer_fee_rate", "interest_rate", "min_due_rate", "min_due_floor", "late_fee", "annual_fee", "annual_fee_month",
                  "opening_balance", "opening_date", "note"]
        widgets = {
            "name": _input(placeholder=_("e.g. UCB Visa Platinum"), autofocus=True),
            "bank": forms.Select(attrs={"class": "form-input"}),
            "network": forms.Select(attrs={"class": "form-input"}),
            "color": forms.Select(attrs={"class": "form-input"}),
            "last4": _input(inputmode="numeric", maxlength=4, placeholder="1234", autocomplete="off"),
            "expiry": _input(inputmode="numeric", maxlength=5, placeholder="08/28", autocomplete="off"),
            "limit": _num(**MONEY),
            "cash_limit": _num(**MONEY),
            "statement_day": _num(min=1, max=31, inputmode="numeric", placeholder="5"),
            "due_day": _num(min=1, max=31, inputmode="numeric", placeholder="25"),
            "transfer_fee_rate": _num(**RATE),
            "interest_rate": _num(**{**RATE, "placeholder": "25"}),
            "min_due_rate": _num(**RATE),
            "min_due_floor": _num(**MONEY),
            "late_fee": _num(**MONEY),
            "annual_fee": _num(**MONEY),
            "annual_fee_month": forms.Select(attrs={"class": "form-input"}),
            "opening_balance": _num(**MONEY),
            "opening_date": forms.DateInput(attrs=DATE, format="%Y-%m-%d"),
            "note": forms.Textarea(attrs={"class": "form-input", "rows": 2}),
        }
        help_texts = {
            "last4": _("Optional. Only the last 4."),
            "expiry": _("Optional. For a reminder before it runs out."),
            "cash_limit": _("Optional. How much of the limit can go to bKash / Nagad or cash."),
            "statement_day": _("The day of the month the bill is made, 1–31."),
            "due_day": _("The last day to pay it, 1–31. If it comes before the bill day, it's in the next month."),
            "transfer_fee_rate": _("% the bank takes when you send money from this card to bKash, Nagad or Rocket. 0 if free. You can change it on each entry."),
            "interest_rate": _("% a year, charged when a bill isn't paid in full. Usually 20–27%."),
            "min_due_rate": _("% of the bill, usually 5%."),
            "min_due_floor": _("The smallest minimum payment, e.g. ৳500."),
            "late_fee": _("Charged if not even the minimum is paid in time."),
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        last4 = self.fields["last4"]                 # a whole number typed by mistake gets a plain message, not "at most 4 characters"
        last4.max_length = None
        last4.validators = [v for v in last4.validators if not isinstance(v, MaxLengthValidator)]
        for name, model, kind, empty in (("bank", CardBank, "card_bank", _("Choose the bank")), ("network", CardNetwork, "card_network", _("Don't say"))):
            f = self.fields[name]
            keep = getattr(self.instance, f"{name}_id", None)
            qs = model.objects.filter(user=user, is_active=True)
            f.queryset = (qs | model.objects.filter(pk=keep)).distinct() if keep else qs
            f.empty_label = empty
            f.quick_add = kind            # the + beside it (apps/core/quick_create.py)
        self.fields["bank"].help_text = _("Not in the list? Tap + to add it.")
        self.fields["annual_fee_month"].choices = [("", "—")] + list(self.fields["annual_fee_month"].choices)[1:]
        for name in ("transfer_fee_rate", "min_due_rate", "min_due_floor", "opening_balance"):
            self.fields[name].required = False
        for name in ("transfer_fee_rate", "interest_rate", "min_due_rate"):
            self.fields[name].percent = True
        for name in ("limit", "cash_limit", "min_due_floor", "late_fee", "annual_fee", "opening_balance"):
            self.fields[name].taka = True

    def groups(self):
        """(title, bound fields, help, folded, open): a folded group opens by itself when one of its fields has an error."""
        out = []
        for title, names, help, folded in self.GROUPS:
            fields = [self[f] for f in names]
            out.append((title, fields, help, folded, not folded or any(f.errors for f in fields)))
        return out

    def clean_last4(self):
        digits = "".join(ch for ch in self.cleaned_data.get("last4", "") if ch.isdigit())
        if digits and len(digits) != 4:
            raise forms.ValidationError(_("Enter the last 4 digits only — the full number isn't needed."))
        return digits

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if Card.objects.filter(user=self.user, name__iexact=name).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(_("You already have a card called “%(name)s”.") % {"name": name})
        return name

    def clean(self):
        data = super().clean()
        defaults = {"transfer_fee_rate": Decimal(0), "min_due_rate": Decimal(5), "min_due_floor": Decimal(500), "opening_balance": Decimal(0)}
        for k, v in defaults.items():
            if data.get(k) is None:
                data[k] = v
        if data.get("cash_limit") and data.get("limit") and data["cash_limit"] > data["limit"]:
            self.add_error("cash_limit", _("This can't be more than the credit limit."))
        return data


KIND_FIELDS = {
    EntryKind.CASH: ["card", "wallet", "amount", "fee_rate", "fee", "date", "note"],
    EntryKind.SPEND: ["card", "amount", "date", "note"],
    EntryKind.CHARGE: ["card", "charge_type", "amount", "date", "note"],
    EntryKind.PAY: ["card", "wallet", "route", "amount", "fee_rate", "fee", "date", "note"],
    EntryKind.REFUND: ["card", "amount", "date", "note"],
}


class EntryForm(forms.ModelForm):
    class Meta:
        model = CardEntry
        fields = ["card", "wallet", "charge_type", "route", "amount", "fee_rate", "fee", "date", "note"]
        widgets = {
            "card": forms.Select(attrs={"class": "form-input"}),
            "wallet": forms.Select(attrs={"class": "form-input"}),
            "charge_type": forms.Select(attrs={"class": "form-input"}),
            "route": forms.Select(attrs={"class": "form-input"}),
            "amount": _num(**MONEY),
            "fee_rate": _num(**RATE),
            "fee": _num(**MONEY),
            "date": forms.DateInput(attrs=DATE, format="%Y-%m-%d"),
            "note": _input(),
        }

    def __init__(self, *args, user, kind, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.core.templatetags.ui import money
        from apps.wallets.models import Wallet, WalletKind
        from apps.wallets.services import balances

        self.user, self.kind = user, kind
        keep = set(KIND_FIELDS[kind])
        for name in list(self.fields):
            if name not in keep:
                del self.fields[name]
        cards = Card.objects.filter(user=user, is_active=True)
        if self.instance.pk:
            cards = (cards | Card.objects.filter(pk=self.instance.card_id)).distinct()
        self.fields["card"].queryset = cards
        self.fields["card"].empty_label = None
        self.fields["card"].label = _("Card")
        if "wallet" in self.fields:
            wallets = Wallet.objects.filter(user=user, is_active=True)
            if self.instance.wallet_id:
                wallets = (wallets | Wallet.objects.filter(pk=self.instance.wallet_id)).distinct()
            held = balances(user)
            mobile_first = sorted(wallets, key=lambda w: (w.kind != WalletKind.MOBILE, w.name.lower()))
            self.fields["wallet"].queryset = wallets
            self.fields["wallet"].quick_add = "card_wallet"
            self.fields["wallet"].choices = ([("", _("Not from a wallet"))] if kind == EntryKind.PAY else [("", "—")]) + [
                (w.pk, f"{w.name} · {money(held.get(w.pk, w.opening_balance))}") for w in mobile_first]
            if kind == EntryKind.CASH:
                self.fields["wallet"].required = True
                self.fields["wallet"].label = _("Sent to")
                self.fields["wallet"].help_text = _("The bKash, Nagad or Rocket wallet (or bank) the money went to. Its balance goes up.")
                self.fields["amount"].label = _("Amount received")
                self.fields["fee"].help_text = _("Added to what you owe on the card.")
            else:
                self.fields["wallet"].required = False
                self.fields["wallet"].label = _("Paid from")
                self.fields["wallet"].help_text = _("The payment and its fee come out of this wallet.")
                self.fields["fee"].help_text = _("The mobile banking (or bank) charge. It comes out of the wallet, not off the card.")
        if "route" in self.fields:
            self.fields["route"].required = False
            self.fields["route"].choices = list(PayRoute.choices)
        if "charge_type" in self.fields:
            self.fields["charge_type"].required = True
            self.fields["charge_type"].choices = [c for c in self.fields["charge_type"].choices if c[0]]
        if "fee_rate" in self.fields:
            self.fields["fee_rate"].label = _("Fee %")
            self.fields["fee_rate"].percent = True
            self.fields["fee"].required = False
            self.fields["fee"].taka = True
            # live fee: amount × rate, until the fee is typed by hand (cards/entry_form.html)
            self.fields["fee_rate"].widget.attrs.update({"x-model": "rate", "@input": "typed = false"})
            self.fields["fee"].widget.attrs.update({"x-model": "fee", "@input": "typed = true"})
            self.fields["amount"].widget.attrs.update({"x-model": "amount"})
        if "wallet" in self.fields:
            self.fields["wallet"].widget.attrs.update({"x-model": "wallet"})
        if "route" in self.fields:
            self.fields["route"].widget.attrs.update({"x-model": "route"})
        self.fields["card"].widget.attrs.update({"x-model": "card"})
        self.fields["note"].required = False
        if kind == EntryKind.SPEND:
            self.fields["note"].widget.attrs["placeholder"] = _("What did you buy? e.g. Laptop, Daraz order")
        elif kind == EntryKind.PAY:
            self.fields["amount"].label = _("Amount paid to the card")

    def clean(self):
        data = super().clean()
        amount = data.get("amount")
        if amount is not None and amount <= 0:
            self.add_error("amount", _("Enter an amount above zero."))
        if data.get("date") and data["date"] > date.today():
            self.add_error("date", _("This date is in the future."))
        if "fee" in self.fields:
            rate = data.get("fee_rate")
            if data.get("fee") in (None, "") and rate and amount:
                data["fee"] = q(amount * rate / 100)
            data["fee"] = data.get("fee") or Decimal(0)
            if data["fee"] < 0:
                self.add_error("fee", _("The fee can't be below zero."))
        if self.kind == EntryKind.PAY:
            w = data.get("wallet")
            route = data.get("route")
            if w is None or w.kind != "mobile":
                data["route"] = PayRoute.DIRECT
            elif route not in (PayRoute.MFS_BILL, PayRoute.MFS_BANK):
                data["route"] = PayRoute.MFS_BILL
        return data

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.kind = self.kind
        if "fee" in self.cleaned_data:
            obj.fee = self.cleaned_data["fee"]
        if "route" in self.cleaned_data:
            obj.route = self.cleaned_data["route"]
        if commit:
            obj.save()
        return obj


class EmiForm(forms.ModelForm):
    class Meta:
        model = EmiPlan
        fields = ["card", "title", "amount", "months", "rate", "fee", "start", "note"]
        widgets = {
            "card": forms.Select(attrs={"class": "form-input"}),
            "title": _input(placeholder=_("e.g. Laptop, the March bill")),
            "amount": _num(**MONEY),
            "months": forms.Select(attrs={"class": "form-input"}, choices=[(n, n) for n in (3, 6, 9, 12, 18, 24, 36)]),
            "rate": _num(**RATE),
            "fee": _num(**MONEY),
            "start": forms.DateInput(attrs=DATE, format="%Y-%m-%d"),
            "note": _input(),
        }
        help_texts = {
            "rate": _("% a year. 0 for a 0% EMI."),
            "fee": _("One-time, added to the next bill. Often 0–1% of the amount."),
            "start": _("The day the bank turned it into EMI. The first installment comes on the bill after."),
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        cards = Card.objects.filter(user=user, is_active=True)
        if self.instance.pk:
            cards = (cards | Card.objects.filter(pk=self.instance.card_id)).distinct()
        self.fields["card"].queryset = cards
        self.fields["card"].empty_label = None
        self.fields["card"].label = _("Card")
        self.fields["months"].widget.choices = [(n, _("%(n)s months") % {"n": n}) for n in (3, 6, 9, 12, 18, 24, 36)]
        self.fields["rate"].required = self.fields["fee"].required = False
        self.fields["rate"].percent = True
        self.fields["fee"].taka = True
        for name, model in (("amount", "amount"), ("months", "months"), ("rate", "rate"), ("start", "start")):
            self.fields[name].widget.attrs["x-model"] = model

    def clean(self):
        data = super().clean()
        data["rate"] = data.get("rate") or Decimal(0)
        data["fee"] = data.get("fee") or Decimal(0)
        return data


class MfsFeesForm(forms.ModelForm):
    class Meta:
        model = MfsFees
        fields = ["pays_bills", "bill_rate", "bank_rate", "note"]
        widgets = {
            "bill_rate": _num(**RATE),
            "bank_rate": _num(**RATE),
            "note": _input(placeholder=_("e.g. free for City Bank cards")),
        }
        help_texts = {
            "pays_bills": _("Its app can pay credit card bills (Pay Bill → Credit card)."),
            "bill_rate": _("% charged when you pay a card bill straight from it. 0 if free."),
            "bank_rate": _("% charged to send money to a bank account or debit card — when you pay the card from the bank."),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("bill_rate", "bank_rate"):
            self.fields[name].required = False
            self.fields[name].percent = True

    def clean(self):
        data = super().clean()
        data["bill_rate"] = data.get("bill_rate") or Decimal(0)
        data["bank_rate"] = data.get("bank_rate") or Decimal(0)
        return data


class CorrectForm(forms.Form):
    """Type what the bank says you owe; the difference is saved as a correction."""

    actual = forms.DecimalField(label=_("What you really owe on it now"), max_digits=12, decimal_places=2,
                                widget=forms.NumberInput(attrs={"class": "form-input", **MONEY}))
    note = forms.CharField(label=_("Note"), required=False, max_length=200,
                           widget=forms.TextInput(attrs={"class": "form-input", "placeholder": _("e.g. checked in the bank app")}))


class PayOffForm(forms.Form):
    closed_on = forms.DateField(label=_("Paid off on"), initial=date.today,
                                widget=forms.DateInput(attrs=DATE, format="%Y-%m-%d"))


# ── The + beside a dropdown (apps/core/quick_create.py) ─────────────────────

class _NameForm(forms.ModelForm):
    allow_same_name = True                     # the popup picks an existing one instead of refusing it

    def clean_name(self):
        return self.cleaned_data["name"].strip()


class CardBankForm(_NameForm):
    class Meta:
        model = CardBank
        fields = ["name"]
        widgets = {"name": forms.TextInput(attrs={"class": "form-input", "placeholder": _("e.g. UCB, EBL, DBBL, City Bank")})}


class CardNetworkForm(_NameForm):
    class Meta:
        model = CardNetwork
        fields = ["name"]
        widgets = {"name": forms.TextInput(attrs={"class": "form-input", "placeholder": _("e.g. Visa, Mastercard, Amex")})}


class QuickWalletForm(_NameForm):
    """A new wallet from the + beside “Sent to” / “Paid from”: usually bKash, Nagad or Rocket."""

    class Meta:
        from apps.wallets.models import Wallet

        model = Wallet
        fields = ["name", "kind", "opening_balance"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-input", "placeholder": _("e.g. bKash, Nagad, Rocket")}),
            "kind": forms.Select(attrs={"class": "form-input"}),
            "opening_balance": forms.NumberInput(attrs={"class": "form-input", **MONEY}),
        }
        help_texts = {"opening_balance": _("What it holds today.")}

    def __init__(self, *args, **kwargs):
        from apps.wallets.models import WalletKind

        super().__init__(*args, **kwargs)
        self.fields["kind"].initial = WalletKind.MOBILE
        self.fields["opening_balance"].required = False

    def clean_opening_balance(self):
        return self.cleaned_data.get("opening_balance") or Decimal(0)
