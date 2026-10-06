"""Zakat helper: lines from the records, nisab, 2.5 in 100, and what it remembers."""
from datetime import date, timedelta
from decimal import Decimal as D

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase
from django.urls import reverse

from apps.business.core.testing import make_farm
from apps.creditors.models import Creditor, Transaction as CT
from apps.debtors.models import Debtor, Transaction as DT
from apps.wallets.models import Wallet

from . import services
from .models import ZakatSettings

TODAY = date.today()


class ZakatTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("me", password="pw12345!")
        self.client.force_login(self.user)
        Wallet.objects.create(user=self.user, name="Bank", kind="bank", opening_balance=D("500000"), opening_date=TODAY - timedelta(days=10))
        d = Debtor.objects.create(user=self.user, name="Rahim")
        DT.objects.create(debtor=d, transaction_type=DT.LEND, amount=D("100000"), date=TODAY)
        c = Creditor.objects.create(user=self.user, name="Karim")
        CT.objects.create(creditor=c, transaction_type=CT.BORROW, amount=D("200000"), date=TODAY)
        self.s = ZakatSettings.objects.create(user=self.user, silver_price=D("150"), gold_price=D("12000"), gold_grams=D("10"))

    def sheet(self):
        req = RequestFactory().get("/zakat/")
        req.user = self.user
        req.session = {}
        return services.sheet(req, self.s)

    def test_lines_nisab_and_due(self):
        sh = self.sheet()
        self.assertEqual((sh.own, sh.owe), (D("720000"), D("200000")))          # 5,00,000 + 1,00,000 + 10 g × 12,000
        self.assertEqual(sh.net, D("520000"))
        self.assertEqual(sh.nisab, D("91854"))                                   # 612.36 g × 150
        self.assertEqual(sh.due, D("13000"))

    def test_untick_a_line_and_gold_basis(self):
        self.s.skip = ["debtors"]
        self.s.basis = "gold"
        sh = self.sheet()
        self.assertEqual(sh.net, D("420000"))
        self.assertEqual(sh.nisab, D("1049760"))                                 # 87.48 g × 12,000
        self.assertEqual(sh.due, D("0"))

    def test_page_saves_prices_and_choices(self):
        r = self.client.get(reverse("zakat"))
        self.assertContains(r, "৳13,000")
        self.client.post(reverse("zakat"), {"basis": "silver", "silver_price": "160", "gold_price": "12000", "gold_grams": "10", "silver_grams": "0",
                                            "other_assets": "0", "other_debts": "20000", "farm_share": "100", "count_wallets": "1", "count_creditors": "1", "count_shops": "1"})
        self.s.refresh_from_db()
        self.assertEqual((self.s.silver_price, self.s.other_debts, self.s.skip), (D("160"), D("20000"), ["debtors"]))

    def test_farm_lines_only_for_money_people_and_at_their_share(self):
        b, owner, staff = make_farm("farm")
        self.client.force_login(owner)
        ZakatSettings.objects.create(user=owner, farm_share=40)
        r = self.client.get(reverse("zakat"))
        self.assertContains(r, "Farm cash &amp; bank")
        self.assertContains(r, "40%")
        self.client.force_login(staff)
        self.assertNotContains(self.client.get(reverse("zakat")), "Farm cash")
