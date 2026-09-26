"""The baki ledger, built from the records that already hold the money.

For each party it lines up, by date:

  opening balance         they owe me → "gave",   I owe them → "got"
  fish sale (buyer)       gave fish worth `net`,  got `received_now`
  feed purchase           got feed worth `total`, gave `paid_now`
  stocking (supplier)     got fingerlings `cost`, gave `paid_now`
  payment in              got money (+ discount)
  payment out             gave money (+ discount)

Balance = everything given − everything got: positive means they owe me.
"Gave / got" (দিলাম / পেলাম) is how a paper khata reads, so the statement
uses the same two columns.

Which bills are still open is worked out from that: a bill's own part-payment
and any payment linked to it settle it first, then everything else settles the
oldest bills first. The open bills give the ageing (0–30 … 90+ days) and each
sale's or purchase's remaining due.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db.models import F
from django.urls import reverse
from django.utils.translation import gettext as _

from apps.business.feed.models import FeedPurchase
from apps.business.parties.models import OpeningType, Party
from apps.business.ponds.models import Stocking
from apps.business.sales.models import FishSale

from .models import Direction, PartyPayment

ZERO = Decimal(0)
BUCKETS = (30, 60, 90)  # 0–30, 31–60, 61–90, 90+ days


@dataclass
class Entry:
    date: date
    kind: str            # opening | sale | feed | stocking | pay_in | pay_out
    key: tuple           # ("sale", 12): what payments link to
    title: str
    detail: str = ""
    gave: Decimal = ZERO
    got: Decimal = ZERO
    url: str = ""
    rank: int = 1        # same day: opening, then bills, then payments
    target: tuple | None = None  # the bill a payment is for
    pk: int = 0
    balance: Decimal = ZERO      # running, after this entry
    open: Decimal = ZERO         # part of this bill still unpaid

    @property
    def is_payment(self):
        return self.kind in ("pay_in", "pay_out")


@dataclass
class Ledger:
    party: Party
    entries: list = field(default_factory=list)
    balance: Decimal = ZERO
    buckets: list = field(default_factory=lambda: [ZERO] * (len(BUCKETS) + 1))
    oldest: date | None = None
    last_payment: date | None = None

    @property
    def owes_me(self):
        return self.balance > 0

    @property
    def amount(self):
        return abs(self.balance)

    @property
    def oldest_days(self):
        return (date.today() - self.oldest).days if self.oldest else None

    @property
    def open_items(self):
        return [e for e in self.entries if e.open > 0]

    @property
    def bucket_rows(self):
        """[(label, amount, percent of the balance)] for the ageing bar."""
        labels, total = bucket_labels(), self.amount
        return [(labels[i], a, round(a * 100 / total) if total else 0) for i, a in enumerate(self.buckets)]

    def due_on(self, key):
        """What is still unpaid on one bill, e.g. ("sale", 12). A receivable
        only counts while they owe me; a payable while I owe them."""
        if (key[0] == "sale") != (self.balance > 0):
            return ZERO
        for e in self.entries:
            if e.key == key:
                return e.open
        return ZERO


def bucket_labels():
    return [_("0–30 days"), _("31–60 days"), _("61–90 days"), _("Over 90 days")]


def _entries(business, party_ids=None):
    """All ledger entries for the business, grouped by party id."""
    out = defaultdict(list)
    parties = Party.objects.filter(business=business)
    if party_ids is not None:
        parties = parties.filter(pk__in=party_ids)
    ids = party_ids
    for p in parties:
        if p.opening_balance:
            on = p.opening_date or p.created_at.date()
            receivable = p.opening_type == OpeningType.RECEIVABLE
            out[p.pk].append(Entry(on, "opening", ("opening", p.pk), _("Balance before using this app"), rank=0,
                                   gave=p.opening_balance if receivable else ZERO, got=ZERO if receivable else p.opening_balance))

    def scope(qs, fk):
        return qs.filter(**{f"{fk}__in": ids}) if ids is not None else qs.filter(**{f"{fk}__isnull": False})

    for s in scope(FishSale.objects.filter(business=business), "buyer").select_related("market").prefetch_related("lines__species", "lines__unit"):
        fish = ", ".join(f"{line.species} {line.quantity.normalize():f} {line.unit.symbol}" for line in s.lines.all())
        detail = " · ".join(x for x in (f"#{s.memo_no}" if s.memo_no else "", str(s.market) if s.market else "", fish) if x)
        out[s.buyer_id].append(Entry(s.date, "sale", ("sale", s.pk), _("Fish sold"), detail, gave=s.net, got=s.received_now,
                                     url=reverse("business:sale_detail", args=[s.pk]), pk=s.pk))
    for f in scope(FeedPurchase.objects.filter(business=business), "supplier").prefetch_related("lines__product"):
        feeds = ", ".join(dict.fromkeys(line.product.name for line in f.lines.all()))
        detail = " · ".join(x for x in (f"#{f.invoice_no}" if f.invoice_no else "", feeds) if x)
        out[f.supplier_id].append(Entry(f.date, "feed", ("feed", f.pk), _("Feed bought"), detail, gave=f.paid_now, got=f.total,
                                        url=reverse("business:feed_purchases_edit", args=[f.pk]), pk=f.pk))
    stockings = scope(Stocking.objects.filter(business=business, cycle__is_deleted=False), "supplier").select_related("species", "cycle__pond")
    for st in stockings:
        detail = " · ".join(x for x in (str(st.cycle.pond), f"{st.count:,}" if st.count else "") if x)
        out[st.supplier_id].append(Entry(st.date, "stocking", ("stocking", st.pk), _("Fingerlings: %(fish)s") % {"fish": st.species}, detail,
                                         gave=st.paid_now, got=st.cost, url=reverse("business:cycle_detail", args=[st.cycle_id]) + "?tab=stocking", pk=st.pk))
    for pay in scope(PartyPayment.objects.filter(business=business), "party").select_related("account", "sale", "feed_purchase", "stocking"):
        is_in = pay.direction == Direction.IN
        target = (("sale", pay.sale_id) if pay.sale_id else ("feed", pay.feed_purchase_id) if pay.feed_purchase_id
                  else ("stocking", pay.stocking_id) if pay.stocking_id else None)
        bits = [str(pay.account) if pay.account else "", f"#{pay.reference}" if pay.reference else ""]
        if pay.discount:
            bits.append(_("incl. %(amount)s discount") % {"amount": _money(pay.discount)})
        if pay.bill:
            bits.append(_("for %(bill)s") % {"bill": _bill_label(pay.bill)})
        out[pay.party_id].append(Entry(pay.date, "pay_in" if is_in else "pay_out", ("pay", pay.pk),
                                       _("Payment received") if is_in else _("Payment made"), " · ".join(b for b in bits if b),
                                       gave=ZERO if is_in else pay.settled, got=pay.settled if is_in else ZERO,
                                       url=reverse("business:payment_edit", args=[pay.pk]), rank=2, target=target, pk=pay.pk))
    return out


def _money(v):
    from apps.business.core.templatetags.business import bdt

    return bdt(v)


def _bill_label(bill):
    if isinstance(bill, FishSale):
        return _("sale of %(date)s") % {"date": f"{bill.date:%d %b}"}
    if isinstance(bill, FeedPurchase):
        return _("feed of %(date)s") % {"date": f"{bill.date:%d %b}"}
    return _("fingerlings of %(date)s") % {"date": f"{bill.date:%d %b}"}


def _settle(entries, balance):
    """Work out what is still open on each bill (see the module docstring)."""
    receivable = balance > 0
    bill_of = (lambda e: e.gave) if receivable else (lambda e: e.got)
    credit_of = (lambda e: e.got) if receivable else (lambda e: e.gave)
    by_key = {}
    for e in entries:
        e.open = bill_of(e)
        by_key[e.key] = e
    pool = ZERO
    for e in entries:
        credit = credit_of(e)
        if not credit:
            continue
        target = by_key.get(e.target or e.key)
        if target is not None and target.open > 0:
            take = min(credit, target.open)
            target.open -= take
            credit -= take
        pool += credit
    for e in entries:  # oldest first
        if pool <= 0:
            break
        take = min(pool, e.open)
        e.open -= take
        pool -= take


def build(business, party_ids=None, today=None):
    """{party id: Ledger} for every party with any entries (or just `party_ids`)."""
    today = today or date.today()
    grouped = _entries(business, party_ids)
    parties = Party.objects.filter(business=business, pk__in=list(grouped) if party_ids is None else party_ids)
    ledgers = {}
    for p in parties:
        entries = sorted(grouped.get(p.pk, []), key=lambda e: (e.date, e.rank, e.pk))
        running = ZERO
        for e in entries:
            running += e.gave - e.got
            e.balance = running
        led = Ledger(party=p, entries=entries, balance=running)
        if running:
            _settle(entries, running)
            for e in led.open_items:
                age = (today - e.date).days
                slot = next((i for i, limit in enumerate(BUCKETS) if age <= limit), len(BUCKETS))
                led.buckets[slot] += e.open
                led.oldest = min(led.oldest or e.date, e.date)
        else:
            for e in entries:
                e.open = ZERO
        pays = [e.date for e in entries if e.is_payment]
        led.last_payment = max(pays) if pays else None
        ledgers[p.pk] = led
    return ledgers


def ledger(party, today=None):
    return build(party.business, [party.pk], today).get(party.pk) or Ledger(party=party)


def balances(business):
    """{party id: balance} without building every statement row."""
    return {pk: led.balance for pk, led in build(business).items()}


def open_dues(business, kind):
    """{pk: still unpaid} for one kind of bill ("sale", "feed", "stocking")
    across the business, e.g. to show each sale's remaining due in a list."""
    out = {}
    for led in build(business).values():
        if (kind == "sale") != (led.balance > 0):  # a sale is only due while they owe me, a purchase while I owe them
            continue
        for e in led.entries:
            if e.kind == kind and e.open > 0:
                out[e.pk] = e.open
    return out


def unlinked_sale_dues(business):
    """Sales with money still due but no buyer to chase (older records)."""
    return {s.pk: s.net - s.received_now for s in FishSale.objects.filter(business=business, buyer__isnull=True, net__gt=F("received_now"))}


def totals(business):
    """Home page / due list headline: to collect and to pay."""
    ledgers = [led for led in build(business).values() if led.balance]
    recv = [led for led in ledgers if led.balance > 0]
    pay = [led for led in ledgers if led.balance < 0]
    return {
        "receivable": sum((led.balance for led in recv), ZERO), "receivable_count": len(recv),
        "payable": -sum((led.balance for led in pay), ZERO), "payable_count": len(pay),
        "ledgers": ledgers,
    }


def whatsapp_number(phone):
    """Bangladesh numbers as wa.me wants them: 01712… → 8801712…"""
    digits = "".join(ch for ch in phone or "" if ch.isdigit())
    if digits.startswith("880"):
        return digits
    if digits.startswith("0") and len(digits) == 11:
        return "88" + digits
    return digits if len(digits) >= 10 else ""
