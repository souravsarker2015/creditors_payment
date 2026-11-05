"""Habits as Loop and Streaks have them: an amount a day ("8 glasses", done when it's reached) and
"3 times a week" on any days (its streak counts weeks)."""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .. import services
from ..models import Habit, HabitCheck

PW = "Str0ng-pass-123"


class HabitAmountAndWeekTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)
        self.today = timezone.localdate()

    def habit(self, **fields):
        h = Habit.objects.create(owner=self.me, name=fields.pop("name", "Water"), **fields)
        Habit.objects.filter(pk=h.pk).update(created_at=timezone.now() - timedelta(days=60))
        h.refresh_from_db()
        return h

    def check(self, h, day, **data):
        return self.client.post(reverse("work:api_habit_check", args=[h.pk]), {"date": day.isoformat(), **data}).json()

    def test_an_amount_counts_once_the_goal_is_reached(self):
        h = self.habit(target=8, unit="glasses")
        self.assertTrue(h.counted)
        r = self.check(h, self.today, amount="3")
        self.assertEqual((r["done"], r["amount"], r["streak"]), (False, 3, 0))      # 3 of 8: not done yet
        r = self.check(h, self.today, amount="8")
        self.assertEqual((r["done"], r["streak"]), (True, 1))
        self.check(h, self.today - timedelta(days=1), amount="10")                   # more than the goal is fine
        self.assertEqual(self.check(h, self.today, amount="8")["streak"], 2)
        r = self.check(h, self.today, amount="0")                                    # 0 takes the day off
        self.assertFalse(HabitCheck.objects.filter(habit=h, date=self.today).exists())
        self.assertEqual(r["streak"], 1)                                             # (yesterday still counts)

    def test_a_plain_tick_still_works(self):
        h = self.habit(name="Run")
        self.assertFalse(h.counted)
        self.assertTrue(self.check(h, self.today, done="1")["done"])
        self.assertEqual(HabitCheck.objects.get(habit=h).amount, 1)
        self.check(h, self.today, done="0")
        self.assertFalse(HabitCheck.objects.exists())

    def test_times_a_week_counts_weeks_in_a_row(self):
        h = self.habit(name="Gym", per_week=2)
        monday = services.habit_week_start(self.today)
        for weeks_ago in (1, 2):                                                     # the last two weeks: twice each
            start = monday - timedelta(days=7 * weeks_ago)
            HabitCheck.objects.create(habit=h, date=start)
            HabitCheck.objects.create(habit=h, date=start + timedelta(days=3))
        HabitCheck.objects.create(habit=h, date=monday - timedelta(days=21))          # three weeks ago: only once
        rows, _span = services.habit_rows(self.me, self.today, days=14)
        row = rows[0]
        self.assertEqual((row["streak"], row["streak_weeks"], row["week_done"]), (2, True, 0))
        self.assertTrue(row["due_today"])                                            # this week still needs two
        self.assertTrue(all(c["due"] for c in row["cells"]))                         # any day will do
        r = self.check(h, self.today, done="1")
        self.assertEqual(r["week"], 1)
        other = monday + timedelta(days=1) if self.today == monday else monday
        r = self.check(h, other, done="1")
        self.assertEqual((r["week"], r["streak"]), (2, 3))                           # this week reached too: 3 weeks

    def test_the_form_offers_days_or_times_a_week(self):
        url = reverse("work:habit_new")
        r = self.client.post(url, {"name": "Gym", "emoji": "💪", "color": "green", "per_week": "3", "target": "1", "unit": ""})
        self.assertEqual(r.status_code, 302)
        gym = Habit.objects.get(name="Gym")
        self.assertEqual((gym.per_week, gym.days), (3, "0123456"))                   # the days it had stay, for going back
        r = self.client.post(url, {"name": "Nothing", "emoji": "x", "color": "green", "per_week": "0", "target": "1"})
        self.assertEqual(r.status_code, 200)                                         # on chosen days, but none chosen
        self.assertFalse(Habit.objects.filter(name="Nothing").exists())
        self.client.post(url, {"name": "Read", "emoji": "📖", "color": "blue", "per_week": "0", "day_list": ["0", "2"], "target": "20", "unit": "pages"})
        read = Habit.objects.get(name="Read")
        self.assertEqual((read.days, read.target, read.unit), ("02", 20, "pages"))

    def test_the_pages_show_amounts_and_weeks(self):
        water = self.habit(target=8, unit="glasses")
        self.habit(name="Gym", per_week=3)
        HabitCheck.objects.create(habit=water, date=self.today, amount=3)
        html = self.client.get(reverse("work:habits")).content.decode()
        self.assertIn("8 glasses", html)
        self.assertIn("this week", html)
        self.assertIn("amount: 3", html)
        today = self.client.get(reverse("work:today")).content.decode()
        self.assertIn("habitDay(", today)
        self.assertIn("amount: 3", today)

    def test_reports_count_a_weekly_habit_by_its_weeks(self):
        h = self.habit(name="Gym", per_week=2)
        monday = services.habit_week_start(self.today) - timedelta(days=7)
        HabitCheck.objects.create(habit=h, date=monday)
        HabitCheck.objects.create(habit=h, date=monday + timedelta(days=2))
        span = [monday + timedelta(days=i) for i in range(7)]
        self.assertEqual(services.habit_rate(h, {monday, monday + timedelta(days=2)}, span), 100)
        self.assertEqual(services.habit_rate(h, {monday}, span), 50)

    def test_an_older_page_without_the_new_fields_still_saves(self):
        r = self.client.post(reverse("work:habit_new"), {"name": "Old way", "emoji": "✅", "color": "green", "day_list": ["0", "1"]})
        self.assertEqual(r.status_code, 302)
        h = Habit.objects.get(name="Old way")
        self.assertEqual((h.per_week, h.target, h.days), (0, 1, "01"))
