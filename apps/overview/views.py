from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import render

from apps.contributors.models import Contribution
from apps.creditors.models import Transaction as CreditorTransaction
from apps.debtors.models import Transaction as DebtorTransaction
from apps.expense.models import Expense
from apps.household.models import Purchase
from apps.income.models import IncomeTransaction
from apps.shops.models import Transaction as ShopTransaction

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

    household_members = list(user.household_members.all())
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

    context = {
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
