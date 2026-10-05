"""Fish prices: noted prices and sale rates on one per-kg board."""
from datetime import date, timedelta
from decimal import Decimal as D

from django.test import TestCase
from django.urls import reverse

from apps.business.core.models import Unit
from apps.business.core.testing import make_farm
from apps.business.finance.models import Account
from apps.business.sales.models import FishSale, FishSaleLine
from apps.business.species.models import Species

from . import prices
from .models import Market, PriceCheck

TODAY = date.today()


class PriceBoardTests(TestCase):
    def setUp(self):
        self.b, self.owner, self.staff = make_farm()
        self.client.force_login(self.owner)
        self.mon = Unit.objects.get(business=self.b, symbol="mon")
        self.kg = Unit.objects.get(business=self.b, symbol="kg")
        self.rui = Species.objects.get(business=self.b, name="Rui")
        self.jessore = Market.objects.create(business=self.b, name="Jessore")
        self.khulna = Market.objects.create(business=self.b, name="Khulna")

    def note(self, rate, unit=None, days=0, market=None):
        return PriceCheck.objects.create(business=self.b, species=self.rui, rate=D(rate), unit=unit or self.mon,
                                         date=TODAY - timedelta(days=days), market=market)

    def test_a_mon_price_is_turned_into_per_kg(self):
        self.assertEqual(self.note("12000").rate_kg, D("300.00"))

    def test_sales_by_weight_feed_the_board(self):
        sale = FishSale.objects.create(business=self.b, date=TODAY, market=self.khulna, received_now=0,
                                       account=Account.objects.get(business=self.b, name="Cash"))
        FishSaleLine.objects.create(business=self.b, sale=sale, species=self.rui, quantity=D("2"), unit=self.mon, rate=D("14000"))
        b = prices.board(self.b)[0]
        self.assertEqual((b.latest.per_kg, b.latest.source), (D("350.00"), "sale"))

    def test_change_high_low_and_best_market(self):
        self.note("280", self.kg, days=20, market=self.jessore)
        self.note("300", self.kg, days=2, market=self.jessore)
        self.note("330", self.kg, days=1, market=self.khulna)
        b = prices.board(self.b)[0]
        self.assertEqual(b.change_pct, 12)                 # 315 vs 280
        self.assertEqual((b.low, b.high), (D("280.00"), D("330.00")))
        self.assertEqual(b.best_market, self.khulna)
        self.assertTrue(b.spark_path)

    def test_page_and_noting_a_price(self):
        r = self.client.post(reverse("business:prices"), {"species": self.rui.pk, "date": TODAY.isoformat(),
                                                          "rate": "13000", "unit": self.mon.pk, "market": self.jessore.pk})
        self.assertRedirects(r, reverse("business:prices"))
        r = self.client.get(reverse("business:prices"))
        self.assertContains(r, "Rui")
        self.assertContains(r, "325")

    def test_viewers_see_prices_but_cannot_add(self):
        from apps.business.core.models import Membership, Role

        Membership.objects.filter(user=self.staff).update(role=Role.VIEWER)
        self.client.force_login(self.staff)
        self.note("12000")
        r = self.client.get(reverse("business:prices"))
        self.assertContains(r, "Rui")
        self.assertNotContains(r, "Save price")
        self.client.post(reverse("business:prices"), {"species": self.rui.pk, "date": TODAY.isoformat(), "rate": "1", "unit": self.mon.pk})
        self.assertEqual(PriceCheck.objects.count(), 1)
