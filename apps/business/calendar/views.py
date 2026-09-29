"""The farm calendar: English and Bangla months, the farm's own events, and
everything else that happens on a date."""
import calendar as pycal
import hashlib
from collections import defaultdict
from datetime import date, timedelta

from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.utils.translation import get_language, gettext as _
from django.views.decorators.http import require_POST

from apps.business.core.access import can
from apps.business.core.decorators import business_access_required

from . import bangla as bn
from .forms import EventForm
from .models import Category, CalendarEvent
from .services import KINDS, collect

WEEK_STARTS = {"sat": 5, "sun": 6, "mon": 0}      # date.weekday() of the first column
WEEKEND = (4, 5)                                  # Friday and Saturday, Bangladesh's weekend
EN_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
EN_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _parse(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _int(value, low, high):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if low <= n <= high else None


class Labels:
    """Month, weekday and day names in the language the app is shown in."""

    def __init__(self, bangla):
        self.bangla = bangla

    def n(self, value):
        return bn.bn_digits(value) if self.bangla else str(value)

    def en_month(self, m):
        return bn.GREGORIAN_BN[m - 1] if self.bangla else EN_MONTHS[m - 1]

    def bn_month(self, m):
        return bn.MONTHS_BN[m - 1] if self.bangla else bn.MONTHS_EN[m - 1]

    def weekday(self, d, short=False):
        if self.bangla:
            return (bn.WEEKDAYS_BN_SHORT if short else bn.WEEKDAYS_BN)[d.weekday()]
        name = EN_WEEKDAYS[d.weekday()]
        return name[:3] if short else name

    def english(self, d, year=True):
        return f"{self.n(d.day)} {self.en_month(d.month)}" + (f" {self.n(d.year)}" if year else "")

    def banglad(self, d, year=True):
        b = bn.to_bangla(d)
        return f"{self.n(b.day)} {self.bn_month(b.month)}" + (f" {self.n(b.year)}" if year else "")

    def season(self, d):
        b = bn.to_bangla(d)
        if self.bangla:
            return b.season_name(True) + "কাল"
        return f"{b.season_name(False)} ({['Grishmo', 'Borsha', 'Shorot', 'Hemonto', 'Sheet', 'Boshonto'][b.season]})"


def _month(cal, y, m):
    """(first, last) day of month m of year y in the chosen calendar."""
    if cal == "bn":
        return bn.month_bounds(y, m)
    return date(y, m, 1), date(y, m, pycal.monthrange(y, m)[1])


def _shift(cal, y, m, n):
    if cal == "bn":
        return bn.add_bangla_months(y, m, n)
    total = y * 12 + m - 1 + n
    return total // 12, total % 12 + 1


def _grid(first, last, ws):
    """Whole weeks around first..last, starting on weekday ws."""
    return first - timedelta(days=(first.weekday() - ws) % 7), last + timedelta(days=6 - (last.weekday() - ws) % 7)


def _weeks(first, last, ws, cal, labels, by_day, holidays, today):
    """Rows of day cells for one month, with both dates in each."""
    grid_start, grid_end = _grid(first, last, ws)
    weeks, d = [], grid_start
    while d <= grid_end:
        row = []
        for _i in range(7):
            bd = bn.to_bangla(d)
            show_month = d == grid_start or (bd.day == 1 if cal == "en" else d.day == 1)
            if cal == "en":
                primary, second = labels.n(d.day), (labels.banglad(d, year=False) if show_month else labels.n(bd.day))
            else:
                primary, second = labels.n(bd.day), (labels.english(d, year=False) if show_month else labels.n(d.day))
            row.append({
                "date": d, "iso": d.isoformat(), "primary": primary, "second": second, "second_start": show_month,
                "in_month": first <= d <= last, "today": d == today, "weekend": d.weekday() in WEEKEND,
                "holiday": d in holidays, "busy": bool(by_day.get(d)),
                "aria": f"{labels.weekday(d)}, {labels.english(d)}, {labels.banglad(d)}",
            })
            d += timedelta(days=1)
        weeks.append(row)
    return weeks


def _titles(cal, y, m, first, last, labels):
    """("September 2026", "Bhadro – Ashwin 1433") for a month in the chosen calendar."""
    if cal == "bn":
        other = (f"{labels.en_month(first.month)} – {labels.en_month(last.month)} {labels.n(last.year)}" if first.month != last.month
                 else f"{labels.en_month(first.month)} {labels.n(first.year)}")
        return f"{labels.bn_month(m)} {labels.n(y)}", other
    fb, lb = bn.to_bangla(first), bn.to_bangla(last)
    return f"{labels.en_month(m)} {labels.n(y)}", f"{labels.bn_month(fb.month)} – {labels.bn_month(lb.month)} {labels.n(lb.year)}"


@business_access_required
def calendar_view(request):
    b = request.business
    today = date.today()
    labels = Labels((get_language() or "").startswith("bn"))
    session = request.session

    cal = request.GET.get("cal") or session.get("cal_primary") or ("bn" if labels.bangla else "en")
    cal = cal if cal in ("en", "bn") else "en"
    week = request.GET.get("week") or session.get("cal_week") or "sat"
    week = week if week in WEEK_STARTS else "sat"
    view = request.GET.get("view") or session.get("cal_view") or "month"
    view = view if view in ("month", "agenda", "year") else "month"
    session["cal_primary"], session["cal_week"], session["cal_view"] = cal, week, view
    ws = WEEK_STARTS[week]

    picked = _parse(request.GET.get("day"))
    anchor = picked or today
    if cal == "bn":
        y = _int(request.GET.get("y"), 1300, 1600) or bn.to_bangla(anchor).year
        m = _int(request.GET.get("m"), 1, 12) or bn.to_bangla(anchor).month
    else:
        y = _int(request.GET.get("y"), 1900, 2200) or anchor.year
        m = _int(request.GET.get("m"), 1, 12) or anchor.month
    if view == "year":
        first, last = _month(cal, y, 1)[0], _month(cal, y, 12)[1]
    else:
        first, last = _month(cal, y, m)
    if picked and first <= picked <= last:
        selected = picked
    else:
        selected = today if first <= today <= last else first

    grid_start, grid_end = _grid(first, last, ws)
    money = can(request.membership, "view_finance")
    items = collect(b, grid_start, grid_end, money=money, today=today)
    by_day = defaultdict(list)
    for item in items:
        by_day[item.date].append(item)
    holidays = {i.date for i in items if i.kind == "holiday"}

    def url(**params):
        base = {"cal": cal, "view": view}
        base.update(params)
        return reverse("business:calendar") + "?" + urlencode({k: v for k, v in base.items() if v is not None})

    days, weeks, minis = {}, [], []
    if view == "year":
        for month in range(1, 13):
            mf, ml = _month(cal, y, month)
            t, o = _titles(cal, y, month, mf, ml, labels)
            minis.append({"title": t, "other": o, "weeks": _weeks(mf, ml, ws, cal, labels, by_day, holidays, today),
                          "url": url(view="month", y=y, m=month), "current": mf <= today <= ml})
        if cal == "bn":
            title = f"{labels.n(y)} বঙ্গাব্দ" if labels.bangla else f"{y} Bangabda"
            other = f"{labels.n(first.year)}–{labels.n(last.year)}"
        else:
            title = labels.n(y)
            fy, ly = bn.to_bangla(first).year, bn.to_bangla(last).year
            other = f"{labels.n(fy)}–{labels.n(ly)} বঙ্গাব্দ" if labels.bangla else f"Bangabda {fy}–{ly}"
        season = ""
        prev_url, next_url = url(y=y - 1), url(y=y + 1)
    else:
        weeks = _weeks(first, last, ws, cal, labels, by_day, holidays, today)
        d = grid_start
        while d <= grid_end:
            if labels.bangla:
                head, sub = f"{labels.weekday(d)}, {labels.banglad(d)}", f"{labels.english(d)} · {labels.season(d)}"
            else:
                head, sub = f"{labels.weekday(d)}, {labels.english(d)}", f"{labels.banglad(d)} · {labels.season(d)}"
            days[d.isoformat()] = {"head": head, "sub": sub}
            d += timedelta(days=1)
        title, other = _titles(cal, y, m, first, last, labels)
        season = labels.season(first + (last - first) / 2)
        py, pm = _shift(cal, y, m, -1)
        ny, nm = _shift(cal, y, m, 1)
        prev_url, next_url = url(y=py, m=pm), url(y=ny, m=nm)

    in_range = [i for i in items if first <= i.date <= last]
    counts = {k: sum(1 for i in in_range if i.kind == k) for k in KINDS}
    agenda = [(day, by_day[day]) for day in sorted(by_day) if first <= day <= last]
    header_days = [grid_start + timedelta(days=i) for i in range(7)]
    return render(request, "business/calendar/calendar.html", {
        "cal": cal, "view": view, "week": week, "title": title, "other": other, "season": season,
        "weeks": weeks, "minis": minis, "weekdays": [{"short": labels.weekday(x, short=True), "weekend": x.weekday() in WEEKEND} for x in header_days],
        "selected": selected.isoformat(), "today_iso": today.isoformat(),
        "items_json": {k.isoformat(): [i.as_json() for i in v] for k, v in by_day.items()},
        "days_json": days, "counts": counts, "kinds": KINDS, "agenda": agenda, "days": days,
        "prev_url": prev_url, "next_url": next_url, "today_url": url(day=today.isoformat(), view="month" if view == "year" else view),
        "month_url": reverse("business:calendar") + "?" + urlencode({"cal": cal, "view": "month"}),
        "cal_urls": {c: reverse("business:calendar") + "?" + urlencode({"cal": c, "view": view, "day": selected.isoformat()}) for c in ("en", "bn")},
        "view_urls": {v: url(view=v, y=y, m=m) if v != "year" else url(view=v, y=y) for v in ("month", "agenda", "year")},
        "week_urls": {k: url(week=k, y=y, m=m) for k in WEEK_STARTS},
        "categories": Category.choices, "money": money,
        "filters": [{"key": k, "label": label, "count": counts[k]} for k, label in _kind_labels().items() if k != "due" or money],
        "kind_labels": _kind_labels(),
        "months_bn": [labels.bn_month(i) for i in range(1, 13)],
        "form": EventForm(business=b, initial={"date": selected}),
        "labels_bangla": labels.bangla,
    })


def _kind_labels():
    return {"mine": _("My events"), "pond": _("Ponds"), "sale": _("Sales"), "feed": _("Feed bought"),
            "due": _("Money due"), "holiday": _("Holidays")}


# ── The farm's own events ───────────────────────────────────────────────────

def _back(request, event_date=None):
    nxt = request.POST.get("next") or request.GET.get("next")
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return nxt
    return reverse("business:calendar") + (f"?day={event_date.isoformat()}" if event_date else "")


@business_access_required(capability="enter_data")
def event_form_view(request, pk=None):
    b = request.business
    obj = get_object_or_404(CalendarEvent, pk=pk, business=b) if pk else None
    initial = {}
    if not obj:
        initial["date"] = _parse(request.GET.get("date")) or date.today()
        if request.GET.get("category") in Category.values:
            initial["category"] = request.GET["category"]
    form = EventForm(request.POST or None, instance=obj, business=b, initial=initial)
    if request.method == "POST" and form.is_valid():
        event = form.save(commit=False)
        event.business = b
        event.save()
        messages.success(request, _("Saved to the calendar."))
        return redirect(_back(request, event.date))
    return render(request, "business/calendar/event_form.html", {"form": form, "obj": obj, "back": _back(request, obj.date if obj else None)})


@business_access_required(capability="enter_data")
@require_POST
def event_done_view(request, pk):
    event = get_object_or_404(CalendarEvent, pk=pk, business=request.business)
    event.done = not event.done
    event.save(update_fields=["done", "updated_at", "updated_by"])
    if request.headers.get("x-requested-with") == "fetch":
        return JsonResponse({"done": event.done})
    return redirect(_back(request, event.date))


@business_access_required(capability="delete")
@require_POST
def event_delete_view(request, pk):
    event = get_object_or_404(CalendarEvent, pk=pk, business=request.business)
    event.soft_delete()
    messages.success(request, _("Removed from the calendar."))
    return redirect(_back(request, event.date))


# ── For Google Calendar and phones ──────────────────────────────────────────

def _ics_text(value):
    return str(value).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line):
    """Calendar files want lines of at most 75 bytes; longer ones continue with a space."""
    out, part = [], ""
    for ch in line:
        if len((part + ch).encode()) > 73:
            out.append(part)
            part = " "
        part += ch
    out.append(part)
    return "\r\n".join(out)


@business_access_required
def calendar_ics_view(request):
    """The next year of the farm's events (and money due, for people who may see it), for other calendar apps."""
    b = request.business
    today = date.today()
    money = can(request.membership, "view_finance")
    items = [i for i in collect(b, today - timedelta(days=30), today + timedelta(days=365), money=money, today=today)
             if i.kind in ("mine", "due", "holiday") or (i.kind == "pond" and i.date >= today)]
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//FinTrack//Farm calendar//EN", "CALSCALE:GREGORIAN",
             f"X-WR-CALNAME:{_ics_text(b.name)}"]
    stamp = today.strftime("%Y%m%dT000000Z")
    for i in items:
        uid = hashlib.sha1(f"{b.pk}|{i.kind}|{i.pk}|{i.date}|{i.title}".encode()).hexdigest()
        lines += ["BEGIN:VEVENT", f"UID:{uid}@fintrack", f"DTSTAMP:{stamp}"]
        if i.time:
            lines.append(f"DTSTART:{i.date:%Y%m%d}T{i.time.replace(':', '')}00")
        else:
            lines += [f"DTSTART;VALUE=DATE:{i.date:%Y%m%d}", f"DTEND;VALUE=DATE:{i.date + timedelta(days=1):%Y%m%d}"]
        lines.append(_fold(f"SUMMARY:{_ics_text(i.title)}"))
        detail = " · ".join(x for x in (i.detail, bn.to_bangla(i.date).format(bangla=False)) if x)
        lines.append(_fold(f"DESCRIPTION:{_ics_text(detail)}"))
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    response = HttpResponse("\r\n".join(lines) + "\r\n", content_type="text/calendar; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="farm-calendar.ics"'
    return response
