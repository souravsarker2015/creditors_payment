"""The Dashboard (every part of the app over 7, 30 or 90 days, beside the days before), its progress email (every 3
days, when the Dashboard is opened — once, however many tabs), and what the whole site shows of Productivity: the
quick note in the top bar and the floating clock."""
from datetime import timedelta

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .. import dashboard, emails
from ..models import Note, NoteCategory, ReadingDay, Status, Task, TimeEntry, WorkSettings

PW = "Str0ng-pass-123"


class Base(TestCase):
    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)
        self.today = timezone.localdate()

    def work(self, back, minutes, kind="timer"):
        start = timezone.now() - timedelta(days=back, hours=1)
        TimeEntry.objects.create(owner=self.me, started_at=start, ended_at=start + timedelta(minutes=minutes), kind=kind)


class DashboardTests(Base):
    def test_the_numbers_beside_the_days_before(self):
        self.work(1, 60)
        self.work(2, 25, "focus")
        self.work(9, 30)                                         # (the 7 days before)
        Task.objects.create(owner=self.me, title="Done", status=Status.DONE, completed_at=timezone.now() - timedelta(days=1))
        ReadingDay.objects.create(owner=self.me, day=self.today - timedelta(days=1), seconds=600)
        r = dashboard.report(self.me, days=7)
        k = {x["key"]: x for x in r["kpis"]}
        self.assertEqual((k["tracked"]["value"], k["focus"]["value"], k["done"]["value"], k["read"]["value"]), ("1h 25m", "25m", 1, "10m"))
        self.assertEqual(k["tracked"]["delta"]["text"], "+183%")
        self.assertEqual(r["now"]["active"], 2)
        self.assertEqual(len(r["bars"]), 7)
        self.assertIn("1h 25m", r["highlights"][0][1])
        self.assertTrue(1 <= len(r["tips"]) <= 3)

    def test_the_page_its_periods_and_the_way_to_it(self):
        r = self.client.get(reverse("work:dashboard"))
        self.assertContains(r, 'class="wdb-kpi"', count=8)
        self.assertContains(self.client.get(reverse("work:dashboard") + "?days=30"), 'class="wdb-stack"', count=30)
        self.assertContains(self.client.get(reverse("work:dashboard") + "?days=5"), 'class="wdb-stack"', count=7)       # (not a choice: 7)
        self.assertContains(self.client.get(reverse("work:today")), reverse("work:dashboard"))

    def test_nothing_yet_still_reads_well(self):
        r = dashboard.report(self.me, days=7)
        self.assertEqual(r["highlights"][-1][1], "Active on 0 of 7 days.")
        self.assertIsNone(r["best"])


class ProgressEmailTests(Base):
    def test_sent_when_the_dashboard_is_opened_then_not_for_3_days(self):
        self.work(1, 45)
        url = reverse("work:api_dashboard_email")
        self.assertTrue(self.client.post(url, {"action": "auto"}).json()["sent"])
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertIn("Your last 3 days", m.subject)
        html = m.alternatives[0][0]
        self.assertIn("Day by day", html)
        self.assertIn("45m", html)
        self.assertFalse(self.client.post(url, {"action": "auto"}).json()["sent"])            # opened again (another tab): not twice
        self.assertEqual(len(mail.outbox), 1)
        WorkSettings.objects.filter(owner=self.me).update(progress_email_sent_at=timezone.now() - timedelta(days=3, minutes=1))
        self.assertTrue(self.client.post(url, {"action": "auto"}).json()["sent"])
        self.assertEqual(len(mail.outbox), 2)

    def test_off_means_off_but_now_is_now(self):
        WorkSettings.for_user(self.me)
        WorkSettings.objects.filter(owner=self.me).update(progress_email=False)
        url = reverse("work:api_dashboard_email")
        self.assertFalse(self.client.post(url, {"action": "auto"}).json()["sent"])
        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(self.client.post(url, {"action": "now", "days": "30"}).json()["sent"])
        self.assertIn("Your last 30 days", mail.outbox[0].subject)

    def test_the_page_asks_only_when_its_due(self):
        self.assertContains(self.client.get(reverse("work:dashboard")), "workDashboard(true,")
        emails.send_progress(self.me)
        self.assertContains(self.client.get(reverse("work:dashboard")), "workDashboard(false,")

    def test_no_address_no_email(self):
        self.me.email = ""
        self.me.save()
        self.assertEqual(self.client.post(reverse("work:api_dashboard_email"), {"action": "auto"}).status_code, 400)


class EverywhereTests(Base):
    def test_the_quick_note_is_in_the_top_bar_of_every_page(self):
        for url in ("/", reverse("work:today")):
            r = self.client.get(url, follow=True)
            self.assertContains(r, 'id="quick-note"')
            self.assertContains(r, "js/quicknote.js")

    def test_a_quick_note_lands_in_notes_with_its_category(self):
        cat = NoteCategory.objects.create(owner=self.me, name="Ideas")
        r = self.client.post(reverse("work:api_note_save"), {"title": "Bank", "body": "Call about the papers", "categories": str(cat.pk)}).json()
        n = Note.objects.get(pk=r["id"])
        self.assertEqual((n.title, list(n.categories.all())), ("Bank", [cat]))

    def test_not_for_someone_who_cant_use_productivity(self):
        other = User.objects.create_user("other", "o@example.com", PW)
        self.client.force_login(other)
        r = self.client.get("/", follow=True)
        self.assertNotContains(r, 'id="quick-note"')

    def test_the_floating_clock_is_on_the_productivity_pages(self):
        self.assertContains(self.client.get(reverse("work:today")), "js/floatclock.js")
