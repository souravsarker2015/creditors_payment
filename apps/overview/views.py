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
    from apps.goals.views import catch_up_autosaves
    catch_up_autosaves(request)

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

    from apps.wallets.models import Wallet
    from apps.wallets.services import balances as wallet_balances

    wallets = list(Wallet.objects.filter(user=user, is_active=True))
    if wallets:
        held = wallet_balances(user)
        for w in wallets:
            w.balance = held.get(w.pk, w.opening_balance)

    wallets_total = sum((w.balance for w in wallets), ZERO)
    hour = timezone.localtime().hour
    context = {
        "greeting": _greeting(hour),
        "starter": _starter_steps(user),
        "recent": _recent_entries(user),
        # Plain answer to "how much do I really have?": the money in your
        # wallets, plus what others owe you, minus what you owe.
        "settled": wallets_total + receivables - payables,
        "wallets": wallets,
        "wallets_total": wallets_total,
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
        "upcoming": _upcoming(user, today),
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


def _greeting(hour):
    from django.utils.translation import gettext as _
    if 5 <= hour < 12:
        return _("Good morning")
    if 12 <= hour < 17:
        return _("Good afternoon")
    return _("Good evening")


def _starter_steps(user):
    """First steps for someone new. None once every step is done, so the
    card disappears by itself."""
    from django.utils.translation import gettext as _
    from apps.budgets.models import Budget
    from apps.creditors.models import Creditor
    from apps.debtors.models import Debtor
    from apps.goals.models import SavingsGoal
    from apps.shops.models import Shop
    from apps.wallets.models import Wallet

    steps = [
        (Wallet.objects.filter(user=user).exists(), _("Add where you keep money"), _("Cash in hand, bank account, bKash or Nagad."), reverse("wallet_create")),
        (IncomeTransaction.objects.filter(source__user=user).exists(), _("Record money you got"), _("Salary, business income, rent or a gift."), reverse("pick", args=["income"])),
        (Expense.objects.filter(user=user).exists(), _("Record something you spent"), _("Rent, bills, food, transport…"), reverse("expense_create")),
        (Creditor.objects.filter(user=user).exists() or Debtor.objects.filter(user=user).exists() or Shop.objects.filter(user=user).exists(),
         _("Add a loan or a due"), _("Money you borrowed, lent, or owe a shop."), reverse("pick", args=["borrow"])),
        (Budget.objects.filter(user=user).exists() or SavingsGoal.objects.filter(user=user).exists(),
         _("Plan ahead"), _("A monthly spending limit or a savings goal."), reverse("budget_list")),
    ]
    done = sum(1 for d, *_rest in steps if d)
    if done == len(steps):
        return None
    return {"done": done, "total": len(steps), "steps": [
        {"no": i, "done": d, "title": t, "text": x, "url": u} for i, (d, t, x, u) in enumerate(steps, 1)
    ]}


def _recent_entries(user, limit=6):
    """The last few things recorded anywhere, newest first, so Home answers
    "did I already write that down?"."""
    from django.utils.translation import gettext as _

    rows = []
    for e in Expense.objects.filter(user=user).select_related("category").order_by("-date", "-pk")[:limit]:
        rows.append((e.date, e.pk, e.category.name if e.category_id else _("General"), _("Spent"), -e.amount, "critical", reverse("expense_list")))
    for t in IncomeTransaction.objects.filter(source__user=user).select_related("source").order_by("-date", "-pk")[:limit]:
        rows.append((t.date, t.pk, t.source.name, _("Money in"), t.amount, "good", reverse("income_source_detail", args=[t.source_id])))
    for t in CreditorTransaction.objects.filter(creditor__user=user).select_related("creditor").order_by("-date", "-pk")[:limit]:
        borrowed = t.transaction_type == CreditorTransaction.BORROW
        rows.append((t.date, t.pk, t.creditor.name, _("Borrowed") if borrowed else _("Paid back"), t.amount if borrowed else -t.amount, "good" if borrowed else "critical", reverse("creditor_detail", args=[t.creditor_id])))
    for t in DebtorTransaction.objects.filter(debtor__user=user).select_related("debtor").order_by("-date", "-pk")[:limit]:
        lent = t.transaction_type == DebtorTransaction.LEND
        rows.append((t.date, t.pk, t.debtor.name, _("Lent") if lent else _("Got back"), -t.amount if lent else t.amount, "critical" if lent else "good", reverse("debtor_detail", args=[t.debtor_id])))
    rows.sort(key=lambda r: (r[0], r[1]), reverse=True)
    return [{"date": d, "title": title, "kind": kind, "amount": amount, "tone": tone, "url": url}
            for d, _pk, title, kind, amount, tone, url in rows[:limit]]


def _bar_percent(value, *comparison_values):
    """Width (0-100) for `value` relative to the largest of comparison_values.
    Never negative, never divides by zero."""
    scale = max((v for v in comparison_values), default=ZERO)
    if scale <= 0 or value <= 0:
        return 0
    return min(100, int((value / scale) * 100))


def _upcoming(user, today):
    from .upcoming import forecast

    return forecast(user, today, 30)


def _attention(user, today):
    """Overdue and due-soon balances across every ledger with due dates,
    most urgent first — so one list answers "what needs doing?"."""
    from apps.plans.services import status as plan_status
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
        for r in rows.select_related("plan"):
            remaining = r.out - r.back
            if remaining > 0:
                plan = getattr(r, "plan", None)
                items.append({
                    # On an installment plan, what's due is the installment (and anything late), not the whole balance.
                    "name": r.name, "amount": plan_status(plan).next_amount if plan else remaining, "due_date": r.due_date, "kind": kind,
                    "installment": plan is not None,
                    "overdue": r.due_date < today, "days": (r.due_date - today).days, "late": (today - r.due_date).days,
                    "url": reverse(urlname, args=[r.pk]),
                })
    items.sort(key=lambda i: i["due_date"])
    return items


# ── "Record money": who was it with? ──
#
# One tap from Home for the everyday entries that belong to a person or a
# source. The list opens that person's page with the entry form ready.

def _pick_kinds():
    from django.utils.translation import gettext_lazy as _
    from apps.creditors.models import Creditor
    from apps.debtors.models import Debtor
    from apps.income.models import IncomeSource
    from apps.shops.models import Shop

    lender = (Creditor, "transactions", CreditorTransaction.BORROW, CreditorTransaction.REPAY, "creditor_detail", "creditor_create")
    borrower = (Debtor, "transactions", DebtorTransaction.LEND, DebtorTransaction.RECEIVE, "debtor_detail", "debtor_create")
    shop = (Shop, "transactions", ShopTransaction.PURCHASE, ShopTransaction.PAYMENT, "shop_detail", "shop_create")
    return {
        "borrow": (_("Who did you borrow from?"), _("Pick the person. If they're new, add them first."), _("Add a new person"), lender, CreditorTransaction.BORROW, "owe"),
        "repay": (_("Who are you paying back?"), _("People you still owe come first."), _("Add a new person"), lender, CreditorTransaction.REPAY, "owe"),
        "lend": (_("Who did you lend money to?"), _("Pick the person. If they're new, add them first."), _("Add a new person"), borrower, DebtorTransaction.LEND, "owed"),
        "collect": (_("Who paid you back?"), _("People who still owe you come first."), _("Add a new person"), borrower, DebtorTransaction.RECEIVE, "owed"),
        "shop": (_("Which shop?"), _("Buying on credit (baki) or paying the shop back."), _("Add a new shop"), shop, "", "owe"),
        "income": (_("Where did the money come from?"), _("Salary, business, rent, a gift… pick where it came from."), _("Add a new source"), None, "", "income"),
    }


@login_required
def pick_view(request, kind):
    from django.http import Http404
    from apps.income.models import IncomeSource

    kinds = _pick_kinds()
    if kind not in kinds:
        raise Http404
    title, help_text, add_label, ledger, record, side = kinds[kind]
    if ledger is None:
        rows = (IncomeSource.objects.filter(user=request.user, is_active=True)
                .annotate(total=Coalesce(Sum("transactions__amount"), Value(0, output_field=DecimalField())))
                .order_by("-total", "name"))
        items = [{"name": s.name, "amount": s.total, "url": reverse("income_source_detail", args=[s.pk]) + "#record"} for s in rows]
        create = reverse("income_source_create") + "?record="
    else:
        model, rel, out_type, in_type, detail, create_name = ledger
        rows = model.objects.filter(user=request.user, is_active=True).annotate(
            out=Coalesce(Sum(f"{rel}__amount", filter=Q(**{f"{rel}__transaction_type": out_type})), Value(0, output_field=DecimalField())),
            back=Coalesce(Sum(f"{rel}__amount", filter=Q(**{f"{rel}__transaction_type": in_type})), Value(0, output_field=DecimalField())),
        )
        items = [{"name": r.name, "amount": r.out - r.back, "url": f"{reverse(detail, args=[r.pk])}?record={record}#record"} for r in rows]
        # Paying back / collecting: people with a balance first, biggest first.
        items.sort(key=lambda i: (-(i["amount"] > 0), -i["amount"], i["name"].lower()))
        create = f"{reverse(create_name)}?record={record}"
    return render(request, "overview/pick.html", {
        "kind": kind, "title": title, "help_text": help_text, "add_label": add_label,
        "items": items, "create_url": create, "side": side,
    })


# ── How this app works: plain words, no accounting terms ──

def _help_content():
    from django.utils.translation import gettext_lazy as _
    steps = [
        (_("Add your wallets"), _("A wallet is anywhere you keep money: cash in hand, a bank account, bKash, Nagad. Add each one with how much is in it today."), "wallet_create"),
        (_("Write down money when it moves"), _("Spent something? Tap “I spent”. Got paid? Tap “I got money”. It takes a few seconds, and the app does all the adding up."), "home"),
        (_("Write down loans and dues"), _("Borrowed from a friend, lent to a cousin, bought on baki at a shop — write it down once, then add each payment as it happens."), "pick"),
        (_("Look at Home"), _("Home shows how much money you have, who owes you, who you owe, and what is due soon. Red means it needs attention."), "home"),
    ]
    words = [
        (_("Wallet"), _("A place you keep money — cash, bank, bKash. Every entry can say which wallet the money came from or went to, so each balance stays right.")),
        (_("Expense"), _("Money you spent and won't get back: food, rent, bills, travel.")),
        (_("Income"), _("Money you earned or received: salary, business profit, rent, a gift.")),
        (_("Creditor"), _("Someone you borrowed money from. You owe them.")),
        (_("Debtor"), _("Someone who borrowed money from you. They owe you.")),
        (_("Shop dues (baki)"), _("A shop where you take things now and pay later. The app keeps the running total.")),
        (_("Household (Bazar)"), _("Daily family shopping. If a family member paid, the app remembers that you owe them.")),
        (_("Contributor"), _("A relative or friend who supports you with money — not a loan, you don't pay it back.")),
        (_("Budget"), _("A limit you set for a month, like “food: ৳8,000”. The app warns you before you cross it.")),
        (_("Savings goal"), _("Something you are saving for, like Eid or a motorbike. Put money aside step by step and see how close you are.")),
        (_("Recurring"), _("An entry that repeats by itself, like monthly rent or salary, so you don't have to type it every time.")),
        (_("If everyone settled up today"), _("Your money now, plus what others owe you, minus what you owe. What you would really have if every loan and due were cleared.")),
    ]
    faqs = [
        (_("I made a mistake. How do I fix it?"), _("Tap the entry, then the ⋯ button, and choose Edit or Delete. Deleted things stay in “Recently deleted” for 30 days, so you can bring them back.")),
        (_("I moved money from bKash to cash. What do I write?"), _("Tap “Move money” on Home. It is not spending, so it won't show as an expense — it only changes the two wallet balances.")),
        (_("Someone paid back only part of a loan."), _("Open that person and add a payment for the amount they gave. The app shows what is still left.")),
        (_("Can I get a reminder before something is due?"), _("Yes. Give a loan or a shop due a “due date”. It shows on Home in “Needs attention” a week before, and in red once it is late.")),
        (_("How do I find an old entry?"), _("Use the search button at the top (the magnifying glass). Type a name, an amount or a note.")),
        (_("Is my data safe? Can I keep a copy?"), _("Only you can see your personal records. Use “Download my data” in the menu any time to save everything as Excel-ready files.")),
        (_("Can I use the app in Bangla?"), _("Yes. Open the menu and pick বাংলা under Language. You can switch back any time.")),
        (_("Can I put it on my phone like an app?"), _("Yes. In Chrome, open the menu and tap “Add to Home screen” (or “Install app”). It then opens full-screen like any other app.")),
    ]
    return steps, words, faqs


@login_required
def upcoming_view(request):
    """Upcoming money: dues, installments and regular income/spending over the
    next days, against what's in the wallets — and the day it would run short."""
    from apps.core.forecast import PERIODS, window

    from .upcoming import forecast

    days = window(request)
    return render(request, "overview/upcoming.html", {
        "f": forecast(request.user, timezone.localdate(), days), "days": days, "periods": PERIODS,
    })


@login_required
def help_view(request):
    steps, words, faqs = _help_content()
    links = {"wallet_create": reverse("wallet_create"), "home": reverse("home"), "pick": reverse("pick", args=["borrow"])}
    return render(request, "overview/help.html", {
        "steps": [(t, x, links[u]) for t, x, u in steps], "words": words, "faqs": faqs,
    })
