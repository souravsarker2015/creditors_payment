"""Every taka adds up: the books stay right when a record is deleted, and everything that cost money counts in profit."""
from datetime import date, timedelta
from decimal import Decimal as D

from django.test import TestCase
from django.urls import reverse

from apps.business.assets.models import Equipment, Service
from apps.business.core.models import Unit
from apps.business.core.testing import make_farm
from apps.business.credit.models import Direction, PartyPayment
from apps.business.loans.models import Lender, Loan, LoanTransaction
from apps.business.parties.models import Party
from apps.business.partners.models import Partner, PartnerEntry
from apps.business.ponds.models import LeasePayment, Pond
from apps.business.sales.models import FishSale
from apps.business.staff.models import Worker, WorkerPayment
from apps.business.supplies.models import SupplyItem, SupplyPurchase

from .. import services
from ..models import Account, Category, RecurringTransaction, Transaction, Transfer

TODAY = date.today()
YEAR_AGO = TODAY - timedelta(days=365)


class BooksBase(TestCase):
    def setUp(self):
        self.b, self.owner, _ = make_farm()
        self.client.force_login(self.owner)
        self.cash = Account.objects.get(business=self.b, name="Cash")
        self.bank = Account.objects.create(business=self.b, name="Bank", kind="bank", opening_balance=D("50000"))

    def profit(self):
        return services.statement(self.b, YEAR_AGO, TODAY).profit

    def balance(self, account=None):
        return (account or self.bank).balance


class DeletedParentTests(BooksBase):
    def loan(self):
        lender = Lender.objects.create(business=self.b, name="Sonali")
        loan = Loan.objects.create(business=self.b, lender=lender, principal=D("10000"), taken_on=TODAY, account=self.bank, rate=D("12"))
        LoanTransaction.objects.create(business=self.b, loan=loan, date=TODAY, principal=D("1000"), interest=D("100"), account=self.bank)
        return loan

    def test_a_deleted_loan_leaves_the_account_as_it_was(self):
        loan = self.loan()
        self.assertEqual(self.balance(), D("58900"))
        loan.soft_delete()
        self.assertEqual(self.balance(), D("50000"))
        self.assertEqual(self.profit(), 0)

    def test_restoring_a_loan_brings_it_all_back(self):
        loan = self.loan()
        loan.soft_delete()
        loan.restore()
        self.assertEqual(self.balance(), D("58900"))
        self.assertEqual(self.profit(), D("-100"))

    def test_a_deleted_machine_takes_its_servicing_with_it(self):
        machine = Equipment.objects.create(business=self.b, name="Aerator", cost=D("5000"), bought_on=TODAY, account=self.bank)
        Service.objects.create(business=self.b, equipment=machine, date=TODAY, cost=D("500"), account=self.bank)
        self.assertEqual(self.balance(), D("44500"))
        machine.soft_delete()
        self.assertEqual(self.balance(), D("50000"))
        self.assertEqual(self.profit(), 0)


class DeleteBoxTests(BooksBase):
    """The box before a delete must say what really happens to the money."""

    def said(self, url):
        return self.client.get(reverse("delete_check"), {"url": url}).json()["lines"]

    def test_a_loan_says_its_payments_go_too(self):
        lender = Lender.objects.create(business=self.b, name="Sonali")
        loan = Loan.objects.create(business=self.b, lender=lender, principal=D("10000"), taken_on=TODAY, account=self.bank)
        LoanTransaction.objects.create(business=self.b, loan=loan, date=TODAY, principal=D("1000"), account=self.bank)
        said = " ".join(self.said(reverse("business:loan_delete", args=[loan.pk])))
        self.assertIn("leave your account balances", said)
        self.assertNotIn("stay as they are", said)

    def test_a_machine_says_its_servicing_goes_too(self):
        machine = Equipment.objects.create(business=self.b, name="Aerator", cost=D("5000"))
        Service.objects.create(business=self.b, equipment=machine, date=TODAY, cost=D("500"))
        said = " ".join(self.said(reverse("business:equipment_delete", args=[machine.pk])))
        self.assertIn("leave your account balances", said)
        self.assertNotIn("stay as they are", said)


class AccountBookLinkTests(BooksBase):
    """Money that stays in the book after its parent is deleted must not link to a page that's gone."""

    def assert_links_work(self):
        book = services.movements(self.b, self.bank)
        self.assertTrue(book)
        for m in book:
            if m.url:
                self.assertEqual(self.client.get(m.url).status_code, 200, m.url)

    def test_a_deleted_pond(self):
        pond = Pond.objects.create(business=self.b, name="East")
        LeasePayment.objects.create(business=self.b, pond=pond, date=TODAY, amount=D("100"), account=self.bank)
        pond.soft_delete()
        self.assert_links_work()

    def test_a_deleted_worker(self):
        worker = Worker.objects.create(business=self.b, name="Rahim", rate=D("100"))
        WorkerPayment.objects.create(business=self.b, worker=worker, date=TODAY, amount=D("100"), account=self.bank)
        worker.soft_delete()
        self.assert_links_work()

    def test_a_deleted_partner(self):
        partner = Partner.objects.create(business=self.b, name="Karim", share_pct=D("50"))
        PartnerEntry.objects.create(business=self.b, partner=partner, date=TODAY, amount=D("100"), account=self.bank)
        partner.soft_delete()
        self.assert_links_work()

    def test_a_deleted_supply(self):
        kg = Unit.objects.filter(business=self.b).first()
        item = SupplyItem.objects.create(business=self.b, name="Lime", unit=kg)
        SupplyPurchase.objects.create(business=self.b, item=item, date=TODAY, quantity=D("1"), unit=kg, cost=D("100"), paid_now=D("100"), account=self.bank)
        item.soft_delete()
        self.assert_links_work()

    def test_a_deleted_party(self):
        party = Party.objects.create(business=self.b, name="Hasan", is_buyer=True)
        PartyPayment.objects.create(business=self.b, party=party, date=TODAY, direction=Direction.IN, amount=D("100"), account=self.bank)
        party.soft_delete()
        self.assert_links_work()


class RegularBillDateTests(TestCase):
    def test_a_bill_on_the_31st_comes_back_to_the_31st(self):
        start, d, seen = date(2026, 1, 31), date(2026, 1, 31), []
        for _ in range(3):
            d = services.next_date(d, "monthly", start)
            seen.append(d)
        self.assertEqual(seen, [date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)])

    def test_a_bill_on_the_10th_stays_on_the_10th(self):
        self.assertEqual(services.next_date(date(2026, 1, 10), "monthly", date(2026, 1, 10)), date(2026, 2, 10))

    def test_a_week_is_seven_days(self):
        self.assertEqual(services.next_date(date(2026, 1, 31), "weekly", date(2026, 1, 31)), date(2026, 2, 7))


class BillConfirmedTwiceTests(BooksBase):
    def setUp(self):
        super().setUp()
        self.category = Category.objects.get(business=self.b, name="Daily labour")
        self.bill = RecurringTransaction.objects.create(business=self.b, name="Rent", category=self.category, amount=D("500"), start_date=TODAY, next_due=TODAY)
        self.url = reverse("business:transaction_add") + f"?from={self.bill.pk}&scope=business"

    def confirm(self):
        return self.client.post(self.url, {"date": TODAY, "category": self.category.pk, "amount": "500", "account": self.bank.pk,
                                           "recurring_due": TODAY.isoformat()})

    def test_the_form_carries_the_date_it_is_for(self):
        self.assertContains(self.client.get(self.url), f'name="recurring_due" value="{TODAY.isoformat()}"')

    def test_a_second_tab_does_not_post_it_again(self):
        self.confirm()
        self.confirm()
        self.assertEqual(Transaction.objects.filter(recurring=self.bill).count(), 1)
        self.bill.refresh_from_db()
        self.assertGreater(self.bill.next_due, TODAY)


class WhatCountsInProfitTests(BooksBase):
    def test_a_transfer_charge_is_a_cost(self):
        Transfer.objects.create(business=self.b, date=TODAY, from_account=self.bank, to_account=self.cash, amount=D("1000"), charge=D("18"))
        self.assertEqual(self.balance() + self.balance(self.cash), D("49982"))
        self.assertEqual(self.profit(), D("-18"))

    def test_a_discount_given_to_a_buyer_comes_off_the_income(self):
        buyer = Party.objects.create(business=self.b, name="Hasan", is_buyer=True)
        FishSale.objects.create(business=self.b, date=TODAY, buyer=buyer, gross=D("1000"), net=D("1000"))
        PartyPayment.objects.create(business=self.b, party=buyer, date=TODAY, direction=Direction.IN, amount=D("900"), discount=D("100"), account=self.bank)
        self.assertEqual(self.profit(), D("900"))

    def test_a_discount_from_a_supplier_lowers_the_cost(self):
        shop = Party.objects.create(business=self.b, name="Mollah", is_supplier=True)
        PartyPayment.objects.create(business=self.b, party=shop, date=TODAY, direction=Direction.OUT, amount=D("900"), discount=D("100"), account=self.bank)
        self.assertEqual(self.profit(), D("100"))

    def test_the_statement_page_shows_them_all(self):
        buyer = Party.objects.create(business=self.b, name="Hasan", is_buyer=True)
        shop = Party.objects.create(business=self.b, name="Mollah", is_supplier=True)
        PartyPayment.objects.create(business=self.b, party=buyer, date=TODAY, direction=Direction.IN, amount=D("900"), discount=D("100"), account=self.bank)
        PartyPayment.objects.create(business=self.b, party=shop, date=TODAY, direction=Direction.OUT, amount=D("900"), discount=D("70"), account=self.bank)
        Transfer.objects.create(business=self.b, date=TODAY, from_account=self.bank, to_account=self.cash, amount=D("1000"), charge=D("18"))
        page = self.client.get(reverse("business:statement")).content.decode()
        for words in ("Bank &amp; bKash charges", "Discounts you let buyers off", "Discounts from suppliers"):
            self.assertIn(words, page)
