"""Where the money is, and where it went.

Money is recorded once, in whichever part of the app it belongs to: fish sales
hold what was received, feed purchases what was paid, the baki ledger its
payments, loans their instalments, and this app the everyday costs and income.

Nothing is copied into a second table. Instead, everything is read together
here, so an account balance and an income/expense report are always in step
with the documents they come from — even after one is edited or deleted.

    balance  = opening + money in − money out
    profit   = income (fish sales + other) − costs (feed, fingerlings,
               farm expenses, loan interest and charges)

Money moved between your own accounts, loan principal, and baki payments are
NOT income or spending: they only move money about, or settle what a sale or
purchase already counted.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.apps import apps
from django.db.models import Sum
from django.urls import reverse
from django.utils.translation import gettext as _

from .models import Account, Category, CategoryType, Scope, Transaction, Transfer

ZERO = Decimal(0)


def _installed(label):
    return apps.is_installed(f"apps.business.{label}")


# ── What moved through the accounts ─────────────────────────────────────────

@dataclass
class Movement:
    """One piece of money in or out of an account."""

    date: date
    account_id: int
    amount: Decimal          # + in, − out
    title: str
    detail: str = ""
    url: str = ""
    kind: str = "other"      # sale | feed | baki_in | baki_out | loan | expense | income | transfer | staff
    balance: Decimal = ZERO  # running, after this movement

    @property
    def is_in(self):
        return self.amount > 0


def movements(business, account=None):
    """Every movement of money, oldest first. `account` limits it to one."""
    rows = []
    only = account.pk if account is not None else None

    def add(when, account_id, amount, title, detail="", url="", kind="other"):
        if amount and account_id and (only is None or account_id == only):
            rows.append(Movement(when, account_id, amount, title, detail, url, kind))

    if _installed("sales"):
        from apps.business.sales.models import FishSale

        for s in FishSale.objects.filter(business=business, received_now__gt=0).select_related("buyer", "market"):
            who = s.buyer or s.market
            add(s.date, s.account_id, s.received_now, _("Fish sold"), str(who) if who else "",
                reverse("business:sale_detail", args=[s.pk]), "sale")
    if _installed("feed"):
        from apps.business.feed.models import FeedPurchase

        for p in FeedPurchase.objects.filter(business=business, paid_now__gt=0).select_related("supplier"):
            add(p.date, p.account_id, -p.paid_now, _("Feed bought"), str(p.supplier),
                reverse("business:feed_purchases_edit", args=[p.pk]), "feed")
    if _installed("credit"):
        from apps.business.credit.models import Direction, PartyPayment

        for pay in PartyPayment.objects.filter(business=business, amount__gt=0).select_related("party"):
            is_in = pay.direction == Direction.IN
            add(pay.date, pay.account_id, pay.amount if is_in else -pay.amount,
                _("Baki received") if is_in else _("Baki paid"), str(pay.party),
                reverse("business:party_statement", args=[pay.party_id]), "baki_in" if is_in else "baki_out")
    if _installed("loans"):
        from apps.business.loans.models import Loan, LoanTransaction, LoanTxnKind

        for loan in Loan.objects.filter(business=business, account__isnull=False).select_related("lender"):
            add(loan.taken_on, loan.account_id, loan.principal, _("Loan received"), str(loan.lender),
                reverse("business:loan_detail", args=[loan.pk]), "loan")
        for t in LoanTransaction.objects.filter(business=business).select_related("loan__lender"):
            taken = t.kind == LoanTxnKind.TOP_UP
            amount = t.principal if taken else -t.total
            add(t.date, t.account_id, amount, _("Loan money taken") if taken else _("Loan instalment"),
                str(t.loan.lender), reverse("business:loan_detail", args=[t.loan_id]), "loan")
    if _installed("assets"):
        from apps.business.assets.models import Equipment, Service

        for e in Equipment.objects.filter(business=business, cost__gt=0, account__isnull=False, bought_on__isnull=False):
            add(e.bought_on, e.account_id, -e.cost, _("Equipment bought"), str(e), reverse("business:equipment_detail", args=[e.pk]), "expense")
        for sv in Service.objects.filter(business=business, cost__gt=0, account__isnull=False).select_related("equipment"):
            add(sv.date, sv.account_id, -sv.cost, sv.get_kind_display(), str(sv.equipment), reverse("business:equipment_detail", args=[sv.equipment_id]), "expense")
    if _installed("ponds"):
        from apps.business.ponds.models import LeasePayment

        for lp in LeasePayment.objects.filter(business=business).select_related("pond"):
            add(lp.date, lp.account_id, -lp.amount, _("Pond lease"), str(lp.pond),
                reverse("business:pond_detail", args=[lp.pond_id]), "expense")
    if _installed("partners"):
        from apps.business.partners.models import PartnerEntry

        for pe in PartnerEntry.objects.filter(business=business).select_related("partner"):
            add(pe.date, pe.account_id, pe.amount if pe.is_in else -pe.amount,
                _("Partner put money in") if pe.is_in else _("Partner took money out"), str(pe.partner),
                reverse("business:partner_detail", args=[pe.partner_id]), "partner")
    if _installed("supplies"):
        from apps.business.supplies.models import SupplyPurchase

        for sp in SupplyPurchase.objects.filter(business=business, paid_now__gt=0, account__isnull=False).select_related("item", "supplier"):
            add(sp.date, sp.account_id, -sp.paid_now, _("Pond supplies bought"), " · ".join(str(x) for x in (sp.item, sp.supplier) if x),
                reverse("business:supply_detail", args=[sp.item_id]), "expense")
    if _installed("staff"):
        from apps.business.staff.models import WorkerPayment

        for p in WorkerPayment.objects.filter(business=business).select_related("worker"):
            add(p.date, p.account_id, -p.amount, _("Advance to staff") if p.kind == "advance" else _("Staff pay"), str(p.worker),
                reverse("business:staff_worker", args=[p.worker_id]), "staff")
    if _installed("ponds"):
        from apps.business.ponds.models import Stocking, Treatment

        for st in Stocking.objects.filter(business=business, paid_now__gt=0, account__isnull=False, cycle__is_deleted=False).select_related("species", "cycle__pond"):
            add(st.date, st.account_id, -st.paid_now, _("Fingerlings bought"), f"{st.species} · {st.cycle.pond}",
                reverse("business:cycle_detail", args=[st.cycle_id]) + "?tab=stocking", "expense")

        for t in Treatment.objects.filter(business=business, cost__gt=0, account__isnull=False, cycle__is_deleted=False).select_related("cycle__pond"):
            add(t.date, t.account_id, -t.cost, _("Pond care"), f"{t.product} · {t.cycle.pond}",
                reverse("business:entry_edit", args=["treatment", t.pk]), "expense")
    for t in Transaction.objects.filter(business=business).select_related("category", "party"):
        add(t.date, t.account_id, t.signed, str(t.category), t.description or (str(t.party) if t.party else ""),
            reverse("business:transaction_edit", args=[t.pk]), "income" if t.is_income else "expense")
    for tr in Transfer.objects.filter(business=business).select_related("from_account", "to_account"):
        url = reverse("business:transfer_edit", args=[tr.pk])
        add(tr.date, tr.from_account_id, -(tr.amount + tr.charge), _("Sent to %(name)s") % {"name": tr.to_account},
            _("incl. %(amount)s charge") % {"amount": _money(tr.charge)} if tr.charge else "", url, "transfer")
        add(tr.date, tr.to_account_id, tr.amount, _("From %(name)s") % {"name": tr.from_account}, "", url, "transfer")

    # Oldest first. Within one day, money in before money out, so a day that
    # both received and spent reads the way a khata is written.
    rows.sort(key=lambda m: (m.date, m.amount < 0))
    return rows


def _money(value):
    from apps.business.core.templatetags.business import bdt

    return bdt(value)


def balances(business):
    """{account id: balance now}, opening balance included."""
    totals = {a.pk: a.opening_balance for a in Account.objects.filter(business=business)}
    for m in movements(business):
        if m.account_id in totals:
            totals[m.account_id] += m.amount
    return totals


def account_history(account, start=None, end=None):
    """(rows, opening, closing) for one account, newest first."""
    rows = movements(account.business, account)
    running = account.opening_balance
    for m in rows:
        running += m.amount
        m.balance = running
    closing = running
    opening = account.opening_balance
    if start:
        before = [m for m in rows if m.date < start]
        opening = before[-1].balance if before else account.opening_balance
        rows = [m for m in rows if m.date >= start]
    if end:
        rows = [m for m in rows if m.date <= end]
        closing = rows[-1].balance if rows else opening
    return list(reversed(rows)), opening, closing


# ── Income and expenses ─────────────────────────────────────────────────────

@dataclass
class Line:
    """One row of the income/expense statement."""

    key: str
    label: str
    amount: Decimal = ZERO
    url: str = ""
    children: list = field(default_factory=list)

    @property
    def has_children(self):
        return len(self.children) > 1 or (len(self.children) == 1 and self.children[0].amount != self.amount)


@dataclass
class Statement:
    start: date
    end: date
    income: list = field(default_factory=list)
    expense: list = field(default_factory=list)

    @property
    def total_income(self):
        return sum((l.amount for l in self.income), ZERO)

    @property
    def total_expense(self):
        return sum((l.amount for l in self.expense), ZERO)

    @property
    def profit(self):
        return self.total_income - self.total_expense

    @property
    def margin(self):
        return round(self.profit * 100 / self.total_income) if self.total_income else None


def statement(business, start, end, scope=Scope.BUSINESS, cycle=None, cache=None):
    """What came in and what went out between two dates.

    A page that asks for several periods at once (the dashboard asks for nine)
    can pass a dict as `cache`, so the feed prices and category names are
    looked up once instead of once per period.

    The farm's own income and costs come from the documents (sales, feed,
    fingerlings, loan interest); household and personal spending come from the
    transactions people type in. Each is counted exactly once.
    """
    s = Statement(start=start, end=end)
    in_range = {"date__gte": start, "date__lte": end}

    if scope == Scope.BUSINESS:
        if _installed("sales"):
            from apps.business.sales.models import FishSale

            sales = FishSale.objects.filter(business=business, **in_range)
            if cycle is not None:
                sales = sales.filter(cycle=cycle)
            total = sales.aggregate(n=Sum("net"))["n"] or ZERO
            if total:
                s.income.append(Line("sales", _("Fish sales"), total, reverse("business:sales")))
        if _installed("feed"):
            from apps.business.feed.models import FeedUsage
            from apps.business.feed.services import cost_per_kg

            used = FeedUsage.objects.filter(business=business, cycle__is_deleted=False, **in_range)
            if cycle is not None:
                used = used.filter(cycle=cycle)
            prices = cost_per_kg(business, cache=cache.setdefault("prices", {}) if cache is not None else None)
            total = sum((u.kg * prices.get(u.product_id, ZERO) for u in used), ZERO)
            if total:
                s.expense.append(Line("feed", _("Feed used"), total.quantize(Decimal("0.01")), reverse("business:feed_stock")))
        if _installed("ponds"):
            from apps.business.ponds.models import Stocking

            stocked = Stocking.objects.filter(business=business, cycle__is_deleted=False, **in_range)
            if cycle is not None:
                stocked = stocked.filter(cycle=cycle)
            total = stocked.aggregate(c=Sum("cost"))["c"] or ZERO
            if total:
                s.expense.append(Line("stocking", _("Fingerlings"), total, reverse("business:ponds")))
        if _installed("ponds"):
            from apps.business.ponds.models import Treatment

            cared = Treatment.objects.filter(business=business, cycle__is_deleted=False, **in_range)
            if cycle is not None:
                cared = cared.filter(cycle=cycle)
            total = cared.aggregate(c=Sum("cost"))["c"] or ZERO
            if total:
                s.expense.append(Line("care", _("Lime, medicine & pond care"), total, reverse("business:ponds")))
        if _installed("assets") and cycle is None:
            from apps.business.assets.services import costs

            bought, upkeep = costs(business, start, end)
            if bought:
                s.expense.append(Line("equipment", _("Equipment bought"), bought, reverse("business:equipment")))
            if upkeep:
                s.expense.append(Line("upkeep", _("Repairs & servicing"), upkeep, reverse("business:equipment")))
        if _installed("ponds") and cycle is None:
            from apps.business.ponds.models import LeasePayment

            total = LeasePayment.objects.filter(business=business, **in_range).aggregate(t=Sum("amount"))["t"] or ZERO
            if total:
                s.expense.append(Line("lease", _("Pond lease"), total, reverse("business:ponds") + "?show=leased"))
        if _installed("staff"):
            from apps.business.staff.services import wages_cost

            total = wages_cost(business, start, end, cycle)
            if total:
                s.expense.append(Line("wages", _("Staff wages"), total, reverse("business:staff")))
        if _installed("loans") and cycle is None:
            from apps.business.loans.models import LoanTransaction

            paid = LoanTransaction.objects.filter(business=business, **in_range).aggregate(i=Sum("interest"), c=Sum("charges"))
            total = (paid["i"] or ZERO) + (paid["c"] or ZERO)
            if total:
                s.expense.append(Line("loan", _("Loan interest & fees"), total, reverse("business:loans")))

    rows = Transaction.objects.filter(business=business, category__scope=scope, **in_range).select_related("category__parent")
    if cycle is not None:
        rows = rows.filter(cycle=cycle)
    groups = defaultdict(lambda: defaultdict(Decimal))
    for t in rows:
        main = t.category.parent or t.category
        groups[(t.category.type, main.pk, main.display_name)][t.category.pk] += t.amount
    if cache is not None and "names" in cache:
        names = cache["names"]
    else:
        names = {c.pk: c.display_name for c in Category.all_objects.filter(business=business)}
        if cache is not None:
            cache["names"] = names
    for (type_, main_pk, main_name), children in sorted(groups.items(), key=lambda kv: -sum(kv[1].values())):
        line = Line(f"cat{main_pk}", main_name, sum(children.values(), ZERO),
                    reverse("business:transactions") + f"?category={main_pk}")
        line.children = [Line(f"cat{pk}", names.get(pk, "") if pk != main_pk else _("(not in a sub-category)"), amount)
                         for pk, amount in sorted(children.items(), key=lambda kv: -kv[1])]
        (s.income if type_ == CategoryType.INCOME else s.expense).append(line)
    s.income.sort(key=lambda l: -l.amount)
    s.expense.sort(key=lambda l: -l.amount)
    return s


def cycle_costs(cycle, cache=None):
    """Farm costs typed in against one pond season (labour, medicine…).

    With a `cache` dict, every season's costs are fetched in one query the
    first time, so a report of many ponds doesn't ask once per pond.
    """
    if cache is not None:
        if "cycle_costs" not in cache:
            rows = (Transaction.objects.filter(business=cycle.business, cycle__isnull=False, category__type=CategoryType.EXPENSE)
                    .values("cycle_id").annotate(t=Sum("amount")))
            cache["cycle_costs"] = {r["cycle_id"]: r["t"] for r in rows}
        return cache["cycle_costs"].get(cycle.pk, ZERO)
    return Transaction.objects.filter(business=cycle.business, cycle=cycle, category__type=CategoryType.EXPENSE
                                      ).aggregate(t=Sum("amount"))["t"] or ZERO


# ── Budgets ─────────────────────────────────────────────────────────────────

@dataclass
class BudgetRow:
    category: object
    planned: Decimal
    spent: Decimal

    @property
    def left(self):
        return self.planned - self.spent

    @property
    def pct(self):
        return min(int(self.spent * 100 / self.planned), 100) if self.planned else 0

    @property
    def over_pct(self):
        return int(self.spent * 100 / self.planned) if self.planned else 0

    @property
    def state(self):
        if self.spent > self.planned:
            return "over"
        return "warn" if self.over_pct >= 80 else "ok"


def budget_rows(business, month):
    """Planned vs spent for one month, in one list."""
    from .models import Budget

    last = _month_end(month)
    spent = defaultdict(Decimal)
    for t in Transaction.objects.filter(business=business, date__gte=month, date__lte=last,
                                        category__type=CategoryType.EXPENSE).select_related("category"):
        spent[t.category.parent_id or t.category_id] += t.amount
    rows = []
    for b in Budget.objects.filter(business=business, month=month).select_related("category"):
        rows.append(BudgetRow(b.category, b.amount, spent.pop(b.category_id, ZERO)))
    rows.sort(key=lambda r: (-r.over_pct, -r.planned))
    extra = [BudgetRow(c, ZERO, spent[c.pk]) for c in Category.objects.filter(business=business, pk__in=list(spent)) if spent[c.pk]]
    extra.sort(key=lambda r: -r.spent)
    return rows, extra


def _month_end(month):
    from calendar import monthrange

    return month.replace(day=monthrange(month.year, month.month)[1])


# ── Recurring ───────────────────────────────────────────────────────────────

STEP = {"weekly": ("days", 7), "monthly": ("months", 1), "quarterly": ("months", 3), "half": ("months", 6), "yearly": ("months", 12)}


def next_date(after, repeat):
    from datetime import timedelta

    from apps.business.loans.schedule import add_months

    unit, n = STEP[repeat]
    return after + timedelta(days=n) if unit == "days" else add_months(after, n)


def due_recurring(business, on=None):
    """Recurring bills waiting to be confirmed, soonest first."""
    from .models import RecurringTransaction

    on = on or date.today()
    rows = (RecurringTransaction.objects.filter(business=business, next_due__isnull=False, next_due__lte=on)
            .select_related("category", "account"))
    return [r for r in rows if not (r.end_date and r.next_due > r.end_date)]
