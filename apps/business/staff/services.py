"""Balances, a worker's khata, the monthly salary sheet and labour cost."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db.models import Q, Sum

from .models import Absence, Earning, EarningKind, PayType, Worker, WorkerPayment

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
    amount: Decimal             # what the month's salary should be: part month if they joined or left, less days off without pay
    added: Earning | None       # the salary already written for this month, if any
    balance: Decimal
    days_off: Decimal = ZERO    # days off without pay this month (from the work sheet)
    cut: Decimal = ZERO         # what those days take off the salary
    leave: Decimal = ZERO       # paid leave: shown, not cut

    @property
    def is_partial(self):
        return self.amount + self.cut != self.worker.rate

    @property
    def days_off_plural(self):     # for "1 day" / "1.5 days"
        return 1 if self.days_off == 1 else 2

    @property
    def leave_plural(self):
        return 1 if self.leave == 1 else 2


def day_rate(worker, month):
    """One day of a monthly salary: the month's salary ÷ the days in that month."""
    import calendar

    return worker.rate / calendar.monthrange(month.year, month.month)[1]


def salary_sheet(business, month):
    """Monthly-paid workers who worked any day of `month`, and whether that month's salary is written."""
    first = month.replace(day=1)
    import calendar

    last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
    workers = (Worker.objects.filter(business=business, pay_type=PayType.MONTHLY, started_on__lte=last)
               .filter(Q(left_on__isnull=True) | Q(left_on__gte=first)))
    added = {e.worker_id: e for e in Earning.objects.filter(business=business, kind=EarningKind.SALARY, month=first)}
    bal = balances(business)
    off, leave = defaultdict(Decimal), defaultdict(Decimal)
    for a in Absence.objects.filter(business=business, date__gte=first, date__lte=last).select_related("worker"):
        if a.worker.works_on(a.date):
            (leave if a.paid else off)[a.worker_id] += a.days
    rows = []
    for w in workers:
        full = w.salary_for(first)
        cut = min((day_rate(w, first) * off[w.pk]).quantize(Decimal("1")), full)
        rows.append(SalaryRow(w, full - cut, added.get(w.pk), bal.get(w.pk, ZERO), off[w.pk], cut, leave[w.pk]))
    return rows


def set_attendance(worker, day, mark):
    """A monthly worker's day on the work sheet: "1" worked, "0.5" half day,
    "0" off without pay, "leave" paid leave. Returns True if it changed."""
    days, paid = {"0.5": (Decimal("0.5"), False), "0": (Decimal(1), False), "leave": (Decimal(1), True)}.get(mark, (None, False))
    now = Absence.objects.filter(worker=worker, date=day).first()
    if days is None:
        if now:
            now.delete()
            return True
        return False
    if now and (now.days, now.paid) == (days, paid):
        return False
    if now is None:
        now = Absence(business=worker.business, worker=worker, date=day)
    now.days, now.paid = days, paid
    now.save()
    return True


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


# ── Attendance: a month at a glance ─────────────────────────────────────────

@dataclass
class AttendanceRow:
    worker: Worker
    cells: list            # [(date, state)] — state: full | half | off | leave | none (not here then, or not yet)
    worked: Decimal = ZERO
    off: Decimal = ZERO
    leave: Decimal = ZERO


def attendance(business, month, today=None):
    """Every worker's days in `month`. Daily workers: the days written on the
    work sheet (no entry for a past day = off). Monthly staff: here every day
    unless marked half, off or on leave."""
    import calendar
    from datetime import timedelta

    today = today or date.today()
    first = month.replace(day=1)
    last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    workers = list(Worker.objects.filter(business=business, started_on__lte=last).filter(Q(left_on__isnull=True) | Q(left_on__gte=first))
                   .order_by("pay_type", "name"))
    worked = defaultdict(Decimal)
    for e in Earning.objects.filter(business=business, kind=EarningKind.WORK, date__gte=first, date__lte=last).values("worker_id", "date").annotate(d=Sum("days")):
        worked[(e["worker_id"], e["date"])] = e["d"] or ZERO
    away = {(a.worker_id, a.date): a for a in Absence.objects.filter(business=business, date__gte=first, date__lte=last)}
    rows = []
    for w in workers:
        row = AttendanceRow(w, [])
        for d in days:
            if not w.works_on(d) or d > today:
                state = "none"
            elif w.is_monthly:
                a = away.get((w.pk, d))
                state = "full" if a is None else "leave" if a.paid else "half" if a.days < 1 else "off"
            else:
                n = worked.get((w.pk, d), ZERO)
                state = "full" if n >= 1 else "half" if n > 0 else ("none" if d == today else "off")
            if state == "full":
                row.worked += 1
            elif state == "half":
                row.worked += Decimal("0.5")
                row.off += Decimal("0.5")
            elif state == "off":
                row.off += 1
            elif state == "leave":
                row.leave += 1
            row.cells.append((d, state))
        rows.append(row)
    return days, rows
