"""Small things that make the app easier to live with, found in the whole-app check:
who still has a balance comes first in a list, averages are whole taka, the + sheet holds the everyday
actions, and an empty "- " line on a note card is a gap rather than a lone dot."""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.core.stats import trend_summary, whole
from apps.creditors.models import Creditor, Transaction as CreditorTx
from apps.debtors.models import Debtor, Transaction as DebtorTx
from apps.expense.models import Expense
from apps.shops.models import Shop, Transaction as ShopTx


def names(response):
    return [p.name for p in response.context["page_obj"]]


class StillOwedFirstTests(TestCase):
    """Paid-off people used to sit among the ones still owed, A–Z; now whoever has a balance comes first."""

    def setUp(self):
        self.user = User.objects.create_user("rina", password="pw-12345!")
        self.client.force_login(self.user)

    def test_creditors(self):
        done = Creditor.objects.create(user=self.user, name="Akhtar")
        owed = Creditor.objects.create(user=self.user, name="Zaman")
        CreditorTx.objects.create(creditor=done, amount=500, transaction_type=CreditorTx.BORROW, date=date(2026, 1, 1))
        CreditorTx.objects.create(creditor=done, amount=500, transaction_type=CreditorTx.REPAY, date=date(2026, 2, 1))
        CreditorTx.objects.create(creditor=owed, amount=900, transaction_type=CreditorTx.BORROW, date=date(2026, 1, 1))
        r = self.client.get(reverse("creditor_list"))
        self.assertEqual(r.context["sort"], "open")
        self.assertEqual(names(r), ["Zaman", "Akhtar"])
        self.assertContains(r, "is-settled")                                   # its 100% bar folds away
        self.assertEqual(names(self.client.get(reverse("creditor_list"), {"sort": "name"})), ["Akhtar", "Zaman"])  # A–Z still there

    def test_debtors(self):
        done = Debtor.objects.create(user=self.user, name="Akhtar")
        owes = Debtor.objects.create(user=self.user, name="Zaman")
        DebtorTx.objects.create(debtor=done, amount=500, transaction_type=DebtorTx.LEND, date=date(2026, 1, 1))
        DebtorTx.objects.create(debtor=done, amount=500, transaction_type=DebtorTx.RECEIVE, date=date(2026, 2, 1))
        DebtorTx.objects.create(debtor=owes, amount=900, transaction_type=DebtorTx.LEND, date=date(2026, 1, 1))
        self.assertEqual(names(self.client.get(reverse("debtor_list"))), ["Zaman", "Akhtar"])

    def test_shops(self):
        done = Shop.objects.create(user=self.user, name="Akhtar Store")
        owed = Shop.objects.create(user=self.user, name="Zaman Store")
        ShopTx.objects.create(shop=done, amount=500, transaction_type=ShopTx.PURCHASE, date=date(2026, 1, 1))
        ShopTx.objects.create(shop=done, amount=500, transaction_type=ShopTx.PAYMENT, date=date(2026, 2, 1))
        ShopTx.objects.create(shop=owed, amount=900, transaction_type=ShopTx.PURCHASE, date=date(2026, 1, 1))
        self.assertEqual(names(self.client.get(reverse("shop_list"))), ["Zaman Store", "Akhtar Store"])


class WholeTakaAveragesTests(TestCase):
    def test_whole_rounds_half_up(self):
        self.assertEqual(whole(Decimal("8597.33")), Decimal("8597"))
        self.assertEqual(whole(Decimal("8194.5")), Decimal("8195"))
        self.assertEqual(whole(None), Decimal("0"))

    def test_trend_average_is_whole(self):
        s = trend_summary([100, 0, 101, 100], ["a", "b", "c", "d"])
        self.assertEqual(s["average"], Decimal("100"))                       # 100.33 → 100
        self.assertEqual(s["total"], Decimal("301"))                          # totals stay exact

    def test_expense_list_average(self):
        user = User.objects.create_user("rina", password="pw-12345!")
        self.client.force_login(user)
        for amount in (100, 100, 101):
            Expense.objects.create(user=user, amount=amount, date=date(2026, 1, 1))
        r = self.client.get(reverse("expense_list"))
        self.assertEqual(r.context["avg_expense"], Decimal("100"))


class AddSheetTests(TestCase):
    """The + button: what people write down every day, from any page — not only "new person"."""

    def test_everyday_actions(self):
        user = User.objects.create_user("rina", password="pw-12345!")
        self.client.force_login(user)
        r = self.client.get(reverse("creditor_list"))
        for kind in ("income", "borrow", "repay", "lend", "collect", "shop"):
            self.assertContains(r, reverse("pick", args=[kind]))
        self.assertContains(r, reverse("expense_create"))
        self.assertContains(r, reverse("wallet_transfer"))
        today = date.today()
        self.assertContains(r, reverse("household_month_detail", args=[today.year, today.month]) + "#record")
