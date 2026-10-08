from datetime import date

from django import forms

from apps.core.receipts import ReceiptInput, attach_viewer
from django.utils.translation import gettext_lazy as _

from apps.business.core.crud import BusinessForm, money_field

from .models import Account, Budget, Category, CategoryType, FamilyMember, RecurringTransaction, Scope, Transaction, Transfer


class CategoryForm(BusinessForm):
    tips = {
        "type": _("Expense: money going out. Income: money coming in."),
        "scope": _("Farm business counts in the farm's profit. Household and Personal are kept apart, so family spending doesn't make the farm look worse."),
        "name_bn": _("Shown instead of the English name when the app is in Bangla."),
    }
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
    tips = {
        "opening_balance": _("How much was in this account on the opening date. Everything recorded after that is added or taken off."),
        "opening_date": _("The day you counted the opening balance. Usually the day you start using the app."),
        "number": _("Account or wallet number, only for your reference."),
    }
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


class CategoryQuickForm(BusinessForm):
    """Add a category without leaving the form you're filling in."""

    unique_name = ()
    layout = [("name",), ("type", "scope"), ("parent",)]

    class Meta:
        model = Category
        fields = ["name", "type", "scope", "parent"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["parent"].queryset = Category.objects.filter(business=self.business, parent=None)
        self.fields["parent"].empty_label = _("— Main category —")
        self.fields["parent"].label_from_instance = lambda c: c.display_name
        self.initial.setdefault("type", CategoryType.EXPENSE)

    def clean(self):
        data = super().clean()
        parent = data.get("parent")
        if parent:
            data["type"], data["scope"] = parent.type, parent.scope
        name = (data.get("name") or "").strip()
        if name and Category.objects.filter(business=self.business, type=data.get("type"), scope=data.get("scope"),
                                            parent=parent, name__iexact=name).exists():
            self.add_error("name", _("“%(value)s” already exists here.") % {"value": name})
        return data


class AccountQuickForm(BusinessForm):
    layout = [("name", "kind")]

    class Meta:
        model = Account
        fields = ["name", "kind"]


class TransactionForm(BusinessForm):
    """One expense or income. Type is chosen by the category picked."""

    tips = {
        "category": _("What the money was for. Farm categories count in the farm's profit; household and personal ones don't."),
        "account": _("Which cash box, bank or wallet the money came out of or went into. Its balance changes."),
        "party": _("Only a note of who it was. It doesn't create any Baki; use Baki for money owed."),
        "cycle": _("Medicine, lime, labour, pond rent… for one pond? Pick its cycle and the cost is added to that pond's profit and loss."),
        "receipt": _("A photo of the memo or receipt, to check later."),
    }
    unique_name = ()
    layout = [("#", _("What and how much")), ("category", "amount"), ("date", "account"), ("description",),
              ("#", _("More (optional)")), ("party", "cycle"), ("receipt",), ("notes",)]

    class Meta:
        model = Transaction
        fields = ["date", "category", "amount", "account", "description", "party", "member", "cycle", "receipt", "notes"]
        widgets = {"date": forms.DateInput(), "description": forms.TextInput(attrs={"placeholder": _("e.g. 3 workers, pond cleaning")}),
                   "receipt": ReceiptInput()}

    def __init__(self, *args, scope=None, **kwargs):
        super().__init__(*args, **kwargs)
        attach_viewer(self, "farm")
        from apps.business.parties.models import Party
        from apps.business.ponds.models import CultureCycle, CycleStatus

        b = self.business
        self.scope = scope or (self.instance.category.scope if self.instance.pk else Scope.BUSINESS)
        cats = Category.objects.filter(business=b, scope=self.scope)
        self.fields["category"].queryset = cats.select_related("parent")
        self.fields["category"].empty_label = _("Choose a category…")
        self.fields["category"].biz_quick_add = "category"
        self.fields["account"].queryset = Account.objects.filter(business=b)
        self.fields["account"].empty_label = _("Not recorded")
        self.fields["account"].biz_quick_add = "account"
        self.fields["party"].queryset = Party.objects.filter(business=b)
        self.fields["party"].empty_label = _("Nobody in particular")
        self.fields["party"].biz_quick_add = "party"
        self.fields["party"].help_text = _("Only to remember who — it does not create any baki.")
        cycles = CultureCycle.objects.filter(business=b, status=CycleStatus.RUNNING)
        if self.instance.pk and self.instance.cycle_id:
            cycles = cycles | CultureCycle.objects.filter(pk=self.instance.cycle_id)
        self.fields["cycle"].queryset = cycles.distinct().select_related("pond")
        self.fields["cycle"].empty_label = _("Not for one pond")
        self.fields["cycle"].help_text = _("Put this cost on one pond's cycle, so its profit is right.")
        money_field(self.fields["amount"])
        if self.scope != Scope.BUSINESS:
            for name in ("cycle", "party"):
                self.fields.pop(name)
            self.fields["member"].queryset = FamilyMember.objects.filter(business=b)
            self.fields["member"].empty_label = _("Not one person")
            self.fields["member"].biz_quick_add = "family_member"
            self.fields["member"].help_text = _("Who earned it (or spent it). The Family income page adds up each person's share.")
            self.layout = [("#", _("What and how much")), ("category", "amount"), ("date", "account"), ("member",), ("description",),
                           ("#", _("More (optional)")), ("receipt",), ("notes",)]
        else:
            self.fields.pop("member")
        if not self.instance.pk:
            self.initial.setdefault("date", date.today())
            self.initial.setdefault("account", Account.objects.filter(business=b, is_default=True).first())
            last = Transaction.objects.filter(business=b, category__scope=self.scope).order_by("-id").first()
            if last and not self.initial.get("account"):
                self.initial["account"] = last.account_id

    def clean_date(self):
        d = self.cleaned_data["date"]
        if d and d > date.today():
            raise forms.ValidationError(_("That date is in the future."))
        return d

    def clean_category(self):
        c = self.cleaned_data["category"]
        if c and c.scope != self.scope:
            raise forms.ValidationError(_("Pick a category from this list."))
        return c


class FamilyIncomeForm(TransactionForm):
    """Money the family brings home from outside the farm: a salary, money sent
    from abroad, crops, rent… Household income, so the farm's profit is untouched."""

    tips = {
        "category": _("Where the money came from. Add your own with the + if it isn't listed."),
        "member": _("Who in the family earned or sent it."),
        "account": _("Which cash box, bank or wallet it went into. Its balance goes up."),
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, scope=Scope.HOUSEHOLD, **kwargs)
        self.fields["category"].queryset = self.fields["category"].queryset.filter(type=CategoryType.INCOME)
        self.fields["category"].label = _("Source")
        self.fields["account"].label = _("Received into")
        self.fields["category"].empty_label = _("Choose where it came from…")
        self.fields["description"].widget.attrs["placeholder"] = _("e.g. October salary, sent by bKash")
        self.layout = [("category", "amount"), ("member",), ("date", "account"), ("description",),
                       ("#", _("More (optional)")), ("receipt",), ("notes",)]
        if not self.instance.pk and not self.initial.get("member"):
            last = Transaction.objects.filter(business=self.business, category__scope=Scope.HOUSEHOLD,
                                              category__type=CategoryType.INCOME).order_by("-id").first()
            if last:   # the same person usually sends it again
                self.initial.setdefault("category", last.category_id)
                self.initial["member"] = last.member_id


class FamilyMemberForm(BusinessForm):
    tips = {"relation": _("How they're related to you: son, brother, wife…")}
    layout = [("name", "relation"), ("phone",), ("notes",)]

    class Meta:
        model = FamilyMember
        fields = ["name", "relation", "phone", "notes"]


class FamilyMemberQuickForm(BusinessForm):
    layout = [("name", "relation")]

    class Meta:
        model = FamilyMember
        fields = ["name", "relation"]


class TransferForm(BusinessForm):
    tips = {
        "from_account": _("Where the money left from."),
        "to_account": _("Where the money arrived."),
    }
    unique_name = ()
    layout = [("from_account", "to_account"), ("amount", "date"), ("charge", "reference"), ("notes",)]

    class Meta:
        model = Transfer
        fields = ["date", "from_account", "to_account", "amount", "charge", "reference", "notes"]
        widgets = {"date": forms.DateInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        accounts = Account.objects.filter(business=self.business)
        for name in ("from_account", "to_account"):
            self.fields[name].queryset = accounts
            self.fields[name].empty_label = _("Choose an account…")
            self.fields[name].biz_quick_add = "account"
        money_field(self.fields["amount"])
        money_field(self.fields["charge"])
        self.fields["charge"].required = False
        if not self.instance.pk:
            self.initial.setdefault("date", date.today())

    def clean(self):
        data = super().clean()
        data["charge"] = data.get("charge") or 0
        if data.get("from_account") and data.get("from_account") == data.get("to_account"):
            self.add_error("to_account", _("Choose a different account to send it to."))
        if data.get("date") and data["date"] > date.today():
            self.add_error("date", _("That date is in the future."))
        return data


class RecurringForm(BusinessForm):
    tips = {
        "repeat": _("How often it comes back. The next due date moves forward each time you record or skip it."),
        "start_date": _("The first due date."),
        "amount": _("The usual amount. You can change it each time before recording."),
    }
    unique_name = ()
    layout = [("name", "amount"), ("category", "account"), ("repeat", "start_date"), ("end_date",), ("description",), ("notes",)]

    class Meta:
        model = RecurringTransaction
        fields = ["name", "amount", "category", "account", "repeat", "start_date", "end_date", "description", "notes"]
        widgets = {"start_date": forms.DateInput(), "end_date": forms.DateInput(),
                   "name": forms.TextInput(attrs={"placeholder": _("e.g. Pond lease, school fees")})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        b = self.business
        self.fields["category"].queryset = Category.objects.filter(business=b).select_related("parent")
        self.fields["category"].empty_label = _("Choose a category…")
        self.fields["category"].biz_quick_add = "category"
        self.fields["account"].queryset = Account.objects.filter(business=b)
        self.fields["account"].empty_label = _("Not set")
        self.fields["account"].biz_quick_add = "account"
        money_field(self.fields["amount"])
        if not self.instance.pk:
            self.initial.setdefault("start_date", date.today())

    def clean(self):
        data = super().clean()
        start, end = data.get("start_date"), data.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", _("It ends before it starts."))
        return data

    def save(self, commit=True):
        obj = super().save(commit=False)
        if not obj.next_due or "start_date" in self.changed_data or "repeat" in self.changed_data:
            obj.next_due = obj.start_date
        if commit:
            obj.save()
        return obj


class BudgetForm(forms.Form):
    """The whole month's budget on one page: one box per main category."""

    def __init__(self, *args, business, month, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import Budget

        self.business, self.month = business, month
        planned = {b.category_id: b.amount for b in Budget.objects.filter(business=business, month=month)}
        self.categories = list(Category.objects.filter(business=business, type=CategoryType.EXPENSE, parent=None).select_related("parent"))
        for c in self.categories:
            f = forms.DecimalField(required=False, min_value=0, max_digits=14, decimal_places=2, label=c.display_name,
                                   widget=forms.NumberInput(attrs={"class": "form-input", "inputmode": "decimal", "step": "any", "placeholder": "0"}))
            f.affix = "৳"
            f.scope_label = c.get_scope_display()
            self.fields[f"c{c.pk}"] = f
            value = planned.get(c.pk)
            if value is not None:
                self.initial[f"c{c.pk}"] = format(value.normalize(), "f")

    def rows(self):
        return [(c, self[f"c{c.pk}"]) for c in self.categories]

    def save(self):
        from .models import Budget

        kept = 0
        for c in self.categories:
            amount = self.cleaned_data.get(f"c{c.pk}")
            row = Budget.all_objects.filter(business=self.business, category=c, month=self.month).first()
            if amount:
                kept += 1
                if row is None:
                    Budget.objects.create(business=self.business, category=c, month=self.month, amount=amount)
                else:
                    row.amount, row.is_deleted, row.deleted_at = amount, False, None
                    row.save(update_fields=["amount", "is_deleted", "deleted_at", "updated_at", "updated_by"])
            elif row is not None and not row.is_deleted:
                row.soft_delete()
        return kept
