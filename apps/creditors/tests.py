from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Creditor, CreditorCategory, Transaction, InterestType, InterestBasis


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

        creditors = list(response.context["page_obj"])
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

        creditors = list(response.context["page_obj"])
        self.assertEqual(len(creditors), 1)
        self.assertEqual(creditors[0].name, "City Bank")
        self.assertEqual(response.context["total_borrowed"], Decimal("500.00"))
        self.assertEqual(response.context["total_paid"], Decimal("100.00"))
        self.assertEqual(response.context["remaining"], Decimal("400.00"))

    def test_creditor_list_search_by_name_is_case_insensitive(self):
        response = self.client.get(reverse("creditor_list"), {"q": "family"})
        self.assertEqual(response.status_code, 200)

        creditors = list(response.context["page_obj"])
        self.assertEqual(len(creditors), 1)
        self.assertEqual(creditors[0].name, "Family Lender")
        self.assertEqual(response.context["search_query"], "family")

    def test_creditor_list_search_combines_with_category_filter(self):
        response = self.client.get(
            reverse("creditor_list"),
            {"q": "bank", "category": CreditorCategory.FAMILY},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["page_obj"]), [])

    def test_creditor_list_payment_status_paid_filter(self):
        paid_creditor = Creditor.objects.create(
            user=self.user, name="Paid Off Uncle", category=CreditorCategory.FAMILY
        )
        Transaction.objects.create(
            creditor=paid_creditor,
            transaction_type=Transaction.BORROW,
            amount=Decimal("400.00"),
            date=date(2026, 4, 5),
        )
        Transaction.objects.create(
            creditor=paid_creditor,
            transaction_type=Transaction.REPAY,
            amount=Decimal("400.00"),
            date=date(2026, 4, 6),
        )

        response = self.client.get(reverse("creditor_list"), {"payment_status": "PAID"})
        self.assertEqual(response.status_code, 200)
        creditors = list(response.context["page_obj"])
        self.assertEqual([c.name for c in creditors], ["Paid Off Uncle"])

    def test_creditor_list_payment_status_unpaid_filter(self):
        paid_creditor = Creditor.objects.create(
            user=self.user, name="Paid Off Uncle", category=CreditorCategory.FAMILY
        )
        Transaction.objects.create(
            creditor=paid_creditor,
            transaction_type=Transaction.BORROW,
            amount=Decimal("400.00"),
            date=date(2026, 4, 5),
        )
        Transaction.objects.create(
            creditor=paid_creditor,
            transaction_type=Transaction.REPAY,
            amount=Decimal("400.00"),
            date=date(2026, 4, 6),
        )

        response = self.client.get(reverse("creditor_list"), {"payment_status": "UNPAID"})
        self.assertEqual(response.status_code, 200)
        creditors = list(response.context["page_obj"])
        self.assertCountEqual([c.name for c in creditors], ["Family Lender", "City Bank"])

    def test_creditor_list_payment_status_is_independent_of_category_filter_type(self):
        """Regression test: payment_status must not be silently flipped by the
        category include/exclude toggle (`filter_type`)."""
        paid_creditor = Creditor.objects.create(
            user=self.user, name="Paid Off Uncle", category=CreditorCategory.FAMILY
        )
        Transaction.objects.create(
            creditor=paid_creditor,
            transaction_type=Transaction.BORROW,
            amount=Decimal("400.00"),
            date=date(2026, 4, 5),
        )
        Transaction.objects.create(
            creditor=paid_creditor,
            transaction_type=Transaction.REPAY,
            amount=Decimal("400.00"),
            date=date(2026, 4, 6),
        )

        response = self.client.get(
            reverse("creditor_list"),
            {
                "payment_status": "PAID",
                "category": CreditorCategory.BANK,
                "filter_type": "exclude",
            },
        )
        self.assertEqual(response.status_code, 200)
        creditors = list(response.context["page_obj"])
        # City Bank is excluded by category; of the remaining creditors, only
        # the fully-repaid one should show up for payment_status=PAID.
        self.assertEqual([c.name for c in creditors], ["Paid Off Uncle"])


class CreditorDueDateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="duedate_user", password="secret123")
        self.today = timezone.now().date()

    def _creditor_with_balance(self, due_date=None, borrowed=Decimal("1000.00"), repaid=Decimal("0.00")):
        creditor = Creditor.objects.create(
            user=self.user, name="Test Creditor", category=CreditorCategory.FAMILY, due_date=due_date
        )
        Transaction.objects.create(
            creditor=creditor, transaction_type=Transaction.BORROW, amount=borrowed, date=self.today - timedelta(days=30)
        )
        if repaid > 0:
            Transaction.objects.create(
                creditor=creditor, transaction_type=Transaction.REPAY, amount=repaid, date=self.today - timedelta(days=1)
            )
        return creditor

    def test_is_overdue_true_when_due_date_passed_and_unpaid(self):
        creditor = self._creditor_with_balance(due_date=self.today - timedelta(days=3))
        self.assertTrue(creditor.is_overdue)
        self.assertFalse(creditor.is_due_soon)

    def test_is_due_soon_true_within_window_not_yet_overdue(self):
        creditor = self._creditor_with_balance(due_date=self.today + timedelta(days=3))
        self.assertFalse(creditor.is_overdue)
        self.assertTrue(creditor.is_due_soon)

    def test_is_due_soon_false_beyond_window(self):
        creditor = self._creditor_with_balance(due_date=self.today + timedelta(days=30))
        self.assertFalse(creditor.is_overdue)
        self.assertFalse(creditor.is_due_soon)

    def test_fully_repaid_balance_never_shows_overdue_even_with_past_due_date(self):
        creditor = self._creditor_with_balance(
            due_date=self.today - timedelta(days=10), borrowed=Decimal("500.00"), repaid=Decimal("500.00")
        )
        self.assertFalse(creditor.is_overdue)
        self.assertFalse(creditor.is_due_soon)

    def test_no_due_date_never_flagged(self):
        creditor = self._creditor_with_balance(due_date=None)
        self.assertFalse(creditor.is_overdue)
        self.assertFalse(creditor.is_due_soon)


class CreditorInterestTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="interest_user", password="secret123")
        self.today = timezone.now().date()

    def _borrow(self, creditor, amount, days_ago):
        Transaction.objects.create(
            creditor=creditor, transaction_type=Transaction.BORROW, amount=amount, date=self.today - timedelta(days=days_ago)
        )

    def test_no_interest_type_accrues_nothing(self):
        creditor = Creditor.objects.create(user=self.user, name="No Interest", category=CreditorCategory.FAMILY)
        self._borrow(creditor, Decimal("1000.00"), 30)
        self.assertEqual(creditor.accrued_interest, Decimal("0.00"))

    def test_fixed_one_time_interest_is_flat_regardless_of_time(self):
        creditor = Creditor.objects.create(
            user=self.user, name="Flat Fee", category=CreditorCategory.MONEYLENDER,
            interest_type=InterestType.FIXED, interest_fixed_amount=Decimal("250.00"),
        )
        self._borrow(creditor, Decimal("1000.00"), 1)
        self.assertEqual(creditor.accrued_interest, Decimal("250.00"))
        # Still flat even much later — Fixed Amount has no time component.
        creditor2 = Creditor.objects.create(
            user=self.user, name="Flat Fee 2", category=CreditorCategory.MONEYLENDER,
            interest_type=InterestType.FIXED, interest_fixed_amount=Decimal("250.00"),
        )
        self._borrow(creditor2, Decimal("1000.00"), 400)
        self.assertEqual(creditor2.accrued_interest, Decimal("250.00"))

    def test_monthly_percentage_prorates_by_days_elapsed(self):
        creditor = Creditor.objects.create(
            user=self.user, name="Percent Lender", category=CreditorCategory.BANK,
            interest_type=InterestType.MONTHLY, interest_basis=InterestBasis.PERCENTAGE,
            interest_rate=Decimal("10.00"),
        )
        self._borrow(creditor, Decimal("1000.00"), 15)
        # 10% of 1000 = 100/month, prorated for 15/30 days = 50.00
        self.assertEqual(creditor.accrued_interest, Decimal("50.00"))

    def test_monthly_fixed_basis_prorates_the_flat_amount(self):
        creditor = Creditor.objects.create(
            user=self.user, name="Flat Monthly", category=CreditorCategory.MICROFINANCE,
            interest_type=InterestType.MONTHLY, interest_basis=InterestBasis.FIXED,
            interest_fixed_amount=Decimal("600.00"),
        )
        self._borrow(creditor, Decimal("1000.00"), 15)
        # ৳600/month prorated for 15/30 days = 300.00
        self.assertEqual(creditor.accrued_interest, Decimal("300.00"))

    def test_accrued_interest_zero_when_balance_is_zero(self):
        creditor = Creditor.objects.create(
            user=self.user, name="Settled", category=CreditorCategory.BANK,
            interest_type=InterestType.MONTHLY, interest_basis=InterestBasis.PERCENTAGE,
            interest_rate=Decimal("10.00"),
        )
        self._borrow(creditor, Decimal("1000.00"), 15)
        Transaction.objects.create(
            creditor=creditor, transaction_type=Transaction.REPAY, amount=Decimal("1000.00"), date=self.today
        )
        self.assertEqual(creditor.accrued_interest, Decimal("0.00"))

    def test_post_accrued_interest_creates_borrow_transaction(self):
        creditor = Creditor.objects.create(
            user=self.user, name="Post Me", category=CreditorCategory.BANK,
            interest_type=InterestType.MONTHLY, interest_basis=InterestBasis.PERCENTAGE,
            interest_rate=Decimal("10.00"),
        )
        self._borrow(creditor, Decimal("1000.00"), 30)
        principal_before = creditor.remaining
        posted = creditor.post_accrued_interest()
        self.assertIsNotNone(posted)
        self.assertEqual(posted.transaction_type, Transaction.BORROW)
        self.assertEqual(posted.amount, Decimal("100.00"))
        creditor.refresh_from_db()
        self.assertEqual(creditor.remaining, principal_before + Decimal("100.00"))

    def test_post_accrued_interest_returns_none_when_nothing_accrued(self):
        creditor = Creditor.objects.create(user=self.user, name="Nothing", category=CreditorCategory.FAMILY)
        self._borrow(creditor, Decimal("1000.00"), 30)
        self.assertIsNone(creditor.post_accrued_interest())

    def test_post_accrued_interest_clears_fixed_one_time_amount_after_posting(self):
        creditor = Creditor.objects.create(
            user=self.user, name="One Time Fee", category=CreditorCategory.MONEYLENDER,
            interest_type=InterestType.FIXED, interest_fixed_amount=Decimal("250.00"),
        )
        self._borrow(creditor, Decimal("1000.00"), 1)
        creditor.post_accrued_interest()
        creditor.refresh_from_db()
        self.assertIsNone(creditor.interest_fixed_amount)
        # Posting again should now do nothing — the one-off charge is spent.
        self.assertEqual(creditor.accrued_interest, Decimal("0.00"))
        self.assertIsNone(creditor.post_accrued_interest())

    def test_post_accrued_interest_keeps_periodic_fixed_amount_but_resets_clock(self):
        creditor = Creditor.objects.create(
            user=self.user, name="Recurring Flat", category=CreditorCategory.MICROFINANCE,
            interest_type=InterestType.MONTHLY, interest_basis=InterestBasis.FIXED,
            interest_fixed_amount=Decimal("600.00"),
        )
        self._borrow(creditor, Decimal("1000.00"), 30)
        creditor.post_accrued_interest()
        creditor.refresh_from_db()
        # A periodic Fixed Amount basis keeps recurring — only the accrual clock resets.
        self.assertEqual(creditor.interest_fixed_amount, Decimal("600.00"))
        self.assertEqual(creditor.accrued_interest, Decimal("0.00"))
