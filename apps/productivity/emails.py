"""Productivity emails, for when the app isn't open:

- "Your day", once each work day when the work day starts: what's late and due,
  the day's plan, today's reminders, habits and flashcards waiting.
- Task reminders: a task whose "Remind me" time has come is emailed once — the
  browser only shows a reminder while the app is open.

Both are opt-in (Timer, focus & sounds → Emails). PythonAnywhere has no
always-on worker, so `manage.py send_work_emails` runs them from a scheduled
task; run it every hour (or more often, for reminders closer to their time).
Running it again sends nothing twice.
"""
import logging
from dataclasses import dataclass, field
from datetime import timedelta

from django.core.mail import EmailMultiAlternatives
from django.db.models import F, Q
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.formats import date_format
from django.utils.translation import gettext as _, ngettext

from . import cards, services
from .models import Deck, JournalEntry, Status, Task, WorkSettings

log = logging.getLogger(__name__)

REMINDER_GRACE = timedelta(hours=3)   # a reminder older than this when the job runs is not sent any more


def _language(user):
    from apps.accounts.models import UserProfile

    return UserProfile.objects.filter(user=user).values_list("language", flat=True).first() or "en"


def _base(request=None):
    from apps.business.core.summary import site_url

    return site_url(request)


def _send(user, subject, txt, html, ctx):
    msg = EmailMultiAlternatives(subject, render_to_string(txt, ctx), None, [user.email])
    msg.attach_alternative(render_to_string(html, ctx), "text/html")
    try:
        msg.send()
    except Exception:  # noqa: BLE001 — a mail outage must never stop the others
        log.exception("work email to user %s", user.pk)
        return False
    return True


# ── Your day ────────────────────────────────────────────────────────────────
@dataclass
class Brief:
    user: object
    today: object
    late: list = field(default_factory=list)
    today_tasks: list = field(default_factory=list)
    plan: list = field(default_factory=list)          # tasks with a time on today's timeline
    reminders: list = field(default_factory=list)
    habits: list = field(default_factory=list)
    cards_due: int = 0
    note: str = ""                                    # "Plan for the day" from the journal

    @property
    def worth_sending(self):
        return bool(self.late or self.today_tasks or self.plan or self.reminders or self.habits or self.cards_due or self.note)

    def headline(self):
        parts = []
        if self.late:
            parts.append(ngettext("%(n)s late", "%(n)s late", len(self.late)) % {"n": len(self.late)})
        if self.today_tasks:
            parts.append(ngettext("%(n)s task today", "%(n)s tasks today", len(self.today_tasks)) % {"n": len(self.today_tasks)})
        if self.plan:
            parts.append(ngettext("%(n)s planned block", "%(n)s planned blocks", len(self.plan)) % {"n": len(self.plan)})
        if self.cards_due:
            parts.append(ngettext("%(n)s flashcard", "%(n)s flashcards", self.cards_due) % {"n": self.cards_due})
        return " · ".join(parts) or _("A clear day")


def brief(user, today=None):
    today = today or timezone.localdate()
    open_tasks, _done = services.today_tasks(user, today)
    lo, hi = services.day_bounds(today)
    b = Brief(user=user, today=today)
    b.late = [t for t in open_tasks if t.due_date and t.due_date < today][:15]
    b.today_tasks = [t for t in open_tasks if not (t.due_date and t.due_date < today)][:20]
    b.plan = list(Task.objects.filter(owner=user, scheduled_at__gte=lo, scheduled_at__lt=hi).exclude(status=Status.DONE)
                  .select_related("project").order_by("scheduled_at")[:15])
    b.reminders = list(Task.objects.filter(owner=user, remind_at__gte=lo, remind_at__lt=hi).exclude(status=Status.DONE).order_by("remind_at")[:10])
    rows, _span = services.habit_rows(user, today, days=1)
    b.habits = [r["habit"] for r in rows if r["due_today"] and not r["done_today"]]
    if Deck.objects.filter(owner=user, is_archived=False).exists():
        b.cards_due = cards.due_count(user, today)
    b.note = (JournalEntry.objects.filter(owner=user, date=today).values_list("plan", flat=True).first() or "").strip()
    return b


def send_brief(user, today=None, request=None, force=False):
    """Email one person their day. Returns "sent", "nothing" or "failed"."""
    today = today or timezone.localdate()
    s = WorkSettings.for_user(user)
    if not user.email:
        return "failed"
    with translation.override(_language(user)):
        b = brief(user, today)
        if not (b.worth_sending or force):
            WorkSettings.objects.filter(pk=s.pk).update(daily_email_sent_on=today)
            return "nothing"
        base = _base(request)
        ctx = {"b": b, "user": user, "base": base, "today_url": reverse("work:today"), "review_url": reverse("work:card_review"),
               "settings_url": reverse("work:settings")}
        subject = _("Your day, %(date)s: %(headline)s") % {"date": date_format(today, "D j M"), "headline": b.headline()}
        sent = _send(user, subject, "work/email/brief.txt", "work/email/brief.html", ctx)
    if not sent:
        return "failed"
    WorkSettings.objects.filter(pk=s.pk).update(daily_email_sent_on=today)
    return "sent"


def briefs_due(now=None):
    """People whose "Your day" should go now: turned on, a work day, their day has started, not sent yet today."""
    now = timezone.localtime(now)
    today = now.date()
    out = []
    for s in (WorkSettings.objects.filter(daily_email=True, owner__is_active=True).exclude(owner__email="")
              .filter(Q(daily_email_sent_on__isnull=True) | Q(daily_email_sent_on__lt=today)).select_related("owner")):
        if s.is_work_day(today) and now.time() >= s.day_start:
            out.append(s.owner)
    return out


# ── Task reminders ──────────────────────────────────────────────────────────
def reminders_due(now=None):
    """{user: [tasks]} whose reminder time has come (in the last few hours) and that weren't emailed for it."""
    now = now or timezone.now()
    tasks = (Task.objects.filter(remind_at__lte=now, remind_at__gt=now - REMINDER_GRACE, owner__is_active=True,
                                 owner__work_settings__reminder_emails=True)
             .exclude(status=Status.DONE).exclude(owner__email="")
             .filter(Q(reminder_sent_at__isnull=True) | Q(reminder_sent_at__lt=F("remind_at")))
             .select_related("owner", "project").order_by("remind_at"))
    out = {}
    for t in tasks:
        out.setdefault(t.owner, []).append(t)
    return out


def send_reminders(user, tasks, request=None, now=None):
    now = now or timezone.now()
    with translation.override(_language(user)):
        base = _base(request)
        ctx = {"tasks": tasks, "user": user, "base": base, "settings_url": reverse("work:settings")}
        subject = (_("Reminder: %(title)s") % {"title": tasks[0].title} if len(tasks) == 1
                   else _("%(n)s reminders: %(title)s and more") % {"n": len(tasks), "title": tasks[0].title})
        sent = _send(user, subject[:200], "work/email/reminder.txt", "work/email/reminder.html", ctx)
    if sent:
        Task.objects.filter(pk__in=[t.pk for t in tasks]).update(reminder_sent_at=now)
    return sent


def run(now=None):
    """Everything due now. Returns counts for the command's report."""
    counts = {"briefs": 0, "quiet": 0, "reminders": 0, "failed": 0}
    for user in briefs_due(now):
        result = send_brief(user, timezone.localtime(now).date())
        counts["briefs" if result == "sent" else "quiet" if result == "nothing" else "failed"] += 1
    for user, tasks in reminders_due(now).items():
        if send_reminders(user, tasks, now=now):
            counts["reminders"] += len(tasks)
        else:
            counts["failed"] += 1
    return counts
