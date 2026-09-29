"""Everything that belongs on the farm calendar, for a range of days.

Nothing is copied: the calendar reads the records themselves (sales, pond
entries, loans, regular bills, baki follow-ups) plus the farm's own events,
so it always agrees with the pages they come from.
"""
import calendar as pycal
from dataclasses import asdict, dataclass
from datetime import date, timedelta

from django.apps import apps
from django.urls import reverse
from django.utils.translation import gettext as _

from .bangla import bn_digits, from_bangla, month_length, to_bangla
from .models import Category, CalendarEvent, Repeat

# The filter groups, in the order shown.
KINDS = ["mine", "pond", "sale", "feed", "due", "holiday"]
DAY = timedelta(days=1)


@dataclass
class Item:
    date: date
    kind: str            # one of KINDS
    title: str
    detail: str = ""
    url: str = ""
    tone: str = ""       # good | warn | critical | info | muted
    icon: str = ""
    time: str = ""       # "07:30"
    cat: str = ""        # a farm event's own category (for its colour)
    pk: int = 0          # a farm event's id (edit, done)
    done: bool = False
    task: bool = False
    repeat: bool = False

    def as_json(self):
        d = asdict(self)
        d["date"] = self.date.isoformat()
        return d


def _installed(label):
    return apps.is_installed(f"apps.business.{label}")


# ── The farm's own events, with repeats ─────────────────────────────────────

def _clamp(year, month, day):
    return date(year, month, min(day, pycal.monthrange(year, month)[1]))


def occurrences(event, start, end):
    """Every date the event falls on between start and end (inclusive)."""
    first = event.date
    stop = min(end, event.repeat_until) if event.repeat_until else end
    if not event.repeat:
        last = event.end_date or first
        d = max(first, start)
        while d <= min(last, end):
            yield d
            d += DAY
        return
    if event.repeat == Repeat.WEEKLY:
        d = first + timedelta(days=max(0, -(-(start - first).days // 7)) * 7)
        while d <= stop:
            yield d
            d += timedelta(days=7)
        return
    if event.repeat in (Repeat.MONTHLY, Repeat.YEARLY):
        y, m = first.year, first.month
        step = 1 if event.repeat == Repeat.MONTHLY else 12
        if start > first:   # jump close to the range instead of walking from the first date
            months = (start.year - y) * 12 + start.month - m - 1
            months = max(0, months - months % step)
            y, m = y + (m - 1 + months) // 12, (m - 1 + months) % 12 + 1
        while True:
            d = _clamp(y, m, first.day)
            if d > stop:
                return
            if d >= start and d >= first:
                yield d
            y, m = y + (m - 1 + step) // 12, (m - 1 + step) % 12 + 1
    b = to_bangla(first)
    if event.repeat in (Repeat.BN_MONTHLY, Repeat.BN_YEARLY):
        step = 1 if event.repeat == Repeat.BN_MONTHLY else 12
        y, m = b.year, b.month
        sb = to_bangla(max(start, first))
        months = (sb.year - y) * 12 + sb.month - m - 1
        months = max(0, months - months % step)
        y, m = y + (m - 1 + months) // 12, (m - 1 + months) % 12 + 1
        while True:
            d = from_bangla(y, m, min(b.day, month_length(y, m)))
            if d > stop:
                return
            if d >= start and d >= first:
                yield d
            y, m = y + (m - 1 + step) // 12, (m - 1 + step) % 12 + 1


def farm_events(business, start, end):
    items = []
    qs = CalendarEvent.objects.filter(business=business).select_related("pond")
    qs = qs.filter(date__lte=end).exclude(repeat="", end_date__isnull=True, date__lt=start).exclude(repeat="", end_date__lt=start)
    for e in qs:
        detail = str(e.pond) if e.pond else ""
        for d in occurrences(e, start, end):
            items.append(Item(d, "mine", e.title, detail, reverse("business:calendar_edit", args=[e.pk]), cat=e.category,
                              icon="check" if e.is_task else "calendar", time=e.time.strftime("%H:%M") if e.time else "",
                              pk=e.pk, done=e.done and not e.repeat, task=e.is_task, repeat=bool(e.repeat)))
    return items


# ── From the rest of the farm ───────────────────────────────────────────────

def pond_items(business, start, end):
    from apps.business.ponds.models import (CultureCycle, CycleStatus, Harvest, Mortality, Pond, PondAlerts,
                                            SampleWeighing, Stocking, WaterTest)
    from apps.business.core.templatetags.business import num

    items = []
    alive = {"business": business, "date__gte": start, "date__lte": end, "cycle__is_deleted": False}

    def cycle_url(cycle_id, tab):
        return reverse("business:cycle_detail", args=[cycle_id]) + f"?tab={tab}"

    for s in Stocking.objects.filter(**alive).select_related("species", "cycle__pond"):
        items.append(Item(s.date, "pond", _("Fingerlings released · %(pond)s") % {"pond": s.cycle.pond.name},
                          " ".join(x for x in (f"{num(s.count)}" if s.count else "", str(s.species)) if x), cycle_url(s.cycle_id, "stocking"),
                          "info", "fish"))
    for h in Harvest.objects.filter(**alive).select_related("species", "unit", "cycle__pond"):
        items.append(Item(h.date, "pond", _("Harvest · %(pond)s") % {"pond": h.cycle.pond.name},
                          f"{num(h.quantity)} {h.unit.symbol} {h.species}", cycle_url(h.cycle_id, "harvest"), "good", "cart"))
    for m in Mortality.objects.filter(**alive).select_related("cycle__pond"):
        items.append(Item(m.date, "pond", _("%(n)s fish died · %(pond)s") % {"n": num(m.count), "pond": m.cycle.pond.name},
                          m.cause, cycle_url(m.cycle_id, "growth"), "critical", "alert"))
    for w in SampleWeighing.objects.filter(**alive).select_related("species", "unit", "cycle__pond"):
        items.append(Item(w.date, "pond", _("Sample weighing · %(pond)s") % {"pond": w.cycle.pond.name},
                          _("%(g)s g each") % {"g": num(w.avg_g)} + f" · {w.species}", cycle_url(w.cycle_id, "growth"), "info", "scale"))
    limits = PondAlerts.for_business(business)
    for t in WaterTest.objects.filter(**alive).select_related("cycle__pond"):
        found = t.problems(limits)
        items.append(Item(t.date, "pond", _("Water test · %(pond)s") % {"pond": t.cycle.pond.name},
                          " · ".join(f.what for f in found) if found else _("All readings within your levels"),
                          cycle_url(t.cycle_id, "water"), "critical" if found else "good", "beaker"))
    cycles = CultureCycle.objects.filter(business=business).select_related("pond")
    for c in cycles.filter(start_date__gte=start, start_date__lte=end):
        items.append(Item(c.start_date, "pond", _("Cycle started · %(pond)s") % {"pond": c.pond.name}, c.label,
                          reverse("business:cycle_detail", args=[c.pk]), "info", "fish"))
    for c in cycles.filter(ended_on__gte=start, ended_on__lte=end):
        items.append(Item(c.ended_on, "pond", _("Cycle finished · %(pond)s") % {"pond": c.pond.name}, c.label,
                          reverse("business:cycle_detail", args=[c.pk]), "muted", "lock"))
    for c in cycles.filter(status=CycleStatus.RUNNING, expected_harvest__gte=start, expected_harvest__lte=end):
        items.append(Item(c.expected_harvest, "pond", _("Planned harvest · %(pond)s") % {"pond": c.pond.name}, c.label,
                          reverse("business:cycle_detail", args=[c.pk]) + "?tab=harvest", "warn", "cart"))
    for p in Pond.objects.filter(business=business, lease_end__gte=start, lease_end__lte=end):
        items.append(Item(p.lease_end, "pond", _("Lease ends · %(pond)s") % {"pond": p.name}, p.lease_from,
                          reverse("business:pond_detail", args=[p.pk]), "warn", "calendar"))
    return items


def sale_items(business, start, end, money):
    from apps.business.core.templatetags.business import bdt
    from apps.business.sales.models import FishSale

    items = []
    for s in FishSale.objects.filter(business=business, date__gte=start, date__lte=end).select_related("buyer", "market"):
        who = s.buyer or s.market
        items.append(Item(s.date, "sale", _("Sale · %(who)s") % {"who": who} if who else _("Cash sale"),
                          bdt(s.net) if money else "", reverse("business:sale_detail", args=[s.pk]), "good", "cart"))
    return items


def feed_items(business, start, end, money):
    from apps.business.core.templatetags.business import bdt
    from apps.business.feed.models import FeedPurchase

    items = []
    for p in FeedPurchase.objects.filter(business=business, date__gte=start, date__lte=end).select_related("supplier"):
        items.append(Item(p.date, "feed", _("Feed bought · %(who)s") % {"who": p.supplier},
                          bdt(p.total) if money else "", reverse("business:feed_purchases_edit", args=[p.pk]), "", "truck"))
    return items


def due_items(business, start, end, today):
    """Loan instalments, regular bills and baki follow-ups: money matters."""
    from apps.business.core.templatetags.business import bdt

    items = []
    if _installed("loans"):
        from apps.business.loans.services import loans_for

        for loan in loans_for(business, closed=False):
            for p in loan.schedule(today).periods:
                if start <= p.due <= end and p.status != "paid":
                    items.append(Item(p.due, "due", _("Loan instalment · %(loan)s") % {"loan": loan.title}, bdt(p.remaining),
                                      reverse("business:loan_detail", args=[loan.pk]), "critical" if p.status == "overdue" else "warn", "banknotes"))
    if _installed("finance"):
        from apps.business.finance.models import RecurringTransaction
        from apps.business.finance.services import next_date

        for r in RecurringTransaction.objects.filter(business=business, next_due__isnull=False, next_due__lte=end):
            d, guard = r.next_due, 0
            while d <= end and guard < 400 and not (r.end_date and d > r.end_date):
                if d >= start:
                    items.append(Item(d, "due", _("%(name)s due") % {"name": r.name}, bdt(r.amount),
                                      reverse("business:recurring"), "critical" if d < today else "warn", "repeat"))
                d, guard = next_date(d, r.repeat), guard + 1
    if _installed("parties"):
        from apps.business.parties.models import Party

        for p in Party.objects.filter(business=business, follow_up_on__gte=start, follow_up_on__lte=end):
            items.append(Item(p.follow_up_on, "due", _("Follow up · %(name)s") % {"name": p.name}, p.follow_up_note,
                              reverse("business:party_statement", args=[p.pk]), "warn", "bell"))
    return items


# Bangladesh's fixed-date national days, and Bangla-calendar festivals. Days
# that move with the moon (the Eids, Durga Puja…) differ each year, so the
# farm adds those itself.
NATIONAL_DAYS = [
    (2, 21, "Shaheed Day & International Mother Language Day"),
    (3, 26, "Independence Day"),
    (5, 1, "May Day"),
    (12, 16, "Victory Day"),
    (12, 25, "Christmas"),
]
BANGLA_FESTIVALS = [
    (1, 1, "Pohela Boishakh (Bangla New Year)"),
    (11, 1, "Pohela Falgun (first day of spring)"),
    (8, 1, "Nobanno (harvest festival)"),
]


def holiday_items(start, end):
    names = {
        "Shaheed Day & International Mother Language Day": _("Shaheed Day & International Mother Language Day"),
        "Independence Day": _("Independence Day"), "May Day": _("May Day"), "Victory Day": _("Victory Day"),
        "Christmas": _("Christmas"), "Pohela Boishakh (Bangla New Year)": _("Pohela Boishakh (Bangla New Year)"),
        "Pohela Falgun (first day of spring)": _("Pohela Falgun (first day of spring)"),
        "Nobanno (harvest festival)": _("Nobanno (harvest festival)"),
    }
    items = []
    for year in range(start.year, end.year + 1):
        for m, d, name in NATIONAL_DAYS:
            day = date(year, m, d)
            if start <= day <= end:
                items.append(Item(day, "holiday", names[name], tone="critical", icon="flag"))
    for byear in range(to_bangla(start).year, to_bangla(end).year + 1):
        for m, d, name in BANGLA_FESTIVALS:
            day = from_bangla(byear, m, d)
            if start <= day <= end:
                items.append(Item(day, "holiday", names[name], tone="critical", icon="flag"))
    return items


def collect(business, start, end, money=False, today=None):
    """Every item between start and end, soonest first."""
    today = today or date.today()
    items = farm_events(business, start, end) + holiday_items(start, end)
    if _installed("ponds"):
        items += pond_items(business, start, end)
    if _installed("sales"):
        items += sale_items(business, start, end, money)
    if _installed("feed"):
        items += feed_items(business, start, end, money)
    if money:
        items += due_items(business, start, end, today)
    order = {k: i for i, k in enumerate(KINDS)}
    items.sort(key=lambda i: (i.date, i.time or "99", order[i.kind], i.title))
    return items


def todays_events(business, today=None):
    """The farm's own events for today, and unfinished to-dos from the last month."""
    today = today or date.today()
    items = [i for i in farm_events(business, today - timedelta(days=30), today)
             if not i.done and (i.date == today or (i.task and not i.repeat))]
    return items


def fmt_day(d, bangla):
    """'29' or '২৯'."""
    return bn_digits(d.day) if bangla else str(d.day)
