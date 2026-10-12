"""The evening summary: what was recorded on the farm today, pond by pond,
who recorded it, and what needs doing — for an owner who wasn't there.

It is a page anyone in the business can open, and an email to the people who
ask for it. The email goes out from a scheduled task (`send_farm_summaries`)
or, where there isn't one, when someone opens the farm home page after
SUMMARY_HOUR: whichever comes first, and only once a day.
"""
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.apps import apps
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db.models import Sum
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.formats import date_format
from django.utils.translation import gettext as _

from .access import can
from .models import AuditLog, Membership

log = logging.getLogger(__name__)
ZERO = Decimal(0)
SUMMARY_HOUR = 20     # 8 pm: the day's work is done


def _installed(name):
    return apps.is_installed(f"apps.business.{name}")


@dataclass
class PondDay:
    name: str
    url: str
    fed_kg: Decimal = ZERO
    deaths: int = 0
    water: list = field(default_factory=list)       # problems found
    oxygen: Decimal | None = None
    weighed_g: Decimal | None = None
    harvested: list = field(default_factory=list)   # "120 kg Rui"
    care: list = field(default_factory=list)        # "Lime 20 kg"

    @property
    def fed(self):
        return self.fed_kg > 0

    @property
    def worry(self):
        return bool(self.water or self.deaths or not self.fed)


@dataclass
class DaySummary:
    business: object
    day: date
    show_money: bool
    ponds: list = field(default_factory=list)
    sales_count: int = 0
    sales_kg: Decimal = ZERO
    sales_net: Decimal = ZERO
    received: Decimal = ZERO          # cash at sales + payments in
    paid: Decimal = ZERO              # payments out
    advances: Decimal = ZERO          # dadon taken today
    feed_bought: Decimal = ZERO
    costs: Decimal = ZERO             # other farm costs typed in
    store_short: Decimal = ZERO       # feed short at a store count
    people: list = field(default_factory=list)       # [(name, number of records)]
    tasks: list = field(default_factory=list)
    night: object = None

    @property
    def fed_ponds(self):
        return [p for p in self.ponds if p.fed]

    @property
    def unfed_ponds(self):
        return [p for p in self.ponds if not p.fed]

    @property
    def unfed_names(self):
        return [p.name for p in self.unfed_ponds]

    @property
    def deaths(self):
        return sum(p.deaths for p in self.ponds)

    @property
    def water_problems(self):
        return [p for p in self.ponds if p.water]

    @property
    def records(self):
        return sum(n for _name, n in self.people)

    @property
    def quiet(self):
        """Nothing at all was recorded."""
        return not self.records

    def headline(self):
        bits = [_("%(fed)s of %(all)s ponds fed") % {"fed": len(self.fed_ponds), "all": len(self.ponds)}] if self.ponds else []
        if self.sales_count:
            from .templatetags.business import bdt, num

            bits.append(_("%(n)s kg sold") % {"n": num(self.sales_kg)} if not self.show_money else _("%(v)s sold") % {"v": bdt(self.sales_net)})
        problems = len(self.water_problems) + (1 if self.deaths else 0)
        if problems:
            bits.append(_("%(n)s to look at") % {"n": problems})
        if self.quiet:
            bits.append(_("nothing recorded"))
        return " · ".join(bits)


def build(business, day=None, show_money=True, with_weather=True):
    from apps.business.ponds.models import CycleStatus, CultureCycle, Harvest, Mortality, PondAlerts, SampleWeighing, Treatment, WaterTest

    day = day or timezone.localdate()
    s = DaySummary(business=business, day=day, show_money=show_money)
    running = list(CultureCycle.objects.filter(business=business, status=CycleStatus.RUNNING, start_date__lte=day)
                   .select_related("pond").order_by("pond__order", "pond__name"))
    rows = {c.pk: PondDay(c.pond.name, reverse("business:cycle_detail", args=[c.pk])) for c in running}
    if _installed("feed"):
        from apps.business.feed.models import FeedCount, FeedPurchase, FeedUsage

        for cid, kg in FeedUsage.objects.filter(business=business, date=day, cycle_id__in=rows).values_list("cycle_id").annotate(kg=Sum("kg")):
            rows[cid].fed_kg = kg
        s.feed_bought = FeedPurchase.objects.filter(business=business, date=day).aggregate(t=Sum("total"))["t"] or ZERO
        s.store_short = -sum((c.value for c in FeedCount.objects.filter(business=business, date=day, opening=False) if c.value < 0), ZERO)
    for cid, n in Mortality.objects.filter(business=business, date=day, cycle_id__in=rows).values_list("cycle_id").annotate(n=Sum("count")):
        rows[cid].deaths = n or 0
    limits = PondAlerts.for_business(business)
    for w in WaterTest.objects.filter(business=business, date=day, cycle_id__in=rows).order_by("id"):
        r = rows[w.cycle_id]
        r.water += [f.what for f in w.problems(limits) if f.what not in r.water]
        if w.oxygen is not None:
            r.oxygen = w.oxygen if r.oxygen is None else min(r.oxygen, w.oxygen)
    for w in SampleWeighing.objects.filter(business=business, date=day, cycle_id__in=rows).select_related("unit"):
        rows[w.cycle_id].weighed_g = w.avg_g
    from .templatetags.business import num

    for h in Harvest.objects.filter(business=business, date=day, cycle_id__in=rows).select_related("species", "unit"):
        rows[h.cycle_id].harvested.append(f"{num(h.quantity)} {h.unit.symbol} {h.species}")
    for t in Treatment.objects.filter(business=business, date=day, cycle_id__in=rows).select_related("unit"):
        what = t.product or (str(t.item) if t.item_id else t.get_kind_display())
        rows[t.cycle_id].care.append(f"{what} {num(t.quantity)} {t.unit.symbol}" if t.quantity and t.unit_id else what)
    s.ponds = list(rows.values())

    if _installed("sales"):
        from apps.business.sales.models import FishSale, FishSaleLine

        sales = FishSale.objects.filter(business=business, date=day)
        agg = sales.aggregate(net=Sum("net"), got=Sum("received_now"))
        s.sales_count = sales.count()
        s.sales_net, s.received = agg["net"] or ZERO, agg["got"] or ZERO
        s.sales_kg = (FishSaleLine.objects.filter(sale__in=sales, unit__unit_type="weight").aggregate(kg=Sum("base_quantity"))["kg"] or ZERO)
    if _installed("credit"):
        from apps.business.credit.models import Direction, PartyPayment

        for p in PartyPayment.objects.filter(business=business, date=day):
            if p.direction == Direction.IN:
                s.received += p.amount
                if p.is_advance:
                    s.advances += p.amount
            else:
                s.paid += p.amount
    if _installed("finance"):
        from apps.business.finance.models import Transaction

        s.costs = (Transaction.objects.filter(business=business, date=day, category__type="expense", category__scope="business")
                   .aggregate(t=Sum("amount"))["t"] or ZERO)

    start = timezone.make_aware(datetime.combine(day, time.min))
    counts = Counter(AuditLog.objects.filter(business=business, at__gte=start, at__lt=start + timedelta(days=1), user__isnull=False)
                     .values_list("user__first_name", "user__last_name", "user__username"))
    named = defaultdict(int)
    for (first, last, username), n in counts.items():
        named[(f"{first} {last}".strip() or username)] += n
    s.people = sorted(named.items(), key=lambda kv: -kv[1])

    if day == timezone.localdate():
        from apps.business.ponds.services import farm_tasks

        s.tasks = farm_tasks(business)[:6]
        if with_weather:
            from apps.business.ponds import weather

            try:
                s.night = weather.tonight(business)
            except Exception:   # the weather is a bonus, never a reason to fail
                log.exception("weather for summary")
    return s


# ── Sending ─────────────────────────────────────────────────────────────────

def due_day(now=None):
    """The day whose summary should have gone out by now."""
    now = now or timezone.localtime()
    return now.date() if now.hour >= SUMMARY_HOUR else now.date() - timedelta(days=1)


def _language(user):
    profile = getattr(user, "profile", None)
    return getattr(profile, "language", None) or settings.LANGUAGE_CODE


def site_url(request=None):
    """https://the-site, for links in an email: from the request when there is
    one, else SITE_URL, else the first allowed host; "" if none is known."""
    if request is not None:
        return request.build_absolute_uri("/").rstrip("/")
    if getattr(settings, "SITE_URL", ""):
        return settings.SITE_URL.rstrip("/")
    hosts = [h for h in settings.ALLOWED_HOSTS if h and h != "*" and not h.startswith(".")]
    return f"https://{hosts[0]}" if hosts else ""


def send(membership, day, request=None):
    """Email one person the summary of one day. True when it went."""
    user = membership.user
    if not user.email:
        return False
    with translation.override(_language(user)):
        s = build(membership.business, day, show_money=can(membership, "view_finance"))
        ctx = {"s": s, "base": site_url(request), "page": reverse("business:day_summary"), "user": user}
        subject = _("%(farm)s — %(date)s: %(headline)s") % {"farm": membership.business.name, "date": date_format(day, "j M"), "headline": s.headline()}
        msg = EmailMultiAlternatives(subject, render_to_string("business/summary/email.txt", ctx), None, [user.email])
        msg.attach_alternative(render_to_string("business/summary/email.html", ctx), "text/html")
    try:
        msg.send()
    except Exception:
        log.exception("evening summary to %s", user.email)
        return False
    Membership.objects.filter(pk=membership.pk).update(summary_sent_on=day)
    return True


def pending(business=None, day=None):
    day = day or due_day()
    qs = (Membership.objects.filter(daily_summary=True, business__isnull=False).exclude(user__email="")
          .exclude(summary_sent_on__gte=day).select_related("business", "user"))
    return qs.filter(business=business) if business is not None else qs


def send_due(business, request=None):
    """Catch-up from a page visit: anyone in this business still owed today's
    (or, before SUMMARY_HOUR, yesterday's) summary gets it now."""
    day = due_day()
    sent = 0
    for m in pending(business, day):
        if m.user.is_active:
            sent += send(m, day, request)
    return sent
