from django import forms

from apps.core.ledger_views import UniqueNameMixin
from django.utils.translation import gettext_lazy as _
from django.urls import reverse_lazy
from .models import Contributor, ContributorCategory, Contribution
from apps.core import people_categories
from apps.wallets.forms import WalletFieldMixin

class ContributorCategoryForm(people_categories.NameForm, forms.ModelForm):
    """The + beside Category: a new category, by name."""

    class Meta:
        model = ContributorCategory
        fields = ["name"]
        widgets = {"name": forms.TextInput(attrs={"class": "form-input", "placeholder": _("e.g. Neighbour, Office colleague")})}


class ContributorForm(UniqueNameMixin, forms.ModelForm):
    owner_related_name = "contributors"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.business.core.audit import current_user

        user = self.instance.user if self.instance.user_id else current_user()
        people_categories.setup_field(self, ContributorCategory, user, user.contributors.all() if user and user.is_authenticated else None,
                                      reverse_lazy("contributor_categories"), "contributor_category")

    class Meta:
        model = Contributor
        fields = ["name", "category", "phone", "note"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-input", "placeholder": _("Full Name")}),
            "category": forms.Select(attrs={"class": "form-input"}),
            "phone": forms.TextInput(attrs={"class": "form-input", "placeholder": _("Phone Number (optional)")}),
            "note": forms.Textarea(attrs={
                "class": "form-input",
                "placeholder": _("Add any additional details..."),
                "rows": 3
            }),
        }

class ContributionForm(WalletFieldMixin, forms.ModelForm):
    class Meta:
        model = Contribution
        fields = ["amount", "wallet", "date", "note"]
        widgets = {
            "amount": forms.NumberInput(attrs={"class": "form-input", "placeholder": "0.00"}),
            "date": forms.DateInput(attrs={"class": "form-input datepicker", "placeholder": _("Select Date")}),
            "note": forms.Textarea(attrs={
                "class": "form-input",
                "placeholder": _("Additional details..."),
                "rows": 2
            }),
        }
