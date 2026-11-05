"""Rollover, as YNAB and Goodbudget's envelopes have it: what's left of a month's limit adds to the
next, and overspending takes from it."""
from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.budgets import services
from apps.budgets.models import Budget
from apps.expense.models import Expense, ExpenseCategory


class RolloverTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("owner", password="pw12345!")
        self.food = ExpenseCategory.objects.create(user=self.user, name="Food", icon="🍚")
        self.budget = Budget.objects.create(user=self.user, category=self.food, amount=1000, rollover=True)
        Budget.objects.filter(pk=self.budget.pk).update(created_at=timezone.make_aware(datetime(2026, 7, 10)))
        self.budget.refresh_from_db()

    def spend(self, amount, day):
        Expense.objects.create(user=self.user, category=self.food, amount=amount, date=day)

    def test_whats_left_and_overspent_carry_on(self):
        self.spend(700, date(2026, 7, 5))      # July: 300 left
        self.spend(1500, date(2026, 8, 5))     # August: 1300 to spend, 200 over
        self.assertEqual(services.carried_in(self.budget, date(2026, 8, 1)), Decimal("300"))
        self.assertEqual(services.carried_in(self.budget, date(2026, 9, 1)), Decimal("-200"))
        s = services.status(self.budget, month=date(2026, 9, 1), today=date(2026, 9, 10))
        self.assertEqual((s["limit"], s["carried"]), (Decimal("800"), Decimal("-200")))

    def test_months_before_the_budget_dont_count(self):
        self.spend(5000, date(2026, 6, 5))     # before the budget was made
        self.assertEqual(services.carried_in(self.budget, date(2026, 7, 1)), 0)
        self.assertEqual(services.carried_in(self.budget, date(2026, 8, 1)), Decimal("1000"))

    def test_off_means_a_fresh_limit_each_month(self):
        self.budget.rollover = False
        self.budget.save()
        self.spend(100, date(2026, 7, 5))
        s = services.status(self.budget, month=date(2026, 8, 1), today=date(2026, 8, 3))
        self.assertEqual((s["limit"], s["carried"]), (Decimal("1000"), 0))

    def test_the_form_and_the_page(self):
        self.client.force_login(self.user)
        r = self.client.post(reverse("budget_edit", args=[self.budget.pk]),
                             {"scope": "category", "category": self.food.pk, "amount": "1000", "alert_at": "80", "rollover": "on"})
        self.assertEqual(r.status_code, 302)
        last_month = (timezone.localdate().replace(day=1) - timezone.timedelta(days=1))
        Budget.objects.filter(pk=self.budget.pk).update(created_at=timezone.now() - timezone.timedelta(days=70))
        self.spend(400, last_month)
        html = self.client.get(reverse("budget_list")).content.decode()
        self.assertIn("carried from", html)
        self.assertIn("carries over", html)
        self.assertIn("🍚", html)
