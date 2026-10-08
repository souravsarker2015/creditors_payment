"""Upcoming money on the personal side: dues and installments either way,
regular income and regular spending, against the money in your wallets."""
from decimal import Decimal

from django.db.models import DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils.translation import gettext as _

from apps.core.forecast import Item, build, repeat

ZERO = Decimal(0)


def _ledgers(user):
    from apps.creditors.models import Creditor, Transaction as CT
    from apps.debtors.models import Debtor, Transaction as DT
    from apps.shops.models import Shop, Transaction as ST

    # (people, money-out type, money-back type, page, + when it comes to you / − when you pay, label)
    return [
        (Creditor.objects.filter(user=user), CT.BORROW, CT.REPAY, "creditor_detail", -1, _("Pay back")),
        (Shop.objects.filter(user=user), ST.PURCHASE, ST.PAYMENT, "shop_detail", -1, _("Shop due")),
        (Debtor.objects.filter(user=user), DT.LEND, DT.RECEIVE, "debtor_detail", 1, _("To collect")),
    ]


def ledger_items(user, today, until):
    """Dues with a date, and installment plans, on every ledger. Also returns
    what's owed with no date set (it can't be placed on a day)."""
    from apps.plans.services import status as plan_status

    items, undated = [], {"count": 0, "in": ZERO, "out": ZERO}
    for qs, out_type, back_type, page, sign, label in _ledgers(user):
        rows = qs.annotate(
            out=Coalesce(Sum("transactions__amount", filter=Q(transactions__transaction_type=out_type)), Value(0, output_field=DecimalField())),
            back=Coalesce(Sum("transactions__amount", filter=Q(transactions__transaction_type=back_type)), Value(0, output_field=DecimalField())),
        ).select_related("plan")
        for r in rows:
            remaining = r.out - r.back
            if remaining <= 0:
                continue
            url = reverse(page, args=[r.pk])
            plan = getattr(r, "plan", None)
            if plan is not None:
                st = plan_status(plan, today)
                left = remaining
                for n, when in enumerate(st.dates[st.paid_count:]):
                    if when > until or left <= 0:
                        break
                    amount = min(st.next_amount if n == 0 else plan.amount, left)
                    left -= amount
                    items.append(Item(when, sign * amount, r.name, _("Installment") + " · " + label, url, "plan"))
            elif r.due_date:
                items.append(Item(r.due_date, sign * remaining, r.name, label, url, "due"))
            else:
                undated["count"] += 1
                undated["in" if sign > 0 else "out"] += remaining
    return items, undated


def recurring_items(user, today, until):
    from apps.expense.models import RecurringExpense
    from apps.income.models import RecurringIncome

    items = []
    for r in RecurringIncome.objects.filter(source__user=user, is_active=True).select_related("source"):
        for d in repeat(r.next_run_date, r._advance, until, r.end_date):
            items.append(Item(r._effective_date(d), r.amount, r.source.name, _("Regular income"), reverse("recurring_income_list"), "recurring"))
    for r in RecurringExpense.objects.filter(user=user, is_active=True).select_related("category"):
        name = r.category.name if r.category_id else _("Regular spending")
        for d in repeat(r.next_run_date, r._advance, until, r.end_date):
            items.append(Item(r._effective_date(d), -r.amount, name, _("Regular spending"), reverse("recurring_expense_list"), "recurring"))
    return items


def forecast(user, today, days):
    from datetime import timedelta

    from apps.expense.models import generate_due_recurring_expense
    from apps.income.models import generate_due_recurring_income
    from apps.wallets.models import Wallet
    from apps.wallets.services import balances

    # Regular income and spending that's due is written down first (as their
    # own pages do), so it's in the wallets rather than counted as late.
    generate_due_recurring_income(user)
    generate_due_recurring_expense(user)
    held = balances(user)
    now = sum((held.get(w.pk, w.opening_balance) for w in Wallet.objects.filter(user=user, is_active=True)), ZERO)
    until = today + timedelta(days=days)
    dues, undated = ledger_items(user, today, until)
    f = build(now, dues + recurring_items(user, today, until), today, days)
    f.undated = undated
    return f
