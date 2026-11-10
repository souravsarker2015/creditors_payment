"""Wallet balances added up by the database must match the entry-by-entry
history exactly, and paying more than a wallet holds is pointed out."""
from datetime import date, timedelta
from decimal import Decimal as D

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.contributors.models import Contribution, Contributor
from apps.creditors.models import Creditor, Transaction as CreditorTx
from apps.debtors.models import Debtor, Transaction as DebtorTx
from apps.expense.models import Expense
from apps.household.models import HouseholdMember, Purchase, Settlement
from apps.income.models import IncomeSource, IncomeTransaction
from apps.shops.models import Shop, Transaction as ShopTx

from .. import services
from ..models import Adjustment, Transfer, Wallet

TODAY = date.today()


class BalanceSumTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("me", password="pw12345!")
        self.client.force_login(self.user)
        start = TODAY - timedelta(days=20)
        self.cash = Wallet.objects.create(user=self.user, name="Cash", opening_balance=D("1000"), opening_date=start)
        self.bank = Wallet.objects.create(user=self.user, name="Bank", opening_balance=D("50000"), opening_date=start)
        self.late = Wallet.objects.create(user=self.user, name="New bKash", opening_balance=D("300"), opening_date=TODAY - timedelta(days=2))

    def fill(self):
        u, cash, bank, late = self.user, self.cash, self.bank, self.late
        old = TODAY - timedelta(days=60)          # before every opening date: must not count
        Expense.objects.create(user=u, amount=D("120.50"), date=TODAY, wallet=cash)
        Expense.objects.create(user=u, amount=D("999"), date=old, wallet=cash)
        Expense.objects.create(user=u, amount=D("40"), date=TODAY - timedelta(days=5), wallet=late)   # before New bKash opened
        src = IncomeSource.objects.create(user=u, name="Salary")
        IncomeTransaction.objects.create(source=src, amount=D("30000"), date=TODAY, wallet=bank)
        cr = Creditor.objects.create(user=u, name="Karim")
        CreditorTx.objects.create(creditor=cr, transaction_type=CreditorTx.BORROW, amount=D("5000"), date=TODAY, wallet=cash)
        CreditorTx.objects.create(creditor=cr, transaction_type=CreditorTx.REPAY, amount=D("700"), date=TODAY, wallet=bank)
        dr = Debtor.objects.create(user=u, name="Rafi")
        DebtorTx.objects.create(debtor=dr, transaction_type=DebtorTx.LEND, amount=D("2500"), date=TODAY, wallet=bank)
        DebtorTx.objects.create(debtor=dr, transaction_type=DebtorTx.RECEIVE, amount=D("400"), date=TODAY, wallet=late)
        shop = Shop.objects.create(user=u, name="Store")
        ShopTx.objects.create(shop=shop, transaction_type=ShopTx.PURCHASE, amount=D("800"), date=TODAY)
        ShopTx.objects.create(shop=shop, transaction_type=ShopTx.PAYMENT, amount=D("600"), date=TODAY, wallet=cash)
        member = HouseholdMember.objects.create(user=u, name="Abba")
        Purchase.objects.create(user=u, amount=D("350"), date=TODAY, wallet=cash)
        Purchase.objects.create(user=u, amount=D("900"), date=TODAY, buyer=member, wallet=cash)   # fronted by Abba: moves no wallet of yours
        Settlement.objects.create(member=member, amount=D("900"), date=TODAY, wallet=bank)
        giver = Contributor.objects.create(user=u, name="Uncle")
        Contribution.objects.create(contributor=giver, amount=D("1500"), date=TODAY, wallet=late)
        Transfer.objects.create(user=u, from_wallet=bank, to_wallet=late, amount=D("2000"), fee=D("37"), date=TODAY)
        Transfer.objects.create(user=u, from_wallet=bank, to_wallet=late, amount=D("100"), fee=D("1"), date=TODAY - timedelta(days=10))
        Adjustment.objects.create(wallet=cash, amount=D("-15.25"), date=TODAY)
        # Someone else's records never count.
        other = User.objects.create_user("them", password="pw12345!")
        Expense.objects.create(user=other, amount=D("10000"), date=TODAY, wallet=cash)

    def test_database_sums_match_the_entry_by_entry_history(self):
        self.fill()
        sums = services.balances(self.user)
        for w in (self.cash, self.bank, self.late):
            _rows, walked = services.history(w)
            self.assertEqual(sums[w.pk], walked, w.name)
        self.assertEqual(services.balances(self.user, only=self.bank.pk), {self.bank.pk: sums[self.bank.pk]})

    def test_known_figures(self):
        self.fill()
        sums = services.balances(self.user)
        # New bKash: only what came after it opened (the transfer 10 days ago and the 40 spent 5 days ago are before).
        self.assertEqual(sums[self.late.pk], D("300") + D("400") + D("1500") + D("2000"))
        self.assertEqual(sums[self.bank.pk], D("50000") + D("30000") - D("700") - D("2500") - D("900") - D("2037") - D("101"))

    def test_spending_more_than_a_wallet_holds_is_pointed_out(self):
        r = self.client.post(reverse("expense_create"), {"amount": "1500", "date": TODAY.isoformat(), "wallet": self.cash.pk}, follow=True)
        self.assertContains(r, "less than nothing")
        r = self.client.post(reverse("expense_create"), {"amount": "10", "date": TODAY.isoformat(), "wallet": self.bank.pk}, follow=True)
        self.assertNotContains(r, "less than nothing")

    def test_moving_more_than_a_wallet_holds_is_pointed_out(self):
        r = self.client.post(reverse("wallet_transfer"), {"from_wallet": self.late.pk, "to_wallet": self.cash.pk, "amount": "500", "fee": "0",
                                                          "date": TODAY.isoformat()}, follow=True)
        self.assertContains(r, "less than nothing")
