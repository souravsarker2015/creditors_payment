"""When to harvest: growth from weighings, carried forward to the selling size."""
from datetime import date, timedelta
from decimal import Decimal as D

from django.test import TestCase
from django.urls import reverse

from apps.business.core.models import Unit
from apps.business.core.testing import make_farm
from apps.business.species.models import Species

from . import forecast
from .models import CultureCycle, Mortality, Pond, SampleWeighing, Stocking

TODAY = date.today()


class ForecastTests(TestCase):
    def setUp(self):
        self.b, self.owner, self.staff = make_farm()
        self.client.force_login(self.owner)
        self.kg = Unit.objects.get(business=self.b, symbol="kg")
        self.rui = Species.objects.get(business=self.b, name="Rui")
        self.pond = Pond.objects.create(business=self.b, name="East")
        self.cycle = CultureCycle.objects.create(business=self.b, pond=self.pond, name="Carp", start_date=TODAY - timedelta(days=100))
        Stocking.objects.create(business=self.b, cycle=self.cycle, date=TODAY - timedelta(days=100), species=self.rui,
                                count=1000, weight=D("50"), weight_unit=self.kg)          # 50 g each

    def weigh(self, days_ago, grams):
        SampleWeighing.objects.create(business=self.b, cycle=self.cycle, date=TODAY - timedelta(days=days_ago), species=self.rui,
                                      fish_count=10, total_weight=D(grams) * 10 / 1000, unit=self.kg)

    def one(self):
        return forecast.for_cycle(CultureCycle.objects.get(pk=self.cycle.pk))[0]

    def test_seeded_fish_have_a_selling_size(self):
        self.assertEqual(self.rui.market_size_g, 1000)

    def test_growth_from_the_last_two_weighings(self):
        self.weigh(30, 400)
        self.weigh(10, 600)                                   # 200 g in 20 days = 10 g a day
        f = self.one()
        self.assertEqual(f.growth, D("10"))
        self.assertEqual(f.now_g, D("700"))                   # 10 more days since
        self.assertEqual(f.status, "growing")
        self.assertEqual(f.ready_on, TODAY + timedelta(days=30))
        self.assertEqual(f.days_left, 30)
        self.assertEqual(f.kg_at_ready, D("1000"))            # 1000 fish × 1 kg

    def test_one_weighing_uses_the_fingerlings_as_the_start(self):
        self.weigh(0, 550)                                    # 500 g in 100 days = 5 g a day
        f = self.one()
        self.assertEqual(f.growth, D("5"))
        self.assertEqual(f.ready_on, TODAY + timedelta(days=90))

    def test_ready_shows_on_the_farm_list(self):
        self.weigh(20, 800)
        self.weigh(0, 1050)
        Mortality.objects.create(business=self.b, cycle=self.cycle, date=TODAY, species=self.rui, count=100)
        f = self.one()
        self.assertEqual(f.status, "ready")
        self.assertEqual(f.alive, 900)
        r = self.client.get(reverse("business:home"))
        self.assertContains(r, "look ready to sell")

    def test_no_growth_is_a_warning(self):
        self.weigh(20, 600)
        self.weigh(0, 601)
        self.assertEqual(self.one().status, "slow")
        self.assertContains(self.client.get(reverse("business:home")), "aren&#x27;t growing")

    def test_without_a_selling_size(self):
        self.rui.market_size_g = None
        self.rui.save()
        self.weigh(0, 550)
        f = self.one()
        self.assertEqual(f.status, "no_size")
        self.assertIsNone(f.ready_on)

    def test_page_calendar_and_cycle_tab(self):
        self.weigh(30, 400)
        self.weigh(10, 600)
        r = self.client.get(reverse("business:harvest_forecast"))
        self.assertContains(r, "East")
        self.assertContains(r, "30 days to go")
        r = self.client.get(reverse("business:cycle_detail", args=[self.cycle.pk]))
        self.assertContains(r, "When will they reach selling size?")
        ready = TODAY + timedelta(days=30)
        r = self.client.get(reverse("business:calendar") + f"?month={ready:%Y-%m}")
        self.assertContains(r, "Ready to sell")

    def test_data_entry_sees_no_money(self):
        self.weigh(30, 400)
        self.weigh(10, 600)
        self.client.force_login(self.staff)
        r = self.client.get(reverse("business:harvest_forecast"))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "Fish worth at selling size")

    def test_very_slow_growth_says_so_instead_of_a_far_date(self):
        self.weigh(20, 300)
        self.weigh(0, 310)                                    # 0.5 g a day: 1,380 days to 1 kg
        f = self.one()
        self.assertTrue(f.far)
        self.assertContains(self.client.get(reverse("business:harvest_forecast")), "take over a year")
