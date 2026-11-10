"""Someone you both borrowed from and lent to.

A friend can be in Creditors (you owe them) and in Debtors (they owe you) at
the same time. Kept apart, neither page says what you owe each other overall.
This finds those pairs, shows the net, and can "set off" one against the
other: the smaller balance is cleared on both sides with one entry each, no
money moving through a wallet — the way people settle it in real life ("you
owe me 3,000, I owe you 5,000, so I give you 2,000").

Two records are the same person when both have a phone number and the
numbers match (last 10 digits, so +880 / 0 prefixes don't matter); when
either has no number, when the names match (case and spacing ignored).
"""
import re
from dataclasses import dataclass
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.ledger_views import safe_next
from apps.core.templatetags.ui import money
from apps.creditors.models import Creditor, Transaction as CreditorTx
from apps.debtors.models import Debtor, Transaction as DebtorTx

ZERO = Decimal("0.00")


def phone_key(phone):
    digits = re.sub(r"\D", "", phone or "")
    return digits[-10:] if len(digits) >= 10 else (digits or None)


def name_key(name):
    return " ".join((name or "").split()).casefold()


def same_person(a, b):
    pa, pb = phone_key(a.phone), phone_key(b.phone)
    if pa and pb:
        return pa == pb
    return name_key(a.name) == name_key(b.name)


def _with_balance(qs, out_type, in_type):
    zero = Value(0, output_field=DecimalField())
    return qs.annotate(
        _out=Coalesce(Sum("transactions__amount", filter=Q(transactions__transaction_type=out_type)), zero),
        _in=Coalesce(Sum("transactions__amount", filter=Q(transactions__transaction_type=in_type)), zero),
    )


@dataclass
class Pair:
    creditor: Creditor
    debtor: Debtor

    @property
    def you_owe(self):
        return max(self.creditor.balance, ZERO)

    @property
    def they_owe(self):
        return max(self.debtor.balance, ZERO)

    @property
    def net(self):
        """+ they owe you overall, − you owe them overall."""
        return self.they_owe - self.you_owe

    @property
    def net_size(self):
        """The net, without its sign, for sentences like "Overall you owe them ৳2,000"."""
        return abs(self.net)

    @property
    def can_set_off(self):
        return min(self.you_owe, self.they_owe)

    @property
    def name(self):
        return self.creditor.name


def pairs(user, creditor=None, debtor=None):
    """Every creditor/debtor pair that is one person, biggest set-off first.
    Narrow with `creditor=` or `debtor=` to find one record's other side."""
    creditors = _with_balance(Creditor.objects.filter(user=user), CreditorTx.BORROW, CreditorTx.REPAY)
    debtors = _with_balance(Debtor.objects.filter(user=user), DebtorTx.LEND, DebtorTx.RECEIVE)
    if creditor is not None:
        creditors = creditors.filter(pk=creditor.pk)
    if debtor is not None:
        debtors = debtors.filter(pk=debtor.pk)
    debtors = list(debtors)
    by_phone, by_name = {}, {}
    for d in debtors:
        d.balance = d._out - d._in
        if phone_key(d.phone):
            by_phone.setdefault(phone_key(d.phone), []).append(d)
        by_name.setdefault(name_key(d.name), []).append(d)
    found = []
    for c in creditors:
        c.balance = c._out - c._in
        candidates = by_phone.get(phone_key(c.phone), []) + by_name.get(name_key(c.name), [])
        seen = set()
        for d in candidates:
            if d.pk not in seen and same_person(c, d):
                seen.add(d.pk)
                found.append(Pair(c, d))
    found.sort(key=lambda p: (-p.can_set_off, -(p.you_owe + p.they_owe), p.name.casefold()))
    return found


@login_required
def people_view(request):
    rows = pairs(request.user)
    return render(request, "overview/people.html", {
        "pairs": rows,
        "can_set_off_total": sum((p.can_set_off for p in rows), ZERO),
    })


@login_required
@require_POST
def set_off_view(request):
    """Clear the smaller of the two balances on both sides. The amount is worked
    out here from the ledgers, never taken from the page."""
    creditor = get_object_or_404(Creditor, pk=request.POST.get("creditor") or 0, user=request.user)
    debtor = get_object_or_404(Debtor, pk=request.POST.get("debtor") or 0, user=request.user)
    back = safe_next(request, reverse("people"))
    if not same_person(creditor, debtor):
        messages.error(request, _("These two aren't the same person (their names or phone numbers differ), so nothing was changed."))
        return redirect(back)
    found = pairs(request.user, creditor=creditor, debtor=debtor)
    amount = found[0].can_set_off if found else ZERO
    if amount <= 0:
        messages.info(request, _("There's nothing to set off: one side owes nothing."))
        return redirect(back)
    today = timezone.localdate()
    # Read above, write here: the live site runs SQLite, where a transaction that
    # reads before it writes can fail with "database is locked".
    with transaction.atomic():
        CreditorTx.objects.create(creditor=creditor, transaction_type=CreditorTx.REPAY, amount=amount, date=today,
                                  note=_("Set off against what %(name)s owes you") % {"name": debtor.name})
        DebtorTx.objects.create(debtor=debtor, transaction_type=DebtorTx.RECEIVE, amount=amount, date=today,
                                note=_("Set off against what you owe %(name)s") % {"name": creditor.name})
    messages.success(request, _("Set off %(amount)s with %(name)s: you owe them that much less, and they owe you that much less. No wallet changed.") % {
        "amount": money(amount), "name": creditor.name})
    return redirect(back)
