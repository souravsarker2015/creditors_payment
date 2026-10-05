"""Balances, a worker's khata, the monthly salary sheet and labour cost."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db.models import Q, Sum

from .models import Earning, EarningKind, PayType, Worker, WorkerPayment

ZERO = Decimal(0)


def balances(business):
    """{worker id: balance} — positive: the farm owes them; negative: they hold an advance."""
    out = {w.pk: w.opening_balance for w in Worker.objects.filter(business=business)}
    earned = (Earning.objects.filter(business=business).values("worker_id", "kind").annotate(t=Sum("amount")))
    for row in earned:
        if row["worker_id"] in out:
            out[row["worker_id"]] += -row["t"] if row["kind"] == EarningKind.DEDUCTION else row["t"]
    for row in WorkerPayment.objects.filter(business=business).values("worker_id").annotate(t=Sum("amount")):
        if row["worker_id"] in out:
            out[row["worker_id"]] -= row["t"]
    return out


def balance(worker):
    return balances(worker.business).get(worker.pk, worker.opening_balance)


@dataclass
class Line:
    date: date
    title: str
    detail: str
    earned: Decimal = ZERO      # + earned, − deducted
    paid: Decimal = ZERO
    balance: Decimal = ZERO
    kind: str = ""
    obj: object = None


def khata(worker):
    """Every earning and payment, oldest first, with the running balance."""
    from django.utils.translation import gettext as _

    lines = []
    for e in worker.earnings.select_related("cycle__pond"):
        detail = ""
        if e.kind == EarningKind.WORK and e.days is not None:
            detail = _("%(days)s day(s) × %(rate)s") % {"days": format(e.days.normalize(), "f"), "rate": format((e.rate or ZERO).normalize(), "f")}
        elif e.kind == EarningKind.SALARY and e.month:
            from django.utils.formats import date_format

            detail = date_format(e.month, "F Y")
        if e.cycle_id:
            detail = " · ".join(x for x in (detail, str(e.cycle.pond)) if x)
        if e.notes:
            detail = " · ".join(x for x in (detail, e.notes) if x)
        lines.append(Line(e.date, e.get_kind_display(), detail, earned=e.signed, kind="earning", obj=e))
    for p in worker.payments.select_related("account"):
        detail = " · ".join(x for x in (str(p.account), p.notes) if x)
        lines.append(Line(p.date, p.get_kind_display(), detail, paid=p.amount, kind="payment", obj=p))
    lines.sort(key=lambda l: (l.date, l.kind != "earning", l.obj.pk))
    running = worker.opening_balance
    for l in lines:
        running += l.earned - l.paid
        l.balance = running
    return lines


# ── Monthly salary sheet ────────────────────────────────────────────────────

@dataclass
class SalaryRow:
    worker: Worker
    amount: Decimal             # what the month's salary should be (part month if they joined or left)
    added: Earning | None       # the salary already written for this month, if any
    balance: Decimal

    @property
    def is_partial(self):
        return self.amount != self.worker.rate


def salary_sheet(business, month):
    """Monthly-paid workers who worked any day of `month`, and whether that month's salary is written."""
    first = month.replace(day=1)
    import calendar

    last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
    workers = (Worker.objects.filter(business=business, pay_type=PayType.MONTHLY, started_on__lte=last)
               .filter(Q(left_on__isnull=True) | Q(left_on__gte=first)))
    added = {e.worker_id: e for e in Earning.objects.filter(business=business, kind=EarningKind.SALARY, month=first)}
    bal = balances(business)
    return [SalaryRow(w, w.salary_for(first), added.get(w.pk), bal.get(w.pk, ZERO)) for w in workers]


def missing_salaries(business, month):
    return [r for r in salary_sheet(business, month) if r.added is None and r.amount > 0]


# ── Labour cost, for reports ────────────────────────────────────────────────

def wages_cost(business, start, end, cycle=None):
    rows = Earning.objects.filter(business=business, date__gte=start, date__lte=end)
    if cycle is not None:
        rows = rows.filter(cycle=cycle)
    total = ZERO
    for r in rows.values("kind").annotate(t=Sum("amount")):
        total += -r["t"] if r["kind"] == EarningKind.DEDUCTION else r["t"]
    return total


def cycle_wages(cycle):
    """Labour written against one pond cycle (uses prefetched rows when a report loaded them).
    A worker who has since left or been removed still cost what they earned."""
    return sum((e.signed for e in cycle.staff_earnings.all()), ZERO)


def by_worker(business, start, end):
    """{worker id: (earned, paid)} in a period, for the staff list."""
    out = defaultdict(lambda: [ZERO, ZERO])
    for e in Earning.objects.filter(business=business, date__gte=start, date__lte=end):
        out[e.worker_id][0] += e.signed
    for p in WorkerPayment.objects.filter(business=business, date__gte=start, date__lte=end):
        out[p.worker_id][1] += p.amount
    return out
