"""What's attached to a record, for the box that asks before a delete (templates/partials/ask.html).

The question itself says what deleting does; these lines say what it touches in this very case: money still
owed, fish in the pond, how many entries go with it. A form asks for them with data-confirm-check.
"""
from urllib.parse import urlsplit

from django.contrib.auth.decorators import login_required
from django.db import models
from django.http import JsonResponse
from django.urls import Resolver404, resolve
from django.utils.module_loading import import_string
from django.utils.translation import gettext as _, ngettext


def _attached(obj):
    """{what deleting does to them: how many}, from every record that points at this one."""
    from apps.business.core.models import AuditLog

    out = {}
    for rel in obj._meta.get_fields(include_hidden=True):
        if not (rel.auto_created and rel.one_to_many) or rel.related_model is AuditLog:
            continue
        count = rel.related_model._default_manager.filter(**{rel.field.name: obj}).count()
        if count:
            out[rel.on_delete] = out.get(rel.on_delete, 0) + count
    return out


def _still_used(obj):
    """A business record is only hidden: whatever uses it stays as it is."""
    count = sum(_attached(obj).values())
    if not count:
        return []
    return [ngettext("%(n)s record uses it, and stays as it is.", "%(n)s records use it, and stay as they are.", count) % {"n": count}]


def _goes_with_it(obj):
    attached, lines = _attached(obj), []
    gone, kept = attached.get(models.CASCADE, 0), attached.get(models.SET_NULL, 0)
    if gone:
        lines.append(ngettext("%(n)s entry goes with it.", "%(n)s entries go with it.", gone) % {"n": gone})
    if kept:
        lines.append(ngettext("%(n)s entry stays, without it.", "%(n)s entries stay, without it.", kept) % {"n": kept})
    return lines


# ── Business: what matters most comes first ─────────────────────────────────

def _pond(pond):
    from apps.business.ponds import services

    lines = []
    running = services.running_cycle(pond)
    if running:
        lines.append(_("Fish are in this pond now (%(cycle)s).") % {"cycle": running.label})
    if pond.is_leased and pond.lease_amount:
        due = services.lease_status(pond).due
        if due > 0:
            lines.append(_("%(amount)s of its lease is still unpaid.") % {"amount": _money(due)})
    return lines


def _account(account):
    lines = []
    balance = account.balance
    if balance:
        lines.append(_("Its balance is %(amount)s. That stops counting in your total money.") % {"amount": _money(balance)})
    if account.is_default:
        lines.append(_("This is your default account. Pick another one for new entries."))
    return lines


def _worker(worker):
    from apps.business.staff import services

    balance = services.balance(worker)
    if balance > 0:
        return [_("You still owe them %(amount)s.") % {"amount": _money(balance)}]
    if balance < 0:
        return [_("They still hold an advance of %(amount)s.") % {"amount": _money(-balance)}]
    return []


def _loan(loan):
    left = loan.schedule().outstanding
    return [_("%(amount)s of this loan is still to pay.") % {"amount": _money(left)}] if left > 0 else []


def _lender(lender):
    return [line for loan in lender.loans.all() for line in _loan(loan)]


def _money(value):
    from apps.business.core.templatetags.business import bdt

    return bdt(value)


BUSINESS = {
    "business:ponds_delete": _pond, "business:accounts_delete": _account, "business:staff_delete": _worker, "business:loan_delete": _loan, "business:lender_delete": _lender,
}
OTHERS = {     # the ones not made by Master (apps/business/core/crud.py)
    "business:loan_delete": "apps.business.loans.models.Loan", "business:lender_delete": "apps.business.loans.models.Lender",
    "business:cycle_delete": "apps.business.ponds.models.CultureCycle",
}


def _business(request, name, pk):
    from apps.business.core.access import active_membership, can
    from apps.business.core.crud import MASTERS

    membership = active_membership(request)
    master, path = MASTERS.get(name), OTHERS.get(name)
    model = master.model if master else import_string(path) if path else None
    if model is None or not can(membership, "delete"):
        return [], False
    obj = model.objects.filter(pk=pk, business=membership.business).first()
    if obj is None:
        return [], False
    problem = master.delete_check(obj) if master and master.delete_check else None
    if problem:         # the server would refuse it: say why now, not after the click
        return [problem], True
    return (BUSINESS[name](obj) if name in BUSINESS else []) + _still_used(obj), False


# ── Personal and Productivity: deleting takes what belongs to it along ──────

def _i_owe(obj):
    return [_("You still owe %(amount)s.") % {"amount": _money(obj.remaining)}] if obj.remaining > 0 else []


def _owed_to_me(obj):
    return [_("You're still owed %(amount)s.") % {"amount": _money(obj.remaining)}] if obj.remaining > 0 else []


def _member(obj):
    return [_("You still owe %(amount)s.") % {"amount": _money(obj.balance_due)}] if obj.balance_due > 0 else []


def _wallet(obj):
    from apps.wallets.services import balances

    balance = balances(obj.user).get(obj.pk)
    return [_("%(amount)s is in this wallet.") % {"amount": _money(balance)}] if balance else []


MINE = {       # the delete's URL name: the record, whose it is, and what to say about its money
    "creditor_delete": ("apps.creditors.models.Creditor", "user", _i_owe),
    "debtor_delete": ("apps.debtors.models.Debtor", "user", _owed_to_me),
    "shop_delete": ("apps.shops.models.Shop", "user", _i_owe),
    "household_member_delete": ("apps.household.models.HouseholdMember", "user", _member),
    "income_source_delete": ("apps.income.models.IncomeSource", "user", None),
    "contributor_delete": ("apps.contributors.models.Contributor", "user", None),
    "wallet_delete": ("apps.wallets.models.Wallet", "user", _wallet),
    "work:project_delete": ("apps.productivity.models.Project", "owner", None),
    "work:exam_subject": ("apps.productivity.models.ExamSubject", "owner", None),
    "work:prep_topic": ("apps.productivity.models.PrepTopic", "owner", None),
}


def _mine(request, name, pk):
    path, owner, money = MINE[name]
    obj = import_string(path)._default_manager.filter(pk=pk, **{owner: request.user}).first()
    if obj is None:
        return []
    return (money(obj) if money else []) + _goes_with_it(obj)


@login_required
def delete_check_view(request):
    try:
        match = resolve(urlsplit(request.GET.get("url", "")).path)
    except Resolver404:
        return JsonResponse({"lines": []})
    name, pk = match.view_name, match.kwargs.get("pk")
    lines, blocked = [], False
    if name in MINE:
        lines = _mine(request, name, pk)
    elif name.startswith("business:"):
        lines, blocked = _business(request, name, pk)
    return JsonResponse({"lines": [str(line) for line in lines], "blocked": blocked})
