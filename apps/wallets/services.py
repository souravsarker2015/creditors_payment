from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.urls import reverse
from django.utils.translation import gettext as _

from apps.core.templatetags.ui import money

from .models import Adjustment, Transfer, Wallet

ZERO = Decimal(0)


@dataclass
class Move:
    date: date
    wallet_id: int
    amount: Decimal       # + into the wallet, − out of it
    title: str
    detail: str = ""
    url: str = ""
    kind: str = ""
    balance: Decimal = ZERO


def _sources(user):
    """(queryset, sign or callable, title, detail fn, url fn, kind) for every entry that can name a wallet."""
    from apps.contributors.models import Contribution
    from apps.creditors.models import Transaction as CreditorTx
    from apps.debtors.models import Transaction as DebtorTx
    from apps.expense.models import Expense
    from apps.household.models import Purchase, Settlement
    from apps.income.models import IncomeTransaction
    from apps.shops.models import Transaction as ShopTx

    return [
        (Expense.objects.filter(user=user).select_related("category"), lambda o: -1, lambda o: str(o.category),
         lambda o: o.note, lambda o: reverse("expense_edit", args=[o.pk]), "expense"),
        (IncomeTransaction.objects.filter(source__user=user).select_related("source"), lambda o: 1, lambda o: str(o.source),
         lambda o: o.note, lambda o: reverse("income_source_detail", args=[o.source_id]), "income"),
        (CreditorTx.objects.filter(creditor__user=user).select_related("creditor"),
         lambda o: 1 if o.transaction_type == CreditorTx.BORROW else -1,
         lambda o: (_("Borrowed from %(name)s") if o.transaction_type == CreditorTx.BORROW else _("Repaid %(name)s")) % {"name": o.creditor.name},
         lambda o: o.note, lambda o: reverse("creditor_detail", args=[o.creditor_id]), "creditor"),
        (DebtorTx.objects.filter(debtor__user=user).select_related("debtor"),
         lambda o: -1 if o.transaction_type == DebtorTx.LEND else 1,
         lambda o: (_("Lent to %(name)s") if o.transaction_type == DebtorTx.LEND else _("Received from %(name)s")) % {"name": o.debtor.name},
         lambda o: o.note, lambda o: reverse("debtor_detail", args=[o.debtor_id]), "debtor"),
        (ShopTx.objects.filter(shop__user=user, transaction_type=ShopTx.PAYMENT).select_related("shop"), lambda o: -1,
         lambda o: _("Paid %(name)s") % {"name": o.shop.name}, lambda o: o.note, lambda o: reverse("shop_detail", args=[o.shop_id]), "shop"),
        (Purchase.objects.filter(user=user, buyer__isnull=True).select_related("category"), lambda o: -1,
         lambda o: _("Bazar: %(what)s") % {"what": o.category}, lambda o: o.description,
         lambda o: reverse("household_month_detail", kwargs={"year": o.date.year, "month": o.date.month}), "household"),
        (Settlement.objects.filter(member__user=user).select_related("member"), lambda o: -1,
         lambda o: _("Paid back %(name)s") % {"name": o.member.name}, lambda o: o.note,
         lambda o: reverse("household_member_detail", args=[o.member_id]), "household"),
        (Contribution.objects.filter(contributor__user=user).select_related("contributor"), lambda o: 1,
         lambda o: _("From %(name)s") % {"name": o.contributor.name}, lambda o: o.note,
         lambda o: reverse("contributor_detail", args=[o.contributor_id]), "contribution"),
    ]


def movements(user, wallet=None):
    """Every movement of money through the user's wallets, oldest first."""
    rows = []
    only = wallet.pk if wallet is not None else None
    for qs, sign, title, detail, url, kind in _sources(user):
        qs = qs.filter(wallet__isnull=False) if only is None else qs.filter(wallet_id=only)
        for o in qs:
            rows.append(Move(o.date, o.wallet_id, o.amount * sign(o), title(o), (detail(o) or "")[:80], url(o), kind))
    transfers = Transfer.objects.filter(user=user).select_related("from_wallet", "to_wallet")
    for t in transfers:
        link = reverse("wallet_transfer_edit", args=[t.pk])
        if only is None or t.from_wallet_id == only:
            rows.append(Move(t.date, t.from_wallet_id, -(t.amount + t.fee), _("Sent to %(name)s") % {"name": t.to_wallet},
                             _("incl. %(fee)s fee") % {"fee": money(t.fee)} if t.fee else (t.note or ""), link, "transfer"))
        if only is None or t.to_wallet_id == only:
            rows.append(Move(t.date, t.to_wallet_id, t.amount, _("From %(name)s") % {"name": t.from_wallet}, t.note or "", link, "transfer"))
    adjustments = Adjustment.objects.filter(wallet__user=user)
    if only is not None:
        adjustments = adjustments.filter(wallet_id=only)
    for a in adjustments:
        rows.append(Move(a.date, a.wallet_id, a.amount, _("Balance corrected"), a.note or "", "", "adjust"))
    # The opening balance already holds everything before its date.
    starts = dict(Wallet.objects.filter(user=user).values_list("pk", "opening_date"))
    rows = [m for m in rows if m.wallet_id in starts and m.date >= starts[m.wallet_id]]
    rows.sort(key=lambda m: (m.date, m.amount < 0))   # within a day, money in before money out
    return rows


def balances(user):
    """{wallet id: balance now}, opening balance included."""
    totals = {w.pk: w.opening_balance for w in Wallet.objects.filter(user=user)}
    for m in movements(user):
        if m.wallet_id in totals:
            totals[m.wallet_id] += m.amount
    return totals


def history(wallet):
    """(moves newest first with a running balance, balance now)."""
    rows = movements(wallet.user, wallet)
    running = wallet.opening_balance
    for m in rows:
        running += m.amount
        m.balance = running
    return list(reversed(rows)), running
