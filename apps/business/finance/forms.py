from datetime import date

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.business.core.crud import BusinessForm, money_field

from .models import Account, Category


class CategoryForm(BusinessForm):
    layout = [("name", "name_bn"), ("type", "scope"), ("parent",), ("notes",)]
    unique_name = ()

    class Meta:
        model = Category
        fields = ["name", "name_bn", "type", "scope", "parent", "notes"]
        widgets = {"name": forms.TextInput(attrs={"placeholder": _("e.g. School fees")})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        qs = Category.objects.filter(business=self.business, parent=None)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        self.fields["parent"].queryset = qs
        self.fields["parent"].empty_label = _("— Main category —")
        self.fields["parent"].help_text = _("Put it inside another category (e.g. Children › School fees), or leave as a main category.")
        self.fields["parent"].label_from_instance = lambda c: f"{c.display_name} ({c.get_type_display()}, {c.get_scope_display()})"
        if self.instance.pk and self.instance.children.exists():
            self.fields["parent"].disabled = True
            self.fields["parent"].help_text = _("It has its own sub-categories, so it stays a main category.")

    def clean(self):
        data = super().clean()
        parent = data.get("parent")
        if parent:  # a sub-category always matches its parent
            data["type"], data["scope"] = parent.type, parent.scope
        name = (data.get("name") or "").strip()
        clash = Category.objects.filter(business=self.business, type=data.get("type"), scope=data.get("scope"), parent=parent,
                                        name__iexact=name).exclude(pk=self.instance.pk)
        if name and clash.exists():
            self.add_error("name", _("“%(value)s” already exists here.") % {"value": name})
        if self.instance.pk and self.instance.is_system and data.get("type") != self.instance.type:
            self.add_error("type", _("This category is filled in automatically; its type can't change."))
        return data


class AccountForm(BusinessForm):
    layout = [("name", "kind"), ("institution", "number"), ("opening_balance", "opening_date"), ("is_default",), ("notes",)]

    class Meta:
        model = Account
        fields = ["name", "kind", "institution", "number", "opening_balance", "opening_date", "is_default", "notes"]
        widgets = {"name": forms.TextInput(attrs={"placeholder": _("e.g. Sonali Bank, bKash personal")}), "opening_date": forms.DateInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        money_field(self.fields["opening_balance"])
        self.fields["opening_balance"].required = False
        if not self.instance.pk:
            self.initial.setdefault("opening_date", date.today())

    def clean(self):
        data = super().clean()
        data["opening_balance"] = data.get("opening_balance") or 0
        return data
