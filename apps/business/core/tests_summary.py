"""The evening summary: the page, the email, and who gets it when."""
from datetime import date, timedelta
from decimal import Decimal as D
from io import StringIO
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.business.core.models import AuditLog, Membership, Unit
from apps.business.core.testing import make_farm
from apps.business.feed.models import FeedProduct, FeedUsage
from apps.business.ponds.models import CultureCycle, Mortality, Pond, WaterTest
from apps.business.sales.models import FishSale, FishSaleLine
from apps.business.species.models import Species

from . import summary

TODAY = timezone.localdate()


class SummaryBase(TestCase):
    def setUp(self):
        self.b, self.owner, self.staff = make_farm()
        self.owner.email, self.owner.first_name = "owner@example.com", "Rahim"
        self.owner.save()
        self.staff.email = "staff@example.com"
        self.staff.save()
        self.client.force_login(self.owner)
        self.kg = Unit.objects.get(business=self.b, symbol="kg")
        start = TODAY - timedelta(days=40)
        self.east = CultureCycle.objects.create(business=self.b, pond=Pond.objects.create(business=self.b, name="East"), start_date=start)
        self.west = CultureCycle.objects.create(business=self.b, pond=Pond.objects.create(business=self.b, name="West"), start_date=start)
        feed = FeedProduct.objects.create(business=self.b, name="Grower", bag_size=D("25"), bag_unit=self.kg)
        FeedUsage.objects.create(business=self.b, cycle=self.east, date=TODAY, product=feed, quantity=D("12"), unit=self.kg)
        Mortality.objects.create(business=self.b, cycle=self.west, date=TODAY, species=Species.objects.get(business=self.b, name="Rui"), count=25)
        WaterTest.objects.create(business=self.b, cycle=self.west, date=TODAY, oxygen=D("2.5"))
        sale = FishSale.objects.create(business=self.b, date=TODAY, received_now=D("5000"))
        FishSaleLine.objects.create(business=self.b, sale=sale, species=Species.objects.get(business=self.b, name="Rui"), quantity=D("40"), unit=self.kg, rate=D("200"))
        sale.recalc()
        AuditLog.objects.create(business=self.b, user=self.staff, action="create", model="x", object_id="1", object_repr="x")
        AuditLog.objects.create(business=self.b, user=self.staff, action="create", model="x", object_id="2", object_repr="y")


class BuildTests(SummaryBase):
    def test_pond_by_pond(self):
        s = summary.build(self.b, TODAY, with_weather=False)
        east, west = s.ponds
        self.assertEqual(east.fed_kg, D("12"))
        self.assertFalse(west.fed)
        self.assertEqual(west.deaths, 25)
        self.assertTrue(west.water)
        self.assertEqual(s.unfed_names, ["West"])
        self.assertEqual(s.sales_count, 1)
        self.assertEqual(s.sales_kg, D("40"))
        self.assertEqual(s.sales_net, D("8000"))
        self.assertEqual(s.received, D("5000"))
        self.assertEqual(s.people, [(self.staff.username, 2)])
        self.assertIn("1 of 2 ponds fed", s.headline())

    def test_a_quiet_day(self):
        s = summary.build(self.b, TODAY - timedelta(days=3), with_weather=False)
        self.assertTrue(s.quiet)
        self.assertIn("nothing recorded", s.headline())


class PageTests(SummaryBase):
    def test_page_and_money_only_for_finance(self):
        url = reverse("business:day_summary")
        r = self.client.get(url)
        self.assertContains(r, "Pond by pond")
        self.assertContains(r, "not fed")
        self.assertContains(r, "25 fish died")
        self.assertContains(r, "৳8,000")
        self.assertContains(self.client.get(reverse("business:home")), url)
        self.client.force_login(self.staff)
        r = self.client.get(url)
        self.assertContains(r, "40 kg")
        self.assertNotContains(r, "৳8,000")

    def test_turn_on_off_and_send_now(self):
        url = reverse("business:day_summary")
        m = Membership.objects.get(business=self.b, user=self.owner)
        r = self.client.post(url, {"action": "on"}, follow=True)
        self.assertContains(r, "owner@example.com")
        m.refresh_from_db()
        self.assertTrue(m.daily_summary)
        self.assertEqual(m.summary_sent_on, summary.due_day())       # nothing owed straight away
        self.client.post(url, {"action": "send"})
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.to, ["owner@example.com"])
        self.assertIn(self.b.name, email.subject)
        self.assertIn("East: fed 12 kg", email.body)
        self.assertIn("West: not fed, 25 fish died", email.body)
        self.assertIn("http://testserver/business/settings/evening-summary/", email.body)
        self.assertIn("text/html", [a[1] for a in email.alternatives])
        self.client.post(url, {"action": "off"})
        m.refresh_from_db()
        self.assertFalse(m.daily_summary)

    def test_an_earlier_day(self):
        r = self.client.get(reverse("business:day_summary") + f"?date={(TODAY - timedelta(days=3)).isoformat()}")
        self.assertContains(r, "Nothing was recorded on this day")
        r = self.client.get(reverse("business:day_summary") + "?date=2999-01-01")   # the future is today
        self.assertEqual(r.context["s"].day, TODAY)


class SendingTests(SummaryBase):
    def setUp(self):
        super().setUp()
        Membership.objects.filter(business=self.b).update(daily_summary=True)

    def test_command_sends_each_person_once_a_day(self):
        out = StringIO()
        call_command("send_farm_summaries", f"--date={TODAY.isoformat()}", stdout=out)
        self.assertIn("sent 2", out.getvalue())
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), ["owner@example.com", "staff@example.com"])
        staff_mail = next(m for m in mail.outbox if m.to == ["staff@example.com"])
        self.assertNotIn("৳8,000", staff_mail.body)          # data entry doesn't see money
        call_command("send_farm_summaries", f"--date={TODAY.isoformat()}", stdout=StringIO())
        self.assertEqual(len(mail.outbox), 2)

    def test_nobody_without_an_email_or_not_signed_up(self):
        self.staff.email = ""
        self.staff.save()
        Membership.objects.filter(user=self.owner).update(daily_summary=False)
        call_command("send_farm_summaries", f"--date={TODAY.isoformat()}", stdout=StringIO())
        self.assertEqual(len(mail.outbox), 0)

    def test_opening_the_farm_after_eight_sends_what_is_owed(self):
        with mock.patch.object(summary, "due_day", return_value=TODAY):
            self.client.get(reverse("business:home"))
            self.assertEqual(len(mail.outbox), 2)
            self.client.get(reverse("business:home"))
            self.assertEqual(len(mail.outbox), 2)

    def test_due_day(self):
        tz = timezone.get_current_timezone()
        evening = timezone.make_aware(timezone.datetime(2026, 10, 12, 20, 30), tz)
        morning = timezone.make_aware(timezone.datetime(2026, 10, 12, 9, 0), tz)
        self.assertEqual(summary.due_day(evening), date(2026, 10, 12))
        self.assertEqual(summary.due_day(morning), date(2026, 10, 11))

    def test_a_mail_problem_never_breaks_the_home_page(self):
        with mock.patch.object(summary, "due_day", return_value=TODAY), mock.patch("django.core.mail.EmailMultiAlternatives.send", side_effect=OSError("smtp down")):
            r = self.client.get(reverse("business:home"))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Membership.objects.filter(summary_sent_on=TODAY).exists())   # tried again later
