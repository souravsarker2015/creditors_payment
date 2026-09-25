from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import GoalEntry, SavingsGoal
from .services import add_months, goal_rows, months_between, progress, totals

TODAY = date(2026, 9, 15)


class GoalMathTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("owner", password="pw12345!")

    def goal(self, target, target_date=None, **kw):
        return SavingsGoal.objects.create(user=self.user, name="Laptop", target_amount=target, target_date=target_date, **kw)

    def put(self, goal, amount, d, kind=GoalEntry.DEPOSIT):
        return GoalEntry.objects.create(goal=goal, kind=kind, amount=amount, date=d)

    def test_calendar_helpers(self):
        self.assertEqual(months_between(date(2026, 9, 15), date(2026, 12, 1)), 4)   # Sep..Dec
        self.assertEqual(add_months(date(2026, 1, 31), 1), date(2026, 2, 28))

    def test_saved_counts_withdrawals(self):
        g = self.goal(10000)
        self.put(g, 3000, date(2026, 9, 1))
        self.put(g, 500, date(2026, 9, 2), GoalEntry.WITHDRAW)
        p = progress(g, TODAY)
        self.assertEqual((p["saved"], p["remaining"], p["pct"]), (2500, 7500, 25))

    def test_monthly_plan_and_on_track(self):
        g = self.goal(12000, date(2026, 12, 31))          # Sep..Dec = 4 months
        self.put(g, 4000, date(2026, 9, 1))
        p = progress(g, TODAY)
        self.assertEqual(p["months_left"], 4)
        self.assertEqual(p["needed_per_month"], 2000)      # 8000 left / 4
        self.assertEqual(p["pace"], 4000)                   # one month of history
        self.assertEqual(p["state"], "on_track")

    def test_behind_when_pace_is_too_slow(self):
        g = self.goal(12000, date(2026, 10, 31))
        for m in (7, 8, 9):
            self.put(g, 1000, date(2026, m, 1))
        p = progress(g, TODAY)
        self.assertEqual(p["pace"], 1000)
        self.assertEqual(p["needed_per_month"], 4500)      # 9000 over Sep+Oct
        self.assertEqual(p["state"], "behind")
        self.assertEqual(p["projected_date"], date(2027, 6, 15))  # 9 more months

    def test_pace_uses_last_three_months_only(self):
        g = self.goal(100000)
        self.put(g, 50000, date(2026, 1, 1))               # old lump sum: not pace
        self.put(g, 3000, date(2026, 8, 1))
        self.assertEqual(progress(g, TODAY)["pace"], 1000)  # 3000 over Jul..Sep

    def test_overdue_reached_and_idle(self):
        late = self.goal(5000, date(2026, 8, 1))
        self.assertEqual(progress(late, TODAY)["state"], "overdue")
        done = self.goal(1000)
        self.put(done, 1200, date(2026, 9, 1))
        self.assertEqual(progress(done, TODAY)["state"], "reached")
        self.assertEqual(progress(self.goal(1000), TODAY)["state"], "idle")

    def test_rows_split_active_reached_archived_and_totals(self):
        a = self.goal(1000)
        self.put(a, 1000, date(2026, 9, 1))                # reached
        b = self.goal(2000)
        self.put(b, 500, date(2026, 9, 1))
        c = self.goal(3000, is_active=False)
        self.put(c, 700, date(2026, 9, 1))
        self.assertEqual([r["goal"] for r in goal_rows(self.user, "active", TODAY)], [b])
        self.assertEqual([r["goal"] for r in goal_rows(self.user, "reached", TODAY)], [a])
        self.assertEqual([r["goal"] for r in goal_rows(self.user, "archived", TODAY)], [c])
        t = totals(self.user)
        self.assertEqual((t["saved"], t["target"]), (1500, 3000))  # archived excluded


class GoalViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("owner", password="pw12345!")
        self.other = User.objects.create_user("other", password="pw12345!")
        self.client.login(username="owner", password="pw12345!")
        self.today = timezone.localdate()

    def test_create_add_money_and_reach(self):
        r = self.client.post(reverse("goal_create"), {"name": "Eid", "target_amount": "2000", "color": "gold", "note": ""})
        g = SavingsGoal.objects.get(user=self.user)
        self.assertRedirects(r, reverse("goal_detail", args=[g.pk]))
        self.client.post(reverse("goal_entry_create", args=[g.pk]), {"kind": "DEPOSIT", "amount": "1500", "date": self.today, "next": reverse("goal_list")})
        r = self.client.post(reverse("goal_detail", args=[g.pk]), {"kind": "DEPOSIT", "amount": "500", "date": self.today, "note": ""}, follow=True)
        g.refresh_from_db()
        self.assertEqual(g.reached_at, self.today)
        self.assertContains(r, "Goal reached")
        # taking money back out re-opens it
        self.client.post(reverse("goal_detail", args=[g.pk]), {"kind": "WITHDRAW", "amount": "100", "date": self.today, "note": ""})
        g.refresh_from_db()
        self.assertIsNone(g.reached_at)

    def test_cannot_take_out_more_than_saved(self):
        g = SavingsGoal.objects.create(user=self.user, name="X", target_amount=1000)
        GoalEntry.objects.create(goal=g, amount=300, date=self.today)
        r = self.client.post(reverse("goal_detail", args=[g.pk]), {"kind": "WITHDRAW", "amount": "400", "date": self.today, "note": ""})
        self.assertIn("amount", r.context["form"].errors)
        self.assertEqual(g.entries.count(), 1)

    def test_new_goal_date_must_be_in_future(self):
        r = self.client.post(reverse("goal_create"), {"name": "Late", "target_amount": "10", "target_date": self.today - timedelta(days=1), "color": "blue"})
        self.assertIn("target_date", r.context["form"].errors)

    def test_other_users_goals_are_off_limits(self):
        g = SavingsGoal.objects.create(user=self.other, name="Theirs", target_amount=10)
        e = GoalEntry.objects.create(goal=g, amount=5, date=self.today)
        for name, arg in [("goal_detail", g.pk), ("goal_edit", g.pk), ("goal_entry_edit", e.pk)]:
            self.assertEqual(self.client.get(reverse(name, args=[arg])).status_code, 404)
        for name, arg in [("goal_entry_create", g.pk), ("goal_toggle_active", g.pk), ("goal_delete", g.pk), ("goal_entry_delete", e.pk)]:
            self.assertEqual(self.client.post(reverse(name, args=[arg]), {"kind": "DEPOSIT", "amount": "1", "date": self.today}).status_code, 404)
        self.assertEqual(GoalEntry.objects.count(), 1)

    def test_archive_delete_and_safe_next(self):
        g = SavingsGoal.objects.create(user=self.user, name="X", target_amount=10)
        r = self.client.post(reverse("goal_toggle_active", args=[g.pk]), {"next": "https://evil.example/"})
        self.assertRedirects(r, reverse("goal_list"), fetch_redirect_response=False)
        g.refresh_from_db()
        self.assertFalse(g.is_active)
        self.assertEqual(self.client.get(reverse("goal_delete", args=[g.pk])).status_code, 405)
        self.client.post(reverse("goal_delete", args=[g.pk]))
        self.assertFalse(SavingsGoal.objects.exists())

    def test_pages_render_and_networth_shows_goals(self):
        g = SavingsGoal.objects.create(user=self.user, name="Emergency fund", target_amount=10000,
                                       target_date=self.today + timedelta(days=90))
        GoalEntry.objects.create(goal=g, amount=2500, date=self.today)
        for url in [reverse("goal_list"), reverse("goal_list") + "?status=reached", reverse("goal_detail", args=[g.pk]), reverse("goal_create")]:
            self.assertEqual(self.client.get(url).status_code, 200, url)
        r = self.client.get(reverse("networth"))
        self.assertContains(r, "Emergency fund")
        self.assertEqual(r.context["goal_totals"]["saved"], 2500)

    def test_goal_money_is_not_counted_as_spending(self):
        before = self.client.get(reverse("networth")).context["net_position"]
        g = SavingsGoal.objects.create(user=self.user, name="X", target_amount=10)
        GoalEntry.objects.create(goal=g, amount=5000, date=self.today)
        self.assertEqual(self.client.get(reverse("networth")).context["net_position"], before)


class NewGoalPlanTests(TestCase):
    def test_new_goal_with_a_date_is_not_behind_and_plan_is_whole_taka(self):
        user = User.objects.create_user("owner", password="pw12345!")
        g = SavingsGoal.objects.create(user=user, name="Hajj", target_amount=900000, target_date=date(2029, 1, 1))
        p = progress(g, TODAY)
        self.assertEqual(p["state"], "idle")
        self.assertEqual(p["needed_per_month"], Decimal("31035"))  # 900000 / 29 months, rounded up
