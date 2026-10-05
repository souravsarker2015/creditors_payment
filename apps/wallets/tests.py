"""Wallets: each balance worked out from the entries that name it."""
from datetime import date, timedelta
from decimal import Decimal as D

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.contributors.models import Contribution, Contributor
from apps.creditors.models import Creditor, Transaction as CreditorTx
from apps.debtors.models import Debtor, Transaction as DebtorTx
from apps.expense.models import Expense, ExpenseCategory, RecurringExpense
from apps.household.models import HouseholdMember, Purchase, Settlement
from apps.income.models import IncomeSource, IncomeTransaction
from apps.shops.models import Shop, Transaction as ShopTx

from . import services
from .models import Adjustment, Transfer, Wallet

TODAY = date.today()


class WalletTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("me", password="pw12345!")
        self.client.force_login(self.user)
        self.cash = Wallet.objects.create(user=self.user, name="Cash", opening_balance=D("1000"), opening_date=TODAY - timedelta(days=30), is_default=True)
        self.bkash = Wallet.objects.create(user=self.user, name="bKash", kind="mobile", opening_balance=D("5000"), opening_date=TODAY - timedelta(days=30))
        self.food = ExpenseCategory.objects.create(user=self.user, name="Food")

    def bal(self, w):
        return services.balances(self.user)[w.pk]

    def test_every_kind_of_entry_moves_the_wallet(self):
        w = self.cash
        Expense.objects.create(user=self.user, category=self.food, amount=D("200"), date=TODAY, wallet=w)                        # −200
        src = IncomeSource.objects.create(user=self.user, name="Salary")
        IncomeTransaction.objects.create(source=src, amount=D("3000"), date=TODAY, wallet=w)                                    # +3000
        cr = Creditor.objects.create(user=self.user, name="Karim")
        CreditorTx.objects.create(creditor=cr, transaction_type=CreditorTx.BORROW, amount=D("500"), date=TODAY, wallet=w)      # +500
        CreditorTx.objects.create(creditor=cr, transaction_type=CreditorTx.REPAY, amount=D("100"), date=TODAY, wallet=w)       # −100
        de = Debtor.objects.create(user=self.user, name="Rahim")
        DebtorTx.objects.create(debtor=de, transaction_type=DebtorTx.LEND, amount=D("400"), date=TODAY, wallet=w)              # −400
        DebtorTx.objects.create(debtor=de, transaction_type=DebtorTx.RECEIVE, amount=D("150"), date=TODAY, wallet=w)           # +150
        shop = Shop.objects.create(user=self.user, name="Grocer")
        ShopTx.objects.create(shop=shop, transaction_type=ShopTx.PURCHASE, amount=D("999"), date=TODAY, wallet=w)              # credit: ignored
        ShopTx.objects.create(shop=shop, transaction_type=ShopTx.PAYMENT, amount=D("300"), date=TODAY, wallet=w)               # −300
        mom = HouseholdMember.objects.create(user=self.user, name="Mom")
        Purchase.objects.create(user=self.user, amount=D("50"), date=TODAY, wallet=w)                                           # −50
        Purchase.objects.create(user=self.user, amount=D("777"), date=TODAY, buyer=mom, wallet=w)                              # fronted: ignored
        Settlement.objects.create(member=mom, amount=D("70"), date=TODAY, wallet=w)                                             # −70
        uncle = Contributor.objects.create(user=self.user, name="Uncle")
        Contribution.objects.create(contributor=uncle, amount=D("1000"), date=TODAY, wallet=w)                                  # +1000
        Expense.objects.create(user=self.user, category=self.food, amount=D("80"), date=TODAY)                                   # no wallet
        self.assertEqual(self.bal(w), D("1000") - 200 + 3000 + 500 - 100 - 400 + 150 - 300 - 50 - 70 + 1000)

    def test_transfer_fee_correction_and_start_date(self):
        Transfer.objects.create(user=self.user, from_wallet=self.bkash, to_wallet=self.cash, amount=D("2000"), fee=D("37"), date=TODAY)
        Adjustment.objects.create(wallet=self.cash, amount=D("-25"), date=TODAY)
        Expense.objects.create(user=self.user, category=self.food, amount=D("999"), date=TODAY - timedelta(days=60), wallet=self.cash)  # before the start
        self.assertEqual((self.bal(self.bkash), self.bal(self.cash)), (D("2963"), D("2975")))

    def test_entry_forms_offer_the_default_wallet_and_save_it(self):
        r = self.client.get(reverse("expense_create"))
        self.assertContains(r, 'name="wallet"')
        self.assertEqual(r.context["form"].initial.get("wallet"), self.cash.pk)
        self.client.post(reverse("expense_create"), {"category": self.food.pk, "amount": "120", "date": TODAY.isoformat(), "wallet": self.bkash.pk})
        self.assertEqual(Expense.objects.get().wallet, self.bkash)

    def test_no_wallets_no_field(self):
        Wallet.objects.all().delete()
        self.assertNotContains(self.client.get(reverse("expense_create")), 'name="wallet"')

    def test_a_shop_purchase_on_credit_never_moves_a_wallet(self):
        shop = Shop.objects.create(user=self.user, name="Grocer")
        self.client.post(reverse("shop_detail", args=[shop.pk]), {"transaction_type": "PURCHASE", "amount": "300", "date": TODAY.isoformat(), "wallet": self.cash.pk})
        tx = ShopTx.objects.get()
        self.assertIsNone(tx.wallet)

    def test_recurring_expenses_keep_their_wallet(self):
        rec = RecurringExpense.objects.create(user=self.user, category=self.food, amount=D("1500"), frequency="MONTHLY",
                                              next_run_date=TODAY, wallet=self.bkash)
        rec.generate_due_transactions(today=TODAY)
        self.assertEqual(Expense.objects.get().wallet, self.bkash)

    def test_correct_the_balance(self):
        self.client.post(reverse("wallet_correct", args=[self.cash.pk]), {"actual": "940", "note": "counted"})
        self.assertEqual(Adjustment.objects.get().amount, D("-60"))
        self.assertEqual(self.bal(self.cash), D("940"))

    def test_transfer_form_and_pages(self):
        r = self.client.post(reverse("wallet_transfer"), {"from_wallet": self.cash.pk, "to_wallet": self.cash.pk, "amount": "10", "date": TODAY.isoformat()})
        self.assertEqual(r.status_code, 200)
        self.client.post(reverse("wallet_transfer"), {"from_wallet": self.cash.pk, "to_wallet": self.bkash.pk, "amount": "400", "date": TODAY.isoformat()})
        self.assertEqual(self.bal(self.bkash), D("5400"))
        self.assertContains(self.client.get(reverse("wallet_list")), "৳6,000")
        self.assertContains(self.client.get(reverse("wallet_detail", args=[self.cash.pk])), "Sent to bKash")
        self.assertContains(self.client.get(reverse("networth")), "In your wallets")

    def test_only_one_default_and_names_are_unique(self):
        self.client.post(reverse("wallet_create"), {"name": "Bank", "kind": "bank", "opening_balance": "0", "opening_date": TODAY.isoformat(), "is_default": "on"})
        self.assertEqual(list(Wallet.objects.filter(is_default=True).values_list("name", flat=True)), ["Bank"])
        r = self.client.post(reverse("wallet_create"), {"name": "cash", "kind": "cash", "opening_balance": "0", "opening_date": TODAY.isoformat()})
        self.assertContains(r, "already have a wallet")

    def test_deleting_a_wallet_keeps_entries_and_undo_relinks_them(self):
        e = Expense.objects.create(user=self.user, category=self.food, amount=D("10"), date=TODAY, wallet=self.cash)
        self.client.post(reverse("wallet_delete", args=[self.cash.pk]))
        e.refresh_from_db()
        self.assertIsNone(e.wallet)
        from apps.trash.models import DeletedItem

        self.client.post(reverse("trash_restore", args=[DeletedItem.objects.get().pk]))
        e.refresh_from_db()
        self.assertEqual(e.wallet_id, self.cash.pk)

    def test_someone_elses_wallet_is_not_offered(self):
        other = User.objects.create_user("them", password="pw12345!")
        Wallet.objects.create(user=other, name="Their cash")
        r = self.client.get(reverse("expense_create"))
        self.assertNotContains(r, "Their cash")
        self.assertEqual(self.client.get(reverse("wallet_detail", args=[Wallet.objects.get(user=other).pk])).status_code, 404)
