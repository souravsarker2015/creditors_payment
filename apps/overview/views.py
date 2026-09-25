from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from apps.contributors.models import Contribution
from apps.creditors.models import Transaction as CreditorTransaction
from apps.debtors.models import Transaction as DebtorTransaction
from apps.expense.models import Expense
from apps.household.models import Purchase
from apps.income.models import IncomeTransaction
from apps.shops.models import Transaction as ShopTransaction
from apps.goals.services import goal_rows, totals as goal_totals
from apps.core.stats import change, last_n_month_starts, month_start, monthly_series, trend_summary

DUE_SOON_DAYS = 7

ZERO = Decimal("0.00")


def _sum(queryset):
    return queryset.aggregate(
        total=Coalesce(Sum("amount"), Value(0, output_field=DecimalField()))
    )["total"]


@login_required
def networth_view(request):
    user = request.user

    # ── Balances: what would be settled if everyone paid up today ──
    #
    # Receivables: money owed TO you.
    debtor_totals = DebtorTransaction.objects.filter(debtor__user=user).aggregate(
        lent=Coalesce(Sum("amount", filter=Q(transaction_type=DebtorTransaction.LEND)), Value(0, output_field=DecimalField())),
        received=Coalesce(Sum("amount", filter=Q(transaction_type=DebtorTransaction.RECEIVE)), Value(0, output_field=DecimalField())),
    )
    receivables = debtor_totals["lent"] - debtor_totals["received"]

    # Payables: money you owe. Creditors and Shops are structurally
    # identical (an amount owed to a third party); Household Members are
    # people who fronted bazar money and haven't been fully paid back.
    # Household Members' balance is clipped to >0 per member (matching the
    # Household dashboard's own convention) since an overpaid member isn't
    # a "negative debt" that offsets what you owe elsewhere.
    creditor_totals = CreditorTransaction.objects.filter(creditor__user=user).aggregate(
        borrowed=Coalesce(Sum("amount", filter=Q(transaction_type=CreditorTransaction.BORROW)), Value(0, output_field=DecimalField())),
        paid=Coalesce(Sum("amount", filter=Q(transaction_type=CreditorTransaction.REPAY)), Value(0, output_field=DecimalField())),
    )
    creditors_payable = creditor_totals["borrowed"] - creditor_totals["paid"]

    shop_totals = ShopTransaction.objects.filter(shop__user=user).aggregate(
        due=Coalesce(Sum("amount", filter=Q(transaction_type=ShopTransaction.PURCHASE)), Value(0, output_field=DecimalField())),
        paid=Coalesce(Sum("amount", filter=Q(transaction_type=ShopTransaction.PAYMENT)), Value(0, output_field=DecimalField())),
    )
    shops_payable = shop_totals["due"] - shop_totals["paid"]

    household_members = list(user.household_members.with_balances())
    household_payable = sum(
        (m.balance_due for m in household_members if m.balance_due > 0), ZERO
    )

    payables = creditors_payable + shops_payable + household_payable
    net_balance = receivables - payables

    # ── Lifetime cash flow: everything ever earned vs ever spent ──
    #
    # Income covers salary/business-style income sources; Contributors
    # covers voluntary support (sponsors, donors) — both are money that
    # came in, so both count as income here.
    income_earned = _sum(IncomeTransaction.objects.filter(source__user=user))
    contributions_received = _sum(Contribution.objects.filter(contributor__user=user))
    total_income = income_earned + contributions_received

    # Expense is the standalone expense log. Household purchases are only
    # counted here when nobody fronted them (buyer is unset) — a purchase a
    # member fronted is already fully represented above as that member's
    # payable, so counting it again here as "spent" would double-subtract
    # the same taka from your net position.
    expense_spent = _sum(Expense.objects.filter(user=user))
    household_spent_by_you = _sum(Purchase.objects.filter(user=user, buyer__isnull=True))
    total_expense = expense_spent + household_spent_by_you

    net_cash_flow = total_income - total_expense

    net_position = net_balance + net_cash_flow

    # ── This month: money in vs money out, and the savings rate ──
    today = timezone.localdate()
    this_start, last_start = month_start(today), month_start(today, -1)
    last_same_day = last_start.replace(day=min(today.day, (this_start - timedelta(days=1)).day))
    income_qs = IncomeTransaction.objects.filter(source__user=user)
    contrib_qs = Contribution.objects.filter(contributor__user=user)
    expense_qs = Expense.objects.filter(user=user)
    bazar_qs = Purchase.objects.filter(user=user, buyer__isnull=True)

    def money_in(start, end):
        return _sum(income_qs.filter(date__gte=start, date__lte=end)) + _sum(contrib_qs.filter(date__gte=start, date__lte=end))

    def money_out(start, end):
        return _sum(expense_qs.filter(date__gte=start, date__lte=end)) + _sum(bazar_qs.filter(date__gte=start, date__lte=end))

    in_month, out_month = money_in(this_start, today), money_out(this_start, today)
    saved_month = in_month - out_month

    months = last_n_month_starts(12, today)
    in_series = [a + b for a, b in zip(monthly_series(income_qs, months), monthly_series(contrib_qs, months))]
    out_series = [a + b for a, b in zip(monthly_series(expense_qs, months), monthly_series(bazar_qs, months))]
    net_series = [a - b for a, b in zip(in_series, out_series)]

    context = {
        "today": today,
        "in_month": in_month,
        "out_month": out_month,
        "saved_month": saved_month,
        "savings_rate": int(saved_month / in_month * 100) if in_month > 0 else None,
        "in_change": change(in_month, money_in(last_start, last_same_day)),
        "out_change": change(out_month, money_out(last_start, last_same_day)),
        "last_label": last_start,
        "months": months,
        "in_series": [float(v) for v in in_series],
        "out_series": [float(v) for v in out_series],
        "in_12": sum(in_series, ZERO),
        "out_12": sum(out_series, ZERO),
        "net_12": sum(net_series, ZERO),
        "positive_months": sum(1 for v in net_series if v > 0),
        "attention": _attention(user, today),
        "goals": goal_rows(user, "active", today)[:3],
        "goal_totals": goal_totals(user),
        "receivables": receivables,
        "creditors_payable": creditors_payable,
        "shops_payable": shops_payable,
        "household_payable": household_payable,
        "payables": payables,
        "net_balance": net_balance,
        "income_earned": income_earned,
        "contributions_received": contributions_received,
        "total_income": total_income,
        "expense_spent": expense_spent,
        "household_spent_by_you": household_spent_by_you,
        "total_expense": total_expense,
        "net_cash_flow": net_cash_flow,
        "net_position": net_position,
        # Pre-clamped 0-100 bar widths, computed here (not via {% widthratio %}
        # in the template) so a negative balance — e.g. someone repaid more
        # than they borrowed — can never produce an invalid negative width.
        "receivables_pct": _bar_percent(receivables, receivables, payables),
        "payables_pct": _bar_percent(payables, receivables, payables),
        "income_pct": _bar_percent(total_income, total_income, total_expense),
        "expense_pct": _bar_percent(total_expense, total_income, total_expense),
    }
    return render(request, "overview/networth.html", context)


def _bar_percent(value, *comparison_values):
    """Width (0-100) for `value` relative to the largest of comparison_values.
    Never negative, never divides by zero."""
    scale = max((v for v in comparison_values), default=ZERO)
    if scale <= 0 or value <= 0:
        return 0
    return min(100, int((value / scale) * 100))


def _attention(user, today):
    """Overdue and due-soon balances across every ledger with due dates,
    most urgent first — so one list answers "what needs doing?"."""
    from apps.creditors.models import Creditor
    from apps.debtors.models import Debtor
    from apps.shops.models import Shop

    ledgers = [
        (Creditor.objects.filter(user=user), CreditorTransaction.BORROW, CreditorTransaction.REPAY, "creditor_detail", "pay"),
        (Shop.objects.filter(user=user), ShopTransaction.PURCHASE, ShopTransaction.PAYMENT, "shop_detail", "pay"),
        (Debtor.objects.filter(user=user), DebtorTransaction.LEND, DebtorTransaction.RECEIVE, "debtor_detail", "collect"),
    ]
    cutoff = today + timedelta(days=DUE_SOON_DAYS)
    items = []
    for qs, out_type, in_type, urlname, kind in ledgers:
        rows = qs.filter(due_date__isnull=False, due_date__lte=cutoff).annotate(
            out=Coalesce(Sum("transactions__amount", filter=Q(transactions__transaction_type=out_type)), Value(0, output_field=DecimalField())),
            back=Coalesce(Sum("transactions__amount", filter=Q(transactions__transaction_type=in_type)), Value(0, output_field=DecimalField())),
        )
        for r in rows:
            remaining = r.out - r.back
            if remaining > 0:
                items.append({
                    "name": r.name, "amount": remaining, "due_date": r.due_date, "kind": kind,
                    "overdue": r.due_date < today, "days": (r.due_date - today).days, "late": (today - r.due_date).days,
                    "url": reverse(urlname, args=[r.pk]),
                })
    items.sort(key=lambda i: i["due_date"])
    return items
