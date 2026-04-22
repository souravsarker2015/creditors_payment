from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Debtor, DebtorCategory, Transaction


class DebtorCategoryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="debtoruser", password="secret123")
        self.client.force_login(self.user)

        self.family_debtor = Debtor.objects.create(
            user=self.user,
            name="Family Debtor",
            category=DebtorCategory.FAMILY,
        )
        self.client_debtor = Debtor.objects.create(
            user=self.user,
            name="Client Debtor",
            category=DebtorCategory.CLIENT,
        )

        Transaction.objects.create(
            debtor=self.family_debtor,
            transaction_type=Transaction.LEND,
            amount=Decimal("1000.00"),
            date=date(2026, 4, 1),
        )
        Transaction.objects.create(
            debtor=self.family_debtor,
            transaction_type=Transaction.RECEIVE,
            amount=Decimal("300.00"),
            date=date(2026, 4, 2),
        )
        Transaction.objects.create(
            debtor=self.client_debtor,
            transaction_type=Transaction.LEND,
            amount=Decimal("800.00"),
            date=date(2026, 4, 3),
        )
        Transaction.objects.create(
            debtor=self.client_debtor,
            transaction_type=Transaction.RECEIVE,
            amount=Decimal("100.00"),
            date=date(2026, 4, 4),
        )

    def test_debtor_default_category_is_other(self):
        debtor = Debtor.objects.create(user=self.user, name="Default Debtor")
        self.assertEqual(debtor.category, DebtorCategory.OTHER)

    def test_dashboard_with_include_category_filter(self):
        response = self.client.get(
            reverse("debtor_dashboard"),
            {"category": DebtorCategory.FAMILY, "filter_type": "include"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["filter_type"], "include")
        self.assertEqual(response.context["selected_categories"], [DebtorCategory.FAMILY])
        self.assertEqual(response.context["total_lent"], Decimal("1000.00"))
        self.assertEqual(response.context["total_received"], Decimal("300.00"))
        self.assertEqual(response.context["remaining"], Decimal("700.00"))
        self.assertEqual(response.context["debtor_labels"], ["Family Debtor"])

    def test_dashboard_with_exclude_category_filter(self):
        response = self.client.get(
            reverse("debtor_dashboard"),
            {"category": DebtorCategory.FAMILY, "filter_type": "exclude"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["filter_type"], "exclude")
        self.assertEqual(response.context["selected_categories"], [DebtorCategory.FAMILY])
        self.assertEqual(response.context["total_lent"], Decimal("800.00"))
        self.assertEqual(response.context["total_received"], Decimal("100.00"))
        self.assertEqual(response.context["remaining"], Decimal("700.00"))
        self.assertEqual(response.context["debtor_labels"], ["Client Debtor"])

    def test_dashboard_with_multiple_categories_exclude_results_empty(self):
        response = self.client.get(
            reverse("debtor_dashboard"),
            [
                ("category", DebtorCategory.FAMILY),
                ("category", DebtorCategory.CLIENT),
                ("filter_type", "exclude"),
            ],
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["selected_categories"],
            [DebtorCategory.FAMILY, DebtorCategory.CLIENT],
        )
        self.assertEqual(response.context["total_lent"], Decimal("0"))
        self.assertEqual(response.context["total_received"], Decimal("0"))
        self.assertEqual(response.context["remaining"], Decimal("0"))
        self.assertEqual(response.context["debtor_labels"], [])
        self.assertEqual(len(response.context["recent_transactions"]), 0)

    def test_list_with_include_category_filter(self):
        response = self.client.get(
            reverse("debtor_list"),
            {"category": DebtorCategory.CLIENT, "filter_type": "include"},
        )
        self.assertEqual(response.status_code, 200)

        debtors = list(response.context["debtors"])
        self.assertEqual(len(debtors), 1)
        self.assertEqual(debtors[0].name, "Client Debtor")
        self.assertEqual(response.context["total_lent"], Decimal("800.00"))
        self.assertEqual(response.context["total_received"], Decimal("100.00"))
        self.assertEqual(response.context["remaining"], Decimal("700.00"))

    def test_list_with_exclude_category_filter(self):
        response = self.client.get(
            reverse("debtor_list"),
            {"category": DebtorCategory.CLIENT, "filter_type": "exclude"},
        )
        self.assertEqual(response.status_code, 200)

        debtors = list(response.context["debtors"])
        self.assertEqual(len(debtors), 1)
        self.assertEqual(debtors[0].name, "Family Debtor")
        self.assertEqual(response.context["total_lent"], Decimal("1000.00"))
        self.assertEqual(response.context["total_received"], Decimal("300.00"))
        self.assertEqual(response.context["remaining"], Decimal("700.00"))
