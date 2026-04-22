from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import IncomeSource, IncomeTransaction


class IncomeFilterTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="income_user", password="secret123")
        self.client.force_login(self.user)

        self.salary = IncomeSource.objects.create(user=self.user, name="Salary")
        self.freelance = IncomeSource.objects.create(user=self.user, name="Freelance")

        IncomeTransaction.objects.create(
            source=self.salary,
            amount=Decimal("1000.00"),
            date=date(2025, 1, 10),
        )
        IncomeTransaction.objects.create(
            source=self.salary,
            amount=Decimal("1500.00"),
            date=date(2026, 2, 10),
        )
        IncomeTransaction.objects.create(
            source=self.freelance,
            amount=Decimal("700.00"),
            date=date(2026, 3, 15),
        )

    def test_dashboard_filters_by_source_include(self):
        response = self.client.get(
            reverse("income_dashboard"),
            {"filter_mode": "include", "source": str(self.salary.id)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_income"], Decimal("2500.00"))
        self.assertEqual(response.context["source_labels"], ["Salary"])

    def test_dashboard_filters_by_source_exclude(self):
        response = self.client.get(
            reverse("income_dashboard"),
            {"filter_mode": "exclude", "source": str(self.salary.id)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_income"], Decimal("700.00"))
        self.assertEqual(response.context["source_labels"], ["Freelance"])

    def test_dashboard_filters_by_year_and_date_range(self):
        response = self.client.get(
            reverse("income_dashboard"),
            {"year": "2026", "date_from": "2026-02-01", "date_to": "2026-02-28"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_income"], Decimal("1500.00"))
        self.assertEqual(response.context["source_labels"], ["Salary"])

    def test_source_list_filters_and_stats(self):
        response = self.client.get(reverse("income_source_list"), {"year": "2026"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_sources"], 2)
        self.assertEqual(response.context["total_income"], Decimal("2200.00"))
        self.assertEqual(response.context["avg_income"], Decimal("1100.00"))

    def test_source_detail_filters_transactions(self):
        response = self.client.get(
            reverse("income_source_detail", kwargs={"pk": self.salary.pk}),
            {"year": "2026"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_source_income"], Decimal("1500.00"))
        self.assertEqual(response.context["transactions"].count(), 1)
