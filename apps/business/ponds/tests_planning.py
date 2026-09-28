"""Planning helpers: last sale prices, "if you sell now", and today's pond work."""
import json
from datetime import date, timedelta
from decimal import Decimal as D

from django.test import TestCase
from django.urls import reverse

from apps.business.core.models import Unit
from apps.business.core.testing import make_farm
from apps.business.feed.models import FeedProduct, FeedUsage
from apps.business.markets.models import DeductionMethod, DeductionType, Market
from apps.business.sales.models import FishSale, FishSaleLine, SaleDeduction
from apps.business.sales.services import last_rates
from apps.business.species.models import Species

from .models import CultureCycle, Ownership, Pond, SampleWeighing, Stocking
from .services import farm_tasks, projection, summarize, usual_price_per_kg


def ago(n):
    return date.today() - timedelta(days=n)


class PlanningBase(TestCase):
    def setUp(self):
        self.b, self.owner, self.staff = make_farm()
        self.client.force_login(self.owner)
        self.kg = Unit.objects.get(business=self.b, symbol="kg")
        self.mon = Unit.objects.get(business=self.b, symbol="mon")
        self.pcs = Unit.objects.get(business=self.b, symbol="pcs")
        self.rui = Species.objects.get(business=self.b, name="Rui")
        self.katla = Species.objects.get(business=self.b, name="Katla")
        self.jessore = Market.objects.create(business=self.b, name="Jessore")
        self.khulna = Market.objects.create(business=self.b, name="Khulna")
        self.pond = Pond.objects.create(business=self.b, name="East")
        self.cycle = CultureCycle.objects.create(business=self.b, pond=self.pond, start_date=ago(100))

    def sell(self, days, species, qty, unit, rate, market=None, cycle=None, commission=None):
        sale = FishSale.objects.create(business=self.b, date=ago(days), market=market, cycle=cycle)
        FishSaleLine.objects.create(business=self.b, sale=sale, species=species, quantity=D(qty), unit=unit, rate=D(rate))
        if commission:
            kind = DeductionType.objects.get_or_create(business=self.b, name="Commission")[0]
            SaleDeduction.objects.create(business=self.b, sale=sale, deduction_type=kind, method=DeductionMethod.PERCENT, value=D(commission))
        sale.recalc()
        return sale


class LastRateTests(PlanningBase):
    def test_latest_sale_wins_and_is_kept_per_market(self):
        self.sell(20, self.rui, "10", self.kg, "280", market=self.jessore)
        self.sell(5, self.rui, "10", self.kg, "300", market=self.jessore)
        self.sell(2, self.rui, "10", self.kg, "310", market=self.khulna)
        rates = last_rates(self.b)
        self.assertEqual(D(rates[f"{self.rui.pk}:{self.jessore.pk}:weight"]["per_base"]), D("300"))
        self.assertEqual(D(rates[f"{self.rui.pk}:{self.khulna.pk}:weight"]["per_base"]), D("310"))
        self.assertEqual(D(rates[f"{self.rui.pk}:*:weight"]["per_base"]), D("310"))   # any market: the newest

    def test_price_is_stored_per_kg_so_any_unit_works(self):
        self.sell(1, self.rui, "2", self.mon, "12000")   # ৳12,000 a mon
        per_kg = D(last_rates(self.b)[f"{self.rui.pk}:*:weight"]["per_base"])
        self.assertEqual(per_kg * self.mon.factor, D("12000"))

    def test_pieces_are_kept_apart_from_weight(self):
        self.sell(1, self.rui, "100", self.pcs, "50")
        rates = last_rates(self.b)
        self.assertIn(f"{self.rui.pk}:*:count", rates)
        self.assertNotIn(f"{self.rui.pk}:*:weight", rates)

    def test_editing_a_sale_ignores_its_own_price(self):
        self.sell(9, self.rui, "10", self.kg, "250")
        sale = self.sell(1, self.rui, "10", self.kg, "999")
        self.assertEqual(D(last_rates(self.b, exclude_sale=sale)[f"{self.rui.pk}:*:weight"]["per_base"]), D("250"))

    def test_deleted_sales_are_ignored(self):
        self.sell(9, self.rui, "10", self.kg, "250")
        sale = self.sell(1, self.rui, "10", self.kg, "999")
        sale.is_deleted = True
        sale.save()
        self.assertEqual(D(last_rates(self.b)[f"{self.rui.pk}:*:weight"]["per_base"]), D("250"))

    def test_sale_form_carries_the_prices(self):
        self.sell(1, self.rui, "10", self.kg, "300", market=self.jessore)
        r = self.client.get(reverse("business:sale_add"))
        self.assertEqual(r.status_code, 200)
        self.assertIn(f'"{self.rui.pk}:{self.jessore.pk}:weight"', r.context["sale_json"])
        self.assertIn("{rate}", json.loads(r.context["sale_json"])["text"]["last"])


class ProjectionTests(PlanningBase):
    def setUp(self):
        super().setUp()
        Stocking.objects.create(business=self.b, cycle=self.cycle, date=ago(100), species=self.rui, count=1000, cost=D("20000"))
        # 20 fish weigh 10 kg → 500 g each → 1,000 fish ≈ 500 kg in the pond
        SampleWeighing.objects.create(business=self.b, cycle=self.cycle, date=ago(3), species=self.rui, fish_count=20,
                                      total_weight=D("10"), unit=self.kg)

    def test_break_even_and_cost_per_kg(self):
        p = projection(summarize(self.cycle))
        self.assertEqual(p.fish_kg, D("500"))
        self.assertEqual(p.to_cover, D("20000"))
        self.assertEqual(p.break_even, D("40"))       # 20,000 over 500 kg
        self.assertEqual(p.cost_per_kg, D("40"))

    def test_sales_already_made_lower_the_break_even(self):
        self.sell(2, self.rui, "10", self.kg, "1500", cycle=self.cycle)   # ৳15,000 in
        p = projection(summarize(self.cycle))
        self.assertEqual(p.to_cover, D("5000"))
        self.assertEqual(p.break_even, D("10"))

    def test_covered_costs_mean_no_break_even_left(self):
        self.sell(2, self.rui, "10", self.kg, "3000", cycle=self.cycle)
        self.assertEqual(projection(summarize(self.cycle)).to_cover, D("0"))

    def test_usual_price_is_after_deductions(self):
        self.sell(10, self.rui, "100", self.kg, "300", commission="10")   # ৳30,000 − 10%
        self.assertEqual(usual_price_per_kg(self.b, [self.rui.pk]), D("270"))

    def test_usual_price_ignores_old_sales_and_other_fish(self):
        self.sell(200, self.rui, "100", self.kg, "100")
        self.sell(5, self.katla, "100", self.kg, "500")
        self.assertIsNone(usual_price_per_kg(self.b, [self.rui.pk]))

    def test_cycle_page_shows_the_projection(self):
        r = self.client.get(reverse("business:cycle_detail", args=[self.cycle.pk]))
        self.assertContains(r, 'id="proj-price"')
        self.assertEqual(r.context["p"].break_even, D("40"))

    def test_without_a_weighing_it_asks_for_one(self):
        SampleWeighing.objects.all().delete()
        r = self.client.get(reverse("business:cycle_detail", args=[self.cycle.pk]))
        self.assertNotContains(r, 'id="proj-price"')
        self.assertIsNone(r.context["p"].break_even)

    def test_finished_cycles_have_no_projection(self):
        self.cycle.status = "finished"
        self.cycle.ended_on = ago(1)
        self.cycle.save()
        r = self.client.get(reverse("business:cycle_detail", args=[self.cycle.pk]))
        self.assertIsNone(r.context["p"])


class FarmTaskTests(PlanningBase):
    def kinds(self):
        return [t.kind for t in farm_tasks(self.b)]

    def test_unfed_pond_is_a_task_until_it_is_fed(self):
        self.assertIn("feed", self.kinds())
        feed = FeedProduct.objects.create(business=self.b, name="Grower", bag_size=25, bag_unit=self.kg)
        FeedUsage.objects.create(business=self.b, cycle=self.cycle, date=date.today(), product=feed, quantity=D("20"), unit=self.kg)
        self.assertNotIn("feed", self.kinds())

    def test_weighing_is_due_after_three_weeks(self):
        SampleWeighing.objects.create(business=self.b, cycle=self.cycle, date=ago(5), species=self.rui, fish_count=10, total_weight=D("2"), unit=self.kg)
        self.assertNotIn("weigh", self.kinds())
        SampleWeighing.objects.all().update(date=ago(25))
        self.assertIn("weigh", self.kinds())

    def test_a_new_cycle_is_not_nagged_to_weigh_at_once(self):
        self.cycle.start_date = ago(3)
        self.cycle.save()
        self.assertNotIn("weigh", self.kinds())

    def test_harvest_soon_and_overdue(self):
        self.cycle.expected_harvest = date.today() + timedelta(days=30)
        self.cycle.save()
        self.assertNotIn("harvest", self.kinds())
        self.cycle.expected_harvest = ago(2)
        self.cycle.save()
        task = next(t for t in farm_tasks(self.b) if t.kind == "harvest")
        self.assertEqual(task.tone, "critical")
        self.assertEqual(farm_tasks(self.b)[0].kind, "harvest")   # most urgent first

    def test_lease_ending_within_a_month(self):
        Pond.objects.create(business=self.b, name="West", ownership=Ownership.LEASED, lease_end=date.today() + timedelta(days=10))
        Pond.objects.create(business=self.b, name="North", ownership=Ownership.LEASED, lease_end=date.today() + timedelta(days=90))
        leases = [t.title for t in farm_tasks(self.b) if t.kind == "lease"]
        self.assertEqual(len(leases), 1)
        self.assertIn("West", leases[0])

    def test_finished_cycles_need_nothing(self):
        self.cycle.status = "finished"
        self.cycle.save()
        self.assertEqual([k for k in self.kinds() if k != "lease"], [])

    def test_home_page_lists_the_tasks(self):
        r = self.client.get(reverse("business:home"))
        self.assertContains(r, reverse("business:feed_usage_bulk"))
        self.assertTrue(r.context["tasks"])

    def test_other_farms_tasks_stay_out(self):
        other, _owner, _staff = make_farm(owner_name="other")
        self.assertEqual(farm_tasks(other), [])
