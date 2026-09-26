from django.db.models import Q, Sum
from django.utils.translation import gettext_lazy as _

from apps.business.core.crud import Master

from .forms import AccountForm, CategoryForm
from .models import Account, Category, CategoryType, Scope


def _tree(objects):
    """Group main categories by type and scope, each followed by its sub-categories."""
    groups = []
    for t_value, t_label in CategoryType.choices:
        for s_value, s_label in Scope.choices:
            mains = [c for c in objects if c.type == t_value and c.scope == s_value and not c.parent_id]
            if not mains:
                continue
            rows = []
            for main in mains:
                rows.append(main)
                rows.extend(c for c in objects if c.parent_id == main.pk)
            groups.append((f"{s_label} · {t_label}", rows))
    return groups


def _no_system(o):
    if o.is_system:
        return _("This category is filled in automatically, so it can't be deleted.")
    return None


def _one_default(obj, request):
    if obj.is_default:
        Account.objects.filter(business=obj.business).exclude(pk=obj.pk).update(is_default=False)


def _accounts_total(objects, business):
    for a in objects:
        a.show_balance = a.balance


categories = Master(
    name="categories", model=Category, form_class=CategoryForm,
    title=_("Categories"), subtitle=_("Group income and spending — for the farm, the household and yourself. Sub-categories keep things tidy."),
    add_label=_("Add category"), row_template="business/finance/category_row.html", icon="tag",
    search_fields=("name", "name_bn"), select_related=("parent",), group=_tree, delete_check=_no_system,
    filters=[(v, label, Q(scope=v)) for v, label in Scope.choices],
    initial=lambda r: {k: r.GET[k] for k in ("type", "scope", "parent") if r.GET.get(k)},
    empty_title=_("No categories"), empty_text=_("Add categories for what the farm and the family spend and earn."),
)

accounts = Master(
    name="accounts", model=Account, form_class=AccountForm, view_cap="view_finance", edit_cap="view_finance",
    title=_("Accounts"), subtitle=_("Where the money is: cash in hand, bank accounts, bKash and Nagad."),
    add_label=_("Add account"), row_template="business/finance/account_row.html", icon="wallet",
    search_fields=("name", "institution", "number"), after_save=_one_default, decorate=_accounts_total,
    empty_title=_("No accounts yet"), empty_text=_("Add your cash box, bank accounts and mobile wallets."),
)
