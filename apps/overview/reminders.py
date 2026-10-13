"""Morning money reminders: one email, early in the day, of the money that's
late and what's due in the next days — loans to pay back, money to collect,
shop dues, installments and regular bills — so nothing slips by unnoticed.

It goes only to people who turned it on (Upcoming money page), only once a
day, and only when there is something to say: a day with nothing late and
nothing due soon sends nothing. PythonAnywhere has no always-on worker, so it
goes out either from a scheduled task (`manage.py send_money_reminders`) or,
failing that, the first time the person opens Home after REMIND_HOUR.
"""
import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.formats import date_format
from django.utils.translation import gettext as _, ngettext

from apps.accounts.models import UserProfile

log = logging.getLogger(__name__)

REMIND_HOUR = 7      # local time; the scheduled task runs at this hour
AHEAD = 7            # days the email looks ahead
NEAR = 3             # something due within this many days is worth an email
ZERO = Decimal(0)
# Regular income and spending are written down by themselves on their day, so
# alone they're no reason to send an email — dues and installments are.
NEEDS_ACTION = ("due", "plan")


@dataclass
class Reminder:
    user: object
    today: date
    late: list = field(default_factory=list)
    due_today: list = field(default_factory=list)
    soon: list = field(default_factory=list)     # Day rows, tomorrow onwards
    short: tuple = None                          # (Day, amount short) or None
    now: Decimal = ZERO
    tracked: bool = False

    @property
    def worth_sending(self):
        near = [i for d in self.soon if d.offset <= NEAR for i in d.items]
        return any(i.kind in NEEDS_ACTION for i in self.late + self.due_today + near) or self.short is not None

    @property
    def to_pay(self):
        return -sum((i.amount for i in self.late + self.due_today if i.amount < 0), ZERO)

    @property
    def to_collect(self):
        return sum((i.amount for i in self.late + self.due_today if i.amount > 0), ZERO)

    @property
    def soon_count(self):
        return sum(len(d.items) for d in self.soon)

    def headline(self):
        parts = []
        if self.late:
            parts.append(ngettext("%(n)s late", "%(n)s late", len(self.late)) % {"n": len(self.late)})
        if self.due_today:
            parts.append(ngettext("%(n)s due today", "%(n)s due today", len(self.due_today)) % {"n": len(self.due_today)})
        if self.soon_count:
            parts.append(ngettext("%(n)s more this week", "%(n)s more this week", self.soon_count) % {"n": self.soon_count})
        if self.short:
            parts.append(_("money runs short on %(day)s") % {"day": date_format(self.short[0].date, "j M")})
        return " · ".join(parts) or _("Nothing due this week")


def build(user, today=None):
    from .upcoming import forecast

    today = today or timezone.localdate()
    f = forecast(user, today, AHEAD)
    r = Reminder(user=user, today=today, now=f.now, tracked=f.tracked, short=f.short)
    for d in f.days:
        if d.offset == 0:
            r.late = [i for i in d.items if i.late]
            r.due_today = [i for i in d.items if not i.late]
        else:
            r.soon.append(d)
    return r


def _language(user):
    return UserProfile.objects.filter(user=user).values_list("language", flat=True).first() or "en"


def send(user, today=None, request=None, force=False):
    """Email one person their reminder. Returns "sent", "nothing" (nothing
    late or due soon — no email) or "failed". `force` sends even then."""
    from apps.business.core.summary import site_url

    today = today or timezone.localdate()
    if not user.email:
        return "failed"
    with translation.override(_language(user)):
        r = build(user, today)
        if not (r.worth_sending or force):
            UserProfile.objects.filter(user=user).update(reminders_sent_on=today)
            return "nothing"
        ctx = {"r": r, "base": site_url(request), "page": reverse("upcoming"), "user": user}
        subject = _("FinTrack — %(date)s: %(headline)s") % {"date": date_format(today, "j M"), "headline": r.headline()}
        msg = EmailMultiAlternatives(subject, render_to_string("overview/email/reminders.txt", ctx), None, [user.email])
        msg.attach_alternative(render_to_string("overview/email/reminders.html", ctx), "text/html")
    try:
        msg.send()
    except Exception:  # noqa: BLE001 — a mail outage must never break a page
        log.exception("money reminder to user %s", user.pk)
        return "failed"
    UserProfile.objects.filter(user=user).update(reminders_sent_on=today)
    return "sent"


def due(now=None):
    """Whether this morning's reminders should have gone out by now."""
    now = now or timezone.localtime()
    return now.hour >= REMIND_HOUR


def pending(today=None):
    today = today or timezone.localdate()
    from django.db.models import Q

    return (get_user_model().objects.filter(is_active=True, profile__money_reminders=True).exclude(email="")
            .filter(Q(profile__reminders_sent_on__isnull=True) | Q(profile__reminders_sent_on__lt=today))
            .select_related("profile"))


def catch_up(request):
    """From a page visit: this person's reminder, if it's due and hasn't gone."""
    user = request.user
    profile = getattr(user, "profile", None)
    today = timezone.localdate()
    if profile is None or not profile.money_reminders or not user.email or not due():
        return None
    if profile.reminders_sent_on and profile.reminders_sent_on >= today:
        return None
    return send(user, today, request)
