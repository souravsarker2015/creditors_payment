from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Creditor, CreditorCategory, Transaction


class CreditorCategoryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="secret123")
        self.client.force_login(self.user)

        self.family_creditor = Creditor.objects.create(
            user=self.user,
            name="Family Lender",
            category=CreditorCategory.FAMILY,
        )
        self.bank_creditor = Creditor.objects.create(
            user=self.user,
            name="City Bank",
            category=CreditorCategory.BANK,
        )

        Transaction.objects.create(
            creditor=self.family_creditor,
            transaction_type=Transaction.BORROW,
            amount=Decimal("1000.00"),
            date=date(2026, 4, 1),
        )
        Transaction.objects.create(
            creditor=self.family_creditor,
            transaction_type=Transaction.REPAY,
            amount=Decimal("200.00"),
            date=date(2026, 4, 2),
        )
        Transaction.objects.create(
            creditor=self.bank_creditor,
            transaction_type=Transaction.BORROW,
            amount=Decimal("500.00"),
            date=date(2026, 4, 3),
        )
        Transaction.objects.create(
            creditor=self.bank_creditor,
            transaction_type=Transaction.REPAY,
            amount=Decimal("100.00"),
            date=date(2026, 4, 4),
        )

    def test_creditor_default_category_is_other(self):
        creditor = Creditor.objects.create(user=self.user, name="Default Category Creditor")
        self.assertEqual(creditor.category, CreditorCategory.OTHER)

    def test_dashboard_without_category_is_unfiltered(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)

        self.assertEqual(response.context["selected_category"], "")
        self.assertEqual(response.context["selected_categories"], [])
        self.assertEqual(response.context["filter_type"], "include")
        self.assertEqual(response.context["total_borrowed"], Decimal("1500.00"))
        self.assertEqual(response.context["total_paid"], Decimal("300.00"))
        self.assertEqual(response.context["remaining"], Decimal("1200.00"))

        self.assertCountEqual(
            response.context["creditor_labels"],
            ["Family Lender", "City Bank"],
        )
        self.assertEqual(len(response.context["recent_transactions"]), 4)

    def test_dashboard_with_valid_category_filters_all_sections(self):
        response = self.client.get(reverse("dashboard"), {"category": CreditorCategory.FAMILY})
        self.assertEqual(response.status_code, 200)

        self.assertEqual(response.context["selected_category"], CreditorCategory.FAMILY)
        self.assertEqual(response.context["selected_categories"], [CreditorCategory.FAMILY])
        self.assertEqual(response.context["filter_type"], "include")
        self.assertEqual(response.context["total_borrowed"], Decimal("1000.00"))
        self.assertEqual(response.context["total_paid"], Decimal("200.00"))
        self.assertEqual(response.context["remaining"], Decimal("800.00"))

        self.assertEqual(response.context["creditor_labels"], ["Family Lender"])
        self.assertEqual(response.context["creditor_remaining"], [800.0])
        self.assertEqual(response.context["creditor_paid"], [200.0])

        recent = list(response.context["recent_transactions"])
        self.assertEqual(len(recent), 2)
        self.assertTrue(all(tx.creditor.category == CreditorCategory.FAMILY for tx in recent))

    def test_dashboard_with_invalid_category_falls_back_to_unfiltered(self):
        response = self.client.get(reverse("dashboard"), {"category": "INVALID"})
        self.assertEqual(response.status_code, 200)

        self.assertEqual(response.context["selected_category"], "")
        self.assertEqual(response.context["selected_categories"], [])
        self.assertEqual(response.context["filter_type"], "include")
        self.assertEqual(response.context["total_borrowed"], Decimal("1500.00"))
        self.assertEqual(response.context["total_paid"], Decimal("300.00"))
        self.assertEqual(response.context["remaining"], Decimal("1200.00"))

        self.assertCountEqual(
            response.context["creditor_labels"],
            ["Family Lender", "City Bank"],
        )
        self.assertEqual(len(response.context["recent_transactions"]), 4)

    def test_dashboard_with_exclude_category_filters_all_sections(self):
        response = self.client.get(
            reverse("dashboard"),
            {"category": CreditorCategory.FAMILY, "filter_type": "exclude"},
        )
        self.assertEqual(response.status_code, 200)

        self.assertEqual(response.context["selected_category"], CreditorCategory.FAMILY)
        self.assertEqual(response.context["selected_categories"], [CreditorCategory.FAMILY])
        self.assertEqual(response.context["filter_type"], "exclude")
        self.assertEqual(response.context["total_borrowed"], Decimal("500.00"))
        self.assertEqual(response.context["total_paid"], Decimal("100.00"))
        self.assertEqual(response.context["remaining"], Decimal("400.00"))

        self.assertEqual(response.context["creditor_labels"], ["City Bank"])
        self.assertEqual(response.context["creditor_remaining"], [400.0])
        self.assertEqual(response.context["creditor_paid"], [100.0])

        recent = list(response.context["recent_transactions"])
        self.assertEqual(len(recent), 2)
        self.assertTrue(all(tx.creditor.category != CreditorCategory.FAMILY for tx in recent))

    def test_dashboard_with_invalid_filter_type_falls_back_to_include(self):
        response = self.client.get(
            reverse("dashboard"),
            {"category": CreditorCategory.FAMILY, "filter_type": "wrong"},
        )
        self.assertEqual(response.status_code, 200)

        self.assertEqual(response.context["selected_category"], CreditorCategory.FAMILY)
        self.assertEqual(response.context["selected_categories"], [CreditorCategory.FAMILY])
        self.assertEqual(response.context["filter_type"], "include")
        self.assertEqual(response.context["total_borrowed"], Decimal("1000.00"))
        self.assertEqual(response.context["total_paid"], Decimal("200.00"))
        self.assertEqual(response.context["remaining"], Decimal("800.00"))

    def test_dashboard_with_multiple_categories_include(self):
        response = self.client.get(
            reverse("dashboard"),
            [("category", CreditorCategory.FAMILY), ("category", CreditorCategory.BANK)],
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["selected_categories"],
            [CreditorCategory.FAMILY, CreditorCategory.BANK],
        )
        self.assertEqual(response.context["filter_type"], "include")
        self.assertEqual(response.context["total_borrowed"], Decimal("1500.00"))
        self.assertEqual(response.context["total_paid"], Decimal("300.00"))
        self.assertEqual(response.context["remaining"], Decimal("1200.00"))
        self.assertCountEqual(response.context["creditor_labels"], ["Family Lender", "City Bank"])

    def test_dashboard_with_multiple_categories_exclude(self):
        response = self.client.get(
            reverse("dashboard"),
            [
                ("category", CreditorCategory.FAMILY),
                ("category", CreditorCategory.BANK),
                ("filter_type", "exclude"),
            ],
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["selected_categories"],
            [CreditorCategory.FAMILY, CreditorCategory.BANK],
        )
        self.assertEqual(response.context["filter_type"], "exclude")
        self.assertEqual(response.context["total_borrowed"], Decimal("0"))
        self.assertEqual(response.context["total_paid"], Decimal("0"))
        self.assertEqual(response.context["remaining"], Decimal("0"))
        self.assertEqual(response.context["creditor_labels"], [])
        self.assertEqual(len(response.context["recent_transactions"]), 0)

    def test_creditor_list_with_include_category_filter(self):
        response = self.client.get(
            reverse("creditor_list"),
            {"category": CreditorCategory.FAMILY, "filter_type": "include"},
        )
        self.assertEqual(response.status_code, 200)

        creditors = list(response.context["creditors"])
        self.assertEqual(len(creditors), 1)
        self.assertEqual(creditors[0].name, "Family Lender")
        self.assertEqual(response.context["total_borrowed"], Decimal("1000.00"))
        self.assertEqual(response.context["total_paid"], Decimal("200.00"))
        self.assertEqual(response.context["remaining"], Decimal("800.00"))

    def test_creditor_list_with_exclude_category_filter(self):
        response = self.client.get(
            reverse("creditor_list"),
            {"category": CreditorCategory.FAMILY, "filter_type": "exclude"},
        )
        self.assertEqual(response.status_code, 200)

        creditors = list(response.context["creditors"])
        self.assertEqual(len(creditors), 1)
        self.assertEqual(creditors[0].name, "City Bank")
        self.assertEqual(response.context["total_borrowed"], Decimal("500.00"))
        self.assertEqual(response.context["total_paid"], Decimal("100.00"))
        self.assertEqual(response.context["remaining"], Decimal("400.00"))
