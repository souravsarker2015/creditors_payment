from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    Expense,
    ExpenseCategory,
    RecurringExpense,
    RecurringFrequency,
    RECURRING_CATCHUP_LIMIT,
    generate_due_recurring_expense,
)


class ExpenseFilterTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="expense_user", password="secret123")
        self.client.force_login(self.user)

        self.food = ExpenseCategory.objects.create(user=self.user, name="Food")
        self.travel = ExpenseCategory.objects.create(user=self.user, name="Travel")

        Expense.objects.create(
            user=self.user,
            category=self.food,
            amount=Decimal("300.00"),
            date=date(2025, 11, 10),
            note="Lunch",
        )
        Expense.objects.create(
            user=self.user,
            category=self.food,
            amount=Decimal("500.00"),
            date=date(2026, 2, 10),
            note="Groceries",
        )
        Expense.objects.create(
            user=self.user,
            category=self.travel,
            amount=Decimal("800.00"),
            date=date(2026, 3, 15),
            note="Bus ticket",
        )
        Expense.objects.create(
            user=self.user,
            category=None,
            amount=Decimal("200.00"),
            date=date(2026, 3, 20),
            note="General expense",
        )

    def test_dashboard_filters_by_category_include(self):
        response = self.client.get(
            reverse("expense_dashboard"),
            {"filter_mode": "include", "category": str(self.food.id)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_spent"], Decimal("800.00"))
        self.assertEqual(response.context["category_labels"], ["Food"])

    def test_dashboard_filters_by_category_exclude(self):
        response = self.client.get(
            reverse("expense_dashboard"),
            {"filter_mode": "exclude", "category": str(self.food.id)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_spent"], Decimal("1000.00"))

    def test_dashboard_filters_by_year_and_date_range(self):
        response = self.client.get(
            reverse("expense_dashboard"),
            {"year": "2026", "date_from": "2026-03-01", "date_to": "2026-03-31"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_spent"], Decimal("1000.00"))

    def test_expense_list_filters_and_stats(self):
        response = self.client.get(reverse("expense_list"), {"year": "2026"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_entries"], 3)
        self.assertEqual(response.context["total_spent"], Decimal("1500.00"))
        self.assertEqual(response.context["avg_expense"], Decimal("500.00"))


class RecurringExpenseTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="recurring_expense_user", password="secret123")
        self.other_user = User.objects.create_user(username="recurring_expense_other", password="secret123")
        self.category = ExpenseCategory.objects.create(user=self.user, name="Rent")
        self.today = timezone.now().date()

    def test_catches_up_all_missed_monthly_occurrences(self):
        schedule = RecurringExpense.objects.create(
            user=self.user, category=self.category, amount=Decimal("15000.00"), frequency=RecurringFrequency.MONTHLY,
            next_run_date=self.today - timedelta(days=95),
        )
        created = schedule.generate_due_transactions(today=self.today)
        self.assertEqual(created, 4)
        self.assertEqual(Expense.objects.filter(user=self.user).count(), 4)
        self.assertTrue(all(e.recurring_source_id == schedule.pk for e in Expense.objects.filter(user=self.user)))
        schedule.refresh_from_db()
        self.assertGreater(schedule.next_run_date, self.today)

    def test_optional_category_can_be_blank(self):
        schedule = RecurringExpense.objects.create(
            user=self.user, category=None, amount=Decimal("500.00"), frequency=RecurringFrequency.MONTHLY,
            next_run_date=self.today - timedelta(days=1),
        )
        schedule.generate_due_transactions(today=self.today)
        expense = Expense.objects.get(user=self.user)
        self.assertIsNone(expense.category)

    def test_paused_schedule_does_not_generate(self):
        schedule = RecurringExpense.objects.create(
            user=self.user, category=self.category, amount=Decimal("1000.00"), frequency=RecurringFrequency.MONTHLY,
            next_run_date=self.today - timedelta(days=1), is_active=False,
        )
        created = schedule.generate_due_transactions(today=self.today)
        self.assertEqual(created, 0)

    def test_catchup_capped_per_call_and_continues_next_call(self):
        schedule = RecurringExpense.objects.create(
            user=self.user, category=self.category, amount=Decimal("100.00"), frequency=RecurringFrequency.WEEKLY,
            next_run_date=self.today - timedelta(days=3 * 365),
        )
        first = schedule.generate_due_transactions(today=self.today)
        self.assertEqual(first, RECURRING_CATCHUP_LIMIT)
        second = schedule.generate_due_transactions(today=self.today)
        self.assertGreater(second, 0)

    def test_manager_function_respects_cross_user_isolation(self):
        RecurringExpense.objects.create(
            user=self.other_user, amount=Decimal("1000.00"), frequency=RecurringFrequency.MONTHLY,
            next_run_date=self.today - timedelta(days=1),
        )
        self.assertEqual(generate_due_recurring_expense(self.user), 0)
        self.assertEqual(generate_due_recurring_expense(self.other_user), 1)

    def test_skip_weekend_shifts_friday_to_thursday_without_drifting_anchor(self):
        friday = self.today
        while friday.weekday() != 4:
            friday += timedelta(days=1)
        thursday = friday - timedelta(days=1)

        schedule = RecurringExpense.objects.create(
            user=self.user, category=self.category, amount=Decimal("1000.00"), frequency=RecurringFrequency.MONTHLY,
            next_run_date=friday, skip_weekend=True,
        )
        schedule.generate_due_transactions(today=friday)
        self.assertEqual(Expense.objects.get(user=self.user).date, thursday)
        from .models import _add_months
        schedule.refresh_from_db()
        self.assertEqual(schedule.next_run_date, _add_months(friday, 1))

    def test_toggle_pause_and_resume_via_view(self):
        self.client.force_login(self.user)
        schedule = RecurringExpense.objects.create(
            user=self.user, category=self.category, amount=Decimal("1000.00"), frequency=RecurringFrequency.MONTHLY,
            next_run_date=self.today + timedelta(days=30),
        )
        self.client.post(reverse("recurring_expense_toggle", args=[schedule.pk]))
        schedule.refresh_from_db()
        self.assertFalse(schedule.is_active)

    def test_delete_schedule_keeps_past_generated_expenses(self):
        schedule = RecurringExpense.objects.create(
            user=self.user, category=self.category, amount=Decimal("1000.00"), frequency=RecurringFrequency.MONTHLY,
            next_run_date=self.today - timedelta(days=1),
        )
        schedule.generate_due_transactions(today=self.today)
        self.assertEqual(Expense.objects.filter(user=self.user).count(), 1)
        schedule.delete()
        self.assertEqual(Expense.objects.filter(user=self.user).count(), 1)
        self.assertIsNone(Expense.objects.get(user=self.user).recurring_source)
