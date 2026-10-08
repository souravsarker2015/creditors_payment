"""Income, expenses, transfers, budgets and recurring bills."""
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction as db_transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.formats import date_format
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.business.core.periods import fy_end, fy_label, fy_start
from apps.business.core.decorators import business_access_required
from apps.business.core.templatetags.business import bdt

from . import services
from .forms import BudgetForm, FamilyIncomeForm, RecurringForm, TransactionForm, TransferForm
from .models import Account, Budget, Category, CategoryType, FamilyMember, RecurringTransaction, Scope, Transaction, Transfer

ZERO = Decimal(0)


def _month(value, today=None):
    today = today or date.today()
    try:
        year, month = (int(x) for x in (value or "").split("-")[:2])
        return date(year, month, 1)
    except (ValueError, TypeError):
        return today.replace(day=1)


def _month_end(month):
    return month.replace(day=monthrange(month.year, month.month)[1])


def _add_months(month, n):
    total = month.year * 12 + month.month - 1 + n
    return date(total // 12, total % 12 + 1, 1)


def _periods(today):
    first = today.replace(day=1)
    last_end = first - timedelta(days=1)
    return [
        ("month", _("This month"), first, today),
        ("last", _("Last month"), last_end.replace(day=1), last_end),
        ("3m", _("Last 3 months"), today - timedelta(days=90), today),
        ("year", _("This year"), today.replace(month=1, day=1), today),
        ("fy", _("This financial year"), fy_start(today), today),
        ("all", _("All"), None, None),
    ]


def _range(request, today):
    periods = _periods(today)
    key = request.GET.get("period", "month")
    _k, label, start, end = next((p for p in periods if p[0] == key), periods[0])
    return periods, key, label, start, end


# ── Money in and out ────────────────────────────────────────────────────────

@business_access_required(capability="view_finance")
def transaction_list_view(request):
    b = request.business
    today = date.today()
    scope = request.GET.get("scope", Scope.BUSINESS)
    if scope not in Scope.values:
        scope = Scope.BUSINESS
    periods, key, label, start, end = _range(request, today)
    qs = Transaction.objects.filter(business=b, category__scope=scope).select_related("category__parent", "account", "party", "cycle__pond")
    if start:
        qs = qs.filter(date__gte=start, date__lte=end)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(description__icontains=q) | Q(category__name__icontains=q) | Q(category__name_bn__icontains=q) |
                       Q(party__name__icontains=q) | Q(notes__icontains=q))
    category = request.GET.get("category")
    if category and category.isdigit():
        qs = qs.filter(Q(category_id=category) | Q(category__parent_id=category))
    kind = request.GET.get("kind")
    if kind in CategoryType.values:
        qs = qs.filter(category__type=kind)
    sums = qs.order_by().values("category__type").annotate(total=Sum("amount"))
    by_type = {r["category__type"]: r["total"] for r in sums}
    return render(request, "business/finance/transaction_list.html", {
        "page_obj": Paginator(qs, 40).get_page(request.GET.get("page")),
        "periods": periods, "period": key, "period_label": label, "q": q, "scope": scope, "kind": kind,
        "scopes": Scope.choices, "income": by_type.get(CategoryType.INCOME) or ZERO, "expense": by_type.get(CategoryType.EXPENSE) or ZERO,
        "category": Category.objects.filter(business=b, pk=category).first() if (category or "").isdigit() else None,
        "deleted_count": Transaction.all_objects.filter(business=b, is_deleted=True).count(),
        "due_recurring": services.due_recurring(b),
    })


@business_access_required(capability="enter_data")
def transaction_form_view(request, pk=None):
    b = request.business
    obj = get_object_or_404(Transaction, pk=pk, business=b) if pk else None
    scope = obj.category.scope if obj else request.GET.get("scope", Scope.BUSINESS)
    if scope not in Scope.values:
        scope = Scope.BUSINESS
    initial = {}
    if not obj:
        for key in ("category", "cycle", "party"):
            if request.GET.get(key, "").isdigit():
                initial[key] = int(request.GET[key])
        if request.GET.get("amount", "").replace(".", "").isdigit():
            initial["amount"] = request.GET["amount"]
        if request.GET.get("description"):
            initial["description"] = request.GET["description"][:200]
    form = TransactionForm(request.POST or None, request.FILES or None, instance=obj, business=b, scope=scope, initial=initial or None)
    from_recurring = RecurringTransaction.objects.filter(business=b, pk=request.GET.get("from") or 0).first()
    if request.method == "POST" and form.is_valid():
        item = form.save(commit=False)
        item.business = b
        if from_recurring is not None and not obj:
            item.recurring = from_recurring
        item.save()
        if from_recurring is not None and not obj:
            _advance(from_recurring, item.date)
        word = _("Income") if item.is_income else _("Expense")
        messages.success(request, _("%(word)s saved: %(amount)s · %(category)s.") % {"word": word, "amount": bdt(item.amount), "category": item.category})
        nxt = request.GET.get("next")
        if nxt and url_has_allowed_host_and_scheme(nxt, {request.get_host()}):
            return redirect(nxt)
        return redirect(reverse("business:transactions") + f"?scope={scope}")
    return render(request, "business/finance/transaction_form.html", {
        "form": form, "obj": obj, "scope": scope, "scope_label": dict(Scope.choices)[scope], "recurring": from_recurring,
        "back": reverse("business:transactions") + f"?scope={scope}",
    })


@business_access_required(capability="delete")
@require_POST
def transaction_delete_view(request, pk):
    obj = get_object_or_404(Transaction, pk=pk, business=request.business)
    scope = obj.category.scope
    obj.soft_delete()
    messages.success(request, _("Deleted. You can restore it from the deleted list."))
    nxt = request.POST.get("next")
    if nxt and url_has_allowed_host_and_scheme(nxt, {request.get_host()}):
        return redirect(nxt)
    return redirect(reverse("business:transactions") + f"?scope={scope}")


# ── Family income: the family's money from outside the farm ────────────────

def _family_income(business):
    return (Transaction.objects.filter(business=business, category__scope=Scope.HOUSEHOLD, category__type=CategoryType.INCOME)
            .select_related("category__parent", "account", "member"))


@business_access_required(capability="view_finance")
def family_income_view(request):
    """Salary, money from abroad, crops, rent… what the family earns outside
    the farm, and how the family's money stands with the farm and the home."""
    from apps.core.stats import ranked

    b = request.business
    today = date.today()
    periods, key, label, start, end = _range(request, today)
    qs = _family_income(b)
    if start:
        qs = qs.filter(date__gte=start, date__lte=end)
    rows = list(qs)
    total = sum((t.amount for t in rows), ZERO)
    by_source, by_person = {}, {}
    for t in rows:
        main = t.category.parent or t.category
        by_source[main] = by_source.get(main, ZERO) + t.amount
        by_person[t.member] = by_person.get(t.member, ZERO) + t.amount
    list_url = reverse("business:transactions") + "?scope=" + Scope.HOUSEHOLD
    sources = ranked([(c.display_name, v, f"{list_url}&category={c.pk}&period={key}") for c, v in by_source.items()])
    people = ranked([(m.name if m else _("Not one person"), v, None) for m, v in by_person.items()]) if any(by_person) else []

    # The family's money in this period: the farm's profit, plus what the family
    # earned outside it, less what the home spent.
    first = start or date(2000, 1, 1)
    farm = services.statement(b, first, end or today).profit
    home = services.statement(b, first, end or today, scope=Scope.HOUSEHOLD).total_expense
    return render(request, "business/finance/family_income.html", {
        "periods": periods, "period": key, "period_label": label,
        "total": total, "count": len(rows), "sources": sources, "people": people,
        "farm": farm, "home": home, "left": farm + total - home,
        "page_obj": Paginator(rows, 40).get_page(request.GET.get("page")),
        "members": FamilyMember.objects.filter(business=b).count(),
    })


@business_access_required(capability="view_finance")   # the family's earnings are private
def family_income_form_view(request, pk=None):
    b = request.business
    obj = get_object_or_404(_family_income(b), pk=pk) if pk else None
    initial = {k: int(request.GET[k]) for k in ("member", "category") if request.GET.get(k, "").isdigit()}
    form = FamilyIncomeForm(request.POST or None, request.FILES or None, instance=obj, business=b, initial=initial or None)
    back = reverse("business:family_income")
    if request.method == "POST" and form.is_valid():
        item = form.save(commit=False)
        item.business = b
        item.save()
        who = f" · {item.member.name}" if item.member else ""
        messages.success(request, _("Family income saved: %(amount)s · %(source)s%(who)s.") % {
            "amount": bdt(item.amount), "source": item.category, "who": who})
        return redirect(back)
    return render(request, "business/finance/transaction_form.html", {
        "form": form, "obj": obj, "scope": Scope.HOUSEHOLD, "back": back,
        "heading": _("Edit family income") if obj else _("Add family income"), "back_label": _("Family income"),
        "scope_label": _("Money the family earns outside the farm. It doesn't change the farm's profit."),
    })


@business_access_required(capability="delete")
@require_POST
def transaction_restore_view(request, pk):
    obj = get_object_or_404(Transaction.all_objects, pk=pk, business=request.business, is_deleted=True)
    obj.restore()
    messages.success(request, _("Restored."))
    return redirect(reverse("business:transactions") + f"?scope={obj.category.scope}")


@business_access_required(capability="view_finance")
def transaction_deleted_view(request):
    rows = Transaction.all_objects.filter(business=request.business, is_deleted=True).select_related("category", "account")
    return render(request, "business/finance/transaction_deleted.html", {"rows": rows})


# ── Transfers ───────────────────────────────────────────────────────────────

@business_access_required(capability="view_finance")
def transfer_form_view(request, pk=None):
    b = request.business
    obj = get_object_or_404(Transfer, pk=pk, business=b) if pk else None
    initial = {"from_account": request.GET["from"]} if request.GET.get("from", "").isdigit() else None
    form = TransferForm(request.POST or None, instance=obj, business=b, initial=initial)
    if request.method == "POST" and form.is_valid():
        item = form.save(commit=False)
        item.business = b
        item.save()
        messages.success(request, _("Moved %(amount)s from %(from)s to %(to)s.") % {
            "amount": bdt(item.amount), "from": item.from_account, "to": item.to_account})
        return redirect("business:accounts")
    return render(request, "business/finance/transfer_form.html", {"form": form, "obj": obj, "back": reverse("business:accounts")})


@business_access_required(capability="delete")
@require_POST
def transfer_delete_view(request, pk):
    obj = get_object_or_404(Transfer, pk=pk, business=request.business)
    obj.soft_delete()
    messages.success(request, _("Transfer deleted."))
    return redirect("business:accounts")


# ── Account pages ───────────────────────────────────────────────────────────

@business_access_required(capability="view_finance")
def account_detail_view(request, pk):
    b = request.business
    account = get_object_or_404(Account, pk=pk, business=b)
    today = date.today()
    periods, key, label, start, end = _range(request, today)
    rows, opening, closing = services.account_history(account, start, end)
    money_in = sum((m.amount for m in rows if m.amount > 0), ZERO)
    money_out = -sum((m.amount for m in rows if m.amount < 0), ZERO)
    return render(request, "business/finance/account_detail.html", {
        "account": account, "rows": rows[:300], "opening": opening, "closing": closing, "balance": account.balance,
        "money_in": money_in, "money_out": money_out, "periods": periods, "period": key, "period_label": label,
        "start": start, "end": end, "more": max(len(rows) - 300, 0), "today": today,
    })


# ── Income and expense statement ────────────────────────────────────────────

@business_access_required(capability="view_reports")
def statement_view(request):
    b = request.business
    today = date.today()
    scope = request.GET.get("scope", Scope.BUSINESS)
    if scope not in Scope.values:
        scope = Scope.BUSINESS
    month = _month(request.GET.get("month"), today)
    period = request.GET.get("period", "month")
    if period == "year":
        start, end, label = date(month.year, 1, 1), min(date(month.year, 12, 31), today), str(month.year)
    elif period == "fy":
        start, end, label = fy_start(month), min(fy_end(month), today), fy_label(month)
    else:
        period = "month"
        start, end = month, min(_month_end(month), today)
        label = date_format(month, "F Y")
    s = services.statement(b, start, end, scope=scope)
    return render(request, "business/finance/statement.html", {
        "s": s, "scope": scope, "scopes": Scope.choices, "period": period, "label": label, "month": month,
        "prev": _add_months(month, -1) if period == "month" else _add_months(start, -12),
        "next": _add_months(month, 1) if period == "month" else _add_months(start, 12),
        "can_go_next": (end < today),
        "max_expense": max((l.amount for l in s.expense), default=ZERO),
        "max_income": max((l.amount for l in s.income), default=ZERO), "today": today,
    })


# ── Budgets ─────────────────────────────────────────────────────────────────

@business_access_required(capability="view_finance")
def budget_view(request):
    b = request.business
    today = date.today()
    month = _month(request.GET.get("month"), today)
    rows, extra = services.budget_rows(b, month)
    planned = sum((r.planned for r in rows), ZERO)
    spent = sum((r.spent for r in rows), ZERO) + sum((r.spent for r in extra), ZERO)
    days_left = (_month_end(month) - today).days if month == today.replace(day=1) else None
    return render(request, "business/finance/budget.html", {
        "rows": rows, "extra": extra, "month": month, "planned": planned, "spent": spent,
        "left": planned - spent, "pct": min(int(spent * 100 / planned), 100) if planned else 0,
        "over": spent > planned, "days_left": days_left,
        "prev": _add_months(month, -1), "next": _add_months(month, 1),
        "copied_from": _add_months(month, -1) if not rows else None,
    })


@business_access_required(capability="view_finance")
def budget_edit_view(request):
    b = request.business
    month = _month(request.GET.get("month"))
    form = BudgetForm(request.POST or None, business=b, month=month)
    if request.method == "POST" and form.is_valid():
        kept = form.save()
        messages.success(request, _("Budget saved for %(month)s: %(n)s categories.") % {"month": date_format(month, "F Y"), "n": kept})
        return redirect(reverse("business:budget") + f"?month={month:%Y-%m}")
    return render(request, "business/finance/budget_form.html", {
        "form": form, "month": month, "back": reverse("business:budget") + f"?month={month:%Y-%m}",
    })


@business_access_required(capability="view_finance")
@require_POST
def budget_copy_view(request):
    b = request.business
    month = _month(request.POST.get("month"))
    source = _add_months(month, -1)
    made = 0
    with db_transaction.atomic():
        for old in Budget.objects.filter(business=b, month=source):
            if not Budget.objects.filter(business=b, category=old.category, month=month).exists():
                Budget.objects.create(business=b, category=old.category, month=month, amount=old.amount)
                made += 1
    if made:
        messages.success(request, _("Copied %(n)s budgets from %(month)s.") % {"n": made, "month": date_format(source, "F Y")})
    else:
        messages.info(request, _("Nothing to copy from %(month)s.") % {"month": date_format(source, "F Y")})
    return redirect(reverse("business:budget") + f"?month={month:%Y-%m}")


# ── Recurring ───────────────────────────────────────────────────────────────

def _advance(recurring, after):
    """Move a recurring bill on to its next date once one is confirmed."""
    nxt = services.next_date(recurring.next_due or after, recurring.repeat)
    recurring.next_due = None if (recurring.end_date and nxt > recurring.end_date) else nxt
    recurring.save(update_fields=["next_due", "updated_at", "updated_by"])


@business_access_required(capability="view_finance")
def recurring_list_view(request):
    b = request.business
    rows = list(RecurringTransaction.objects.filter(business=b).select_related("category", "account"))
    today = date.today()
    return render(request, "business/finance/recurring_list.html", {
        "due": [r for r in rows if r.next_due and r.next_due <= today],
        "upcoming": [r for r in rows if r.next_due and r.next_due > today],
        "finished": [r for r in rows if not r.next_due],
        "monthly": sum((r.amount for r in rows if r.repeat == "monthly" and r.next_due), ZERO),
    })


@business_access_required(capability="view_finance")
def recurring_form_view(request, pk=None):
    b = request.business
    obj = get_object_or_404(RecurringTransaction, pk=pk, business=b) if pk else None
    form = RecurringForm(request.POST or None, instance=obj, business=b)
    if request.method == "POST" and form.is_valid():
        item = form.save(commit=False)
        item.business = b
        item = form.save()
        messages.success(request, _("Saved: %(name)s.") % {"name": item})
        return redirect("business:recurring")
    return render(request, "business/finance/recurring_form.html", {"form": form, "obj": obj, "back": reverse("business:recurring")})


@business_access_required(capability="enter_data")
@require_POST
def recurring_skip_view(request, pk):
    r = get_object_or_404(RecurringTransaction, pk=pk, business=request.business)
    when = r.next_due
    _advance(r, date.today())
    messages.success(request, _("Skipped %(name)s for %(date)s.") % {"name": r.name, "date": date_format(when, "j M Y")} if when
                     else _("Skipped %(name)s.") % {"name": r.name})
    return redirect(request.POST.get("next") or "business:recurring")


@business_access_required(capability="delete")
@require_POST
def recurring_delete_view(request, pk):
    r = get_object_or_404(RecurringTransaction, pk=pk, business=request.business)
    r.soft_delete()
    messages.success(request, _("“%(name)s” stopped. You can add it again any time.") % {"name": r.name})
    return redirect("business:recurring")
