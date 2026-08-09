from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.contributors.models import Contributor, Contribution
from apps.creditors.models import Creditor, Transaction as CreditorTransaction
from apps.debtors.models import Debtor, Transaction as DebtorTransaction
from apps.expense.models import Expense
from apps.household.models import HouseholdMember, Purchase, Settlement
from apps.income.models import IncomeSource, IncomeTransaction
from apps.shops.models import Shop, Transaction as ShopTransaction


class NetWorthTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="networth_user", password="secret123")
        self.client.force_login(self.user)

    def test_zero_data_does_not_crash(self):
        response = self.client.get(reverse("networth"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["net_position"], 0)
        self.assertEqual(response.context["receivables"], 0)
        self.assertEqual(response.context["payables"], 0)

    def test_receivables_and_payables_combine_into_net_balance(self):
        debtor = Debtor.objects.create(user=self.user, name="Owes Me")
        DebtorTransaction.objects.create(debtor=debtor, transaction_type=DebtorTransaction.LEND, amount=Decimal("1000.00"), date=date(2026, 1, 1))
        DebtorTransaction.objects.create(debtor=debtor, transaction_type=DebtorTransaction.RECEIVE, amount=Decimal("200.00"), date=date(2026, 1, 5))

        creditor = Creditor.objects.create(user=self.user, name="I Owe")
        CreditorTransaction.objects.create(creditor=creditor, transaction_type=CreditorTransaction.BORROW, amount=Decimal("300.00"), date=date(2026, 1, 1))
        CreditorTransaction.objects.create(creditor=creditor, transaction_type=CreditorTransaction.REPAY, amount=Decimal("50.00"), date=date(2026, 1, 5))

        shop = Shop.objects.create(user=self.user, name="Corner Store")
        ShopTransaction.objects.create(shop=shop, transaction_type=ShopTransaction.PURCHASE, amount=Decimal("100.00"), date=date(2026, 1, 1))

        response = self.client.get(reverse("networth"))
        self.assertEqual(response.context["receivables"], Decimal("800.00"))
        self.assertEqual(response.context["creditors_payable"], Decimal("250.00"))
        self.assertEqual(response.context["shops_payable"], Decimal("100.00"))
        self.assertEqual(response.context["payables"], Decimal("350.00"))
        self.assertEqual(response.context["net_balance"], Decimal("450.00"))  # 800 - 350

    def test_lifetime_cash_flow_combines_income_and_contributions_minus_expense(self):
        source = IncomeSource.objects.create(user=self.user, name="Salary")
        IncomeTransaction.objects.create(source=source, amount=Decimal("50000.00"), date=date(2026, 1, 1))

        contributor = Contributor.objects.create(user=self.user, name="Uncle")
        Contribution.objects.create(contributor=contributor, amount=Decimal("5000.00"), date=date(2026, 1, 1))

        Expense.objects.create(user=self.user, amount=Decimal("10000.00"), date=date(2026, 1, 1))

        response = self.client.get(reverse("networth"))
        self.assertEqual(response.context["total_income"], Decimal("55000.00"))
        self.assertEqual(response.context["total_expense"], Decimal("10000.00"))
        self.assertEqual(response.context["net_cash_flow"], Decimal("45000.00"))

    def test_household_purchase_fronted_by_member_counted_once_not_twice(self):
        """The one real accounting trap: a purchase a member fronted must show up
        as that member's payable, and must NOT also be counted as spending —
        otherwise the same taka is subtracted from net position twice."""
        member = HouseholdMember.objects.create(user=self.user, name="Karim")
        Purchase.objects.create(user=self.user, buyer=member, amount=Decimal("500.00"), date=date(2026, 1, 1))

        response = self.client.get(reverse("networth"))
        # Counted once, as the member's payable...
        self.assertEqual(response.context["household_payable"], Decimal("500.00"))
        self.assertEqual(response.context["payables"], Decimal("500.00"))
        # ...and NOT again as household spending.
        self.assertEqual(response.context["household_spent_by_you"], Decimal("0.00"))
        self.assertEqual(response.context["total_expense"], Decimal("0.00"))

    def test_household_purchase_with_no_buyer_counted_as_spending_not_payable(self):
        """A purchase nobody fronted (paid directly by the account owner) is
        ordinary spending, not a debt to anyone."""
        Purchase.objects.create(user=self.user, buyer=None, amount=Decimal("300.00"), date=date(2026, 1, 1))

        response = self.client.get(reverse("networth"))
        self.assertEqual(response.context["household_payable"], Decimal("0.00"))
        self.assertEqual(response.context["household_spent_by_you"], Decimal("300.00"))
        self.assertEqual(response.context["total_expense"], Decimal("300.00"))

    def test_settled_household_member_no_longer_counts_as_payable(self):
        member = HouseholdMember.objects.create(user=self.user, name="Karim")
        Purchase.objects.create(user=self.user, buyer=member, amount=Decimal("500.00"), date=date(2026, 1, 1))
        Settlement.objects.create(member=member, amount=Decimal("500.00"), date=date(2026, 1, 5))

        response = self.client.get(reverse("networth"))
        self.assertEqual(response.context["household_payable"], Decimal("0.00"))

    def test_overpaid_household_member_does_not_offset_other_payables(self):
        """An overpaid member has a negative balance_due — that must be clipped
        to 0, not treated as a negative debt that reduces what's owed elsewhere."""
        member = HouseholdMember.objects.create(user=self.user, name="Karim")
        Purchase.objects.create(user=self.user, buyer=member, amount=Decimal("100.00"), date=date(2026, 1, 1))
        Settlement.objects.create(member=member, amount=Decimal("150.00"), date=date(2026, 1, 5))
        self.assertLess(member.balance_due, 0)

        creditor = Creditor.objects.create(user=self.user, name="I Owe")
        CreditorTransaction.objects.create(creditor=creditor, transaction_type=CreditorTransaction.BORROW, amount=Decimal("200.00"), date=date(2026, 1, 1))

        response = self.client.get(reverse("networth"))
        self.assertEqual(response.context["household_payable"], Decimal("0.00"))
        self.assertEqual(response.context["payables"], Decimal("200.00"))

    def test_accrued_but_unposted_interest_is_excluded_from_net_worth(self):
        from apps.creditors.models import InterestType, InterestBasis

        creditor = Creditor.objects.create(
            user=self.user, name="Bank Loan", interest_type=InterestType.MONTHLY,
            interest_basis=InterestBasis.PERCENTAGE, interest_rate=Decimal("10.00"),
        )
        CreditorTransaction.objects.create(
            creditor=creditor, transaction_type=CreditorTransaction.BORROW, amount=Decimal("1000.00"), date=date(2026, 1, 1)
        )
        self.assertGreater(creditor.accrued_interest, 0)

        response = self.client.get(reverse("networth"))
        # Only the real, posted principal counts — the live interest estimate does not.
        self.assertEqual(response.context["creditors_payable"], Decimal("1000.00"))

    def test_net_position_is_sum_of_balance_and_cash_flow(self):
        debtor = Debtor.objects.create(user=self.user, name="Owes Me")
        DebtorTransaction.objects.create(debtor=debtor, transaction_type=DebtorTransaction.LEND, amount=Decimal("1000.00"), date=date(2026, 1, 1))

        source = IncomeSource.objects.create(user=self.user, name="Salary")
        IncomeTransaction.objects.create(source=source, amount=Decimal("500.00"), date=date(2026, 1, 1))

        response = self.client.get(reverse("networth"))
        expected = response.context["net_balance"] + response.context["net_cash_flow"]
        self.assertEqual(response.context["net_position"], expected)
        self.assertEqual(response.context["net_position"], Decimal("1500.00"))

    def test_figures_never_leak_between_users(self):
        other_user = User.objects.create_user(username="networth_other", password="secret123")
        other_source = IncomeSource.objects.create(user=other_user, name="Other Salary")
        IncomeTransaction.objects.create(source=other_source, amount=Decimal("99999.00"), date=date(2026, 1, 1))

        source = IncomeSource.objects.create(user=self.user, name="My Salary")
        IncomeTransaction.objects.create(source=source, amount=Decimal("100.00"), date=date(2026, 1, 1))

        response = self.client.get(reverse("networth"))
        self.assertEqual(response.context["income_earned"], Decimal("100.00"))

        other_client = self.client_class()
        other_client.force_login(other_user)
        other_response = other_client.get(reverse("networth"))
        self.assertEqual(other_response.context["income_earned"], Decimal("99999.00"))
