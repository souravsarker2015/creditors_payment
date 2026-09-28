"""Phase 5: income and expenses, transfers, account balances, budgets, recurring."""
from datetime import date, timedelta
from decimal import Decimal as D

from django.test import TestCase
from django.urls import reverse

from apps.business.core.models import Role, Unit
from apps.business.core.testing import make_farm
from apps.business.credit.models import Direction, PartyPayment
from apps.business.feed.models import FeedProduct, FeedPurchase, FeedPurchaseLine, FeedUsage
from apps.business.loans.models import Lender, Loan, LoanTransaction
from apps.business.parties.models import Party
from apps.business.ponds.models import CultureCycle, Pond, Stocking
from apps.business.ponds.services import summarize
from apps.business.sales.models import FishSale
from apps.business.species.models import Species

from . import services
from .models import Account, Budget, Category, CategoryType, RecurringTransaction, Scope, Transaction, Transfer


def ago(n):
    return date.today() - timedelta(days=n)


class MoneyBase(TestCase):
    def setUp(self):
        self.b, self.owner, self.staff = make_farm()
        self.client.force_login(self.owner)
        self.cash = Account.objects.get(business=self.b, name="Cash")
        self.bank = Account.objects.create(business=self.b, name="Sonali Bank", kind="bank", opening_balance=D("50000"))
        self.labour = Category.objects.get(business=self.b, name="Labour", parent=None)
        self.daily = Category.objects.get(business=self.b, name="Daily labour")
        self.bazar = Category.objects.get(business=self.b, name="Groceries (bazar)")
        self.other_income = Category.objects.get(business=self.b, name="Other income")

    def spend(self, amount, category=None, days=0, account=None, **kw):
        return Transaction.objects.create(business=self.b, date=ago(days), category=category or self.daily,
                                          amount=D(amount), account=account or self.cash, **kw)


class AccountBalanceTests(MoneyBase):
    def test_opening_balance_is_the_start(self):
        self.assertEqual(self.bank.balance, D("50000"))

    def test_spending_and_income_move_the_balance(self):
        self.spend(2000)
        Transaction.objects.create(business=self.b, date=ago(1), category=self.other_income, amount=D("500"), account=self.cash)
        self.assertEqual(self.cash.balance, D("-1500"))

    def test_a_sale_receipt_goes_into_the_account(self):
        buyer = Party.objects.create(business=self.b, name="Hasan", is_buyer=True)
        FishSale.objects.create(business=self.b, date=ago(2), buyer=buyer, gross=D("10000"), net=D("10000"),
                                received_now=D("6000"), account=self.cash)
        self.assertEqual(self.cash.balance, D("6000"))

    def test_feed_paid_now_comes_out_of_the_account(self):
        supplier = Party.objects.create(business=self.b, name="Mollah", is_supplier=True)
        FeedPurchase.objects.create(business=self.b, date=ago(3), supplier=supplier, subtotal=D("20000"),
                                    total=D("20000"), paid_now=D("8000"), account=self.bank)
        self.assertEqual(self.bank.balance, D("42000"))

    def test_baki_payments_move_money_both_ways(self):
        buyer = Party.objects.create(business=self.b, name="Hasan", is_buyer=True)
        supplier = Party.objects.create(business=self.b, name="Mollah", is_supplier=True)
        PartyPayment.objects.create(business=self.b, party=buyer, direction=Direction.IN, date=ago(1), amount=D("5000"), account=self.cash)
        PartyPayment.objects.create(business=self.b, party=supplier, direction=Direction.OUT, date=ago(1), amount=D("2000"), account=self.cash)
        self.assertEqual(self.cash.balance, D("3000"))

    def test_loan_instalment_leaves_the_account(self):
        lender = Lender.objects.create(business=self.b, name="Sonali", kind="bank")
        loan = Loan.objects.create(business=self.b, lender=lender, principal=D("100000"), taken_on=ago(60), rate=D(12))
        LoanTransaction.objects.create(business=self.b, loan=loan, date=ago(5), principal=D("5000"), interest=D("1000"), account=self.bank)
        self.assertEqual(self.bank.balance, D("44000"))

    def test_a_discount_on_a_baki_payment_does_not_move_money(self):
        buyer = Party.objects.create(business=self.b, name="Hasan", is_buyer=True)
        PartyPayment.objects.create(business=self.b, party=buyer, direction=Direction.IN, date=ago(1),
                                    amount=D("1000"), discount=D("50"), account=self.cash)
        self.assertEqual(self.cash.balance, D("1000"))

    def test_deleted_entries_drop_out_of_the_balance(self):
        t = self.spend(2000)
        self.assertEqual(self.cash.balance, D("-2000"))
        t.soft_delete()
        self.assertEqual(self.cash.balance, D("0"))


class TransferTests(MoneyBase):
    def test_transfer_moves_money_and_charges_the_sender(self):
        Transfer.objects.create(business=self.b, date=ago(1), from_account=self.bank, to_account=self.cash,
                                amount=D("10000"), charge=D("100"))
        self.assertEqual(self.bank.balance, D("39900"))
        self.assertEqual(self.cash.balance, D("10000"))

    def test_a_transfer_is_not_income_or_spending(self):
        Transfer.objects.create(business=self.b, date=ago(1), from_account=self.bank, to_account=self.cash, amount=D("10000"))
        s = services.statement(self.b, ago(30), date.today())
        self.assertEqual((s.total_income, s.total_expense), (0, 0))

    def test_cannot_send_to_the_same_account(self):
        r = self.client.post(reverse("business:transfer_add"), {
            "date": date.today().isoformat(), "from_account": self.cash.pk, "to_account": self.cash.pk, "amount": "500", "charge": ""})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Transfer.objects.exists())


class StatementTests(MoneyBase):
    def test_farm_income_and_costs_come_from_the_documents(self):
        buyer = Party.objects.create(business=self.b, name="Hasan", is_buyer=True)
        FishSale.objects.create(business=self.b, date=ago(3), buyer=buyer, gross=D("20000"), net=D("18000"), received_now=D("18000"))
        pond = Pond.objects.create(business=self.b, name="East")
        cycle = CultureCycle.objects.create(business=self.b, pond=pond, start_date=ago(30))
        rui = Species.objects.get(business=self.b, name="Rui")
        Stocking.objects.create(business=self.b, cycle=cycle, date=ago(30), species=rui, count=500, cost=D("5000"))
        self.spend(3000, days=2)
        s = services.statement(self.b, ago(40), date.today())
        self.assertEqual(s.total_income, D("18000"))
        self.assertEqual(s.total_expense, D("8000"))
        self.assertEqual(s.profit, D("10000"))

    def test_feed_counts_when_it_is_eaten_not_when_bought(self):
        supplier = Party.objects.create(business=self.b, name="Mollah", is_supplier=True)
        kg = Unit.objects.get(business=self.b, symbol="kg")
        product = FeedProduct.objects.create(business=self.b, name="Float 28", bag_size=25, bag_unit=kg)
        purchase = FeedPurchase.objects.create(business=self.b, date=ago(20), supplier=supplier)
        FeedPurchaseLine.objects.create(business=self.b, purchase=purchase, product=product, quantity=D("10"), rate=D("1000"))
        purchase.recalc()
        pond = Pond.objects.create(business=self.b, name="East")
        cycle = CultureCycle.objects.create(business=self.b, pond=pond, start_date=ago(30))
        FeedUsage.objects.create(business=self.b, cycle=cycle, date=ago(5), product=product, quantity=D("50"), unit=kg)
        s = services.statement(self.b, ago(40), date.today())
        feed = next(l for l in s.expense if l.key == "feed")
        self.assertEqual(feed.amount, D("2000"))  # 50 kg × ৳40/kg (10 bags × 25 kg for ৳10,000)

    def test_loan_interest_is_a_cost_but_principal_is_not(self):
        lender = Lender.objects.create(business=self.b, name="Sonali", kind="bank")
        loan = Loan.objects.create(business=self.b, lender=lender, principal=D("100000"), taken_on=ago(60), rate=D(12))
        LoanTransaction.objects.create(business=self.b, loan=loan, date=ago(5), principal=D("5000"), interest=D("1000"), charges=D("50"))
        s = services.statement(self.b, ago(40), date.today())
        self.assertEqual(s.total_expense, D("1050"))

    def test_household_and_farm_are_kept_apart(self):
        self.spend(3000)
        self.spend(1500, category=self.bazar)
        farm = services.statement(self.b, ago(30), date.today(), scope=Scope.BUSINESS)
        home = services.statement(self.b, ago(30), date.today(), scope=Scope.HOUSEHOLD)
        self.assertEqual(farm.total_expense, D("3000"))
        self.assertEqual(home.total_expense, D("1500"))

    def test_costs_are_grouped_under_the_main_category(self):
        self.spend(1000, category=self.daily)
        self.spend(500, category=Category.objects.get(business=self.b, name="Salaries"))
        s = services.statement(self.b, ago(30), date.today())
        line = next(l for l in s.expense if l.label == "Labour")
        self.assertEqual(line.amount, D("1500"))
        self.assertEqual(len(line.children), 2)

    def test_dates_outside_the_range_are_left_out(self):
        self.spend(1000, days=200)
        s = services.statement(self.b, ago(30), date.today())
        self.assertEqual(s.total_expense, 0)


class CyclePLTests(MoneyBase):
    def test_a_cost_put_on_a_pond_joins_its_season(self):
        pond = Pond.objects.create(business=self.b, name="East")
        cycle = CultureCycle.objects.create(business=self.b, pond=pond, start_date=ago(30))
        rui = Species.objects.get(business=self.b, name="Rui")
        Stocking.objects.create(business=self.b, cycle=cycle, date=ago(30), species=rui, count=500, cost=D("5000"))
        self.spend(2000, cycle=cycle)
        s = summarize(cycle)
        self.assertEqual(s.other_cost, D("2000"))
        self.assertEqual(s.cost, D("7000"))


class BudgetTests(MoneyBase):
    def setUp(self):
        super().setUp()
        self.month = date.today().replace(day=1)

    def test_spending_counts_against_the_main_category_budget(self):
        Budget.objects.create(business=self.b, category=self.labour, month=self.month, amount=D("10000"))
        self.spend(4000, category=self.daily)
        rows, extra = services.budget_rows(self.b, self.month)
        self.assertEqual(rows[0].spent, D("4000"))
        self.assertEqual(rows[0].left, D("6000"))
        self.assertEqual(rows[0].state, "ok")
        self.assertEqual(extra, [])

    def test_going_over_is_flagged(self):
        Budget.objects.create(business=self.b, category=self.labour, month=self.month, amount=D("1000"))
        self.spend(1500)
        rows, _extra = services.budget_rows(self.b, self.month)
        self.assertEqual(rows[0].state, "over")
        self.assertEqual(rows[0].left, D("-500"))

    def test_spending_without_a_budget_is_listed_separately(self):
        self.spend(700, category=self.bazar)
        rows, extra = services.budget_rows(self.b, self.month)
        self.assertEqual(rows, [])
        self.assertEqual(extra[0].spent, D("700"))

    def test_set_the_whole_month_on_one_page(self):
        r = self.client.post(reverse("business:budget_edit") + f"?month={self.month:%Y-%m}",
                             {f"c{self.labour.pk}": "8000", f"c{self.bazar.pk}": ""})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Budget.objects.get().amount, D("8000"))

    def test_clearing_a_box_removes_that_budget(self):
        Budget.objects.create(business=self.b, category=self.labour, month=self.month, amount=D("8000"))
        self.client.post(reverse("business:budget_edit") + f"?month={self.month:%Y-%m}", {f"c{self.labour.pk}": ""})
        self.assertFalse(Budget.objects.exists())

    def test_copy_last_months_budget(self):
        last = services.next_date(self.month, "monthly")
        Budget.objects.create(business=self.b, category=self.labour, month=self.month, amount=D("8000"))
        r = self.client.post(reverse("business:budget_copy"), {"month": f"{last:%Y-%m}"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Budget.objects.filter(month=last).get().amount, D("8000"))


class RecurringTests(MoneyBase):
    def make(self, **kw):
        data = {"business": self.b, "name": "Pond lease", "category": self.labour, "amount": D("5000"),
                "repeat": "monthly", "start_date": ago(3), "next_due": ago(3)}
        data.update(kw)
        return RecurringTransaction.objects.create(**data)

    def test_due_bills_are_listed(self):
        self.make()
        self.make(name="Later", next_due=date.today() + timedelta(days=10))
        due = services.due_recurring(self.b)
        self.assertEqual([r.name for r in due], ["Pond lease"])

    def test_confirming_one_records_it_and_moves_the_date_on(self):
        r = self.make()
        self.client.post(reverse("business:transaction_add") + f"?from={r.pk}",
                         {"date": date.today().isoformat(), "category": self.labour.pk, "amount": "5000", "account": self.cash.pk,
                          "description": "Lease"})
        t = Transaction.objects.get()
        self.assertEqual((t.amount, t.recurring_id), (D("5000"), r.pk))
        r.refresh_from_db()
        self.assertEqual(r.next_due, services.next_date(ago(3), "monthly"))

    def test_skipping_moves_the_date_on_without_recording(self):
        r = self.make()
        self.client.post(reverse("business:recurring_skip", args=[r.pk]))
        r.refresh_from_db()
        self.assertEqual(r.next_due, services.next_date(ago(3), "monthly"))
        self.assertFalse(Transaction.objects.exists())

    def test_it_stops_after_the_end_date(self):
        r = self.make(end_date=date.today())
        self.client.post(reverse("business:recurring_skip", args=[r.pk]))
        r.refresh_from_db()
        self.assertIsNone(r.next_due)
        self.assertTrue(r.is_finished)

    def test_weekly_and_quarterly_steps(self):
        self.assertEqual(services.next_date(date(2026, 1, 5), "weekly"), date(2026, 1, 12))
        self.assertEqual(services.next_date(date(2026, 1, 31), "quarterly"), date(2026, 4, 30))


class PageTests(MoneyBase):
    def test_money_list_splits_farm_and_household(self):
        self.spend(3000)
        self.spend(1500, category=self.bazar)
        r = self.client.get(reverse("business:transactions"))
        self.assertEqual(r.context["expense"], D("3000"))
        r = self.client.get(reverse("business:transactions") + "?scope=household")
        self.assertEqual(r.context["expense"], D("1500"))

    def test_add_an_expense(self):
        r = self.client.post(reverse("business:transaction_add"), {
            "date": date.today().isoformat(), "category": self.daily.pk, "amount": "1200", "account": self.cash.pk,
            "description": "3 workers"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Transaction.objects.get().amount, D("1200"))

    def test_a_future_date_is_refused(self):
        r = self.client.post(reverse("business:transaction_add"), {
            "date": (date.today() + timedelta(days=3)).isoformat(), "category": self.daily.pk, "amount": "100"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Transaction.objects.exists())

    def test_the_category_must_match_the_list_shown(self):
        r = self.client.post(reverse("business:transaction_add") + "?scope=business", {
            "date": date.today().isoformat(), "category": self.bazar.pk, "amount": "100"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Transaction.objects.exists())

    def test_account_book_shows_every_kind_of_movement(self):
        buyer = Party.objects.create(business=self.b, name="Hasan", is_buyer=True)
        FishSale.objects.create(business=self.b, date=ago(3), buyer=buyer, gross=D("9000"), net=D("9000"),
                                received_now=D("9000"), account=self.cash)
        self.spend(2000, days=1)
        r = self.client.get(reverse("business:account_detail", args=[self.cash.pk]) + "?period=all")
        kinds = {m.kind for m in r.context["rows"]}
        self.assertEqual(kinds, {"sale", "expense"})
        self.assertEqual(r.context["closing"], D("7000"))

    def test_statement_page(self):
        self.spend(3000)
        r = self.client.get(reverse("business:statement"))
        self.assertEqual(r.context["s"].total_expense, D("3000"))

    def test_delete_and_restore(self):
        t = self.spend(500)
        self.client.post(reverse("business:transaction_delete", args=[t.pk]))
        self.assertEqual(self.cash.balance, D("0"))
        self.client.post(reverse("business:transaction_restore", args=[t.pk]))
        self.assertEqual(self.cash.balance, D("-500"))

    def test_home_page_money_card(self):
        self.spend(3000)
        r = self.client.get(reverse("business:home"))
        self.assertEqual(r.context["money"]["farm"].total_expense, D("3000"))

    def test_other_farms_cannot_see_the_entries(self):
        t = self.spend(500)
        _b2, owner2, _s = make_farm("other")
        self.client.force_login(owner2)
        self.assertEqual(self.client.get(reverse("business:transaction_edit", args=[t.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("business:account_detail", args=[self.cash.pk])).status_code, 404)


class AccessTests(TestCase):
    def test_data_entry_staff_can_add_but_not_see_the_statement(self):
        b, _owner, staff = make_farm()
        self.client.force_login(staff)
        self.assertEqual(self.client.get(reverse("business:transaction_add")).status_code, 200)
        self.assertEqual(self.client.get(reverse("business:transactions")).status_code, 403)
        self.assertEqual(self.client.get(reverse("business:statement")).status_code, 403)

    def test_viewer_sees_reports_but_cannot_add(self):
        b, _owner, viewer = make_farm(staff_role=Role.VIEWER)
        self.client.force_login(viewer)
        self.assertEqual(self.client.get(reverse("business:statement")).status_code, 200)
        self.assertEqual(self.client.get(reverse("business:transaction_add")).status_code, 403)
