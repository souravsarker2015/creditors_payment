"""Reports as the best time trackers lay them out: a Summary against the period before with highlights and
projects that open onto their tasks (Toggl, Clockify), one Day on a timeline with its breaks, said in words
(RescueTime, Rize), a Week's timesheet of tasks by day, and every entry in a Detailed list — all with one filter."""
from datetime import datetime, time, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .. import reports, services
from ..models import EntryKind, Project, Status, Tag, Task, TimeEntry, WorkSettings

PW = "Str0ng-pass-123"


class ReportTabsTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)
        self.today = timezone.localdate()
        self.day = self.today - timedelta(days=1)
        self.site = Project.objects.create(owner=self.me, name="Website", color="blue")
        self.app = Project.objects.create(owner=self.me, name="App", color="green")
        self.login = Task.objects.create(owner=self.me, title="Fix login", project=self.site)
        self.deep = Tag.objects.create(owner=self.me, name="deep")

    def at(self, day, hh, mm=0):
        return timezone.make_aware(datetime.combine(day, time(hh, mm)))

    def entry(self, day, a, b, **fields):
        tags = fields.pop("tags", ())
        e = TimeEntry.objects.create(owner=self.me, started_at=self.at(day, *a), ended_at=self.at(day, *b), **fields)
        e.tags.set(tags)
        return e

    def a_day(self, day):
        self.entry(day, (9, 0), (10, 30), task=self.login, project=self.site, tags=[self.deep])      # 1h 30m
        self.entry(day, (10, 32), (11, 0), task=self.login, project=self.site)                        # 28m, no real break
        self.entry(day, (11, 30), (12, 0), project=self.app, description="Standup", kind=EntryKind.FOCUS)  # after a 30m break
        self.entry(day, (14, 0), (15, 0), description="Email")                                         # after lunch: 2h break

    # ── Day ──
    def test_the_day_report(self):
        self.a_day(self.day)
        Task.objects.filter(pk=self.login.pk).update(status=Status.DONE, completed_at=self.at(self.day, 11, 1))
        d = reports.day_report(self.me, self.day, WorkSettings.for_user(self.me), self.today)
        self.assertEqual(d["tracked"], (90 + 28 + 30 + 60) * 60)
        self.assertEqual([b["secs"] // 60 for b in d["breaks"]], [30, 120])               # the 2-minute gap isn't a break
        self.assertEqual(d["longest"], 120 * 60)                                         # 9:00–11:00 in one stretch
        self.assertEqual((d["by_task"][0]["label"], d["by_task"][0]["sessions"]), ("Fix login", 2))
        self.assertEqual(d["focus_count"], 1)
        self.assertEqual([t.title for t in d["done"]], ["Fix login"])
        self.assertIn("between 09:00 and 15:00", d["story"][0])
        r = self.client.get(reverse("work:report_day"), {"date": self.day.isoformat()})
        html = r.content.decode()
        self.assertEqual(r.status_code, 200)
        for text in ("Timeline", "Where the time went", "Fix login", "Break, 30m", "Yesterday"):
            self.assertIn(text, html)

    def test_a_day_with_nothing_and_a_day_in_the_future(self):
        html = self.client.get(reverse("work:report_day")).content.decode()
        self.assertIn("Nothing tracked today yet", html)
        r = self.client.get(reverse("work:report_day"), {"date": (self.today + timedelta(days=3)).isoformat()})
        self.assertEqual(r.context["day"], self.today)                                   # can't look ahead

    def test_against_your_usual_day(self):
        for i in (2, 3, 4):
            self.entry(self.today - timedelta(days=i), (9, 0), (11, 0))                   # 2h a day
        self.a_day(self.day)
        d = reports.day_report(self.me, self.day, WorkSettings.for_user(self.me), self.today)
        self.assertEqual((d["usual"], d["vs_usual"]["dir"]), (2 * 3600, "up"))
        self.assertTrue(any("more than your usual day" in line for line in d["story"]))

    # ── Week ──
    def test_the_weekly_timesheet(self):
        s = WorkSettings.for_user(self.me)
        first, _last = s.week_of(self.today)
        self.a_day(first)
        w = reports.week_report(self.me, first, s, self.today)
        site = next(g for g in w["groups"] if g["project"] == self.site)
        self.assertEqual((site["total"], site["days"][0]), (118 * 60, 118 * 60))
        self.assertEqual([(r["label"], r["total"]) for r in site["rows"]], [("Fix login", 118 * 60)])
        none = next(g for g in w["groups"] if g["project"] is None)
        self.assertEqual(none["rows"][0]["label"], "Email")
        self.assertEqual(w["total"], 208 * 60)
        r = self.client.get(reverse("work:report_week"))
        self.assertContains(r, "Timesheet")
        csv = self.client.get(reverse("work:report_week"), {"export": "csv"}).content.decode()
        self.assertIn("Website,Fix login,1.97", csv)

    # ── Detailed ──
    def test_every_entry_searchable(self):
        self.a_day(self.day)
        r = self.client.get(reverse("work:report_detailed"), {"range": "30"})
        self.assertEqual(r.context["d"]["count"], 4)
        self.assertEqual(self.client.get(reverse("work:report_detailed"), {"range": "30", "q": "stand"}).context["d"]["count"], 1)
        self.assertEqual(self.client.get(reverse("work:report_detailed"), {"range": "30", "q": "deep"}).context["d"]["count"], 1)  # a tag
        html = r.content.decode()
        self.assertIn(reverse("work:entry", args=[TimeEntry.objects.filter(description="Email").get().pk]), html)
        csv = self.client.get(reverse("work:report_detailed"), {"range": "30", "q": "email", "export": "csv"}).content.decode()
        self.assertIn("Email", csv)
        self.assertNotIn("Standup", csv)

    # ── the filter, the comparison, highlights ──
    def test_the_filter_narrows_every_report(self):
        self.a_day(self.day)
        q = {"range": "30", "project": self.site.pk}
        r = self.client.get(reverse("work:reports"), q)
        self.assertEqual(r.context["t"].seconds, 118 * 60)
        self.assertContains(r, "Showing only")
        self.assertEqual(self.client.get(reverse("work:reports"), {"range": "30", "project": "none"}).context["t"].seconds, 60 * 60)
        self.assertEqual(self.client.get(reverse("work:reports"), {"range": "30", "tag": self.deep.pk}).context["t"].seconds, 90 * 60)
        self.assertEqual(self.client.get(reverse("work:report_detailed"), q).context["d"]["count"], 2)
        other = User.objects.create_user("other", password=PW)
        theirs = Project.objects.create(owner=other, name="Theirs")
        r = self.client.get(reverse("work:reports"), {"range": "30", "project": theirs.pk})
        self.assertFalse(r.context["flt"].active)                                        # someone else's: ignored
        self.assertEqual(r.context["t"].seconds, 208 * 60)

    def test_summary_compares_and_points_things_out(self):
        s = WorkSettings.for_user(self.me)
        first, _last = s.week_of(self.today)
        self.a_day(first)
        r = self.client.get(reverse("work:reports"), {"range": "week"})
        before = reports.previous_period(r.context["start"], r.context["end"])[0]          # (on the week's first day that's only the day before)
        self.entry(before, (9, 0), (10, 0), project=self.site)                             # the same length of time just before: 1h
        r = self.client.get(reverse("work:reports"), {"range": "week"})
        cmp = r.context["cmp"]
        self.assertEqual((cmp["tracked"]["dir"], cmp["tracked"]["before"]), ("up", 3600))
        texts = " ".join(text for _icon, text in r.context["highlights"])
        self.assertIn("Most of your time went to Website", texts)
        self.assertIn("more than the period before", texts)
        site = next(p for p in r.context["projects"] if p["p"] == self.site)
        self.assertEqual([x["task"] for x in site["tasks"]], [self.login])
        self.assertIn("conic-gradient(", r.context["donut"])
        self.assertContains(r, "Highlights")

    def test_the_tabs_carry_the_filter(self):
        html = self.client.get(reverse("work:reports"), {"project": self.site.pk}).content.decode()
        self.assertIn(f'{reverse("work:report_week")}?project={self.site.pk}', html)
        self.assertIn(f'{reverse("work:report_detailed")}?project={self.site.pk}', html)

    def test_totals_with_a_filter(self):
        self.a_day(self.day)
        f = reports.Filter(project=str(self.site.pk))
        self.assertEqual(services.totals(self.me, self.day, self.day, f).seconds, 118 * 60)
        self.assertEqual(services.totals(self.me, self.day, self.day, reports.Filter(billable=True)).seconds, 0)

    def test_every_report_needs_signing_in(self):
        self.client.logout()
        for name in ("work:reports", "work:report_day", "work:report_week", "work:report_detailed"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 302, name)
