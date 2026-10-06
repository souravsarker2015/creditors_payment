import calendar
import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum

from .models import Frequency

ZERO = Decimal(0)
MAX_INSTALLMENTS = 600


def add_months(d, n):
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return d.replace(year=y, month=m, day=min(d.day, calendar.monthrange(y, m)[1]))


def nth_date(plan, k):
    if plan.frequency == Frequency.MONTHLY:
        return add_months(plan.start_date, k)
    return plan.start_date + timedelta(days=k * (7 if plan.frequency == Frequency.WEEKLY else 14))


def _ledger(plan):
    """(payments queryset, outstanding now) on the plan's ledger."""
    party = plan.party
    tx = party.transactions
    if plan.creditor_id:
        from apps.creditors.models import Transaction as T
        out_type, back_type = T.BORROW, T.REPAY
    elif plan.debtor_id:
        from apps.debtors.models import Transaction as T
        out_type, back_type = T.LEND, T.RECEIVE
    else:
        from apps.shops.models import Transaction as T
        out_type, back_type = T.PURCHASE, T.PAYMENT
    owed = tx.filter(transaction_type=out_type).aggregate(t=Sum("amount"))["t"] or ZERO
    back = tx.filter(transaction_type=back_type)
    return back, owed - (back.aggregate(t=Sum("amount"))["t"] or ZERO)


@dataclass
class Status:
    plan: object
    remaining: Decimal          # still owed on the ledger
    paid: Decimal               # paid toward the plan (since its first date, less one period of grace)
    dates: list = field(default_factory=list)
    today: date = None

    @property
    def total(self):
        return self.paid + max(self.remaining, ZERO)

    @property
    def count(self):
        return len(self.dates)

    @property
    def paid_count(self):
        return min(int(self.paid // self.plan.amount), self.count)

    @property
    def done(self):
        return self.remaining <= 0

    @property
    def due_so_far(self):
        """What should have been paid by today."""
        return min(sum(1 for d in self.dates if d <= self.today) * self.plan.amount, self.total)

    @property
    def behind(self):
        return max(self.due_so_far - self.paid, ZERO)

    @property
    def missed(self):
        return math.ceil(self.behind / self.plan.amount) if self.behind else 0

    @property
    def next_date(self):
        return None if self.done else (self.dates[self.paid_count] if self.paid_count < self.count else None)

    @property
    def next_amount(self):
        """The next installment (or what's left of it), or everything that's late."""
        if self.done:
            return ZERO
        part = self.plan.amount - (self.paid - self.paid_count * self.plan.amount)
        return min(max(self.behind, part), self.remaining)

    @property
    def last_date(self):
        return self.dates[-1] if self.dates else None

    def upcoming(self, n=5):
        """The next unpaid installments: [(date, "late" | "today" | "next" | "later")]."""
        out, seen_next = [], False
        for d in self.dates[self.paid_count:self.paid_count + n]:
            if d < self.today:
                state = "late"
            elif d == self.today:
                state = "today"
            elif not seen_next:
                state, seen_next = "next", True
            else:
                state = "later"
            out.append((d, state))
        return out

    @property
    def pct(self):
        return min(int(self.paid * 100 / self.total), 100) if self.total else 100


def status(plan, today=None):
    today = today or date.today()
    payments, remaining = _ledger(plan)
    grace = nth_date(plan, 0) - (nth_date(plan, 1) - nth_date(plan, 0))   # an early first payment still counts
    paid = payments.filter(date__gte=grace).aggregate(t=Sum("amount"))["t"] or ZERO
    total = paid + max(remaining, ZERO)
    n = min(max(math.ceil(total / plan.amount), 1), MAX_INSTALLMENTS)
    return Status(plan, remaining, paid, [nth_date(plan, k) for k in range(n)], today)


def sync_due_date(plan):
    """Keep the ledger's due date on the next installment (empty once it's paid off)."""
    st = status(plan)
    party = plan.party
    if party.due_date != st.next_date:
        type(party).objects.filter(pk=party.pk).update(due_date=st.next_date)
        party.due_date = st.next_date
    return st
