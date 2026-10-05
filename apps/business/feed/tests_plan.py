"""Feed plan: fish weight × rate for their size, cut for the water; stock days."""
from datetime import date, timedelta
from decimal import Decimal as D

from django.test import TestCase
from django.urls import reverse

from apps.business.core.models import Unit
from apps.business.core.testing import make_farm
from apps.business.ponds.models import CultureCycle, Pond, SampleWeighing, Stocking, WaterTest
from apps.business.species.models import Species

from . import planner
from .models import FeedProduct, FeedPurchase, FeedPurchaseLine, FeedUsage

TODAY = date.today()


class PlanTests(TestCase):
    def setUp(self):
        self.b, self.owner, self.staff = make_farm()
        self.client.force_login(self.owner)
        self.kg = Unit.objects.get(business=self.b, symbol="kg")
        self.rui = Species.objects.get(business=self.b, name="Rui")
        self.pond = Pond.objects.create(business=self.b, name="East")
        self.cycle = CultureCycle.objects.create(business=self.b, pond=self.pond, name="Carp", start_date=TODAY - timedelta(days=60))
        Stocking.objects.create(business=self.b, cycle=self.cycle, date=TODAY - timedelta(days=60), species=self.rui,
                                count=1000, weight=D("20"), weight_unit=self.kg)          # 20 g each

    def plan(self):
        return planner.plans(self.b)[0]

    def test_rates_fall_as_fish_grow(self):
        self.assertEqual(planner.rate_for(D("3")), D("10"))
        self.assertEqual(planner.rate_for(D("150")), D("3"))
        self.assertEqual(planner.rate_for(D("1500")), D("1.5"))

    def test_before_weighing_it_uses_the_fingerling_weight(self):
        p = self.plan()
        self.assertEqual(p.fish_kg, D("20.0"))
        self.assertEqual(p.per_day, D("1.4"))         # 20 kg × 7%
        self.assertTrue(p.stale)
        self.assertFalse(p.fish[0].from_weighing)

    def test_after_weighing_it_follows_the_fish(self):
        SampleWeighing.objects.create(business=self.b, cycle=self.cycle, date=TODAY, species=self.rui, fish_count=10, total_weight=D("2"), unit=self.kg)
        p = self.plan()                                 # 1000 × 200 g = 200 kg × 3%
        self.assertEqual(p.per_day, D("6.0"))
        self.assertEqual(p.per_meal, D("3.0"))
        self.assertFalse(p.stale)

    def test_cold_water_and_low_oxygen_cut_the_feed(self):
        SampleWeighing.objects.create(business=self.b, cycle=self.cycle, date=TODAY, species=self.rui, fish_count=10, total_weight=D("2"), unit=self.kg)
        WaterTest.objects.create(business=self.b, cycle=self.cycle, date=TODAY, temperature=D("19"))
        self.assertEqual(self.plan().per_day, D("3.6"))
        WaterTest.objects.create(business=self.b, cycle=self.cycle, date=TODAY, oxygen=D("2"))
        self.assertEqual(self.plan().per_day, D("3.0"))
        self.assertIn("oxygen", str(self.plan().reason).lower())

    def test_compares_with_what_was_fed(self):
        feed = FeedProduct.objects.create(business=self.b, name="Floating", bag_size=D("25"), bag_unit=self.kg)
        for n in range(7):
            FeedUsage.objects.create(business=self.b, cycle=self.cycle, date=TODAY - timedelta(days=n), product=feed, quantity=D("3"), unit=self.kg)
        p = self.plan()
        self.assertEqual(p.fed_per_day, D("3.0"))
        self.assertEqual(p.verdict, "over")              # 3 kg vs 1.4 planned

    def test_stock_days(self):
        feed = FeedProduct.objects.create(business=self.b, name="Floating", bag_size=D("25"), bag_unit=self.kg)
        from apps.business.parties.models import Party

        sup = Party.objects.create(business=self.b, name="Dealer", is_supplier=True)
        buy = FeedPurchase.objects.create(business=self.b, supplier=sup, date=TODAY - timedelta(days=20))
        FeedPurchaseLine.objects.create(business=self.b, purchase=buy, product=feed, quantity=D("100"), unit=self.kg, rate=D("50"))
        for n in range(14):
            FeedUsage.objects.create(business=self.b, cycle=self.cycle, date=TODAY - timedelta(days=n), product=feed, quantity=D("2"), unit=self.kg)
        s = planner.stock_days(self.b)[0]
        self.assertEqual((s.left_kg, s.per_day, s.days), (D("72"), D("2.0"), 36))

    def test_page_and_filling_todays_feeding(self):
        r = self.client.get(reverse("business:feed_plan"))
        self.assertContains(r, "East")
        self.assertContains(r, "1.4")
        r = self.client.get(reverse("business:feed_usage_bulk") + "?plan=1")
        self.assertContains(r, 'value="1.4"')
