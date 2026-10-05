"""Partners: capital khata, money in accounts, and profit split by share."""
from datetime import date, timedelta
from decimal import Decimal as D

from django.test import TestCase
from django.urls import reverse

from apps.business.core.testing import make_farm
from apps.business.finance import services as money
from apps.business.finance.models import Account, Category, Transaction

from . import services
from .models import Partner, PartnerEntry

TODAY = date.today()
JAN = TODAY.replace(month=1, day=1)


class PartnerTests(TestCase):
    def setUp(self):
        self.b, self.owner, self.staff = make_farm()
        self.client.force_login(self.owner)
        self.cash = Account.objects.get(business=self.b, name="Cash")
        self.karim = Partner.objects.create(business=self.b, name="Karim", share_pct=D("60"), opening_capital=D("100000"), joined_on=JAN)
        self.rahim = Partner.objects.create(business=self.b, name="Rahim", share_pct=D("40"), joined_on=JAN)

    def entry(self, partner, kind, amount):
        return PartnerEntry.objects.create(business=self.b, partner=partner, date=TODAY, kind=kind, amount=D(amount), account=self.cash)

    def earn(self, amount):
        cat = Category.objects.filter(business=self.b, type="income", scope="business").first()
        Transaction.objects.create(business=self.b, date=TODAY, category=cat, amount=D(amount), account=self.cash)

    def test_khata(self):
        self.entry(self.karim, "in", "50000")
        self.entry(self.karim, "out", "20000")
        k = services.khatas(self.b)[self.karim.pk]
        self.assertEqual((k.put_in, k.taken_out, k.net), (D("150000"), D("20000"), D("130000")))

    def test_money_moves_but_profit_does_not(self):
        before = money.balances(self.b)[self.cash.pk]
        r = self.client.post(reverse("business:partner_entry", args=[self.rahim.pk]),
                             {"date": TODAY.isoformat(), "kind": "in", "amount": "30000", "account": self.cash.pk})
        self.assertRedirects(r, reverse("business:partner_detail", args=[self.rahim.pk]))
        self.assertEqual(money.balances(self.b)[self.cash.pk], before + D("30000"))
        self.assertEqual(money.statement(self.b, JAN, TODAY).profit, D("0"))

    def test_profit_split_by_share_less_what_was_taken(self):
        self.earn("50000")
        self.entry(self.rahim, "out", "25000")
        s = services.sharing(self.b, JAN, TODAY)
        rows = {r.partner.name: r for r in s.rows}
        self.assertEqual(s.profit, D("50000"))
        self.assertEqual((rows["Karim"].share, rows["Karim"].left), (D("30000"), D("30000")))
        self.assertEqual((rows["Rahim"].share, rows["Rahim"].left), (D("20000"), D("-5000")))
        r = self.client.get(reverse("business:partner_sharing"))
        self.assertContains(r, "taken beyond share")
        self.assertNotContains(r, "add up to")

    def test_shares_cannot_pass_100(self):
        r = self.client.post(reverse("business:partners_add"), {"name": "Salam", "share_pct": "10", "joined_on": TODAY.isoformat()})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "can&#x27;t be more than 100")
        self.rahim.share_pct = D("30")
        self.rahim.save()
        r = self.client.post(reverse("business:partners_add"), {"name": "Salam", "share_pct": "10", "joined_on": TODAY.isoformat()})
        self.assertEqual(r.status_code, 302)

    def test_shares_short_of_100_are_flagged(self):
        self.rahim.share_pct = D("30")
        self.rahim.save()
        self.earn("10000")
        s = services.sharing(self.b, JAN, TODAY)
        self.assertEqual(s.unshared, D("1000"))
        self.assertContains(self.client.get(reverse("business:partner_sharing") + "?period=all"), "add up to 90")

    def test_pages_and_periods(self):
        self.assertContains(self.client.get(reverse("business:partners")), "Karim")
        self.assertContains(self.client.get(reverse("business:partner_detail", args=[self.karim.pk])), "1,00,000")
        r = self.client.get(reverse("business:partner_sharing") + f"?from={JAN - timedelta(days=400):%Y-%m-%d}&to={TODAY:%Y-%m-%d}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["period"], "custom")

    def test_data_entry_cannot_see_partners(self):
        self.client.force_login(self.staff)
        for url in (reverse("business:partners"), reverse("business:partner_detail", args=[self.karim.pk]), reverse("business:partner_sharing")):
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_a_loss_year_is_shown_as_a_share_of_the_loss(self):
        cat = Category.objects.filter(business=self.b, type="expense", scope="business").first()
        Transaction.objects.create(business=self.b, date=TODAY, category=cat, amount=D("10000"), account=self.cash)
        r = self.client.get(reverse("business:partner_sharing"))
        self.assertContains(r, "share of the loss")
        self.assertNotContains(r, "taken beyond share")
        r = self.client.get(reverse("business:partner_detail", args=[self.karim.pk]))
        self.assertContains(r, "share of the loss")
        self.assertContains(r, "6,000")
