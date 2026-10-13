"""Spending more than usual: this month against the usual by the same day."""
from datetime import date
from decimal import Decimal as D

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.budgets.models import Budget, BudgetScope
from apps.expense.models import Expense, ExpenseCategory
from apps.household.models import Purchase

from .insights import jumps

TODAY = date(2026, 10, 15)


class InsightTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("rahim", "rahim@example.com", "pw-123456789")
        self.food = ExpenseCategory.objects.create(user=self.user, name="Food")
        self.rent = ExpenseCategory.objects.create(user=self.user, name="Rent")

    def spend(self, cat, amount, *days):
        for d in days:
            Expense.objects.create(user=self.user, category=cat, amount=D(amount), date=d)

    def usual_food(self):
        # ৳3,000 by the 15th in each of the last three months, ৳6,000 a whole month
        for m in (7, 8, 9):
            self.spend(self.food, "1500", date(2026, m, 5), date(2026, m, 12), date(2026, m, 20), date(2026, m, 28))

    def test_ahead_of_usual(self):
        self.usual_food()
        self.spend(self.food, "2500", date(2026, 10, 3), date(2026, 10, 10))       # ৳5,000 by the 15th
        [j] = jumps(self.user, TODAY)
        self.assertEqual((j.name, j.so_far, j.usual_by_now, j.usual_month), ("Food", D("5000"), D("3000"), D("6000")))
        self.assertEqual(j.pct, 66)
        self.assertEqual(j.change_text, "+66%")
        self.assertFalse(j.past_month)
        self.assertIn(f"category={self.food.pk}", j.url)
        self.assertIn(f"category={self.food.pk}", j.budget_url)
        self.assertIn("amount=6000", j.budget_url)

    def test_normal_months_show_nothing(self):
        self.usual_food()
        self.spend(self.food, "1600", date(2026, 10, 5), date(2026, 10, 12))         # ৳3,200: about usual
        self.assertEqual(jumps(self.user, TODAY), [])

    def test_rent_on_the_first_is_not_a_jump(self):
        for m in (7, 8, 9, 10):
            self.spend(self.rent, "15000", date(2026, m, 1))
        self.assertEqual(jumps(self.user, TODAY), [])

    def test_small_amounts_and_one_offs_are_left_out(self):
        for m in (7, 8, 9):
            self.spend(self.food, "100", date(2026, m, 5))
        self.spend(self.food, "800", date(2026, 10, 5))                               # 8× usual, but only ৳700 more
        self.spend(self.rent, "20000", date(2026, 8, 3))                              # once in three months: no usual
        self.spend(self.rent, "20000", date(2026, 10, 3))
        self.assertEqual(jumps(self.user, TODAY), [])

    def test_past_a_whole_month(self):
        self.usual_food()
        self.spend(self.food, "7000", date(2026, 10, 2))
        [j] = jumps(self.user, TODAY)
        self.assertTrue(j.past_month)
        self.assertEqual(j.change_text, "+133%")
        self.spend(self.food, "3000", date(2026, 10, 3))                             # ৳10,000: over 3× usual
        self.assertEqual(jumps(self.user, TODAY)[0].change_text, "×3")

    def test_bazar_and_budgets(self):
        for m in (7, 8, 9):
            Purchase.objects.create(user=self.user, amount=D("4000"), date=date(2026, m, 6))
        Purchase.objects.create(user=self.user, amount=D("9000"), date=date(2026, 10, 6))
        [j] = jumps(self.user, TODAY)
        self.assertEqual(j.name, "Bazar")
        self.assertIn("scope=bazar", j.budget_url)
        Budget.objects.create(user=self.user, scope=BudgetScope.BAZAR, amount=D("5000"))
        self.assertEqual(jumps(self.user, TODAY)[0].budget_url, "")

    def test_end_of_month_days(self):
        # On the 31st, a 30-day month counts up to its 30th.
        for m in (7, 8, 9):
            self.spend(self.food, "2000", date(2026, m, 28))
        self.spend(self.food, "6000", date(2026, 10, 30))
        [j] = jumps(self.user, date(2026, 10, 31))
        self.assertEqual(j.usual_by_now, D("2000"))

    def test_on_home_and_only_yours(self):
        self.usual_food()
        self.spend(self.food, "2500", date.today().replace(day=1))
        self.client.force_login(self.user)
        r = self.client.get(reverse("home"))
        self.assertIn("jumps", r.context)
        other = User.objects.create_user("other", "o@example.com", "pw-123456789")
        self.assertEqual(jumps(other, TODAY), [])

    def test_shown_on_home(self):
        from unittest import mock

        self.usual_food()
        self.spend(self.food, "2500", date(2026, 10, 3), date(2026, 10, 10))
        self.client.force_login(self.user)
        with mock.patch("apps.overview.views.jumps", lambda user, today: jumps(user, TODAY)):
            r = self.client.get(reverse("home"))
        self.assertContains(r, "Spending more than usual")
        self.assertContains(r, 'data-jump="%s"' % self.food.pk)
        self.assertContains(r, "Set a monthly limit")
