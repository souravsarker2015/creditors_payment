"""The dashboard: how a stretch of days went, every part of the app at once — time, focus, tasks, reading, practice
(flashcards and exam questions), habits, notes, mood — each beside the same number of days before, with what stands
out said in plain words and a few next steps. The same figures make the progress email (emails.send_progress).

Made for a glance: the numbers that matter, a trend line each, the days you were active (consistency beats
intensity), streaks, and never more than three suggestions."""
from collections import defaultdict
from datetime import timedelta

from django.db.models import Avg
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import gettext as _, ngettext

from . import reading, services
from .models import (CardReview, ExamNote, Habit, JournalEntry, Note, ReadingDay, ReadingProgress, Status, Task, TimeEntry,
                     WorkSettings)

PERIODS = (7, 30, 90)
EMAIL_EVERY = timedelta(days=3)


def hm(seconds):
    """1h 05m, 25m, 0m."""
    m = int(round((seconds or 0) / 60))
    return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{m}m"


def _span(start, end):
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def collect(user, start, end):
    """Everything counted between two days (both included), as totals and one value a day."""
    days = _span(start, end)
    lo, hi = services.day_bounds(start)[0], services.day_bounds(end)[1]
    tracked, focus, sessions = defaultdict(int), defaultdict(int), defaultdict(int)
    projects = defaultdict(int)
    for e in TimeEntry.objects.filter(owner=user, started_at__gte=lo, started_at__lt=hi, ended_at__isnull=False).select_related("project"):
        d = timezone.localtime(e.started_at).date()
        tracked[d] += e.seconds
        if e.kind == "focus":
            focus[d] += e.seconds
            sessions[d] += 1
        projects[e.project.name if e.project else _("No project")] += e.seconds
    done = defaultdict(int)
    for at in Task.objects.filter(owner=user, status=Status.DONE, completed_at__gte=lo, completed_at__lt=hi).values_list("completed_at", flat=True):
        done[timezone.localtime(at).date()] += 1
    read = dict(ReadingDay.objects.filter(owner=user, day__gte=start, day__lte=end).values_list("day", "seconds"))
    practice = defaultdict(int)
    answers = CardReview.objects.filter(owner=user, reviewed_at__gte=lo, reviewed_at__lt=hi)
    for at in answers.values_list("reviewed_at", flat=True):
        practice[timezone.localtime(at).date()] += 1
    for at in ExamNote.objects.filter(owner=user, reviewed_at__gte=lo, reviewed_at__lt=hi).values_list("reviewed_at", flat=True):
        practice[timezone.localtime(at).date()] += 1
    n_answers = answers.count()
    remembered = round(100 * answers.filter(rating__gt=1).count() / n_answers) if n_answers else None
    notes = defaultdict(int)
    for at in Note.objects.filter(owner=user, is_template=False, updated_at__gte=lo, updated_at__lt=hi).values_list("updated_at", flat=True):
        notes[timezone.localtime(at).date()] += 1
    feel = JournalEntry.objects.filter(owner=user, date__gte=start, date__lte=end).aggregate(mood=Avg("mood"), energy=Avg("energy"))
    rates, today = [], timezone.localdate()
    for h in Habit.objects.filter(owner=user, is_archived=False):
        checked = services.habit_done_days(h, h.checks.filter(date__gte=start, date__lte=end).values_list("date", "amount"))
        span = [d for d in days if d >= h.created_at.date() and (d < today or d in checked)]
        if [d for d in span if h.is_due(d)]:
            rates.append(services.habit_rate(h, checked, span))
    active = [d for d in days if tracked[d] or done[d] or read.get(d) or practice[d] or notes[d]]
    return {
        "start": start, "end": end, "days": days, "n_days": len(days),
        "tracked": sum(tracked.values()), "focus": sum(focus.values()), "sessions": sum(sessions.values()),
        "done": sum(done.values()), "read": sum(read.values()), "practice": sum(practice.values()), "remembered": remembered,
        "notes": sum(notes.values()), "mood": feel["mood"], "energy": feel["energy"],
        "habits": round(sum(rates) / len(rates)) if rates else None, "active": len(active),
        "chapters": ReadingProgress.objects.filter(owner=user, done=True, done_at__gte=lo, done_at__lt=hi).count(),
        "created": Task.objects.filter(owner=user, created_at__gte=lo, created_at__lt=hi).count(),
        "series": {"tracked": [tracked[d] for d in days], "focus": [focus[d] for d in days], "done": [done[d] for d in days],
                   "read": [read.get(d, 0) for d in days], "practice": [practice[d] for d in days], "notes": [notes[d] for d in days]},
        "projects": sorted(projects.items(), key=lambda kv: -kv[1])[:5],
    }


def _delta(now, before):
    """+25 % / −10 % / new / None (nothing either time)."""
    if now is None or before is None:
        return None
    if not before:
        return {"pct": None, "up": now > 0, "text": _("new") if now else ""} if now else None
    pct = round(100 * (now - before) / before)
    return {"pct": pct, "up": pct >= 0, "text": ("+" if pct >= 0 else "−") + f"{abs(pct)}%"}


def _spark(values, w=96, h=28):
    """An SVG polyline's points for a small trend line."""
    if not values or not any(values):
        return ""
    top, n = max(values) or 1, len(values)
    step = w / max(1, n - 1)
    return " ".join(f"{round(i * step, 1)},{round(h - 2 - (v / top) * (h - 4), 1)}" for i, v in enumerate(values))


def report(user, days=7, end=None):
    """The figures for the last `days` days (ending `end`, today by default) and the same number of days before."""
    end = end or timezone.localdate()
    start = end - timedelta(days=days - 1)
    now = collect(user, start, end)
    was = collect(user, start - timedelta(days=days), start - timedelta(days=1))
    s = WorkSettings.for_user(user)
    stats = reading.day_stats(user)
    urls = {k: reverse(v) for k, v in (("time", "work:time"), ("focus", "work:focus"), ("tasks", "work:tasks"), ("notes", "work:notes"),
                                         ("habits", "work:habits"), ("cards", "work:card_review"), ("exam", "work:exam"), ("journal", "work:journal"),
                                         ("reports", "work:reports"))}
    s_ = now["series"]
    kpis = [
        {"key": "tracked", "icon": "⏱️", "label": _("Time tracked"), "value": hm(now["tracked"]), "delta": _delta(now["tracked"], was["tracked"]),
         "spark": _spark(s_["tracked"]), "url": urls["time"]},
        {"key": "focus", "icon": "🍅", "label": _("Focus"), "value": hm(now["focus"]),
         "sub": ngettext("%(n)s session", "%(n)s sessions", now["sessions"]) % {"n": now["sessions"]},
         "delta": _delta(now["focus"], was["focus"]), "spark": _spark(s_["focus"]), "url": urls["focus"]},
        {"key": "done", "icon": "✅", "label": _("Tasks done"), "value": now["done"],
         "sub": ngettext("%(n)s added", "%(n)s added", now["created"]) % {"n": now["created"]},
         "delta": _delta(now["done"], was["done"]), "spark": _spark(s_["done"]), "url": urls["tasks"]},
        {"key": "read", "icon": "📖", "label": _("Reading"), "value": hm(now["read"]),
         "sub": ngettext("%(n)s chapter finished", "%(n)s chapters finished", now["chapters"]) % {"n": now["chapters"]},
         "delta": _delta(now["read"], was["read"]), "spark": _spark(s_["read"]), "url": urls["notes"]},
        {"key": "practice", "icon": "🧠", "label": _("Practice"), "value": now["practice"],
         "sub": (_("%(n)s%% remembered") % {"n": now["remembered"]}) if now["remembered"] is not None else _("flashcards and exam questions"),
         "delta": _delta(now["practice"], was["practice"]), "spark": _spark(s_["practice"]), "url": urls["cards"]},
        {"key": "habits", "icon": "🔁", "label": _("Habits kept"), "value": f"{now['habits']}%" if now["habits"] is not None else "—",
         "sub": "" if now["habits"] is not None else _("no habits due"),
         "delta": _delta(now["habits"], was["habits"]), "spark": "", "url": urls["habits"]},
        {"key": "notes", "icon": "📝", "label": _("Notes written"), "value": now["notes"], "delta": _delta(now["notes"], was["notes"]),
         "spark": _spark(s_["notes"]), "url": urls["notes"]},
        {"key": "mood", "icon": "🙂", "label": _("Mood"), "value": f"{now['mood']:.1f} / 5" if now["mood"] else "—",
         "sub": (_("energy %(n)s / 5") % {"n": f"{now['energy']:.1f}"}) if now["energy"] else _("from your journal"),
         "delta": _delta(now["mood"], was["mood"]), "spark": "", "url": urls["journal"]},
    ]
    # the days, one bar each: focus, the rest of the time tracked, reading (minutes)
    peak = max([(a + r) for a, r in zip(s_["tracked"], s_["read"])] + [1])
    bars = [{"day": d, "label": date_format(d, "D j" if days <= 31 else "j M"), "short": date_format(d, "D")[:2] if days <= 7 else date_format(d, "j"),
             "focus": round(100 * f / peak, 1), "other": round(100 * (t - f) / peak, 1), "read": round(100 * r / peak, 1),
             "title": f"{date_format(d, 'D j M')}: {hm(t)} " + _("tracked") + (f", {hm(f)} " + _("focus") if f else "") + (f", {hm(r)} " + _("reading") if r else ""),
             "done": dn, "today": d == timezone.localdate()}
            for d, t, f, r, dn in zip(now["days"], s_["tracked"], s_["focus"], s_["read"], s_["done"])]
    best = max(bars, key=lambda b: b["focus"] + b["other"] + b["read"]) if any(b["focus"] + b["other"] + b["read"] for b in bars) else None
    late = Task.objects.filter(owner=user, due_date__lt=timezone.localdate()).exclude(status=Status.DONE).count()
    streaks = [
        {"icon": "📖", "label": _("Reading"), "n": stats["streak"]},
        {"icon": "🍅", "label": _("Focus goal"), "n": services.focus_goal_streak(user, s.focus_goal, timezone.localdate())},
        {"icon": "✅", "label": _("Task goal"), "n": services.task_goal_streak(user, s.task_goal, timezone.localdate())},
    ]
    return {
        "days": days, "start": start, "end": end, "now": now, "was": was, "kpis": kpis, "bars": bars, "best": best, "late": late,
        "streaks": streaks, "heat": heatmap(user, end), "projects": [{"name": n, "time": hm(v), "pct": round(100 * v / now["tracked"]) if now["tracked"] else 0}
                                                                    for n, v in now["projects"]],
        "highlights": highlights(now, was, best, days), "tips": tips(user, now, late, s, stats), "consistency": round(100 * now["active"] / now["n_days"]),
    }


def heatmap(user, end, weeks=12):
    """The last few weeks, a square a day, darker the more was done (minutes tracked and read, tasks done) — weeks as columns."""
    start = end - timedelta(days=weeks * 7 - 1)
    start -= timedelta(days=start.weekday())                     # columns start on a Monday
    c = collect(user, start, end)
    score = [t / 60 + r / 60 + dn * 15 + p for t, r, dn, p in zip(c["series"]["tracked"], c["series"]["read"], c["series"]["done"], c["series"]["practice"])]
    top = max(score + [1])
    cells = [{"day": d, "level": 0 if not v else min(4, 1 + int(3.999 * v / top)), "title": f"{date_format(d, 'D j M')}"} for d, v in zip(c["days"], score)]
    return [cells[i:i + 7] for i in range(0, len(cells), 7)]


def highlights(now, was, best, days):
    """What stands out, said plainly (the first is the headline)."""
    out = []
    if now["tracked"] or now["read"] or now["done"]:
        more = now["tracked"] - was["tracked"]
        if now["tracked"]:
            out.append(("⏱️", (_("You tracked %(time)s — %(diff)s more than the %(n)s days before.") if more >= 0 else
                              _("You tracked %(time)s — %(diff)s less than the %(n)s days before.")) % {"time": hm(now["tracked"]), "diff": hm(abs(more)), "n": days}))
        if now["done"]:
            out.append(("✅", ngettext("%(n)s task done.", "%(n)s tasks done.", now["done"]) % {"n": now["done"]}))
        if now["read"]:
            out.append(("📖", ngettext("%(time)s of reading, %(n)s chapter finished.", "%(time)s of reading, %(n)s chapters finished.", now["chapters"])
                        % {"time": hm(now["read"]), "n": now["chapters"]}))
        if best:
            out.append(("🏆", _("Best day: %(day)s.") % {"day": date_format(best["day"], "l, j F")}))
    out.append(("📅", _("Active on %(a)s of %(n)s days.") % {"a": now["active"], "n": now["n_days"]}))
    return out


def tips(user, now, late, s, stats):
    """At most three next steps, the most useful first."""
    out = []
    if late:
        out.append(ngettext("%(n)s task is late: do it first, or give it a new date.", "%(n)s tasks are late: do one first, or give them new dates.", late) % {"n": late})
    if not now["read"]:
        out.append(_("Read for %(n)s minutes today — open Continue reading on Notes. Small and daily beats long and rare.") % {"n": stats["goal"] or 10})
    if s.focus_goal and now["sessions"] < s.focus_goal * now["n_days"] / 3:
        out.append(_("Try two focus sessions before noon: the morning is when attention is freshest."))
    if now["active"] < now["n_days"] / 2:
        out.append(_("Aim for a little every day — consistency matters more than long days."))
    if now["habits"] is not None and now["habits"] < 50:
        out.append(_("A habit that keeps slipping is too big: make it smaller (2 minutes) until it sticks."))
    if not now["practice"] and (ExamNote.objects.filter(owner=user).exists() or CardReview.objects.filter(owner=user).exists()):
        out.append(_("Revise a few flashcards or exam questions — recalling is what makes things stay."))
    if not out:
        out.append(_("A good stretch. Keep the same rhythm, and plan tomorrow before you stop today."))
    return out[:3]
