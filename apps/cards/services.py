"""Everything about a card worked out from what was recorded: what you owe,
each bill (statement) with its due date, minimum and whether it was paid in
full, the EMIs, every fee, and the cheapest way to pay.

How a bill is made (the usual way banks in Bangladesh do it):

    Everything from the day after the last bill day up to this bill day lands
    on this bill. You pay by the pay-by day: in the same month when it comes
    after the bill day (bill on the 5th, pay by the 25th), otherwise in the
    next month (bill on the 20th, pay by the 10th).

    The bill = what was left from the bill before + everything new − payments,
    refunds and anything turned into EMI. Paid in full by the due date: no
    interest. Less than that: interest, and below the minimum a late fee too —
    the app warns, and you record what the bank actually charged.

    An EMI takes its amount off the bill it was made on; then one installment
    (its share of the amount + that month's interest) lands on each bill after.
    What you owe on the card in total doesn't change by turning it into EMI,
    only when you have to pay it.
"""
import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import F, Sum
from django.urls import reverse
from django.utils.translation import gettext as _

from apps.core.templatetags.ui import money

from .models import DEFAULT_NETWORKS, Card, CardBank, CardEntry, CardNetwork, ChargeType, EmiPlan, EntryKind, MfsFees, PayRoute

ZERO = Decimal(0)
CENT = Decimal("0.01")
SOON_DAYS = 7


def q(x):
    return Decimal(x).quantize(CENT, rounding=ROUND_HALF_UP)


# ── Bill days ────────────────────────────────────────────────────────────────

def _day(y, m, d):
    return date(y, m, min(d, calendar.monthrange(y, m)[1]))


def _step(y, m, n=1):
    i = y * 12 + (m - 1) + n
    return i // 12, i % 12 + 1


def bill_on(card, y, m):
    """The bill day in a month (the 31st is the last day in a short month)."""
    return _day(y, m, card.statement_day)


def bill_for(card, d):
    """The bill that something done on day d lands on."""
    s = bill_on(card, d.year, d.month)
    return s if d <= s else bill_on(card, *_step(d.year, d.month))


def bill_after(card, s):
    return bill_on(card, *_step(s.year, s.month))


def last_bill(card, d):
    """The last bill made on or before day d."""
    s = bill_on(card, d.year, d.month)
    return s if s <= d else bill_on(card, *_step(d.year, d.month, -1))


def due_for(card, s):
    """The pay-by date of the bill made on day s."""
    if card.due_day > card.statement_day:
        return _day(s.year, s.month, card.due_day)
    return _day(*_step(s.year, s.month), card.due_day)


# ── EMI ──────────────────────────────────────────────────────────────────────

@dataclass
class Installment:
    n: int
    date: date
    principal: Decimal
    interest: Decimal

    @property
    def total(self):
        return self.principal + self.interest


def emi_amount(amount, months, rate):
    """Each month's installment: equal payments, interest on what's left (the bank's usual way)."""
    amount, rate = Decimal(amount), Decimal(rate or 0)
    if months <= 0:
        return amount
    i = rate / Decimal(1200)
    if not i:
        return q(amount / months)
    return q(amount * i / (1 - (1 + i) ** -months))


def schedule(plan, card=None):
    card = card or plan.card
    each = emi_amount(plan.amount, plan.months, plan.rate)
    i = Decimal(plan.rate or 0) / Decimal(1200)
    left, rows = Decimal(plan.amount), []
    s = bill_for(card, plan.start)
    if s == plan.start:                       # turned into EMI on the bill day: the first installment is on the next bill
        s = bill_after(card, s)
    for n in range(1, plan.months + 1):
        interest = q(left * i)
        principal = left if n == plan.months else min(left, each - interest)
        rows.append(Installment(n, s, principal, interest))
        left -= principal
        s = bill_after(card, s)
    return rows


@dataclass
class EmiState:
    plan: EmiPlan
    rows: list
    each: Decimal
    billed: list
    left: Decimal              # of the amount, not yet on a bill
    next: Installment = None
    closed: bool = False

    @property
    def done(self):
        return self.closed or self.left <= 0

    @property
    def count(self):
        return len(self.billed)

    @property
    def pct(self):
        return int(self.count * 100 / self.plan.months) if self.plan.months else 100

    @property
    def interest_total(self):
        return sum((r.interest for r in self.rows), ZERO)

    @property
    def months_left(self):
        return 0 if self.done else self.plan.months - self.count


def emi_state(plan, today, card=None):
    rows = schedule(plan, card)
    end = min(today, plan.closed_on) if plan.closed_on else today
    billed = [r for r in rows if r.date <= end]
    closed = bool(plan.closed_on and plan.closed_on <= today)
    left = ZERO if closed else plan.amount - sum((r.principal for r in billed), ZERO)
    nxt = None if closed else next((r for r in rows if r.date > end), None)
    return EmiState(plan, rows, emi_amount(plan.amount, plan.months, plan.rate), billed, left, nxt, closed)


# ── What happened on a card, in order ────────────────────────────────────────

@dataclass
class Event:
    date: date
    owed: Decimal              # change in what you owe on the card
    billable: Decimal          # change in what goes on the bills
    kind: str
    title: str
    detail: str = ""
    entry: CardEntry = None
    plan: EmiPlan = None
    order: int = 0
    balance: Decimal = ZERO    # what you owe after it (filled in by ledger())


def events(card, entries=None, plans=None):
    entries = list(card.entries.select_related("wallet")) if entries is None else entries
    plans = list(card.emis.all()) if plans is None else plans
    out = []
    if card.opening_balance:
        out.append(Event(card.opening_date, card.opening_balance, card.opening_balance, "open", _("Already owed when you started"), order=0))
    for e in entries:
        detail = []
        if e.wallet_id:
            detail.append((_("to %(wallet)s") if e.kind == EntryKind.CASH else _("from %(wallet)s")) % {"wallet": e.wallet})
        if e.fee:
            detail.append(_("%(fee)s fee") % {"fee": money(e.fee)})
        if e.note:
            detail.append(e.note)
        out.append(Event(e.date, e.debt, e.debt, e.kind, e.title, " · ".join(detail), entry=e, order=2 if e.debt < 0 else 1))
    for p in plans:
        rows = schedule(p, card)
        if p.fee:
            out.append(Event(p.start, p.fee, p.fee, "emi_fee", _("EMI processing fee"), p.title, plan=p, order=1))
        out.append(Event(p.start, ZERO, -p.amount, "emi_move", _("Turned into EMI"), _("%(title)s · %(n)s months") % {"title": p.title, "n": p.months}, plan=p, order=2))
        for r in rows:
            if p.closed_on and r.date > p.closed_on:
                break
            out.append(Event(r.date, r.interest, r.total, "emi_inst", _("EMI installment %(n)s of %(of)s") % {"n": r.n, "of": p.months}, p.title, plan=p, order=1))
        if p.closed_on:
            done = [r for r in rows if r.date <= p.closed_on]
            rest = p.amount - sum((r.principal for r in done), ZERO)
            if rest > 0:
                out.append(Event(p.closed_on, ZERO, rest, "emi_close", _("EMI paid off early"), p.title, plan=p, order=1))
    out.sort(key=lambda e: (e.date, e.order, e.entry.pk if e.entry else 0))
    return out


def _upto(evs, d, attr="billable"):
    return sum((getattr(e, attr) for e in evs if e.date <= d), ZERO)


# ── Bills ────────────────────────────────────────────────────────────────────

PAID, OPEN, LATE, PARTIAL, MISSED, NONE = "paid", "open", "late", "partial", "missed", "none"


@dataclass
class Bill:
    date: date
    due: date
    opening: Decimal
    charges: Decimal
    payments: Decimal
    credits: Decimal
    closing: Decimal
    min_due: Decimal
    paid: Decimal             # paid towards it by the due date (or so far, while it's open)
    left: Decimal
    status: str
    events: list = field(default_factory=list)
    interest: Decimal = ZERO  # a month's interest if what's left stays unpaid (an estimate)
    days: int = 0             # days to the due date (− when past it)

    @property
    def overdue(self):
        return self.status in (PARTIAL, MISSED)

    @property
    def to_pay(self):
        return self.status in (OPEN, PARTIAL, MISSED) and self.left > 0


def _min_due(card, closing):
    if closing <= 0:
        return ZERO
    return min(closing, max(q(closing * card.min_due_rate / 100), card.min_due_floor))


def bills(card, evs, today):
    if not evs:
        return []
    s, last = bill_for(card, evs[0].date), last_bill(card, today)
    dates = []
    while s <= last:
        dates.append(s)
        s = bill_after(card, s)
    out, opening, prev = [], ZERO, date.min
    for i, s in enumerate(dates):
        cyc = [e for e in evs if prev < e.date <= s]
        charges = sum((e.billable for e in cyc if e.billable > 0), ZERO)
        payments = -sum((e.billable for e in cyc if e.billable < 0 and e.kind == EntryKind.PAY), ZERO)
        credits = -sum((e.billable for e in cyc if e.billable < 0 and e.kind != EntryKind.PAY), ZERO)
        closing = opening + charges - payments - credits
        due = due_for(card, s)
        until = min(dates[i + 1], today) if i + 1 < len(dates) else today
        # what brings the bill down after it's made: payments, and refunds or an EMI made before it's paid
        after = [e for e in evs if s < e.date <= until and e.billable < 0]
        by_due = -sum((e.billable for e in after if e.date <= due), ZERO)
        since = -sum((e.billable for e in after), ZERO)
        min_due = _min_due(card, closing)
        pay_by_due = -sum((e.billable for e in after if e.date <= due and e.kind == EntryKind.PAY), ZERO)
        pay_since = -sum((e.billable for e in after if e.kind == EntryKind.PAY), ZERO)
        if closing <= 0:
            status, left, paid = NONE, ZERO, ZERO
        elif today <= due:
            paid, left = pay_since, max(closing - since, ZERO)
            status = PAID if left == 0 else OPEN
        else:
            paid, left = pay_by_due, max(closing - by_due, ZERO)
            if left == 0:
                status = PAID
            elif since >= closing:
                status, left, paid = LATE, ZERO, pay_since
            else:
                status = PARTIAL if by_due >= min_due else MISSED
                left = max(closing - since, ZERO)      # paid some more after the due date: less is left now
        b = Bill(s, due, opening, charges, payments, credits, closing, min_due, paid, left, status, cyc, days=(due - today).days)
        if card.interest_rate and status in (OPEN, PARTIAL, MISSED) and left > 0:
            b.interest = q(left * card.interest_rate / 1200)
        out.append(b)
        opening, prev = closing, s
    return out


# ── One card, all worked out ─────────────────────────────────────────────────

@dataclass
class Costs:
    card_fee: Decimal = ZERO       # the card's fee for sending money to bKash/Nagad
    wallet_fee: Decimal = ZERO     # the wallet's fee for paying a bill
    interest: Decimal = ZERO
    late: Decimal = ZERO
    annual: Decimal = ZERO
    vat: Decimal = ZERO
    other: Decimal = ZERO
    emi_interest: Decimal = ZERO
    emi_fee: Decimal = ZERO

    @property
    def total(self):
        return sum((getattr(self, k) for k in self.__dataclass_fields__), ZERO)

    def add(self, other):
        for k in self.__dataclass_fields__:
            setattr(self, k, getattr(self, k) + getattr(other, k))
        return self

    def rows(self):
        labels = {
            "card_fee": _("Card fee for sending to mobile banking"),
            "wallet_fee": _("Mobile banking fee for paying bills"),
            "interest": _("Interest"), "late": _("Late fees"), "annual": _("Annual fees"), "vat": _("VAT / tax"),
            "other": _("Other charges"), "emi_interest": _("EMI interest"), "emi_fee": _("EMI processing fees"),
        }
        return [(labels[k], getattr(self, k)) for k in self.__dataclass_fields__ if getattr(self, k)]


def costs(evs, start=None, end=None):
    c = Costs()
    for e in evs:
        if (start and e.date < start) or (end and e.date > end):
            continue
        if e.entry is not None:
            x = e.entry
            if x.kind == EntryKind.CASH:
                c.card_fee += x.fee
            elif x.kind == EntryKind.PAY:
                c.wallet_fee += x.fee
            elif x.kind == EntryKind.CHARGE:
                key = x.charge_type if x.charge_type in ChargeType.values else "other"
                setattr(c, key, getattr(c, key) + x.amount)
        elif e.kind == "emi_inst":
            c.emi_interest += e.owed
        elif e.kind == "emi_fee":
            c.emi_fee += e.owed
    return c


@dataclass
class CardState:
    card: Card
    events: list
    bills: list
    owed: Decimal
    billable: Decimal
    emis: list
    next_bill: date
    next_due: date
    so_far: Decimal            # new on the card since the last bill
    projected: Decimal         # the next bill, if nothing else is paid or spent
    costs: Costs
    taken: Decimal = ZERO      # money taken out to wallets, all time
    spent: Decimal = ZERO
    paid: Decimal = ZERO

    @property
    def bill(self):
        return self.bills[-1] if self.bills else None

    @property
    def emi_left(self):
        return max(self.owed - self.billable, ZERO)

    @property
    def available(self):
        return None if self.card.limit is None else self.card.limit - max(self.owed, ZERO)

    @property
    def used_pct(self):
        if not self.card.limit:
            return None
        return max(0, min(100, int(max(self.owed, ZERO) * 100 / self.card.limit)))

    @property
    def to_pay(self):
        """The bill to pay now, if there is one."""
        b = self.bill
        return b if b and b.to_pay else None

    @property
    def next_new(self):
        """What's new on the next bill (not counting what's still unpaid from this one)."""
        b = self.to_pay
        return max(self.projected - (b.left if b else ZERO), ZERO)

    @property
    def tone(self):
        b = self.to_pay
        if b and b.overdue:
            return "critical"
        if b and b.days <= SOON_DAYS:
            return "warn"
        if self.used_pct is not None and self.used_pct >= 70:
            return "warn"
        return "good"


def card_state(card, today):
    entries = list(card.entries.select_related("wallet"))
    plans = list(card.emis.all())
    evs = events(card, entries, plans)
    past = [e for e in evs if e.date <= today]
    bl = bills(card, past, today)
    nb = bill_for(card, today)
    if nb == today and bl and bl[-1].date == today:
        nb = bill_after(card, nb)
    billable_now = _upto(evs, today)
    last = bl[-1].date if bl else date.min
    so_far = sum((e.billable for e in past if e.date > last and e.billable > 0), ZERO)
    coming = sum((e.billable for e in evs if today < e.date <= nb and e.kind in ("emi_inst", "emi_close")), ZERO)
    return CardState(
        card=card, events=evs, bills=bl, owed=_upto(evs, today, "owed"), billable=billable_now,
        emis=[emi_state(p, today, card) for p in plans], next_bill=nb, next_due=due_for(card, nb),
        so_far=so_far, projected=max(billable_now + coming, ZERO), costs=costs(past),
        taken=sum((x.amount for x in entries if x.kind == EntryKind.CASH and x.date <= today), ZERO),
        spent=sum((x.amount for x in entries if x.kind == EntryKind.SPEND and x.date <= today), ZERO),
        paid=sum((x.amount for x in entries if x.kind == EntryKind.PAY and x.date <= today), ZERO),
    )


def ledger(st, today):
    """The card's history, newest first, each with what you owed after it."""
    rows, running = [], ZERO
    for e in st.events:
        if e.date > today:
            break
        if e.kind == "emi_inst" and not e.owed:
            continue                                   # an interest-free installment: shown on its bill, not here
        running += e.owed
        e.balance = running
        rows.append(e)
    return list(reversed(rows))


def ensure_networks(user):
    """Visa, Mastercard… are there the first time someone adds a card; after that the list is theirs."""
    if not CardNetwork.objects.filter(user=user).exists():
        CardNetwork.objects.bulk_create([CardNetwork(user=user, name=n) for n in DEFAULT_NETWORKS])


LISTS = {"bank": CardBank, "network": CardNetwork}


# ── Every card ───────────────────────────────────────────────────────────────

def user_cards(user, include_stopped=True):
    qs = Card.objects.filter(user=user)
    return qs if include_stopped else qs.filter(is_active=True)


def states(user, today):
    out = [card_state(c, today) for c in user_cards(user)]
    return [s for s in out if s.card.is_active or s.owed or s.to_pay]


def total_owed(user, today):
    """What you owe on all your cards right now (for Home)."""
    return sum((max(s.owed, ZERO) for s in states(user, today)), ZERO)


def month_starts(n, today):
    y, m = today.year, today.month
    return [date(*_step(y, m, -k), 1) for k in range(n - 1, -1, -1)]


def series(all_states, today, n=12):
    months = month_starts(n, today)
    idx = {(d.year, d.month): i for i, d in enumerate(months)}
    taken, spent, paid, fees = ([0.0] * n for _ in range(4))
    for st in all_states:
        for e in st.events:
            i = idx.get((e.date.year, e.date.month))
            if i is None or e.date > today:
                continue
            x = e.entry
            if x is not None:
                if x.kind == EntryKind.CASH:
                    taken[i] += float(x.amount)
                    fees[i] += float(x.fee)
                elif x.kind == EntryKind.SPEND:
                    spent[i] += float(x.amount)
                elif x.kind == EntryKind.PAY:
                    paid[i] += float(x.amount)
                    fees[i] += float(x.fee)
                elif x.kind == EntryKind.CHARGE:
                    fees[i] += float(x.amount)
            elif e.kind in ("emi_inst", "emi_fee"):
                fees[i] += float(e.owed)
    return {"months": months, "taken": taken, "spent": spent, "paid": paid, "fees": fees}


def borrowing_cost(all_states, today):
    """The fee for sending card money to mobile banking, as a yearly rate: 1.5% for a ~35-day loan ≈ 15.6% a year."""
    since = today - timedelta(days=365)
    amount = fee = weighted = ZERO
    for st in all_states:
        for e in st.events:
            x = e.entry
            if x is None or x.kind != EntryKind.CASH or not (since <= x.date <= today):
                continue
            days = (due_for(st.card, bill_for(st.card, x.date)) - x.date).days
            amount += x.amount
            fee += x.fee
            weighted += x.amount * days
    if not amount:
        return None
    days = int(weighted / amount) or 1
    rate = fee * 100 / amount
    return {"amount": amount, "fee": fee, "rate": q(rate), "days": days, "yearly": q(rate * 365 / days)}


# ── Mobile banking ───────────────────────────────────────────────────────────

def fees_for(wallet):
    try:
        return wallet.card_fees
    except MfsFees.DoesNotExist:
        return MfsFees(wallet=wallet)


def mfs_wallets(user):
    """bKash, Nagad, Rocket… — every mobile-banking wallet, and any other wallet a card has used."""
    from django.db.models import Q

    from apps.wallets.models import Wallet, WalletKind

    used = set(CardEntry.objects.filter(card__user=user, wallet__isnull=False).values_list("wallet_id", flat=True))
    return list(Wallet.objects.filter(user=user).filter(Q(kind=WalletKind.MOBILE) | Q(pk__in=used))
                .select_related("card_fees").order_by("-is_active", "name"))


@dataclass
class MfsRow:
    wallet: object
    fees: MfsFees
    balance: Decimal = ZERO
    received: Decimal = ZERO      # from cards
    card_fee: Decimal = ZERO      # the cards' fees for sending it
    paid: Decimal = ZERO          # card bills paid from it
    pay_fee: Decimal = ZERO       # its fees for paying them
    times_in: int = 0
    times_out: int = 0
    by_card: dict = field(default_factory=dict)
    entries: list = field(default_factory=list)

    @property
    def fees_total(self):
        return self.card_fee + self.pay_fee


def mfs_rows(user, today, only=None):
    from apps.wallets.services import balances

    held = balances(user)
    wallets = mfs_wallets(user)
    if only is not None:
        wallets = [w for w in wallets if w.pk == only.pk] or [only]
    rows = {w.pk: MfsRow(w, fees_for(w), held.get(w.pk, w.opening_balance)) for w in wallets}
    qs = CardEntry.objects.filter(card__user=user, wallet_id__in=list(rows), date__lte=today).select_related("card")
    for x in qs:
        r = rows[x.wallet_id]
        r.entries.append(x)
        c = r.by_card.setdefault(x.card_id, {"card": x.card, "received": ZERO, "paid": ZERO, "fees": ZERO})
        if x.kind == EntryKind.CASH:
            r.received += x.amount
            r.card_fee += x.fee
            r.times_in += 1
            c["received"] += x.amount
            c["fees"] += x.fee
        elif x.kind == EntryKind.PAY:
            r.paid += x.amount
            r.pay_fee += x.fee
            r.times_out += 1
            c["paid"] += x.amount
            c["fees"] += x.fee
    return list(rows.values())


# ── Paying: which way costs least ────────────────────────────────────────────

@dataclass
class Route:
    wallet: object
    route: str
    rate: Decimal
    fee: Decimal
    balance: Decimal

    @property
    def enough(self):
        return self.balance >= 0

    @property
    def short(self):
        """How much more the wallet needs for this (balance here is what would be left after paying)."""
        return max(-self.balance, ZERO)

    @property
    def label(self):
        return dict(PayRoute.choices)[self.route]


def pay_routes(user, amount, limit=4):
    """Every way you could pay `amount`, cheapest first (ties: the wallet that has the money)."""
    from apps.wallets.models import Wallet, WalletKind
    from apps.wallets.services import balances

    held = balances(user)
    out = []
    for w in Wallet.objects.filter(user=user, is_active=True).select_related("card_fees"):
        bal = held.get(w.pk, w.opening_balance)
        if w.kind == WalletKind.MOBILE:
            f = fees_for(w)
            if f.pays_bills:
                fee = q(amount * f.bill_rate / 100)
                out.append(Route(w, PayRoute.MFS_BILL, f.bill_rate, fee, bal - amount - fee))
            fee = q(amount * f.bank_rate / 100)
            out.append(Route(w, PayRoute.MFS_BANK, f.bank_rate, fee, bal - amount - fee))
        else:
            out.append(Route(w, PayRoute.DIRECT, ZERO, ZERO, bal - amount))
    out.sort(key=lambda r: (not r.enough, r.fee, -r.balance))
    return out[:limit]


def last_rate(card, wallet_id, kind, route=""):
    """The fee rate used the last time this card and wallet did the same thing — a better guess than the default."""
    qs = CardEntry.objects.filter(card=card, wallet_id=wallet_id, kind=kind, fee_rate__isnull=False)
    if route:
        qs = qs.filter(route=route)
    return qs.order_by("-date", "-id").values_list("fee_rate", flat=True).first()


def rate_guide(card, user):
    """For the entry forms: the fee rate to suggest for each wallet (and way of paying)."""
    from apps.wallets.models import Wallet, WalletKind

    out = {}
    for w in Wallet.objects.filter(user=user).select_related("card_fees"):
        f = fees_for(w)
        mobile = w.kind == WalletKind.MOBILE
        cash = last_rate(card, w.pk, EntryKind.CASH) if card else None
        out[str(w.pk)] = {
            "mobile": mobile,
            "cash": float(card.transfer_fee_rate if cash is None and card else (cash or 0)),
            "mfs_bill": float(last_rate(card, w.pk, EntryKind.PAY, PayRoute.MFS_BILL) or f.bill_rate) if card else float(f.bill_rate),
            "mfs_bank": float(last_rate(card, w.pk, EntryKind.PAY, PayRoute.MFS_BANK) or f.bank_rate) if card else float(f.bank_rate),
            "direct": 0.0,
            "pays": bool(f.pays_bills) if mobile else False,
        }
    return out


# ── For the rest of the app: wallets, Home, Upcoming, the money report ─────

def wallet_moves(user, only=None):
    """(date, wallet id, amount ±, title, detail, url) for card money that went through a wallet."""
    qs = CardEntry.objects.filter(card__user=user, wallet__isnull=False, kind__in=[EntryKind.CASH, EntryKind.PAY]).select_related("card")
    if only is not None:
        qs = qs.filter(wallet_id=only)
    for x in qs:
        url = reverse("card_entry_edit", args=[x.pk])
        if x.kind == EntryKind.CASH:
            yield x.date, x.wallet_id, x.amount, _("From card %(card)s") % {"card": x.card}, x.note, url
        else:
            detail = " · ".join(t for t in (_("incl. %(fee)s fee") % {"fee": money(x.fee)} if x.fee else "", x.note) if t)
            yield x.date, x.wallet_id, -(x.amount + x.fee), _("Card bill: %(card)s") % {"card": x.card}, detail, url


def wallet_querysets(user):
    """(queryset, amount expression, sign) — summed by the database for wallet balances."""
    base = CardEntry.objects.filter(card__user=user)
    return [
        (base.filter(kind=EntryKind.CASH), "amount", 1),
        (base.filter(kind=EntryKind.PAY), F("amount") + F("fee"), -1),
    ]


def due_items(user, today):
    """Card bills to pay, for Home's "needs attention" and Upcoming money."""
    out = []
    for st in states(user, today):
        b = st.to_pay
        if b:
            out.append({"state": st, "bill": b})
    out.sort(key=lambda r: r["bill"].due)
    return out


def money_out_querysets(user):
    """What counts as money spent: things bought on a card, bank charges (amount) and every fee (fee)."""
    base = CardEntry.objects.filter(card__user=user)
    return base.filter(kind__in=[EntryKind.SPEND, EntryKind.CHARGE]), base.filter(fee__gt=0)


def totals_between(user, start, end):
    spend, fees = money_out_querysets(user)

    def s(qs, f):
        return qs.filter(date__gte=start, date__lte=end).aggregate(t=Sum(f))["t"] or ZERO

    return s(spend.filter(kind=EntryKind.SPEND), "amount"), s(spend.filter(kind=EntryKind.CHARGE), "amount") + s(fees, "fee")
