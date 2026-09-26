"""Loan schedule engine.

Nothing here is stored. The schedule is worked out every time from the loan's
terms plus what has actually happened (payments, extra borrowing, rate
changes), so editing any of those re-plans everything and nothing goes stale.

How it works, in order:
  1. Due dates: every N months (or weeks) from the first due date, until the
     end date. A loan without an end date gets due dates up to today plus
     the next one.
  2. Principal plan: how much of the loan each due date should pay back
     (nothing until the end / equal parts / equal instalments).
  3. Actual principal paid covers those planned amounts oldest first. What is
     still uncovered on future dates is assumed to be paid on time, which
     gives the projected balance.
  4. Interest per period, on the balance day by day (reducing) or on the full
     amount borrowed (flat), at the rate that applied on each day. A regular
     period costs exactly balance × period rate, so 2% a month on ৳1,00,000
     is ৳2,000 every month, not a day-count approximation of it.
  5. Actual interest paid covers the interest due, oldest first.

The engine uses plain values (Terms and tuples), so the loan form's live
preview and saved loans share exactly the same maths.
"""
import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from itertools import pairwise

ZERO = Decimal("0")
CENT = Decimal("0.01")
MAX_PERIODS = 600          # 50 years of monthly payments; a safety stop
DUE_SOON_DAYS = 7


def money(value):
    return Decimal(value).quantize(CENT, ROUND_HALF_UP)


def add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


@dataclass
class Terms:
    principal: Decimal
    taken_on: date
    rate: Decimal = ZERO             # % per rate_period
    rate_period: str = "year"        # "year" | "month"
    method: str = "reducing"         # "reducing" | "flat"
    repayment: str = "end"           # "end" | "equal" | "emi"
    every: int = 1
    every_unit: str = "month"        # "month" | "week"
    first_due: date | None = None
    maturity: date | None = None
    closed_on: date | None = None

    def step(self, d, k=1):
        """k payment intervals after (or before, if negative) d."""
        if self.every_unit == "week":
            return d + timedelta(weeks=self.every * k)
        return add_months(d, self.every * k)

    @property
    def first(self):
        return self.first_due or self.step(self.taken_on)

    def annual(self, rate):
        return rate * 12 if self.rate_period == "month" else rate

    def period_rate(self, rate):
        """The loan's rate (in its own terms) → the rate for one full payment interval."""
        years = Decimal(self.every) / 12 if self.every_unit == "month" else Decimal(self.every * 7) / 365
        return self.annual(rate) / 100 * years


@dataclass
class Period:
    no: int
    start: date
    due: date
    rate: Decimal
    interest: Decimal
    principal: Decimal
    interest_paid: Decimal = ZERO
    principal_paid: Decimal = ZERO
    balance_after: Decimal = ZERO    # planned balance once this is paid
    status: str = "upcoming"         # paid | overdue | due_soon | upcoming
    is_current: bool = False

    @property
    def total(self):
        return self.interest + self.principal

    @property
    def paid(self):
        return self.interest_paid + self.principal_paid

    @property
    def remaining(self):
        return max(self.total - self.paid, ZERO)

    @property
    def interest_left(self):
        return max(self.interest - self.interest_paid, ZERO)

    @property
    def principal_left(self):
        return max(self.principal - self.principal_paid, ZERO)

    @property
    def is_partial(self):
        return self.status != "paid" and self.paid > 0


@dataclass
class Schedule:
    terms: Terms
    today: date
    periods: list = field(default_factory=list)
    borrowed: Decimal = ZERO
    principal_paid: Decimal = ZERO
    interest_paid: Decimal = ZERO
    charges_paid: Decimal = ZERO
    interest_planned: Decimal = ZERO
    unpaid_interest: Decimal = ZERO   # owed as of today, incl. interest building up in the current period
    late_interest: Decimal = ZERO     # interest after the last due date (loan past its end)

    @property
    def outstanding(self):
        return max(self.borrowed - self.principal_paid, ZERO)

    @property
    def payoff(self):
        """What it takes to close the loan today."""
        return self.outstanding + self.unpaid_interest

    @property
    def total_paid(self):
        return self.principal_paid + self.interest_paid + self.charges_paid

    @property
    def progress(self):
        return int(min(self.principal_paid / self.borrowed * 100, 100)) if self.borrowed else 0

    @property
    def is_paid_off(self):
        return self.outstanding < CENT and self.unpaid_interest < 1

    @property
    def overdue_periods(self):
        return [p for p in self.periods if p.status == "overdue"]

    @property
    def overdue(self):
        return sum((p.remaining for p in self.overdue_periods), ZERO)

    @property
    def next_due(self):
        """The oldest period not fully paid (it may already be overdue)."""
        return next((p for p in self.periods if p.status != "paid"), None)

    @property
    def upcoming(self):
        return next((p for p in self.periods if p.status in ("due_soon", "upcoming")), None)

    @property
    def interest_left(self):
        return max(self.interest_planned - self.interest_paid, ZERO)

    @property
    def unpaid_count(self):
        return sum(1 for p in self.periods if p.status != "paid")

    @property
    def instalment(self):
        """A typical payment: the second one (the first may be a short period)."""
        regular = [p for p in self.periods if p.total > 0]
        if not regular:
            return ZERO
        return (regular[1] if len(regular) > 2 else regular[0]).total

    @property
    def interest_due_now(self):
        """Interest to settle first when splitting a payment: everything owed up
        to and including the next due date."""
        limit = self.upcoming.due if self.upcoming else self.today
        return sum((p.interest_left for p in self.periods if p.due <= limit), ZERO) + self.late_interest


# ── Building blocks ─────────────────────────────────────────────────────────

def _rate_at(terms, changes, d):
    rate = terms.rate
    for when, value in changes:
        if when <= d:
            rate = value
    return rate


def _due_dates(terms, horizon):
    dates, first = [], terms.first
    for k in range(MAX_PERIODS):
        d = terms.step(first, k)
        if terms.maturity and d >= terms.maturity:
            dates.append(terms.maturity)
            break
        dates.append(d)
        if not terms.maturity and d > horizon:
            break
    if terms.closed_on:
        kept = []
        for d in dates:
            if kept and kept[-1] >= terms.closed_on:
                break
            kept.append(min(d, terms.closed_on))
        dates = kept
    return dates


def _plan_principal(terms, dues, starts, disbursements, changes):
    """How much of the loan each due date is meant to pay back."""
    n = len(dues) if terms.maturity else None
    planned, pending, out = ZERO, list(disbursements), []
    for i, due in enumerate(dues):
        while pending and pending[0][0] < due:
            planned += pending.pop(0)[1]
        last = n is not None and i == n - 1
        if n is None or terms.repayment == "end":
            part = planned if last else ZERO
        elif last:
            part = planned
        else:
            left = n - i
            r = terms.period_rate(_rate_at(terms, changes, starts[i]))
            if terms.repayment == "emi" and terms.method == "reducing" and r > 0:
                emi = planned * r / (1 - (1 + r) ** -left)
                part = emi - planned * r
            else:  # equal parts (and flat-rate instalments, which are equal parts too)
                part = planned / left
        part = min(max(money(part), ZERO), planned)
        planned -= part
        out.append(part)
    return out


def _cover(amounts, paid):
    """Spread `paid` over `amounts`, oldest first."""
    out = []
    for a in amounts:
        take = min(a, paid)
        out.append(take)
        paid -= take
    return out


def _accrue(terms, a, b, nominal_days, balance_events, changes):
    """Interest from a to b (b excluded) on the balance, split wherever the
    balance or the rate changes."""
    if b <= a or nominal_days <= 0:
        return ZERO
    cuts = {d for d, _ in balance_events if a < d < b} | {d for d, _ in changes if a < d < b}
    total = ZERO
    for x, y in pairwise(sorted({a, b} | cuts)):
        bal = max(sum((v for d, v in balance_events if d <= x), ZERO), ZERO)
        if bal:
            total += bal * terms.period_rate(_rate_at(terms, changes, x)) * (y - x).days / nominal_days
    return total


# ── The schedule ────────────────────────────────────────────────────────────

def build(terms, payments=(), topups=(), rate_changes=(), today=None):
    """payments: (date, principal, interest, charges); topups: (date, amount);
    rate_changes: (effective date, rate in the loan's own terms)."""
    today = today or date.today()
    changes = sorted(rate_changes)
    disb = sorted([(terms.taken_on, money(terms.principal))] + [(d, money(a)) for d, a in topups])
    payments = sorted(payments)

    s = Schedule(terms=terms, today=today)
    s.borrowed = sum((a for _, a in disb), ZERO)
    s.principal_paid = sum((money(p) for _, p, _, _ in payments), ZERO)
    s.interest_paid = sum((money(i) for _, _, i, _ in payments), ZERO)
    s.charges_paid = sum((money(c) for _, _, _, c in payments), ZERO)

    horizon = max([today] + [d for d, _ in disb] + [p[0] for p in payments])
    dues = _due_dates(terms, horizon)
    starts = [terms.taken_on] + dues[:-1]
    planned = _plan_principal(terms, dues, starts, disb, changes)
    covered = _cover(planned, s.principal_paid)

    # Balance over time: actual up to now, then planned payments assumed on time.
    if terms.method == "flat":
        events = list(disb)
    else:
        events = disb + [(d, -money(p)) for d, p, _, _ in payments if p]
        events += [(due, -(p - c)) for due, p, c in zip(dues, planned, covered) if due > today and p > c]

    periods, balance = [], s.borrowed
    for i, (start, due) in enumerate(zip(starts, dues)):
        if i == 0 and not terms.first_due:
            nominal = (due - start).days
        else:
            nominal = (terms.step(terms.first, i) - terms.step(terms.first, i - 1)).days
        interest = money(_accrue(terms, start, due, nominal, events, changes))
        balance -= planned[i]
        periods.append(Period(no=i + 1, start=start, due=due, rate=_rate_at(terms, changes, start),
                              interest=interest, principal=planned[i], principal_paid=covered[i],
                              balance_after=max(balance, ZERO), is_current=start <= today < due))

    for p, c in zip(periods, _cover([p.interest for p in periods], s.interest_paid)):
        p.interest_paid = c
    s.interest_planned = sum((p.interest for p in periods), ZERO)

    for p in periods:
        if p.remaining < CENT:
            p.status = "paid"
        elif p.due < today:
            p.status = "overdue"
        elif (p.due - today).days <= DUE_SOON_DAYS:
            p.status = "due_soon"

    # Interest owed today: past periods, plus what has built up so far in the
    # current one, plus anything after the last due date, minus what's paid.
    actual = list(disb) if terms.method == "flat" else disb + [(d, -money(p)) for d, p, _, _ in payments if p]
    owed = sum((p.interest for p in periods if p.due <= today), ZERO)
    current = next((p for p in periods if p.is_current), None)
    if current:
        i = current.no - 1
        nominal = (terms.step(terms.first, i) - terms.step(terms.first, i - 1)).days if (i or terms.first_due) else (current.due - current.start).days
        owed += _accrue(terms, current.start, today, nominal, actual, changes)
    if periods and today > periods[-1].due and not terms.closed_on:
        last = periods[-1].due
        nominal = (terms.step(last) - last).days
        s.late_interest = money(_accrue(terms, last, today, nominal, actual, changes))
        owed += s.late_interest
    s.unpaid_interest = max(money(owed) - s.interest_paid, ZERO)

    # Periods with nothing to pay (interest-free, principal at the end) are just noise.
    s.periods = [p for p in periods if p.total > 0]
    for n, p in enumerate(s.periods, 1):
        p.no = n
    return s
