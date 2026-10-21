"""Whole-farm costs shared between the ponds, and each pond at a glance."""
from datetime import date, timedelta
from decimal import Decimal as D

from django.test import TestCase
from django.urls import reverse

from apps.business.assets.models import Equipment, Service
from apps.business.core.models import Unit
from apps.business.core.testing import make_farm
from apps.business.feed.models import FeedProduct, FeedUsage
from apps.business.finance.models import Account, Category, Transaction
from apps.business.species.models import Species
from apps.business.staff.models import Earning, Worker

from . import services
from .models import CultureCycle, Mortality, Pond, SampleWeighing, Stocking, WaterTest
from .shared import shares

TODAY = date.today()


def ago(n):
    return TODAY - timedelta(days=n)


class SharedBase(TestCase):
    """Two ponds with fish: North is 100 decimals, South 50."""

    def setUp(self):
        self.b, self.owner, self.staff = make_farm()
        self.client.force_login(self.owner)
        self.cash = Account.objects.get(business=self.b, name="Cash")
        self.power = Category.objects.get(business=self.b, name="Electricity", scope="business")
        dec = Unit.objects.get(business=self.b, symbol="dec")
        self.north = Pond.objects.create(business=self.b, name="North", area=D("100"), area_unit=dec)
        self.south = Pond.objects.create(business=self.b, name="South", area=D("50"), area_unit=dec)
        self.c1 = CultureCycle.objects.create(business=self.b, pond=self.north, start_date=ago(90))
        self.c2 = CultureCycle.objects.create(business=self.b, pond=self.south, start_date=ago(30))

    def spend(self, amount, when, **kw):
        return Transaction.objects.create(business=self.b, date=when, category=self.power, account=self.cash, amount=D(amount), **kw)

    def share(self, cycle):
        return services.summarize(CultureCycle.objects.get(pk=cycle.pk)).shared_cost


class ShareTests(SharedBase):
    def test_split_by_pond_size_between_the_ponds_with_fish_that_day(self):
        self.spend("3000", ago(10))       # both ponds: 2 : 1
        self.spend("900", ago(60))        # only North had fish
        self.assertEqual(self.share(self.c1), D("2900"))
        self.assertEqual(self.share(self.c2), D("1000"))

    def test_counts_in_the_cycle_cost_and_profit(self):
        before = services.summarize(self.c1).cost
        self.spend("3000", ago(10))
        s = services.summarize(CultureCycle.objects.get(pk=self.c1.pk))
        self.assertEqual(s.cost - before, D("2000"))
        self.assertEqual(s.shared_lines, [("Electricity", D("2000.00"))])

    def test_equal_split_and_turned_off(self):
        self.spend("3000", ago(10))
        self.b.share_costs = "equal"
        self.b.save()
        self.assertEqual(self.share(self.c1), D("1500"))
        self.b.share_costs = "none"
        self.b.save()
        self.assertEqual(self.share(self.c1), D("0"))

    def test_a_pond_with_no_size_means_an_equal_split(self):
        Pond.objects.filter(pk=self.south.pk).update(area=None, area_decimal=None)
        self.spend("3000", ago(10))
        self.assertEqual(self.share(self.c1), D("1500"))

    def test_costs_already_on_a_pond_are_not_shared_again(self):
        self.spend("3000", ago(10), cycle=self.c2)
        self.assertEqual(self.share(self.c1), D("0"))
        s = services.summarize(CultureCycle.objects.get(pk=self.c2.pk))
        self.assertEqual((s.other_cost, s.shared_cost), (D("3000"), D("0")))

    def test_a_day_with_no_fish_anywhere_goes_to_no_pond(self):
        self.spend("5000", ago(200))
        farm = shares(self.b)
        self.assertEqual(farm.unshared, D("5000"))
        self.assertEqual(farm.total(self.c1.pk), D("0"))

    def test_household_spending_is_never_shared(self):
        home = Category.objects.filter(business=self.b, scope="household", type="expense").first()
        Transaction.objects.create(business=self.b, date=ago(5), category=home, account=self.cash, amount=D("4000"))
        self.assertEqual(self.share(self.c1), D("0"))

    def test_finished_cycle_keeps_its_share_up_to_its_last_day(self):
        CultureCycle.objects.filter(pk=self.c1.pk).update(status="finished", ended_on=ago(20))
        self.spend("3000", ago(25))        # both had fish
        self.spend("600", ago(5))          # only South
        self.assertEqual(self.share(self.c1), D("2000"))
        self.assertEqual(self.share(self.c2), D("1600"))

    def test_staff_wages_and_repairs(self):
        guard = Worker.objects.create(business=self.b, name="Guard", rate=D("9000"), started_on=ago(300))
        Earning.objects.create(business=self.b, worker=guard, kind="bonus", date=ago(10), amount=D("1500"))   # whole farm
        Earning.objects.create(business=self.b, worker=guard, kind="bonus", date=ago(10), amount=D("700"), cycle=self.c2)  # already South's
        pump = Equipment.objects.create(business=self.b, name="Pump", kind="pump", pond=self.south)
        Service.objects.create(business=self.b, equipment=pump, date=ago(10), cost=D("800"))                     # South's own machine
        self.assertEqual(self.share(self.c1), D("1000"))
        self.assertEqual(self.share(self.c2), D("1300"))      # 500 of the wages + the pump

    def test_shown_on_the_cycle_page_and_the_reports(self):
        self.spend("3000", ago(10))
        r = self.client.get(reverse("business:cycle_detail", args=[self.c1.pk]))
        self.assertContains(r, "data-shared-cost")
        self.assertContains(r, "farm share ৳2,000")
        for kind in ("pond", "cycle"):
            r = self.client.get(reverse("business:report", args=[kind]) + "?period=all")
            self.assertContains(r, "data-share-note")
            self.assertContains(r, "৳3,000 of whole-farm costs")
        csv = self.client.get(reverse("business:report", args=["pond"]) + "?period=all&export=csv").content.decode()
        self.assertIn("Of which farm share", csv)

    def test_setting_on_the_business_details_page(self):
        url = reverse("business:profile")
        self.assertContains(self.client.get(url), 'name="share_costs"')
        self.client.post(url, {"name": self.b.name, "share_costs": "equal"})
        self.b.refresh_from_db()
        self.assertEqual(self.b.share_costs, "equal")
        self.client.post(url, {"name": self.b.name})          # an older page without the choice keeps it
        self.b.refresh_from_db()
        self.assertEqual(self.b.share_costs, "equal")


class GlanceTests(SharedBase):
    def setUp(self):
        super().setUp()
        kg = Unit.objects.get(business=self.b, symbol="kg")
        rui = Species.objects.get(business=self.b, name="Rui")
        Stocking.objects.create(business=self.b, cycle=self.c1, date=ago(90), species=rui, count=1000, weight=D("20"), weight_unit=kg, cost=D("3000"))
        Mortality.objects.create(business=self.b, cycle=self.c1, date=ago(1), species=rui, count=10)
        SampleWeighing.objects.create(business=self.b, cycle=self.c1, date=ago(3), species=rui, fish_count=10, total_weight=D("4"), unit=kg)
        feed = FeedProduct.objects.create(business=self.b, name="Grower", bag_size=D("25"), bag_unit=kg)
        FeedUsage.objects.create(business=self.b, cycle=self.c1, date=TODAY, product=feed, quantity=D("12"), unit=kg)
        FeedUsage.objects.create(business=self.b, cycle=self.c2, date=ago(1), product=feed, quantity=D("5"), unit=kg)
        WaterTest.objects.create(business=self.b, cycle=self.c2, date=TODAY, time_of_day="morning", oxygen=D("2.5"))

    def test_each_pond(self):
        g1, g2 = services.glance(self.b)
        self.assertEqual((g1.pond, g1.alive, g1.avg_g, g1.kg_round), (self.north, 990, D("400"), D("396")))
        self.assertEqual((g1.fed_today, g1.died_recently, g1.tone), (D("12"), 10, "good"))
        self.assertFalse(g2.fed)
        self.assertEqual(g2.fed_yesterday, D("5"))
        self.assertTrue(g2.water_problems)
        self.assertEqual(g2.tone, "critical")

    def test_on_the_home_page_and_the_pond_list(self):
        r = self.client.get(reverse("business:home"))
        self.assertContains(r, "data-home-ponds")
        self.assertContains(r, "Fed 12 kg")
        self.assertContains(r, "Not fed yet")
        self.assertContains(r, f'{reverse("business:cycle_detail", args=[self.c2.pk])}?add=feeding')
        r = self.client.get(reverse("business:ponds"))
        self.assertContains(r, "pond-glance")
        self.assertContains(r, "≈ 400 g")

    def test_no_ponds_with_fish_no_section(self):
        CultureCycle.objects.update(status="finished", ended_on=TODAY)
        self.assertEqual(services.glance(self.b), [])
        self.assertNotContains(self.client.get(reverse("business:home")), "data-home-ponds")
