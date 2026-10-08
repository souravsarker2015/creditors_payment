"""Upcoming money: what's coming in and going out over the next days, and
whether the money will last.

Both sides of the app use this: the personal side (dues, installments,
regular income and spending) and the farm (loan instalments, regular bills,
baki follow-ups, wages). Each gives the money there is now and a list of
dated items; this works out the balance day by day and the first day it
would fall below zero.

Something that was due before today and is still unpaid is counted today
(and marked late): it hasn't happened yet, so it still has to come from
somewhere.
"""
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

ZERO = Decimal(0)
PERIODS = (7, 30, 90)


@dataclass
class Item:
    date: date
    amount: Decimal          # + coming in, − going out
    title: str
    detail: str = ""
    url: str = ""
    kind: str = ""           # what it is, for the icon: due | plan | recurring | loan | bill | baki | wages
    late: bool = False       # was due before today and still isn't settled

    @property
    def is_in(self):
        return self.amount > 0


@dataclass
class Day:
    date: date
    items: list = field(default_factory=list)
    balance: Decimal = ZERO  # after this day's money
    offset: int = 0          # days from today: 0 today, 1 tomorrow…

    @property
    def total(self):
        return sum((i.amount for i in self.items), ZERO)


@dataclass
class Forecast:
    today: date
    end: date
    days_ahead: int
    now: Decimal
    days: list = field(default_factory=list)

    @property
    def items(self):
        return [i for d in self.days for i in d.items]

    @property
    def coming_in(self):
        return sum((i.amount for i in self.items if i.amount > 0), ZERO)

    @property
    def going_out(self):
        return -sum((i.amount for i in self.items if i.amount < 0), ZERO)

    @property
    def end_balance(self):
        return self.now + self.coming_in - self.going_out

    @property
    def late(self):
        return [i for i in self.items if i.late]

    @property
    def short(self):
        """The first day the money would run out: (day, how much short), or None."""
        for d in self.days:
            if d.balance < 0:
                return d, -d.balance
        return None

    @property
    def lowest(self):
        return min((d.balance for d in self.days), default=self.now)


def build(now, items, today=None, days=30):
    """`now`: money there is today. `items`: Item list (any dates; ones after
    the window are left out, late ones are counted today)."""
    today = today or date.today()
    end = today + timedelta(days=days)
    by_day = {}
    for item in items:
        if not item.amount or item.date > end:
            continue
        if item.date < today:
            item.late = True
        when = max(item.date, today)
        by_day.setdefault(when, []).append(item)
    f = Forecast(today=today, end=end, days_ahead=days, now=now)
    running = now
    for when in sorted(by_day):
        # Within a day, money in before money out — the way a khata reads.
        rows = sorted(by_day[when], key=lambda i: (i.amount < 0, not i.late, i.title))
        running += sum((i.amount for i in rows), ZERO)
        f.days.append(Day(when, rows, running, (when - today).days))
    return f


def window(request):
    """How many days ahead the page shows (?days=7|30|90, default 30)."""
    try:
        days = int(request.GET.get("days", 30))
    except (TypeError, ValueError):
        days = 30
    return days if days in PERIODS else 30


def repeat(first, step, until, end_date=None, limit=400):
    """The dates of something that repeats: first, step(first), … up to `until`
    (and not after `end_date`)."""
    out, d = [], first
    while d and d <= until and (end_date is None or d <= end_date) and len(out) < limit:
        out.append(d)
        nxt = step(d)
        if nxt <= d:   # a step that doesn't move on would never end
            break
        d = nxt
    return out
