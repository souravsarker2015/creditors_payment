from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

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

        debtors = list(response.context["page_obj"])
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

        debtors = list(response.context["page_obj"])
        self.assertEqual(len(debtors), 1)
        self.assertEqual(debtors[0].name, "Family Debtor")
        self.assertEqual(response.context["total_lent"], Decimal("1000.00"))
        self.assertEqual(response.context["total_received"], Decimal("300.00"))
        self.assertEqual(response.context["remaining"], Decimal("700.00"))

    def test_list_search_by_name_is_case_insensitive(self):
        response = self.client.get(reverse("debtor_list"), {"q": "CLIENT"})
        self.assertEqual(response.status_code, 200)

        debtors = list(response.context["page_obj"])
        self.assertEqual(len(debtors), 1)
        self.assertEqual(debtors[0].name, "Client Debtor")
        self.assertEqual(response.context["search_query"], "CLIENT")

    def test_list_payment_status_paid_filter(self):
        paid_debtor = Debtor.objects.create(
            user=self.user, name="Fully Repaid Friend", category=DebtorCategory.FRIEND
        )
        Transaction.objects.create(
            debtor=paid_debtor,
            transaction_type=Transaction.LEND,
            amount=Decimal("250.00"),
            date=date(2026, 4, 5),
        )
        Transaction.objects.create(
            debtor=paid_debtor,
            transaction_type=Transaction.RECEIVE,
            amount=Decimal("250.00"),
            date=date(2026, 4, 6),
        )

        response = self.client.get(reverse("debtor_list"), {"payment_status": "PAID"})
        self.assertEqual(response.status_code, 200)
        debtors = list(response.context["page_obj"])
        self.assertEqual([d.name for d in debtors], ["Fully Repaid Friend"])

    def test_list_payment_status_unpaid_filter(self):
        paid_debtor = Debtor.objects.create(
            user=self.user, name="Fully Repaid Friend", category=DebtorCategory.FRIEND
        )
        Transaction.objects.create(
            debtor=paid_debtor,
            transaction_type=Transaction.LEND,
            amount=Decimal("250.00"),
            date=date(2026, 4, 5),
        )
        Transaction.objects.create(
            debtor=paid_debtor,
            transaction_type=Transaction.RECEIVE,
            amount=Decimal("250.00"),
            date=date(2026, 4, 6),
        )

        response = self.client.get(reverse("debtor_list"), {"payment_status": "UNPAID"})
        self.assertEqual(response.status_code, 200)
        debtors = list(response.context["page_obj"])
        self.assertCountEqual([d.name for d in debtors], ["Family Debtor", "Client Debtor"])

    def test_list_payment_status_is_independent_of_category_filter_type(self):
        """Regression test: payment_status must not be silently flipped by the
        category include/exclude toggle (`filter_type`)."""
        paid_debtor = Debtor.objects.create(
            user=self.user, name="Fully Repaid Friend", category=DebtorCategory.FRIEND
        )
        Transaction.objects.create(
            debtor=paid_debtor,
            transaction_type=Transaction.LEND,
            amount=Decimal("250.00"),
            date=date(2026, 4, 5),
        )
        Transaction.objects.create(
            debtor=paid_debtor,
            transaction_type=Transaction.RECEIVE,
            amount=Decimal("250.00"),
            date=date(2026, 4, 6),
        )

        response = self.client.get(
            reverse("debtor_list"),
            {
                "payment_status": "PAID",
                "category": DebtorCategory.CLIENT,
                "filter_type": "exclude",
            },
        )
        self.assertEqual(response.status_code, 200)
        debtors = list(response.context["page_obj"])
        self.assertEqual([d.name for d in debtors], ["Fully Repaid Friend"])


class DebtorDueDateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="debtor_duedate_user", password="secret123")
        self.today = timezone.now().date()

    def _debtor_with_balance(self, due_date=None, lent=Decimal("1000.00"), received=Decimal("0.00")):
        debtor = Debtor.objects.create(
            user=self.user, name="Test Debtor", category=DebtorCategory.FAMILY, due_date=due_date
        )
        Transaction.objects.create(
            debtor=debtor, transaction_type=Transaction.LEND, amount=lent, date=self.today - timedelta(days=30)
        )
        if received > 0:
            Transaction.objects.create(
                debtor=debtor, transaction_type=Transaction.RECEIVE, amount=received, date=self.today - timedelta(days=1)
            )
        return debtor

    def test_is_overdue_true_when_due_date_passed_and_unpaid(self):
        debtor = self._debtor_with_balance(due_date=self.today - timedelta(days=3))
        self.assertTrue(debtor.is_overdue)
        self.assertFalse(debtor.is_due_soon)

    def test_is_due_soon_true_within_window_not_yet_overdue(self):
        debtor = self._debtor_with_balance(due_date=self.today + timedelta(days=3))
        self.assertFalse(debtor.is_overdue)
        self.assertTrue(debtor.is_due_soon)

    def test_is_due_soon_false_beyond_window(self):
        debtor = self._debtor_with_balance(due_date=self.today + timedelta(days=30))
        self.assertFalse(debtor.is_overdue)
        self.assertFalse(debtor.is_due_soon)

    def test_fully_received_balance_never_shows_overdue_even_with_past_due_date(self):
        debtor = self._debtor_with_balance(
            due_date=self.today - timedelta(days=10), lent=Decimal("500.00"), received=Decimal("500.00")
        )
        self.assertFalse(debtor.is_overdue)
        self.assertFalse(debtor.is_due_soon)

    def test_no_due_date_never_flagged(self):
        debtor = self._debtor_with_balance(due_date=None)
        self.assertFalse(debtor.is_overdue)
        self.assertFalse(debtor.is_due_soon)
