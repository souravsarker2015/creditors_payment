"""Goals a day and looking back, as the best apps have them: the journal's "On this day", writing streak and
mood strip (Day One), the focus goal and last week (Forest, Pomofocus), tasks done against a goal (Todoist)."""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .. import services
from ..models import JournalEntry, Status, Task, TimeEntry, WorkSettings

PW = "Str0ng-pass-123"


class JournalLookingBackTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)
        self.today = timezone.localdate()

    def entry(self, day, **fields):
        return JournalEntry.objects.create(owner=self.me, date=day, **fields)

    def test_on_this_day_brings_back_earlier_years_and_months(self):
        try:
            year_ago = self.today.replace(year=self.today.year - 1)
        except ValueError:                                   # 29 February
            return
        self.entry(year_ago, wins="Shipped the first version", mood=5)
        self.entry(self.today - timedelta(days=2), wins="Not on this date")
        self.entry(year_ago.replace(year=year_ago.year - 1))                     # nothing written: left out
        found = services.journal_memories(self.me, self.today)
        self.assertEqual([(m["ago"], m["entry"].wins) for m in found], [("1 year ago", "Shipped the first version")])
        html = self.client.get(reverse("work:journal")).content.decode()
        self.assertIn("On this day", html)
        self.assertIn("Shipped the first version", html)

    def test_the_writing_streak(self):
        for i in (1, 2, 3):
            self.entry(self.today - timedelta(days=i), notes="x")
        self.entry(self.today - timedelta(days=5), notes="x")
        self.assertEqual(services.journal_streak(self.me, self.today), 3)          # today still open: counts to yesterday
        self.entry(self.today, mood=4)
        self.assertEqual(services.journal_streak(self.me, self.today), 4)
        self.assertIn("4 days in a row", self.client.get(reverse("work:journal")).content.decode())

    def test_the_mood_strip_shows_only_with_moods(self):
        self.assertNotIn("Mood, last 30 days", self.client.get(reverse("work:journal")).content.decode())
        self.entry(self.today - timedelta(days=3), mood=2)
        r = self.client.get(reverse("work:journal"))
        self.assertIn('data-mood="2"', r.content.decode())
        self.assertEqual(len(r.context["mood_days"]), 30)


class DailyGoalTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)
        self.today = timezone.localdate()
        self.ws = WorkSettings.for_user(self.me)

    def focus(self, day, n):
        start = timezone.make_aware(timezone.datetime.combine(day, timezone.datetime.min.time())) + timedelta(hours=9)
        for i in range(n):
            TimeEntry.objects.create(owner=self.me, kind="focus", started_at=start + timedelta(minutes=30 * i),
                                     ended_at=start + timedelta(minutes=30 * i + 25))

    def test_the_focus_goal_its_streak_and_the_week(self):
        self.ws.focus_goal = 2
        self.ws.save()
        self.focus(self.today - timedelta(days=1), 2)
        self.focus(self.today - timedelta(days=2), 3)
        self.focus(self.today, 1)
        self.assertEqual(services.focus_goal_streak(self.me, 2, self.today), 2)      # today not reached yet
        r = self.client.get(reverse("work:focus"))
        self.assertEqual((r.context["goal"], r.context["goal_pct"], r.context["goal_streak"]), (2, 50, 2))
        self.assertEqual([d["sessions"] for d in r.context["week"]][-3:], [3, 2, 1])
        self.ws.focus_goal = 0
        self.ws.save()
        self.assertNotIn("sessions today", self.client.get(reverse("work:focus")).content.decode())

    def test_tasks_done_against_a_daily_goal(self):
        self.ws.task_goal = 2
        self.ws.save()
        now = timezone.now()
        for days_ago, n in ((1, 2), (2, 2), (3, 1)):
            for _i in range(n):
                Task.objects.create(owner=self.me, title="t", status=Status.DONE, completed_at=now - timedelta(days=days_ago))
        Task.objects.create(owner=self.me, title="today", status=Status.DONE, completed_at=now)
        self.assertEqual(services.task_goal_streak(self.me, 2, self.today), 2)
        r = self.client.get(reverse("work:today"))
        self.assertEqual((r.context["task_goal"], r.context["task_goal_pct"], r.context["task_streak"]), (2, 50, 2))
        self.assertIn("tasks done", r.content.decode())

    def test_the_goals_are_in_settings(self):
        html = self.client.get(reverse("work:settings")).content.decode()
        self.assertIn('name="s-focus_goal"', html)
        self.assertIn('name="s-task_goal"', html)
