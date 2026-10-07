"""Fish moved between ponds, and the fish left in a pond after uncounted harvests."""
from datetime import date, timedelta
from decimal import Decimal as D

from django.test import TestCase
from django.urls import reverse

from apps.business.core.models import Role, Unit
from apps.business.core.testing import make_farm
from apps.business.finance.services import statement
from apps.business.species.models import Species

from . import forecast, services
from .models import CultureCycle, CycleStatus, FishMove, Harvest, Mortality, Pond, PondStatus, SampleWeighing, Stocking

TODAY = date.today()


class Base(TestCase):
    def setUp(self):
        self.b, self.owner, self.staff = make_farm()
        self.client.force_login(self.owner)
        self.kg = Unit.objects.get(business=self.b, symbol="kg")
        self.mon = Unit.objects.get(business=self.b, symbol="mon")
        self.pcs = Unit.objects.get(business=self.b, symbol="pcs")
        self.rui = Species.objects.get(business=self.b, name="Rui")
        self.katla = Species.objects.get(business=self.b, name="Katla")
        self.nursery = Pond.objects.create(business=self.b, name="Nursery")
        self.big = Pond.objects.create(business=self.b, name="Big pond", status=PondStatus.EMPTY)
        self.cycle = CultureCycle.objects.create(business=self.b, pond=self.nursery, start_date=TODAY - timedelta(days=60))
        Stocking.objects.create(business=self.b, cycle=self.cycle, date=TODAY - timedelta(days=60), species=self.rui,
                                count=10000, weight=D("10"), weight_unit=self.kg, cost=D("20000"), paid_now=D("20000"))

    def summary(self, cycle=None):
        return services.summarize(CultureCycle.objects.get(pk=(cycle or self.cycle).pk))

    def move(self, **data):
        post = {"move-date": TODAY.isoformat(), "move-species": self.rui.pk, "move-to_pond": self.big.pk,
                "move-count": "4000", "move-weight": "200", "move-weight_unit": self.kg.pk, "move-value": "8000"}
        post.update({f"move-{k}": v for k, v in data.items()})
        return self.client.post(reverse("business:entry_add", args=[self.cycle.pk, "move"]), post)


class MoveTests(Base):
    def test_moving_into_an_empty_pond_starts_a_cycle_there(self):
        r = self.move()
        self.assertEqual(r.status_code, 302)
        m = FishMove.objects.get()
        target = m.to_cycle
        self.assertEqual(target.pond, self.big)
        self.assertEqual(target.status, CycleStatus.RUNNING)
        self.assertEqual(target.start_date, TODAY)
        self.big.refresh_from_db()
        self.assertEqual(self.big.status, PondStatus.IN_USE)

    def test_moving_into_a_running_cycle_joins_it(self):
        running = CultureCycle.objects.create(business=self.b, pond=self.big, start_date=TODAY - timedelta(days=5))
        self.move()
        self.assertEqual(FishMove.objects.get().to_cycle, running)
        self.assertEqual(CultureCycle.objects.filter(pond=self.big).count(), 1)

    def test_fish_and_value_leave_one_pond_and_join_the_other(self):
        self.move()
        src, dst = self.summary(), self.summary(FishMove.objects.get().to_cycle)
        self.assertEqual(src.alive, 6000)
        self.assertEqual(src.moved_out, 4000)
        self.assertEqual(src.moved_out_value, D("8000"))
        self.assertEqual(src.profit, D("8000") - D("20000"))        # the moved fish count as earned
        self.assertEqual(dst.alive, 4000)
        self.assertEqual(dst.moved_in, 4000)
        self.assertEqual(dst.cost, D("8000"))
        self.assertEqual(dst.species[0].stocked_kg, D("200"))       # their size, for growth and FCR
        self.assertEqual(src.profit + dst.profit, -D("20000"))      # the farm as a whole: no money appeared

    def test_no_money_moves_and_no_fingerling_cost_is_added(self):
        self.move()
        s = statement(self.b, TODAY - timedelta(days=90), TODAY)
        fingerlings = sum((l.amount for l in s.expense if l.key == "stocking"), D(0))
        self.assertEqual(fingerlings, D("20000"))

    def test_cannot_move_more_fish_than_are_left(self):
        r = self.move(count="12000")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(FishMove.objects.exists())
        self.assertContains(r, "Only about 10,000")

    def test_date_before_the_target_cycle_started_is_refused(self):
        CultureCycle.objects.create(business=self.b, pond=self.big, start_date=TODAY)
        r = self.move(date=(TODAY - timedelta(days=3)).isoformat())
        self.assertEqual(r.status_code, 200)
        self.assertFalse(FishMove.objects.exists())

    def test_the_value_is_suggested_from_the_cost_so_far(self):
        r = self.client.get(reverse("business:cycle_detail", args=[self.cycle.pk]))
        self.assertContains(r, "৳2.00 a fish")                      # ৳20,000 over 10,000 fish

    def test_both_cycle_pages_show_the_move_and_edit_and_delete_work(self):
        self.move()
        m = FishMove.objects.get()
        self.assertContains(self.client.get(reverse("business:cycle_detail", args=[self.cycle.pk])), "moved to Big pond")
        self.assertContains(self.client.get(reverse("business:cycle_detail", args=[m.to_cycle_id])), "came from Nursery")
        r = self.client.post(reverse("business:entry_edit", args=["move", m.pk]), {
            "date": TODAY.isoformat(), "species": self.rui.pk, "to_pond": self.big.pk, "count": "3000",
            "weight": "", "weight_unit": self.kg.pk, "value": "6000"})
        self.assertEqual(r.status_code, 302)
        m.refresh_from_db()
        self.assertEqual((m.count, m.value), (3000, D("6000")))
        self.client.post(reverse("business:entry_delete", args=["move", m.pk]))
        self.assertEqual(self.summary().alive, 10000)

    def test_data_entry_staff_can_move_fish(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.move().status_code, 302)

    def test_forecast_uses_moved_fish(self):
        self.move()
        target = FishMove.objects.get().to_cycle
        fc = forecast.for_cycle(CultureCycle.objects.get(pk=target.pk))
        self.assertEqual(fc[0].alive, 4000)
        self.assertEqual(fc[0].last, None)                        # not weighed yet in the new pond

    def test_calendar_lists_the_move(self):
        self.move()
        r = self.client.get(reverse("business:calendar"))
        self.assertContains(r, "Fish moved \\u00b7 Nursery \\u2192 Big pond")


class FishLeftTests(Base):
    def test_uncounted_harvest_by_weight_is_counted_by_size(self):
        SampleWeighing.objects.create(business=self.b, cycle=self.cycle, date=TODAY - timedelta(days=5), species=self.rui,
                                      fish_count=10, total_weight=D("1"), unit=self.kg)          # 100 g each
        Harvest.objects.create(business=self.b, cycle=self.cycle, date=TODAY, species=self.rui, quantity=D("5"), unit=self.mon)  # 200 kg
        s = self.summary()
        self.assertEqual(s.species[0].harvested_count, 2000)
        self.assertTrue(s.estimated)
        self.assertEqual(s.alive, 8000)
        self.assertEqual(s.biomass_kg, D("800"))

    def test_a_typed_count_wins(self):
        Harvest.objects.create(business=self.b, cycle=self.cycle, date=TODAY, species=self.rui, quantity=D("50"), unit=self.kg, fish_count=300)
        s = self.summary()
        self.assertEqual(s.alive, 9700)
        self.assertFalse(s.estimated)

    def test_harvest_in_pieces_is_its_own_count(self):
        Harvest.objects.create(business=self.b, cycle=self.cycle, date=TODAY, species=self.rui, quantity=D("700"), unit=self.pcs)
        self.assertEqual(self.summary().alive, 9300)

    def test_size_before_any_weighing_comes_from_the_fingerlings(self):
        Harvest.objects.create(business=self.b, cycle=self.cycle, date=TODAY, species=self.rui, quantity=D("1"), unit=self.kg)   # 1 g each
        self.assertEqual(self.summary().alive, 9000)

    def test_deaths_without_a_species_lower_the_fish_left(self):
        Stocking.objects.create(business=self.b, cycle=self.cycle, date=TODAY - timedelta(days=60), species=self.katla, count=10000)
        Mortality.objects.create(business=self.b, cycle=self.cycle, date=TODAY, count=1000)
        s = self.summary()
        self.assertEqual(s.alive, 19000)
        self.assertEqual({r.species.name: r.alive for r in s.species}, {"Rui": 9500, "Katla": 9500})

    def test_death_alert_counts_mixed_deaths(self):
        Mortality.objects.create(business=self.b, cycle=self.cycle, date=TODAY, count=500)    # 5% of the pond
        tasks = services.farm_tasks(self.b)
        self.assertTrue(any(t.kind == "deaths" for t in tasks))

    def test_harvest_form_tip_mentions_the_estimate(self):
        r = self.client.get(reverse("business:cycle_detail", args=[self.cycle.pk]))
        self.assertContains(r, "worked out from the weight")


class DeathCauseTests(Base):
    def test_suggested_causes_are_offered(self):
        r = self.client.get(reverse("business:cycle_detail", args=[self.cycle.pk]))
        self.assertContains(r, 'list="death-causes-mortality"')
        self.assertContains(r, "Escaped in flood or rain")


class UnsoldHarvestTests(Base):
    def test_harvest_not_sold_is_pointed_out(self):
        from apps.business.sales.models import FishSale, FishSaleLine

        Harvest.objects.create(business=self.b, cycle=self.cycle, date=TODAY, species=self.rui, quantity=D("100"), unit=self.kg, fish_count=500)
        sale = FishSale.objects.create(business=self.b, cycle=self.cycle, date=TODAY)
        FishSaleLine.objects.create(business=self.b, sale=sale, species=self.rui, quantity=D("1"), unit=self.mon, rate=D("8000"))   # 40 kg
        r = self.client.get(reverse("business:cycle_detail", args=[self.cycle.pk]))
        self.assertContains(r, "100 kg harvested · 40 kg sold")
        self.assertContains(r, "60 kg harvested but not sold")
        FishSaleLine.objects.create(business=self.b, sale=sale, species=self.rui, quantity=D("60"), unit=self.kg, rate=D("200"))
        self.assertNotContains(self.client.get(reverse("business:cycle_detail", args=[self.cycle.pk])), "harvested but not sold")
