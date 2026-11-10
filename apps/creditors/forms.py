from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from .models import Creditor, InterestBasis, InterestType, Transaction
from apps.core.ledger_views import UniqueNameMixin
from apps.core.receipts import ReceiptInput, attach_viewer
from apps.core.templatetags.ui import money
from apps.wallets.forms import WalletFieldMixin

# The fields that make up a creditor's interest terms.
INTEREST_TERMS = ("interest_type", "interest_basis", "interest_rate", "interest_fixed_amount")


class CreditorForm(UniqueNameMixin, forms.ModelForm):
    owner_related_name = "creditors"

    interest_from = forms.DateField(
        required=False,
        label=_("Count interest from"),
        widget=forms.DateInput(attrs={"class": "form-input datepicker", "placeholder": _("From the first amount borrowed")}),
        help_text=_("Interest builds up from this day. When you change the terms it starts from today — pick an earlier day if the agreement started earlier. Leave empty to count from the first amount borrowed."),
    )
    post_old_interest = forms.BooleanField(required=False, initial=True)

    field_order = ["name", "category", "phone", "due_date", *INTEREST_TERMS, "interest_from", "post_old_interest", "note"]

    class Meta:
        model = Creditor
        fields = ["name", "category", "phone", "due_date", "interest_type", "interest_basis", "interest_rate", "interest_fixed_amount", "note"]
        widgets = {
            "name": forms.TextInput(attrs={
                "class": "form-input",
                "placeholder": _("Full Name")
            }),
            "category": forms.Select(attrs={
                "class": "form-input",
            }),
            "phone": forms.TextInput(attrs={
                "class": "form-input",
                "placeholder": _("Phone Number (optional)")
            }),
            "due_date": forms.DateInput(attrs={
                "class": "form-input datepicker",
                "placeholder": _("Select a due date (optional)"),
            }),
            "interest_type": forms.Select(attrs={
                "class": "form-input",
                "x-model": "interestType",
            }),
            "interest_basis": forms.Select(attrs={
                "class": "form-input",
                "x-model": "interestBasis",
            }),
            "interest_rate": forms.NumberInput(attrs={
                "class": "form-input",
                "placeholder": _("e.g. 2 (% per period, optional)"),
                "step": "0.01",
                "min": "0",
            }),
            "interest_fixed_amount": forms.NumberInput(attrs={
                "class": "form-input",
                "placeholder": _("e.g. 2000 (flat ৳ amount, optional)"),
                "step": "0.01",
                "min": "0",
            }),
            "note": forms.Textarea(attrs={
                "class": "form-input",
                "placeholder": _("Add any additional details..."),
                "rows": 3
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.posted_old_interest = None
        self.old_accrued = 0
        if self.instance.pk:
            self.fields["interest_from"].initial = self.instance.interest_from
            if self.instance.interest_type:
                self.old_accrued = self.instance.accrued_interest
        if self.old_accrued > 0:
            field = self.fields["post_old_interest"]
            field.label = _("Post the %(amount)s built up under the current terms first") % {"amount": money(self.old_accrued)}
            field.help_text = _("Only used if you change the terms above, so the interest that has already built up isn't lost.")
        else:
            del self.fields["post_old_interest"]

    def terms_changed(self):
        return bool(self.instance.pk) and any(name in self.changed_data for name in INTEREST_TERMS)

    def clean(self):
        cleaned_data = super().clean()
        interest_type = cleaned_data.get("interest_type")
        interest_basis = cleaned_data.get("interest_basis")
        interest_rate = cleaned_data.get("interest_rate")
        interest_fixed_amount = cleaned_data.get("interest_fixed_amount")

        if interest_type == InterestType.FIXED:
            # One-time flat charge — no period, no basis, no rate.
            if not interest_fixed_amount:
                self.add_error(
                    "interest_fixed_amount",
                    _("Enter a flat interest amount, or clear the interest type."),
                )
            cleaned_data["interest_rate"] = None
            cleaned_data["interest_basis"] = None
        elif interest_type:
            # A periodic type — basis decides whether rate or fixed_amount applies.
            if interest_basis == InterestBasis.FIXED:
                if not interest_fixed_amount:
                    self.add_error(
                        "interest_fixed_amount",
                        _("Enter a flat interest amount, or choose Percentage instead."),
                    )
                cleaned_data["interest_rate"] = None
            elif interest_basis == InterestBasis.PERCENTAGE:
                if not interest_rate:
                    self.add_error(
                        "interest_rate",
                        _("Enter an interest rate, or choose Fixed Amount instead."),
                    )
                cleaned_data["interest_fixed_amount"] = None
            else:
                self.add_error("interest_basis", _("Choose Percentage or Fixed Amount."))
        else:
            cleaned_data["interest_basis"] = None
            cleaned_data["interest_rate"] = None
            cleaned_data["interest_fixed_amount"] = None

        start = cleaned_data.get("interest_from")
        if start and start > timezone.localdate():
            self.add_error("interest_from", _("Pick today or an earlier day."))
        elif (start and "interest_from" in self.changed_data and start < timezone.localdate()
                and cleaned_data.get("post_old_interest") and self.terms_changed()):
            # Posting counts every day up to today under the old terms; starting the
            # new ones earlier would charge those days twice.
            self.add_error("interest_from", _("The interest built up so far is being posted, so the new terms can only start today. Untick that box to count the new terms from an earlier day."))
        return cleaned_data

    def save(self, commit=True):
        """New interest terms count from today unless a day is picked; what
        built up under the old terms can be posted first, so it isn't lost."""
        start_picked = "interest_from" in self.changed_data
        if self.terms_changed():
            if self.cleaned_data.get("post_old_interest") and self.old_accrued > 0:
                # Post on a fresh copy: this form has already put the new terms on self.instance.
                self.posted_old_interest = Creditor.objects.get(pk=self.instance.pk).post_accrued_interest()
            if not start_picked:
                self.instance.interest_from = timezone.localdate()
        if start_picked or not self.instance.pk:
            self.instance.interest_from = self.cleaned_data.get("interest_from")
        return super().save(commit)

class TransactionForm(WalletFieldMixin, forms.ModelForm):
    class Meta:
        model = Transaction
        fields = ["transaction_type", "amount", "wallet", "date", "note", "receipt"]
        widgets = {
            "receipt": ReceiptInput(),
            "transaction_type": forms.Select(attrs={"class": "form-input"}),
            "amount": forms.NumberInput(attrs={"class": "form-input", "placeholder": "0.00"}),
            "date": forms.DateInput(attrs={"class": "form-input datepicker", "placeholder": _("Select Date")}),
            "note": forms.TextInput(attrs={"class": "form-input", "placeholder": _("Quick note...")}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        attach_viewer(self, "loan")
