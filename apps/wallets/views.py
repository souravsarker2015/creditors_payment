from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.templatetags.ui import money, signed_money
from apps.trash.undo import delete_with_undo

from . import services
from .forms import CorrectBalanceForm, TransferForm, WalletForm
from .models import Adjustment, Transfer, Wallet, WalletKind

ZERO = Decimal(0)


def _wallet(request, pk):
    return get_object_or_404(Wallet, pk=pk, user=request.user)


@login_required
def wallet_list_view(request):
    wallets = list(Wallet.objects.filter(user=request.user))
    balances = services.balances(request.user)
    for w in wallets:
        w.balance = balances.get(w.pk, w.opening_balance)
    active = [w for w in wallets if w.is_active]
    return render(request, "wallets/list.html", {
        "wallets": active, "stopped": [w for w in wallets if not w.is_active],
        "total": sum((w.balance for w in active), ZERO),
        "by_kind": [(label, sum((w.balance for w in active if w.kind == kind), ZERO))
                    for kind, label in WalletKind.choices if any(w.kind == kind for w in active)],
        "transfers": Transfer.objects.filter(user=request.user).select_related("from_wallet", "to_wallet")[:8],
    })


@transaction.atomic
def _save_wallet(form, user):
    w = form.save(commit=False)
    w.user = user
    w.save()
    if w.is_default:
        Wallet.objects.filter(user=user, is_default=True).exclude(pk=w.pk).update(is_default=False)
    return w


@login_required
def wallet_form_view(request, pk=None):
    obj = _wallet(request, pk) if pk else None
    first = not Wallet.objects.filter(user=request.user).exists()
    form = WalletForm(request.POST or None, instance=obj, user=request.user, initial={"is_default": True} if first else None)
    if request.method == "POST" and form.is_valid():
        w = _save_wallet(form, request.user)
        messages.success(request, _("Saved: %(name)s.") % {"name": w.name})
        return redirect("wallet_detail", pk=w.pk)
    return render(request, "wallets/form.html", {
        "form": form, "title": _("Edit wallet") if obj else _("Add a wallet"),
        "subtitle": None if obj else _("Cash in hand, a bank account or bKash — wherever you keep money."),
        "back": reverse("wallet_detail", args=[obj.pk]) if obj else reverse("wallet_list"),
    })


@login_required
def wallet_detail_view(request, pk):
    w = _wallet(request, pk)
    rows, balance = services.history(w)
    return render(request, "wallets/detail.html", {
        "w": w, "rows": rows[:300], "more": len(rows) > 300, "balance": balance,
        "money_in": sum((m.amount for m in rows if m.amount > 0), ZERO),
        "money_out": -sum((m.amount for m in rows if m.amount < 0), ZERO),
        "correct_form": CorrectBalanceForm(initial={"actual": format(balance, "f")}),
    })


@login_required
@require_POST
def correct_balance_view(request, pk):
    w = _wallet(request, pk)
    form = CorrectBalanceForm(request.POST)
    if form.is_valid():
        _rows, balance = services.history(w)
        diff = form.cleaned_data["actual"] - balance
        if diff:
            Adjustment.objects.create(wallet=w, amount=diff, note=form.cleaned_data["note"])
            messages.success(request, _("Balance corrected by %(amount)s. %(name)s now shows %(balance)s.") % {
                "amount": signed_money(diff), "name": w.name, "balance": money(form.cleaned_data["actual"])})
        else:
            messages.info(request, _("That's what the app shows already — nothing to correct."))
    else:
        messages.error(request, _("Enter the amount the wallet really holds."))
    return redirect("wallet_detail", pk=w.pk)


@login_required
@require_POST
def wallet_toggle_view(request, pk):
    w = _wallet(request, pk)
    w.is_active = not w.is_active
    if not w.is_active:
        w.is_default = False
    w.save(update_fields=["is_active", "is_default"])
    messages.success(request, (_("%(name)s is in use again.") if w.is_active else _("%(name)s is no longer offered for new entries.")) % {"name": w.name})
    return redirect("wallet_detail", pk=w.pk)


@login_required
@require_POST
def wallet_delete_view(request, pk):
    w = _wallet(request, pk)
    delete_with_undo(request, w, _("Wallet deleted: %(name)s. Its entries are kept, without a wallet.") % {"name": w.name},
                     label=w.name, back_url=reverse("wallet_detail", args=[w.pk]))
    return redirect("wallet_list")


@login_required
def transfer_form_view(request, pk=None):
    obj = get_object_or_404(Transfer, pk=pk, user=request.user) if pk else None
    initial = {}
    if not obj and request.GET.get("from", "").isdigit():
        initial["from_wallet"] = request.GET["from"]
    form = TransferForm(request.POST or None, instance=obj, user=request.user, initial=initial)
    if request.method == "POST" and form.is_valid():
        t = form.save(commit=False)
        t.user = request.user
        t.save()
        messages.success(request, _("Moved %(amount)s from %(a)s to %(b)s.") % {"amount": money(t.amount), "a": t.from_wallet, "b": t.to_wallet})
        return redirect("wallet_list")
    return render(request, "wallets/form.html", {
        "form": form, "title": _("Edit transfer") if obj else _("Move money between wallets"),
        "subtitle": _("e.g. cash out from bKash, or put cash in the bank."), "back": reverse("wallet_list"),
        "transfer": obj,
    })


@login_required
@require_POST
def transfer_delete_view(request, pk):
    t = get_object_or_404(Transfer, pk=pk, user=request.user)
    delete_with_undo(request, t, _("Transfer of %(amount)s deleted.") % {"amount": money(t.amount)},
                     label=f"{t.from_wallet} → {t.to_wallet} · {money(t.amount)}", back_url=reverse("wallet_list"))
    return redirect("wallet_list")
