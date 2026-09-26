import json
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import quote

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.business.core.access import can
from apps.business.core.decorators import business_access_required
from apps.business.core.templatetags.business import bdt
from apps.business.parties.models import Party

from . import services
from .forms import FollowUpForm, PaymentForm
from .models import Direction, PartyPayment

ZERO = Decimal(0)


# ── Due list ────────────────────────────────────────────────────────────────

@business_access_required(capability="view_finance")
def due_list_view(request):
    b = request.business
    today = date.today()
    t = services.totals(b)
    side = request.GET.get("side") or ("pay" if not t["receivable_count"] and t["payable_count"] else "receive")
    rows = [led for led in t["ledgers"] if (led.balance > 0) == (side == "receive")]
    q = request.GET.get("q", "").strip().lower()
    if q:
        rows = [led for led in rows if q in led.party.name.lower() or q in (led.party.phone or "")]
    sort = request.GET.get("sort", "amount")
    if sort == "oldest":
        rows.sort(key=lambda led: led.oldest or today)
    elif sort == "name":
        rows.sort(key=lambda led: led.party.name.lower())
    else:
        rows.sort(key=lambda led: -led.amount)
    buckets = [sum((led.buckets[i] for led in rows), ZERO) for i in range(4)]
    total = sum((led.amount for led in rows), ZERO)
    for led in rows:
        led.wa = _whatsapp_link(b, led)
    follow = [led for led in t["ledgers"] if led.party.follow_up_on and led.party.follow_up_on <= today]
    follow.sort(key=lambda led: led.party.follow_up_on)
    return render(request, "business/credit/due_list.html", {
        "t": t, "side": side, "rows": rows, "q": request.GET.get("q", ""), "sort": sort, "total": total,
        "ageing": [(label, amount, round(amount * 100 / total) if total else 0) for label, amount in zip(services.bucket_labels(), buckets)],
        "follow_ups": follow,
    })


def _whatsapp_link(business, led):
    number = services.whatsapp_number(led.party.phone)
    if not number or not led.owes_me:
        return ""
    text = _("Assalamu alaikum %(name)s. As per %(farm)s's records, %(amount)s is due from you. Please pay when you can. Thank you.") % {
        "name": led.party.name, "farm": business.name, "amount": bdt(led.amount)}
    return f"https://wa.me/{number}?text={quote(text)}"


# ── Party statement ─────────────────────────────────────────────────────────

def _periods(today):
    first = today.replace(day=1)
    last_end = first - timedelta(days=1)
    return [
        ("all", _("All"), None, None),
        ("month", _("This month"), first, today),
        ("last", _("Last month"), last_end.replace(day=1), last_end),
        ("3m", _("Last 3 months"), today - timedelta(days=90), today),
        ("year", _("This year"), today.replace(month=1, day=1), today),
    ]


def _parse(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


@business_access_required(capability="view_finance")
def statement_view(request, pk):
    b = request.business
    party = get_object_or_404(Party, pk=pk, business=b)
    led = services.ledger(party)
    today = date.today()
    periods = _periods(today)
    period = request.GET.get("period", "all")
    start, end = _parse(request.GET.get("from")), _parse(request.GET.get("to"))
    if start or end:
        period = "custom"
    else:
        _k, _l, start, end = next((p for p in periods if p[0] == period), periods[0])
    rows = led.entries
    brought = None
    if start:
        before = [e for e in rows if e.date < start]
        brought = before[-1].balance if before else ZERO
        rows = [e for e in rows if e.date >= start]
    if end:
        rows = [e for e in rows if e.date <= end]
    shown_gave = sum((e.gave for e in rows), ZERO)
    shown_got = sum((e.got for e in rows), ZERO)
    closing = rows[-1].balance if rows else (brought or ZERO)
    return render(request, "business/credit/statement.html", {
        "party": party, "led": led, "rows": list(reversed(rows)) if request.GET.get("order") == "new" else rows,
        "brought": brought, "closing": closing, "shown_gave": shown_gave, "shown_got": shown_got,
        "periods": periods, "period": period, "start": start, "end": end, "newest_first": request.GET.get("order") == "new",
        "wa": _whatsapp_link(b, led), "follow_form": FollowUpForm(instance=party),
        "open_items": led.open_items, "today": today,
        "follow_quick": [(1, _("Tomorrow")), (3, _("In 3 days")), (7, _("In a week")), (15, _("In 15 days"))],
    })


@business_access_required(capability="enter_data")
@require_POST
def follow_up_view(request, pk):
    party = get_object_or_404(Party, pk=pk, business=request.business)
    if request.POST.get("clear"):
        party.follow_up_on, party.follow_up_note = None, ""
        party.save(update_fields=["follow_up_on", "follow_up_note", "updated_at", "updated_by"])
        messages.success(request, _("Follow-up cleared."))
    else:
        form = FollowUpForm(request.POST, instance=party)
        if form.is_valid():
            form.save()
            if party.follow_up_on:
                messages.success(request, _("You'll be reminded on %(date)s.") % {"date": f"{party.follow_up_on:%d %b %Y}"})
        else:
            messages.error(request, _("Please check the date."))
    return redirect("business:party_statement", party.pk)


# ── Payments ────────────────────────────────────────────────────────────────

def _payment_data(business, form, payment=None):
    """Per party: balance and the bills still open, for the payment page; and
    the party dropdown grouped by who owes whom, amounts in the labels."""
    ledgers = services.build(business)
    data = {}
    for pk, led in ledgers.items():
        bills = [{"key": f"{e.kind}:{e.pk}", "title": e.title, "detail": e.detail, "date": e.date.strftime("%d %b %Y"),
                  "open": str(e.open), "days": (date.today() - e.date).days}
                 for e in led.open_items if e.kind in ("sale", "feed", "stocking")]
        balance = led.balance
        if payment is not None and payment.pk and payment.party_id == pk:
            # Editing: show the balance as it would be without this payment.
            balance += payment.settled if payment.direction == Direction.IN else -payment.settled
        data[pk] = {"balance": str(balance), "bills": bills}
    owe_me, i_owe, rest = [], [], []
    for p in form.fields["party"].queryset:
        bal = ledgers[p.pk].balance if p.pk in ledgers else ZERO
        if bal > 0:
            owe_me.append((-bal, p.name.lower(), (p.pk, _("%(name)s — owes you %(amount)s") % {"name": p.name, "amount": bdt(bal)})))
        elif bal < 0:
            i_owe.append((bal, p.name.lower(), (p.pk, _("%(name)s — you owe %(amount)s") % {"name": p.name, "amount": bdt(-bal)})))
        else:
            rest.append((0, p.name.lower(), (p.pk, p.name)))
    groups = [("", form.fields["party"].empty_label)]
    for label, items in ((_("They owe you"), owe_me), (_("You owe them"), i_owe), (_("Settled"), rest)):
        if items:
            groups.append((label, [choice for *_sort, choice in sorted(items)]))
    form.fields["party"].widget.choices = groups
    return json.dumps(data)


@business_access_required(capability="enter_data")
def payment_form_view(request, pk=None):
    b = request.business
    payment = get_object_or_404(PartyPayment, pk=pk, business=b) if pk else None
    initial = {}
    if not payment:
        if request.GET.get("party", "").isdigit():
            initial["party"] = int(request.GET["party"])
        if request.GET.get("dir") in Direction.values:
            initial["direction"] = request.GET["dir"]
        if request.GET.get("against"):
            initial["against"] = request.GET["against"]
    form = PaymentForm(request.POST or None, instance=payment, business=b, initial=initial or None)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.business = b
        obj.save()
        led = services.ledger(obj.party)
        if obj.direction == Direction.IN:
            msg = _("Received %(amount)s from %(name)s.") % {"amount": bdt(obj.amount), "name": obj.party}
        else:
            msg = _("Paid %(amount)s to %(name)s.") % {"amount": bdt(obj.amount), "name": obj.party}
        if led.balance > 0:
            msg += " " + _("They still owe %(amount)s.") % {"amount": bdt(led.balance)}
        elif led.balance < 0:
            msg += " " + _("You still owe %(amount)s.") % {"amount": bdt(-led.balance)}
        else:
            msg += " " + _("All settled.")
            if obj.party.follow_up_on:  # nothing left to chase
                obj.party.follow_up_on, obj.party.follow_up_note = None, ""
                obj.party.save(update_fields=["follow_up_on", "follow_up_note", "updated_at", "updated_by"])
        messages.success(request, msg)
        nxt = request.GET.get("next")
        if nxt and url_has_allowed_host_and_scheme(nxt, {request.get_host()}):
            return redirect(nxt)
        if can(request.membership, "view_finance"):
            return redirect("business:party_statement", obj.party_id)
        return redirect("business:payment_add")
    return render(request, "business/credit/payment_form.html", {
        "form": form, "obj": payment, "pay_json": _payment_data(b, form, payment),
        "back": reverse("business:party_statement", args=[payment.party_id]) if payment else request.GET.get("next") or reverse("business:dues"),
    })


@business_access_required(capability="delete")
@require_POST
def payment_delete_view(request, pk):
    payment = get_object_or_404(PartyPayment, pk=pk, business=request.business)
    payment.soft_delete()
    messages.success(request, _("Payment deleted. You can restore it from the payments list."))
    return redirect("business:party_statement", payment.party_id)


@business_access_required(capability="delete")
@require_POST
def payment_restore_view(request, pk):
    payment = get_object_or_404(PartyPayment.all_objects, pk=pk, business=request.business, is_deleted=True)
    payment.restore()
    messages.success(request, _("Payment restored."))
    return redirect("business:party_statement", payment.party_id)


@business_access_required(capability="view_finance")
def payment_list_view(request):
    b = request.business
    today = date.today()
    periods = [p for p in _periods(today) if p[0] != "3m"]
    periods = periods[1:] + periods[:1]  # This month first
    period = request.GET.get("period", "month")
    show = request.GET.get("show", "")
    key, label, start, end = next((p for p in periods if p[0] == period), periods[0])
    deleted = show == "deleted"
    qs = (PartyPayment.all_objects.filter(business=b, is_deleted=deleted) if deleted else PartyPayment.objects.filter(business=b))
    qs = qs.select_related("party", "account", "sale", "feed_purchase", "stocking")
    if start and not deleted:
        qs = qs.filter(date__gte=start, date__lte=end)
    if show in Direction.values:
        qs = qs.filter(direction=show)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(party__name__icontains=q) | Q(reference__icontains=q) | Q(notes__icontains=q))
    sums = qs.order_by().values("direction").annotate(total=Sum("amount"), n=Count("id"))
    by_dir = {r["direction"]: r for r in sums}
    return render(request, "business/credit/payment_list.html", {
        "page_obj": Paginator(qs, 40).get_page(request.GET.get("page")), "periods": periods, "period": key, "period_label": label,
        "show": show, "q": q, "received": by_dir.get("in", {}).get("total") or 0, "paid": by_dir.get("out", {}).get("total") or 0,
        "deleted_count": PartyPayment.all_objects.filter(business=b, is_deleted=True).count(),
    })
