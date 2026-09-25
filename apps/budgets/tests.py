from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.expense.models import Expense, ExpenseCategory
from apps.household.models import Purchase
from .models import Budget, BudgetScope
from .services import alert_message, status


class BudgetStatusTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("owner", password="pw12345!")
        self.food = ExpenseCategory.objects.create(user=self.user, name="Food")
        self.rent = ExpenseCategory.objects.create(user=self.user, name="Rent")

    def spend(self, amount, day, category=None):
        Expense.objects.create(user=self.user, category=category or self.food, amount=amount, date=date(2026, 9, day))

    def test_category_budget_counts_only_its_category_this_month(self):
        b = Budget.objects.create(user=self.user, scope=BudgetScope.CATEGORY, category=self.food, amount=1000)
        self.spend(300, 2)
        self.spend(999, 3, self.rent)
        Expense.objects.create(user=self.user, category=self.food, amount=500, date=date(2026, 8, 31))
        s = status(b, today=date(2026, 9, 10))
        self.assertEqual((s["spent"], s["remaining"], s["pct"], s["state"]), (300, 700, 30, "ok"))
        self.assertEqual(s["days_left"], 21)                      # 10th..30th
        self.assertEqual(s["per_day"], Decimal("700") / 21)
        self.assertEqual(s["projected"], Decimal("900"))          # 300 in 10 days → 900 in 30

    def test_warns_on_pace_even_below_the_alert_level(self):
        b = Budget.objects.create(user=self.user, scope=BudgetScope.CATEGORY, category=self.food, amount=1000)
        self.spend(500, 5)  # 50% used, but on the 5th: pace is 3000
        self.assertEqual(status(b, today=date(2026, 9, 5))["state"], "warn")

    def test_over_budget_and_past_months(self):
        b = Budget.objects.create(user=self.user, scope=BudgetScope.ALL_EXPENSES, amount=1000)
        self.spend(700, 1)
        self.spend(600, 2, self.rent)
        s = status(b, today=date(2026, 9, 20))
        self.assertEqual((s["state"], s["over_by"], s["per_day"]), ("over", 300, 0))
        past = status(b, month=date(2026, 8, 1), today=date(2026, 9, 20))
        self.assertEqual((past["spent"], past["is_current"], past["state"]), (0, False, "ok"))

    def test_bazar_budget_counts_household_purchases(self):
        b = Budget.objects.create(user=self.user, scope=BudgetScope.BAZAR, amount=5000)
        Purchase.objects.create(user=self.user, amount=4500, date=date(2026, 9, 3))
        self.assertEqual(status(b, today=date(2026, 9, 25))["state"], "warn")  # 90% ≥ 80%

    def test_alert_message_only_for_relevant_budgets(self):
        today = timezone.localdate()
        Budget.objects.create(user=self.user, scope=BudgetScope.CATEGORY, category=self.food, amount=100)
        Expense.objects.create(user=self.user, category=self.food, amount=150, date=today)
        self.assertIn("Food", alert_message(self.user, category_id=self.food.pk))
        self.assertIsNone(alert_message(self.user, category_id=self.rent.pk))


class BudgetViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("owner", password="pw12345!")
        self.other = User.objects.create_user("other", password="pw12345!")
        self.client.login(username="owner", password="pw12345!")
        self.food = ExpenseCategory.objects.create(user=self.user, name="Food")

    def test_create_list_edit_delete(self):
        r = self.client.post(reverse("budget_create"), {"scope": "category", "category": self.food.pk, "amount": "8000", "alert_at": "80"})
        self.assertRedirects(r, reverse("budget_list"))
        b = Budget.objects.get(user=self.user)
        self.assertContains(self.client.get(reverse("budget_list")), "Food")
        self.client.post(reverse("budget_edit", args=[b.pk]), {"scope": "category", "category": self.food.pk, "amount": "9000", "alert_at": "90"})
        b.refresh_from_db()
        self.assertEqual((b.amount, b.alert_at), (9000, 90))
        self.assertEqual(self.client.get(reverse("budget_delete", args=[b.pk])).status_code, 405)
        self.client.post(reverse("budget_delete", args=[b.pk]))
        self.assertFalse(Budget.objects.exists())

    def test_category_required_only_for_category_scope_and_no_duplicates(self):
        r = self.client.post(reverse("budget_create"), {"scope": "category", "amount": "100", "alert_at": "80"})
        self.assertIn("category", r.context["form"].errors)
        self.client.post(reverse("budget_create"), {"scope": "bazar", "category": self.food.pk, "amount": "100", "alert_at": "80"})
        self.assertIsNone(Budget.objects.get(scope="bazar").category)  # category ignored for bazar
        r = self.client.post(reverse("budget_create"), {"scope": "bazar", "amount": "200", "alert_at": "80"})
        self.assertTrue(r.context["form"].non_field_errors())

    def test_cannot_touch_another_users_budget(self):
        foreign = Budget.objects.create(user=self.other, scope=BudgetScope.BAZAR, amount=10)
        self.assertEqual(self.client.get(reverse("budget_edit", args=[foreign.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("budget_delete", args=[foreign.pk])).status_code, 404)

    def test_suggestions_from_last_three_months(self):
        today = timezone.localdate()
        m = today.replace(day=1)
        for back in (1, 2, 3):
            y, mo = divmod(m.year * 12 + m.month - 1 - back, 12)
            Expense.objects.create(user=self.user, category=self.food, amount=1100, date=date(y, mo + 1, 5))
        s = self.client.get(reverse("budget_list")).context["suggestions"]
        self.assertEqual((s[0]["name"], s[0]["amount"]), ("Food", 1500))  # avg 1100 → next ৳500 step

    def test_saving_an_expense_warns_when_budget_crossed(self):
        Budget.objects.create(user=self.user, scope=BudgetScope.CATEGORY, category=self.food, amount=100)
        r = self.client.post(reverse("expense_create"), {"category": self.food.pk, "amount": "95", "date": timezone.localdate().isoformat(), "note": ""}, follow=True)
        self.assertContains(r, "95%")

    def test_dashboards_show_budgets(self):
        Budget.objects.create(user=self.user, scope=BudgetScope.CATEGORY, category=self.food, amount=100)
        Budget.objects.create(user=self.user, scope=BudgetScope.BAZAR, amount=5000)
        self.assertContains(self.client.get(reverse("expense_dashboard")), 'class="budget-mini"')
        self.assertIsNotNone(self.client.get(reverse("household_dashboard")).context["bazar_budget"])
