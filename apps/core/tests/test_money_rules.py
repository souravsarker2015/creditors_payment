"""What makes the totals true: amounts above zero, one post per due date, and every taka that left counted once."""
from datetime import date, timedelta
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.contributors.forms import ContributionForm
from apps.creditors.forms import TransactionForm as CreditorEntry
from apps.creditors.models import Creditor, Transaction as CreditorTx
from apps.debtors.forms import TransactionForm as DebtorEntry
from apps.debtors.models import Debtor, Transaction as DebtorTx
from apps.expense.forms import ExpenseForm, RecurringExpenseForm
from apps.expense.models import Expense, RecurringExpense
from apps.goals.models import AutoSave, GoalEntry, SavingsGoal
from apps.goals.services import run_autosave
from apps.household.forms import PurchaseForm, SettlementForm
from apps.household.models import HouseholdMember, Purchase, Settlement
from apps.income.forms import IncomeTransactionForm, RecurringIncomeForm
from apps.income.models import IncomeSource, IncomeTransaction, RecurringIncome
from apps.overview.report import Ledger
from apps.shops.forms import TransactionForm as ShopEntry
from apps.shops.models import Shop, Transaction as ShopTx
from apps.wallets.models import Transfer, Wallet
from apps.wallets.services import holding

User = get_user_model()


class AmountsAboveZeroTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("rahim", password="pw")

    def test_no_money_form_takes_a_negative_or_zero_amount(self):
        forms = [(ExpenseForm, True), (RecurringExpenseForm, True), (IncomeTransactionForm, False), (RecurringIncomeForm, False), (CreditorEntry, False),
                 (DebtorEntry, False), (ShopEntry, False), (PurchaseForm, True), (SettlementForm, False), (ContributionForm, False)]
        for form, wants_user in forms:
            for amount in ("-500", "0", "0.00"):
                with self.subTest(form=form.__module__ + "." + form.__name__, amount=amount):
                    bound = form({"amount": amount}, **({"user": self.user} if wants_user else {}))
                    self.assertFalse(bound.is_valid())
                    self.assertIn("amount", bound.errors)

    def test_a_small_amount_is_fine(self):
        bound = ExpenseForm({"amount": "0.01", "date": "2025-03-01"}, user=self.user)
        self.assertTrue(bound.is_valid(), bound.errors)

    def test_the_page_says_why(self):
        self.client.force_login(self.user)
        r = self.client.post(reverse("expense_create"), {"amount": "-500", "date": "2025-03-01"})
        self.assertContains(r, "Enter an amount above zero.")
        self.assertFalse(Expense.objects.exists())


class PostedOnceTests(TestCase):
    """Two pages opening together each load the schedule before either has posted: the second must post nothing."""

    def setUp(self):
        self.user = User.objects.create_user("rahim", password="pw")
        self.today = timezone.localdate()
        self.due = self.today - timedelta(days=1)

    def test_a_regular_expense(self):
        pk = RecurringExpense.objects.create(user=self.user, amount=D("100"), frequency="MONTHLY", start_date=self.due, next_run_date=self.due).pk
        first, second = RecurringExpense.objects.get(pk=pk), RecurringExpense.objects.get(pk=pk)
        self.assertEqual(first.generate_due_transactions(today=self.today), 1)
        self.assertEqual(second.generate_due_transactions(today=self.today), 0)
        self.assertEqual(Expense.objects.count(), 1)
        self.assertEqual(second.next_run_date, RecurringExpense.objects.get(pk=pk).next_run_date)

    def test_regular_income(self):
        source = IncomeSource.objects.create(user=self.user, name="Salary")
        pk = RecurringIncome.objects.create(source=source, amount=D("100"), frequency="MONTHLY", start_date=self.due, next_run_date=self.due).pk
        first, second = RecurringIncome.objects.get(pk=pk), RecurringIncome.objects.get(pk=pk)
        self.assertEqual(first.generate_due_transactions(today=self.today), 1)
        self.assertEqual(second.generate_due_transactions(today=self.today), 0)
        self.assertEqual(IncomeTransaction.objects.count(), 1)

    def test_a_goals_auto_save(self):
        goal = SavingsGoal.objects.create(user=self.user, name="Eid", target_amount=D("1000"))
        pk = AutoSave.objects.create(goal=goal, amount=D("100"), next_run_date=self.due).pk
        first, second = AutoSave.objects.get(pk=pk), AutoSave.objects.get(pk=pk)
        self.assertEqual(run_autosave(first, self.today)[0], 1)
        self.assertEqual(run_autosave(second, self.today)[0], 0)
        self.assertEqual(GoalEntry.objects.count(), 1)

    def test_missed_months_are_all_filled_in(self):
        start = self.today - timedelta(days=70)
        schedule = RecurringExpense.objects.create(user=self.user, amount=D("100"), frequency="MONTHLY", start_date=start, next_run_date=start)
        self.assertGreaterEqual(schedule.generate_due_transactions(today=self.today), 2)
        self.assertGreater(RecurringExpense.objects.get(pk=schedule.pk).next_run_date, self.today)


class MoneyOutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("rahim", password="pw")
        self.client.force_login(self.user)
        self.day = date(2025, 3, 10)
        self.shop = Shop.objects.create(user=self.user, name="Karim Store")
        ShopTx.objects.create(shop=self.shop, transaction_type=ShopTx.PURCHASE, amount=D("5000"), date=self.day)
        self.mother = HouseholdMember.objects.create(user=self.user, name="Mother")
        Purchase.objects.create(user=self.user, buyer=self.mother, amount=D("800"), date=self.day)

    def test_buying_on_credit_is_not_spending_yet(self):
        self.assertEqual(Ledger(self.user).money_out(self.day, self.day), 0)

    def test_paying_is(self):
        ShopTx.objects.create(shop=self.shop, transaction_type=ShopTx.PAYMENT, amount=D("3000"), date=self.day)
        Settlement.objects.create(member=self.mother, amount=D("800"), date=self.day)
        self.assertEqual(Ledger(self.user).money_out(self.day, self.day), D("3800"))

    def test_the_report_shows_where_it_went(self):
        ShopTx.objects.create(shop=self.shop, transaction_type=ShopTx.PAYMENT, amount=D("3000"), date=self.day)
        Settlement.objects.create(member=self.mother, amount=D("800"), date=self.day)
        c = self.client.get(reverse("money_report"), {"month": "2025-03"}).context
        self.assertEqual(c["out_total"], D("3800"))
        self.assertEqual({row["label"] for row in c["out_rank"]}, {"Paid to shops", "Paid back to family"})
        self.assertEqual(self.client.get(reverse("money_report"), {"year": "2025"}).context["months"][2]["out"], D("3800"))

    def test_home_agrees_with_the_report(self):
        today = timezone.localdate()
        ShopTx.objects.create(shop=self.shop, transaction_type=ShopTx.PAYMENT, amount=D("3000"), date=today)
        Settlement.objects.create(member=self.mother, amount=D("800"), date=today)
        c = self.client.get(reverse("home")).context
        self.assertEqual(c["out_month"], D("3800"))
        self.assertEqual(c["total_expense"], D("3800"))
        self.assertEqual(c["out_series"][-1], 3800.0)

    def test_someone_elses_payments_stay_out(self):
        other = User.objects.create_user("karim", password="pw")
        theirs = Shop.objects.create(user=other, name="Theirs")
        ShopTx.objects.create(shop=theirs, transaction_type=ShopTx.PAYMENT, amount=D("9"), date=self.day)
        self.assertEqual(Ledger(self.user).money_out(self.day, self.day), 0)


class StoppedWalletTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("rahim", password="pw")
        self.client.force_login(self.user)
        self.day = date(2025, 1, 1)
        self.cash = Wallet.objects.create(user=self.user, name="Cash", opening_balance=D("100"), opening_date=self.day)
        self.old = Wallet.objects.create(user=self.user, name="Old bank", opening_balance=D("5000"), opening_date=self.day, is_active=False)
        self.empty = Wallet.objects.create(user=self.user, name="Closed", opening_balance=D("0"), opening_date=self.day, is_active=False)

    def test_money_in_it_still_counts(self):
        self.assertEqual({w.name for w in holding(self.user)}, {"Cash", "Old bank"})
        c = self.client.get(reverse("home")).context
        self.assertEqual(c["wallets_total"], D("5100"))
        self.assertEqual(self.client.get(reverse("wallet_list")).context["total"], D("5100"))

    def test_stopping_one_says_what_it_still_holds(self):
        r = self.client.post(reverse("wallet_toggle", args=[self.cash.pk]), follow=True)
        self.assertContains(r, "It still holds")

    def test_stopping_an_empty_one_says_nothing_more(self):
        self.empty.is_active = True
        self.empty.save()
        r = self.client.post(reverse("wallet_toggle", args=[self.empty.pk]), follow=True)
        self.assertNotContains(r, "It still holds")


class OverpaidTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("rahim", password="pw")
        self.client.force_login(self.user)

    def entry(self, url, kind, amount):
        return self.client.post(url, {"transaction_type": kind, "amount": amount, "date": "2025-03-02"}, follow=True)

    def test_paying_a_creditor_too_much(self):
        c = Creditor.objects.create(user=self.user, name="Bank")
        CreditorTx.objects.create(creditor=c, transaction_type=CreditorTx.BORROW, amount=D("1000"), date=date(2025, 3, 1))
        url = reverse("creditor_detail", args=[c.pk])
        self.assertNotContains(self.entry(url, CreditorTx.REPAY, "1000"), "more than the balance")
        self.assertContains(self.entry(url, CreditorTx.REPAY, "500"), "more than the balance")
        self.assertEqual(c.transactions.count(), 3)          # it's saved all the same

    def test_getting_back_too_much(self):
        d = Debtor.objects.create(user=self.user, name="Karim")
        DebtorTx.objects.create(debtor=d, transaction_type=DebtorTx.LEND, amount=D("1000"), date=date(2025, 3, 1))
        self.assertContains(self.entry(reverse("debtor_detail", args=[d.pk]), DebtorTx.RECEIVE, "10000"), "more than the balance")

    def test_paying_a_shop_too_much(self):
        s = Shop.objects.create(user=self.user, name="Karim Store")
        ShopTx.objects.create(shop=s, transaction_type=ShopTx.PURCHASE, amount=D("1000"), date=date(2025, 3, 1))
        self.assertContains(self.entry(reverse("shop_detail", args=[s.pk]), ShopTx.PAYMENT, "10000"), "more than the balance")

    def test_paying_family_back_too_much(self):
        m = HouseholdMember.objects.create(user=self.user, name="Mother")
        Purchase.objects.create(user=self.user, buyer=m, amount=D("1000"), date=date(2025, 3, 1))
        r = self.client.post(reverse("household_member_detail", args=[m.pk]), {"amount": "10000", "date": "2025-03-02"}, follow=True)
        self.assertContains(r, "more than the balance")


class TransferFeeTests(TestCase):
    """Moving money isn't spending, but the fee on the way is: it's gone."""

    def setUp(self):
        self.user = User.objects.create_user("fee", password="x")
        self.client.force_login(self.user)
        self.today = timezone.localdate()
        bank = Wallet.objects.create(user=self.user, name="Bank", opening_balance=D("5000"), opening_date=self.today)
        cash = Wallet.objects.create(user=self.user, name="Cash", opening_balance=0, opening_date=self.today)
        Transfer.objects.create(user=self.user, from_wallet=bank, to_wallet=cash, amount=D("1000"), fee=D("18.50"), date=self.today)

    def test_the_fee_counts_and_the_amount_does_not(self):
        self.assertEqual(Ledger(self.user).money_out(self.today, self.today), D("18.50"))

    def test_the_report_names_it(self):
        response = self.client.get(reverse("money_report"))
        self.assertEqual(response.context["out_total"], D("18.50"))
        self.assertEqual([row[0] for row in response.context["out_rows"]], ["Transfer fees"])

    def test_a_year_report_counts_it_in_its_month(self):
        response = self.client.get(reverse("money_report"), {"year": self.today.year})
        self.assertEqual(sum(m["out"] for m in response.context["months"]), D("18.50"))

    def test_home_counts_it_too(self):
        self.assertEqual(self.client.get(reverse("home")).context["transfer_fees"], D("18.50"))
