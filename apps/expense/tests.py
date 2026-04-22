from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Expense, ExpenseCategory


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
