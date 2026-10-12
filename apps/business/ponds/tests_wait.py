"""FCR while the fish grow, and "sell now or wait?"."""
from datetime import date, timedelta
from decimal import Decimal as D

from django.test import TestCase
from django.urls import reverse

from apps.business.core.models import Unit
from apps.business.core.testing import make_farm
from apps.business.feed.models import FeedProduct, FeedPurchase, FeedPurchaseLine, FeedUsage
from apps.business.parties.models import Party
from apps.business.species.models import Species

from . import forecast, services
from .models import CultureCycle, Mortality, Pond, SampleWeighing, Stocking

TODAY = date.today()


def ago(n):
    return TODAY - timedelta(days=n)


class WaitBase(TestCase):
    def setUp(self):
        self.b, self.owner, self.staff = make_farm()
        self.client.force_login(self.owner)
        self.kg = Unit.objects.get(business=self.b, symbol="kg")
        self.rui = Species.objects.get(business=self.b, name="Rui")        # sells at 1,000 g
        self.cycle = CultureCycle.objects.create(business=self.b, pond=Pond.objects.create(business=self.b, name="East"), start_date=ago(60))
        Stocking.objects.create(business=self.b, cycle=self.cycle, date=ago(60), species=self.rui, count=1000,
                                weight=D("20"), weight_unit=self.kg, cost=D("3000"))          # 20 g each
        feed = FeedProduct.objects.create(business=self.b, name="Grower", bag_size=D("25"), bag_unit=self.kg)
        buy = FeedPurchase.objects.create(business=self.b, date=ago(60), supplier=Party.objects.create(business=self.b, name="Dealer", is_supplier=True))
        FeedPurchaseLine.objects.create(business=self.b, purchase=buy, product=feed, quantity=D("20"), rate=D("1250"))  # ৳50/kg
        buy.recalc()
        FeedUsage.objects.create(business=self.b, cycle=self.cycle, date=ago(1), product=feed, quantity=D("500"), unit=self.kg)
        Mortality.objects.create(business=self.b, cycle=self.cycle, date=ago(20), species=self.rui, count=100)

    def weigh(self, days, grams):
        SampleWeighing.objects.create(business=self.b, cycle=self.cycle, date=ago(days), species=self.rui,
                                      fish_count=10, total_weight=D(grams) * 10 / 1000, unit=self.kg)

    def summary(self):
        return services.summarize(CultureCycle.objects.get(pk=self.cycle.pk))


class FcrSoFarTests(WaitBase):
    def test_counts_the_fish_still_in_the_pond(self):
        s = self.summary()
        self.assertIsNone(s.fcr_so_far)                    # no weighing: nothing to go on
        self.weigh(0, "400")
        s = self.summary()
        self.assertIsNone(s.fcr)                           # nothing harvested yet
        self.assertEqual(s.fcr_so_far, D("1.47"))          # 500 kg ÷ (900 × 400 g − 20 kg)
        self.assertEqual(s.fcr_now, D("1.47"))

    def test_shown_on_the_cycle_the_report_and_the_dashboard(self):
        self.weigh(0, "400")
        self.assertContains(self.client.get(reverse("business:cycle_detail", args=[self.cycle.pk])), "FCR so far ≈ 1.47")
        r = self.client.get(reverse("business:report", args=["cycle"]) + "?period=all")
        self.assertContains(r, "≈ 1.47")
        self.assertContains(self.client.get(reverse("business:dashboard")), "FCR 1.47")


class WaitPlanTests(WaitBase):
    def plan(self):
        cycle = CultureCycle.objects.get(pk=self.cycle.pk)
        return services.wait_plan(services.summarize(cycle), forecast.for_cycle(cycle))

    def test_more_fish_against_more_feed_and_losses(self):
        self.weigh(30, "100")
        self.weigh(0, "400")                               # 10 g a day: 1,000 g in 60 days
        w = self.plan()
        self.assertEqual(w.ready_on, TODAY + timedelta(days=60))
        self.assertEqual(w.days, 60)
        self.assertEqual(w.kg_now, D("360"))
        self.assertEqual(w.fish_lost, 90)                  # 100 died in 60 days: 10% more in the next 60
        self.assertEqual(w.kg_then, D("810"))              # 810 fish × 1,000 g
        self.assertEqual(w.more_kg, D("450"))
        self.assertEqual(w.fcr, D("1.47"))
        self.assertFalse(w.fcr_guessed)
        self.assertEqual(w.feed_cost, D("33075"))          # 450 kg × 1.47 × ৳50
        self.assertEqual(w.other_cost, 0)

    def test_running_costs_carry_on_while_waiting(self):
        from apps.business.finance.models import Category, Transaction

        self.weigh(30, "100")
        self.weigh(0, "400")
        cat = Category.objects.filter(business=self.b, type="expense", scope="business").first()
        Transaction.objects.create(business=self.b, date=ago(5), category=cat, amount=D("6000"), cycle=self.cycle)
        self.assertEqual(self.plan().other_cost, D("6000"))   # ৳100 a day so far × 60 days

    def test_nothing_to_wait_for(self):
        self.assertIsNone(self.plan())                     # never weighed
        self.weigh(30, "1000")
        self.weigh(0, "1100")                              # already past selling size
        self.assertIsNone(self.plan())

    def test_the_cycle_page_compares_both(self):
        self.weigh(30, "100")
        self.weigh(0, "400")
        r = self.client.get(reverse("business:cycle_detail", args=[self.cycle.pk]))
        self.assertContains(r, "Sell now or wait?")
        self.assertContains(r, "Wait until")
        self.assertContains(r, "≈ 810 kg (+450)")
        self.assertContains(r, "this pond's FCR so far (1.47)")
        self.assertContains(r, "About 90 fish lost on the way")
