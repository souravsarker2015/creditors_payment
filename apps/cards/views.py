from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.ledger_views import _build_pagination_window
from apps.core.nav import back_to
from apps.core.templatetags.ui import money, signed_money
from apps.trash.undo import delete_with_undo
from apps.wallets.models import Wallet, WalletKind
from apps.wallets.services import warn_if_short

from . import services as sv
from .forms import CardForm, CorrectForm, EmiForm, EntryForm, MfsFeesForm, PayOffForm
from .models import Card, CardEntry, EmiPlan, EntryKind, MfsFees

ZERO = Decimal(0)

def _texts():
    """(title, subtitle, button) for each kind of entry."""
    return {
        EntryKind.CASH: (_("Take money to bKash / Nagad"), _("Money sent from the card to a mobile banking wallet (or bank). The card owes it plus its fee."), _("Save")),
        EntryKind.SPEND: (_("Bought with the card"), _("Something paid for with the card — it counts as spending, and goes on the next bill."), _("Save")),
        EntryKind.CHARGE: (_("Bank charge"), _("Interest, a late fee, the annual fee or VAT the bank put on the bill."), _("Save")),
        EntryKind.PAY: (_("Pay the card bill"), _("Money paid to the card. Pick the wallet it came from — its fee comes out of that wallet too."), _("Save payment")),
        EntryKind.REFUND: (_("Refund / cashback"), _("Money the shop or bank put back on the card."), _("Save")),
    }


def _today():
    return timezone.localdate()


def _steps(user):
    """The first five things to do, each ticked by itself once it's done (the dashboard and the guide show them)."""
    cards = Card.objects.filter(user=user)
    mobile = Wallet.objects.filter(user=user, kind=WalletKind.MOBILE)
    entries = CardEntry.objects.filter(card__user=user)
    first_card = cards.filter(is_active=True).first()
    first_mobile = mobile.filter(is_active=True).first()
    steps = [
        {"done": cards.exists(), "title": _("Add your credit card"),
         "text": _("Its name and two dates from the card bill: the bill day and the pay-by day. Add each card you have — UCB, EBL, DBBL…"),
         "url": reverse("card_create"), "button": _("Add a card")},
        {"done": mobile.exists(), "title": _("Add your mobile banking"),
         "text": _("bKash, Nagad, Rocket — whichever you use, with what each holds today."),
         "url": reverse("card_mfs_add"), "button": _("Add mobile banking")},
        {"done": MfsFees.objects.filter(wallet__user=user).exists(), "title": _("Set each one's charges"),
         "text": _("What bKash, Nagad or Rocket charge to pay a card bill, or to send money to a bank. The app then picks the cheapest way to pay."),
         "url": reverse("card_mfs_detail", args=[first_mobile.pk]) if first_mobile else reverse("card_mfs"), "button": _("Set charges")},
        {"done": entries.filter(kind__in=[EntryKind.CASH, EntryKind.SPEND]).exists(), "title": _("Record money taken from a card"),
         "text": _("Sent money from a card to bKash or Nagad? Record it with the card's fee (1%, 1.5%…). Bought something with the card? Record that too."),
         "url": reverse("card_entry_new", args=["cash"]), "button": _("Take money to bKash / Nagad")},
        {"done": entries.filter(kind=EntryKind.PAY).exists(), "title": _("Pay a bill"),
         "text": _("When the bill comes, record what you paid and from which wallet — in full, the minimum, or any part."),
         "url": reverse("card_entry_add", args=[first_card.pk, "pay"]) if first_card else reverse("card_entry_new", args=["pay"]), "button": _("Pay a bill")},
    ]
    nxt = next((s for s in steps if not s["done"]), None)
    if nxt:
        nxt["next"] = True
    done = sum(1 for s in steps if s["done"])
    return {"rows": steps, "done": done, "total": len(steps), "pct": done * 100 // len(steps), "all": done == len(steps)}


def _next(request, fallback):
    """Where to go after saving or deleting: the page it was opened from (?next=), else `fallback`."""
    return back_to(request, request.POST.get("next") or request.GET.get("next"), fallback)


@login_required
def guide_view(request):
    """How the credit card pages work, for someone who has never used them."""
    return render(request, "cards/guide.html", {"steps": _steps(request.user), "has_cards": Card.objects.filter(user=request.user).exists()})


def _card(request, pk):
    return get_object_or_404(Card, pk=pk, user=request.user)


# ── The dashboard ────────────────────────────────────────────────────────────

@login_required
def dashboard_view(request):
    today = _today()
    states = sv.states(request.user, today)
    active = [s for s in states if s.card.is_active]
    owed = sum((max(s.owed, ZERO) for s in states), ZERO)
    limit = sum((s.card.limit or ZERO for s in active), ZERO)
    to_pay = sorted([s for s in states if s.to_pay], key=lambda s: s.to_pay.due)
    month_start = today.replace(day=1)
    year_start = today.replace(month=1, day=1)
    cost_all, cost_month, cost_year = sv.Costs(), sv.Costs(), sv.Costs()
    for s in states:
        cost_all.add(s.costs)
        cost_month.add(sv.costs(s.events, month_start, today))
        cost_year.add(sv.costs(s.events, year_start, today))
    series = sv.series(states, today)
    emis = [(s.card, e) for s in states for e in s.emis if not e.done]
    recent = sorted((e for s in states for e in s.events if e.entry is not None and e.date <= today),
                    key=lambda e: (e.date, e.entry.pk), reverse=True)[:8]
    return render(request, "cards/dashboard.html", {
        "states": states, "active": active, "today": today,
        "owed": owed, "limit": limit, "available": limit - sum((max(s.owed, ZERO) for s in active if s.card.limit), ZERO) if limit else None,
        "used_pct": max(0, min(100, int(sum((max(s.owed, ZERO) for s in active if s.card.limit), ZERO) * 100 / limit))) if limit else None,
        "billed": sum((s.to_pay.left for s in to_pay), ZERO),
        "to_pay": to_pay, "next": to_pay[0] if to_pay else None,
        "emi_left": sum((s.emi_left for s in states), ZERO),
        "emis": emis,
        "cost_all": cost_all, "cost_month": cost_month, "cost_year": cost_year,
        "taken_month": sum((x.amount for s in states for x in (e.entry for e in s.events if e.entry is not None)
                            if x.kind == EntryKind.CASH and month_start <= x.date <= today), ZERO),
        "chart": {"labels": [m.strftime("%b %y") for m in series["months"]], **{k: series[k] for k in ("taken", "spent", "paid", "fees")}},
        "has_chart": any(any(series[k]) for k in ("taken", "spent", "paid", "fees")),
        "mfs": sv.mfs_rows(request.user, today),
        "cost": sv.borrowing_cost(states, today),
        "tips": _tips(states, today),
        "recent": recent,
        "steps": _steps(request.user),
        "record_count": CardEntry.objects.filter(card__user=request.user).count(),
    })


def _tips(states, today):
    """Plain advice from the numbers, most useful first (at most 4)."""
    tips = []
    for s in states:
        b = s.to_pay
        c = s.card
        if b and b.status == sv.MISSED:
            tips.append(("critical", _("%(card)s: not even the minimum (%(min)s) was paid by %(due)s. Pay at least that now — a late fee and interest are likely.") % {
                "card": c, "min": money(b.min_due), "due": b.due.strftime("%d %b")}))
        elif b and b.status == sv.PARTIAL:
            tips.append(("warn", _("%(card)s: %(left)s of the bill is still unpaid. Interest is charged until it's paid in full%(interest)s.") % {
                "card": c, "left": money(b.left), "interest": (_(" — about %(x)s a month") % {"x": money(b.interest)}) if b.interest else ""}))
        elif b and b.status == sv.OPEN and b.days <= sv.SOON_DAYS:
            tips.append(("warn", _("%(card)s: pay %(left)s by %(due)s (in %(days)s days) to avoid any interest.") % {
                "card": c, "left": money(b.left), "due": b.due.strftime("%d %b"), "days": b.days}))
        if s.used_pct is not None and s.used_pct >= 70 and c.is_active:
            tips.append(("warn", _("%(card)s is %(pct)s%% used. Keeping it under 30%% is better for your credit record.") % {"card": c, "pct": s.used_pct}))
        if c.annual_fee and c.annual_fee_month and c.is_active:
            months_to = (c.annual_fee_month - today.month) % 12
            if months_to <= 1:
                tips.append(("info", _("%(card)s: the annual fee (%(fee)s) is due around %(month)s. Ask the bank if it can be waived — many waive it after enough card use.") % {
                    "card": c, "fee": money(c.annual_fee), "month": c.get_annual_fee_month_display()}))
        if c.expiry and c.is_active:
            try:
                mm, yy = (int(x) for x in c.expiry.split("/"))
                left = (2000 + yy - today.year) * 12 + mm - today.month
                if 0 <= left <= 2:
                    tips.append(("info", _("%(card)s runs out at the end of %(expiry)s. Check the bank has sent the new one.") % {"card": c, "expiry": c.expiry}))
            except ValueError:
                pass
    order = {"critical": 0, "warn": 1, "info": 2}
    return sorted(tips, key=lambda t: order[t[0]])[:4]


# ── A card ───────────────────────────────────────────────────────────────────

@login_required
def card_form_view(request, pk=None):
    obj = _card(request, pk) if pk else None
    sv.ensure_networks(request.user)
    form = CardForm(request.POST or None, instance=obj, user=request.user)
    if request.method == "POST" and form.is_valid():
        c = form.save(commit=False)
        c.user = request.user
        c.save()
        messages.success(request, _("Saved: %(name)s.") % {"name": c.name})
        return redirect("card_detail", pk=c.pk)
    return render(request, "cards/form.html", {
        "form": form, "obj": obj,
        "title": _("Edit card") if obj else _("Add a credit card"),
        "back": reverse("card_detail", args=[obj.pk]) if obj else reverse("card_dashboard"),
    })


@login_required
def card_detail_view(request, pk):
    c = _card(request, pk)
    today = _today()
    st = sv.card_state(c, today)
    pay_amount = st.to_pay.left if st.to_pay else (st.billable if st.billable > 0 else ZERO)
    rows = sv.ledger(st, today)[:300]
    groups = {"cash": ("cash",), "spend": ("spend",), "pay": ("pay", "refund"), "charge": ("charge", "emi_fee", "adjust", "open"),
              "emi": ("emi_move", "emi_inst", "emi_close")}
    for e in rows:
        e.group = next((g for g, kinds in groups.items() if e.kind in kinds), "charge")
    tab = request.GET.get("tab", "")
    return render(request, "cards/detail.html", {
        "c": c, "st": st, "today": today,
        "tab": tab if tab in ("overview", "bills", "records", "emis", "details") else "overview",
        "bills": list(reversed(st.bills))[:24],
        "rows": rows,
        "row_groups": [(g, label, sum(1 for e in rows if e.group == g)) for g, label in (
            ("cash", _("Taken out")), ("spend", _("Bought")), ("pay", _("Paid")), ("charge", _("Charges")), ("emi", _("EMI")))],
        "here": reverse("card_detail", args=[c.pk]) + "?tab=records",
        "routes": sv.pay_routes(request.user, pay_amount) if pay_amount > 0 else [],
        "pay_amount": pay_amount,
        "correct_form": CorrectForm(initial={"actual": format(st.owed, "f")}),
        "cost_rows": st.costs.rows(),
        "emis": st.emis,
    })


@login_required
@require_POST
def card_toggle_view(request, pk):
    c = _card(request, pk)
    c.is_active = not c.is_active
    c.save(update_fields=["is_active"])
    messages.success(request, (_("%(name)s is in use again.") if c.is_active else _("%(name)s is no longer offered for new entries.")) % {"name": c.name})
    return redirect("card_detail", pk=c.pk)


@login_required
@require_POST
def card_delete_view(request, pk):
    c = _card(request, pk)
    delete_with_undo(request, c, _("Card deleted: %(name)s, with its entries and EMIs.") % {"name": c.name},
                     label=c.name, back_url=reverse("card_detail", args=[c.pk]))
    return redirect("card_dashboard")


@login_required
@require_POST
def card_correct_view(request, pk):
    c = _card(request, pk)
    form = CorrectForm(request.POST)
    if form.is_valid():
        st = sv.card_state(c, _today())
        diff = form.cleaned_data["actual"] - st.owed
        if diff:
            CardEntry.objects.create(card=c, kind=EntryKind.ADJUST, amount=diff, date=_today(),
                                     note=form.cleaned_data["note"] or _("Matched to the bank"))
            messages.success(request, _("Corrected by %(amount)s. %(name)s now shows %(owed)s owed.") % {
                "amount": signed_money(diff), "name": c.name, "owed": money(form.cleaned_data["actual"])})
        else:
            messages.info(request, _("That's what the app shows already — nothing to correct."))
    else:
        messages.error(request, _("Enter what you really owe on the card."))
    return redirect("card_detail", pk=c.pk)


# ── Entries ──────────────────────────────────────────────────────────────────

def _entry_page(request, form, kind, card, obj=None):
    title, subtitle, button = _texts()[kind]
    user = request.user
    cards = Card.objects.filter(user=user)
    rates = {str(c.pk): sv.rate_guide(c, user) for c in cards} if kind in (EntryKind.CASH, EntryKind.PAY) else {}
    owed = {}
    if kind == EntryKind.PAY:
        for c in cards.filter(is_active=True):
            st = sv.card_state(c, _today())
            owed[str(c.pk)] = {"bill": float(st.to_pay.left) if st.to_pay else 0.0, "min": float(st.to_pay.min_due) if st.to_pay else 0.0,
                               "all": float(max(st.billable, ZERO))}
    initial_amount = form["amount"].value() or ""
    return render(request, "cards/entry_form.html", {
        "form": form, "kind": kind, "obj": obj, "card": card,
        "title": _("Edit") + " · " + title if obj else title, "subtitle": subtitle, "submit_label": button,
        "back": _next(request, reverse("card_entry_detail", args=[obj.pk]) if obj else reverse("card_detail", args=[card.pk]) if card else reverse("card_dashboard")),
        "next": back_to(request, request.POST.get("next") or request.GET.get("next"), ""),
        "guide": ({"rates": rates, "owed": owed, "card": str(form["card"].value() or ""), "wallet": str(form["wallet"].value() or "") if "wallet" in form.fields else "",
                             "route": form["route"].value() or "" if "route" in form.fields else "", "amount": str(initial_amount),
                             "rate": str(form["fee_rate"].value() or "") if "fee_rate" in form.fields else "",
                             "fee": str(form["fee"].value() or "") if "fee" in form.fields else "", "typed": bool(obj and obj.fee)}),
        "has_wallets": Wallet.objects.filter(user=user, is_active=True).exists(),
        "has_mobile": Wallet.objects.filter(user=user, is_active=True, kind=WalletKind.MOBILE).exists(),
    })


def _after_save(request, e, created):
    c = e.card
    if e.kind == EntryKind.CASH:
        msg = _("%(amount)s to %(wallet)s from %(card)s.") % {"amount": money(e.amount), "wallet": e.wallet, "card": c}
        if e.fee:
            msg += " " + _("The card owes %(total)s with the fee.") % {"total": money(e.amount + e.fee)}
        messages.success(request, msg)
        st = sv.card_state(c, _today())
        if st.available is not None and st.available < 0:
            messages.warning(request, _("That's %(over)s over the card's limit. Check the amount, or the limit on the card.") % {"over": money(-st.available)})
        elif c.cash_limit and sum((x.amount + x.fee for x in c.entries.filter(kind=EntryKind.CASH, date__gt=(st.bill.date if st.bill else c.opening_date))), ZERO) > c.cash_limit:
            messages.warning(request, _("More than the card's cash / transfer limit since the last bill — the bank may refuse the next one."))
    elif e.kind == EntryKind.PAY:
        msg = _("%(amount)s paid to %(card)s.") % {"amount": money(e.amount), "card": c}
        if e.fee:
            msg += " " + _("Fee %(fee)s, from %(wallet)s.") % {"fee": money(e.fee), "wallet": e.wallet or _("the wallet")}
        st = sv.card_state(c, _today())
        if st.bill and st.bill.closing > 0 and st.bill.status in (sv.PAID, sv.LATE) and e.date > st.bill.date:
            msg += " " + _("The bill of %(date)s is paid in full.") % {"date": st.bill.date.strftime("%d %b")}
        elif st.to_pay:
            msg += " " + _("%(left)s of the bill is still to pay.") % {"left": money(st.to_pay.left)}
        messages.success(request, msg)
        if st.owed < 0:
            messages.info(request, _("You've paid %(extra)s more than you owe — the bank keeps it as credit for your next bill.") % {"extra": money(-st.owed)})
        warn_if_short(request, e.wallet_id)
    else:
        messages.success(request, _("Saved: %(what)s, %(amount)s on %(card)s.") % {"what": e.title, "amount": money(e.amount), "card": c})


@login_required
def entry_add_view(request, kind, pk=None):
    if kind not in sv_kinds():
        return redirect("card_dashboard")
    card = _card(request, pk) if pk else None
    cards = Card.objects.filter(user=request.user, is_active=True)
    if not cards.exists():
        messages.info(request, _("Add your card first."))
        return redirect("card_create")
    if card is None and cards.count() == 1:
        card = cards.first()
    initial = {"date": _today()}
    if card:
        initial["card"] = card.pk
    if request.GET.get("wallet", "").isdigit():
        initial["wallet"] = request.GET["wallet"]
    if request.GET.get("amount"):
        initial["amount"] = request.GET["amount"]
    if request.GET.get("route"):
        initial["route"] = request.GET["route"]
    copy = CardEntry.objects.filter(pk=request.GET.get("copy"), card__user=request.user, kind=kind).first() \
        if request.GET.get("copy", "").isdigit() else None
    if copy:                                     # "Record again": the same card, wallet, way and amount, dated today
        card = copy.card if copy.card.is_active else card
        initial.update({"card": card.pk if card else None, "wallet": copy.wallet_id, "route": copy.route, "amount": copy.amount,
                        "fee_rate": copy.fee_rate, "charge_type": copy.charge_type, "note": copy.note})
    if kind == EntryKind.CASH and card:
        initial.setdefault("fee_rate", card.transfer_fee_rate)
    form = EntryForm(request.POST or None, user=request.user, kind=kind, initial=initial)
    if request.method == "POST" and form.is_valid():
        e = form.save()
        _after_save(request, e, True)
        if "another" in request.POST:            # "Save and add another": the same form again, for the same card
            return redirect(reverse("card_entry_add", args=[e.card_id, kind]))
        return redirect(_next(request, reverse("card_detail", args=[e.card_id])))
    return _entry_page(request, form, kind, card)


def sv_kinds():
    return {EntryKind.CASH, EntryKind.SPEND, EntryKind.CHARGE, EntryKind.PAY, EntryKind.REFUND}


@login_required
def entry_edit_view(request, pk):
    e = get_object_or_404(CardEntry, pk=pk, card__user=request.user)
    if e.kind == EntryKind.ADJUST:
        messages.info(request, _("A correction can't be edited — delete it and correct the balance again."))
        return redirect("card_detail", pk=e.card_id)
    form = EntryForm(request.POST or None, user=request.user, kind=e.kind, instance=e)
    if request.method == "POST" and form.is_valid():
        e = form.save()
        _after_save(request, e, False)
        return redirect(_next(request, reverse("card_entry_detail", args=[e.pk])))
    return _entry_page(request, form, e.kind, e.card, obj=e)


@login_required
@require_POST
def entry_delete_view(request, pk):
    e = get_object_or_404(CardEntry, pk=pk, card__user=request.user)
    card_id = e.card_id
    delete_with_undo(request, e, _("Deleted: %(what)s of %(amount)s.") % {"what": e.title, "amount": money(e.amount)},
                     label=f"{e.card} · {e.title} · {money(e.amount)}", back_url=reverse("card_detail", args=[card_id]))
    back = _next(request, reverse("card_detail", args=[card_id]) + "?tab=records")
    if f"/entry/{pk}/" in back:                  # not back to the page of the record that's gone
        back = reverse("card_detail", args=[card_id]) + "?tab=records"
    return redirect(back)


@login_required
def entry_detail_view(request, pk):
    """Everything about one record: what it was, what it did to the card and the wallet, and which bill it's on."""
    e = get_object_or_404(CardEntry.objects.select_related("card", "card__bank", "wallet"), pk=pk, card__user=request.user)
    today = _today()
    st = sv.card_state(e.card, today)
    on_bill = next((b for b in st.bills if any(x.entry is not None and x.entry.pk == e.pk for x in b.events)), None)
    paid_bill = None
    if e.kind in (EntryKind.PAY, EntryKind.REFUND):
        paid_bill = next((b for b in reversed(st.bills) if b.date < e.date), None)
    after = next((x.balance for x in sv.ledger(st, today) if x.entry is not None and x.entry.pk == e.pk), None)
    card_change = e.debt
    wallet_change = None
    if e.wallet_id and e.kind == EntryKind.CASH:
        wallet_change = e.amount
    elif e.wallet_id and e.kind == EntryKind.PAY:
        wallet_change = -(e.amount + e.fee)
    return render(request, "cards/entry_detail.html", {
        "e": e, "c": e.card, "today": today, "on_bill": on_bill, "paid_bill": paid_bill,
        "later": None if on_bill or paid_bill or e.date > today else (st.next_bill, st.next_due),
        "future": e.date > today, "after": after,
        "card_change": card_change, "wallet_change": wallet_change,
        "can_edit": e.kind != EntryKind.ADJUST,
        "copy_url": reverse("card_entry_new", args=[e.kind]) + f"?copy={e.pk}" if e.kind in sv_kinds() else "",
        "back": _next(request, reverse("card_detail", args=[e.card_id]) + "?tab=records"),
    })


# ── Every record, on every card ──────────────────────────────────────────────

RECORD_KINDS = (EntryKind.CASH, EntryKind.SPEND, EntryKind.PAY, EntryKind.CHARGE, EntryKind.REFUND, EntryKind.ADJUST)


@login_required
def records_view(request):
    """Every record on every card, with filters: card, kind, wallet, dates and words in the note."""
    user = request.user
    qs = CardEntry.objects.filter(card__user=user).select_related("card", "wallet")
    f = {k: (request.GET.get(k) or "").strip() for k in ("card", "kind", "wallet", "start", "end", "q")}
    if f["card"].isdigit():
        qs = qs.filter(card_id=f["card"])
    if f["kind"] in RECORD_KINDS:
        qs = qs.filter(kind=f["kind"])
    if f["wallet"].isdigit():
        qs = qs.filter(wallet_id=f["wallet"])
    from django.utils.dateparse import parse_date
    start, end = parse_date(f["start"]) if f["start"] else None, parse_date(f["end"]) if f["end"] else None
    if start:
        qs = qs.filter(date__gte=start)
    if end:
        qs = qs.filter(date__lte=end)
    if f["q"]:
        qs = qs.filter(Q(note__icontains=f["q"]) | Q(card__name__icontains=f["q"]) | Q(wallet__name__icontains=f["q"]))
    sums = {k: v or ZERO for k, v in qs.order_by().values("kind").annotate(t=Sum("amount")).values_list("kind", "t")}
    fees = qs.aggregate(t=Sum("fee"))["t"] or ZERO
    charges = sums.get(EntryKind.CHARGE, ZERO)
    page = Paginator(qs.order_by("-date", "-id"), 40).get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    active = {k: v for k, v in f.items() if v}
    wallet_ids = set(CardEntry.objects.filter(card__user=user, wallet__isnull=False).values_list("wallet_id", flat=True))
    return render(request, "cards/records.html", {
        "page_obj": page, "rows": page.object_list, "pagination_window": _build_pagination_window(page),
        "base_query_string": query.urlencode(), "f": f, "filtered": bool(active),
        "count": page.paginator.count,
        "totals": {"taken": sums.get(EntryKind.CASH, ZERO), "spent": sums.get(EntryKind.SPEND, ZERO),
                   "paid": sums.get(EntryKind.PAY, ZERO) + sums.get(EntryKind.REFUND, ZERO), "costs": fees + charges},
        "cards": Card.objects.filter(user=user),
        "wallets": Wallet.objects.filter(Q(pk__in=wallet_ids) | Q(user=user, kind=WalletKind.MOBILE), user=user).order_by("name"),
        "kinds": [(k, EntryKind(k).label) for k in RECORD_KINDS],
        "here": request.get_full_path(),
        "has_any": CardEntry.objects.filter(card__user=user).exists(),
        "active_cards": Card.objects.filter(user=user, is_active=True).exists(),
    })


# ── EMI ──────────────────────────────────────────────────────────────────────

@login_required
def emi_form_view(request, pk=None, emi=None):
    obj = get_object_or_404(EmiPlan, pk=emi, card__user=request.user) if emi else None
    card = obj.card if obj else (_card(request, pk) if pk else None)
    initial = {}
    if not obj:
        initial = {"start": _today(), "months": 12}
        if card:
            initial["card"] = card.pk
            if request.GET.get("amount"):
                initial["amount"] = request.GET["amount"]
            initial["title"] = request.GET.get("title", "")
    if not Card.objects.filter(user=request.user, is_active=True).exists() and not obj:
        messages.info(request, _("Add your card first."))
        return redirect("card_create")
    form = EmiForm(request.POST or None, instance=obj, user=request.user, initial=initial)
    if request.method == "POST" and form.is_valid():
        p = form.save()
        st = sv.emi_state(p, _today())
        messages.success(request, _("EMI saved: %(each)s a month for %(n)s months, from the bill of %(first)s.") % {
            "each": money(st.each), "n": p.months, "first": st.rows[0].date.strftime("%d %b %Y")})
        return redirect("card_emi_detail", emi=p.pk)
    return render(request, "cards/emi_form.html", {
        "form": form, "obj": obj, "card": card,
        "title": _("Edit EMI") if obj else _("Turn into EMI"),
        "back": reverse("card_emi_detail", args=[obj.pk]) if obj else reverse("card_detail", args=[card.pk]) if card else reverse("card_dashboard"),
    })


@login_required
def emi_detail_view(request, emi):
    """One EMI: each month's installment, what's paid and left, and paying it off early."""
    p = get_object_or_404(EmiPlan.objects.select_related("card"), pk=emi, card__user=request.user)
    st = sv.emi_state(p, _today())
    return render(request, "cards/emi_detail.html", {
        "p": p, "c": p.card, "st": st,
        "payoff": PayOffForm() if not p.closed_on else None,
        "paid": sum((r.total for r in st.billed), ZERO),
        "total": sum((r.total for r in st.rows), ZERO),
        "back": _next(request, reverse("card_detail", args=[p.card_id]) + "?tab=emis"),
    })


@login_required
@require_POST
def emi_payoff_view(request, emi):
    p = get_object_or_404(EmiPlan, pk=emi, card__user=request.user)
    if "reopen" in request.POST:
        p.closed_on = None
        p.save(update_fields=["closed_on"])
        messages.success(request, _("The EMI runs again."))
        return redirect("card_emi_detail", emi=p.pk)
    form = PayOffForm(request.POST)
    if form.is_valid():
        p.closed_on = form.cleaned_data["closed_on"]
        p.save(update_fields=["closed_on"])
        st = sv.emi_state(p, _today())
        rest = p.amount - sum((r.principal for r in st.billed), ZERO)
        messages.success(request, _("EMI paid off early. The %(rest)s left goes on the next bill — pay it with the bill.") % {"rest": money(rest)})
    return redirect("card_emi_detail", emi=p.pk)


@login_required
@require_POST
def emi_delete_view(request, emi):
    p = get_object_or_404(EmiPlan, pk=emi, card__user=request.user)
    card_id = p.card_id
    delete_with_undo(request, p, _("EMI deleted: %(title)s.") % {"title": p.title}, label=f"{p.card} · EMI · {p.title}",
                     back_url=reverse("card_detail", args=[card_id]))
    back = _next(request, reverse("card_detail", args=[card_id]) + "?tab=emis")
    if f"/emi/{emi}/" in back:
        back = reverse("card_detail", args=[card_id]) + "?tab=emis"
    return redirect(back)


# ── Mobile banking ───────────────────────────────────────────────────────────

@login_required
def mfs_view(request):
    today = _today()
    rows = sv.mfs_rows(request.user, today)
    return render(request, "cards/mfs.html", {
        "rows": rows, "today": today,
        "received": sum((r.received for r in rows), ZERO), "paid": sum((r.paid for r in rows), ZERO),
        "fees": sum((r.fees_total for r in rows), ZERO),
    })


@login_required
def mfs_detail_view(request, wallet):
    w = get_object_or_404(Wallet, pk=wallet, user=request.user)
    today = _today()
    row = sv.mfs_rows(request.user, today, only=w)[0]
    fees = sv.fees_for(w)
    form = MfsFeesForm(request.POST or None, instance=fees)
    if request.method == "POST" and form.is_valid():
        f = form.save(commit=False)
        f.wallet = w
        f.save()
        messages.success(request, _("Charges saved for %(name)s.") % {"name": w.name})
        return redirect(_next(request, reverse("card_mfs_detail", args=[w.pk])))
    month = today.replace(day=1)
    return render(request, "cards/mfs_detail.html", {
        "w": w, "row": row, "form": form, "today": today,
        "entries": sorted(row.entries, key=lambda x: (x.date, x.pk), reverse=True)[:200],
        "month_in": sum((x.amount for x in row.entries if x.kind == EntryKind.CASH and x.date >= month), ZERO),
        "month_out": sum((x.amount for x in row.entries if x.kind == EntryKind.PAY and x.date >= month), ZERO),
        "month_fees": sum((x.fee for x in row.entries if x.date >= month), ZERO),
        "cards": list(row.by_card.values()),
    })


@login_required
def mfs_add_view(request):
    """A new mobile banking wallet (Upay, mCash…) and its charges in one go."""
    from apps.wallets.forms import WalletForm

    form = WalletForm(request.POST or None, user=request.user, initial={"kind": WalletKind.MOBILE})
    fees = MfsFeesForm(request.POST or None, prefix="fees")
    if request.method == "POST" and form.is_valid() and fees.is_valid():
        with transaction.atomic():
            w = form.save(commit=False)
            w.user = request.user
            w.save()
            f = fees.save(commit=False)
            f.wallet = w
            f.save()
        messages.success(request, _("Added %(name)s.") % {"name": w.name})
        return redirect("card_mfs_detail", wallet=w.pk)
    return render(request, "cards/mfs_add.html", {"form": form, "fees": fees, "back": reverse("card_mfs"),
                                                  "title": _("Add mobile banking")})


@login_required
def mfs_edit_view(request, wallet):
    """Change a mobile banking wallet — its name, number, what it held at the start — and its charges, in one form."""
    from apps.wallets.forms import WalletForm

    w = get_object_or_404(Wallet, pk=wallet, user=request.user)
    form = WalletForm(request.POST or None, instance=w, user=request.user)
    fees = MfsFeesForm(request.POST or None, instance=sv.fees_for(w), prefix="fees")
    if request.method == "POST" and form.is_valid() and fees.is_valid():
        with transaction.atomic():
            w = form.save()
            if w.is_default:
                Wallet.objects.filter(user=request.user, is_default=True).exclude(pk=w.pk).update(is_default=False)
            f = fees.save(commit=False)
            f.wallet = w
            f.save()
        messages.success(request, _("Saved: %(name)s.") % {"name": w.name})
        return redirect(_next(request, reverse("card_mfs_detail", args=[w.pk])))
    return render(request, "cards/mfs_add.html", {"form": form, "fees": fees, "obj": w, "title": _("Edit %(name)s") % {"name": w.name},
                                                  "back": _next(request, reverse("card_mfs_detail", args=[w.pk]))})


@login_required
@require_POST
def mfs_toggle_view(request, wallet):
    w = get_object_or_404(Wallet, pk=wallet, user=request.user)
    w.is_active = not w.is_active
    if not w.is_active:
        w.is_default = False
    w.save(update_fields=["is_active", "is_default"])
    messages.success(request, (_("%(name)s is in use again.") if w.is_active else _("%(name)s is no longer offered for new entries.")) % {"name": w.name})
    return redirect(_next(request, reverse("card_mfs_detail", args=[w.pk])))


@login_required
@require_POST
def mfs_delete_view(request, wallet):
    w = get_object_or_404(Wallet, pk=wallet, user=request.user)
    delete_with_undo(request, w, _("Deleted: %(name)s. Card records that used it are kept, without a wallet.") % {"name": w.name},
                     label=w.name, back_url=reverse("card_mfs_detail", args=[w.pk]))
    return redirect("card_mfs")


# ── Your lists: banks and card types ────────────────────────────────────────

@login_required
def lists_view(request):
    """Add, rename, hide or delete the banks and card types offered when adding a card."""
    sv.ensure_networks(request.user)
    if request.method == "POST":
        model = sv.LISTS.get(request.POST.get("list"))
        if model is None:
            return redirect("card_lists")
        mine = model.objects.filter(user=request.user)
        action, name = request.POST.get("action"), (request.POST.get("name") or "").strip()[:80]
        obj = mine.filter(pk=request.POST.get("pk")).first() if request.POST.get("pk", "").isdigit() else None
        if action == "add" and name:
            if mine.filter(name__iexact=name).exists():
                messages.info(request, _("“%(name)s” is already in the list.") % {"name": name})
            else:
                model.objects.create(user=request.user, name=name)
                messages.success(request, _("Added %(name)s.") % {"name": name})
        elif action == "rename" and obj and name:
            if mine.filter(name__iexact=name).exclude(pk=obj.pk).exists():
                messages.error(request, _("“%(name)s” is already in the list.") % {"name": name})
            else:
                obj.name = name
                obj.save(update_fields=["name"])
                messages.success(request, _("Renamed to %(name)s. Every card using it shows the new name.") % {"name": name})
        elif action == "toggle" and obj:
            obj.is_active = not obj.is_active
            obj.save(update_fields=["is_active"])
            messages.success(request, (_("%(name)s is offered again.") if obj.is_active else _("%(name)s is hidden from the list. Cards using it keep it.")) % {"name": obj.name})
        elif action == "delete" and obj:
            if obj.cards.exists():
                messages.error(request, _("%(name)s is used by a card — hide it instead, or change that card first.") % {"name": obj.name})
            else:
                obj.delete()
                messages.success(request, _("Deleted %(name)s.") % {"name": obj.name})
        return redirect(request.POST.get("next") or "card_lists")
    from django.db.models import Count

    return render(request, "cards/lists.html", {
        "lists": [
            ("bank", _("Banks"), _("e.g. UCB, EBL, DBBL, City Bank"), sv.CardBank.objects.filter(user=request.user).annotate(n=Count("cards")).prefetch_related("cards")),
            ("network", _("Card types"), _("e.g. Visa, Mastercard, Amex"), sv.CardNetwork.objects.filter(user=request.user).annotate(n=Count("cards")).prefetch_related("cards")),
        ],
    })
