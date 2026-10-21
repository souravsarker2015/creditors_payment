"""This season against the last one, on the same day of each."""
from datetime import date, timedelta
from decimal import Decimal as D

from django.test import TestCase
from django.urls import reverse

from apps.business.core.models import Unit
from apps.business.core.testing import make_farm
from apps.business.feed.models import FeedProduct, FeedUsage
from apps.business.species.models import Species

from . import compare
from .models import CultureCycle, Harvest, Mortality, Pond, SampleWeighing, Stocking

TODAY = date.today()


def ago(n):
    return TODAY - timedelta(days=n)


class CompareTests(TestCase):
    """Last season (day 200 → 100 ago) and this one (started 60 days ago), both 1,000 Rui at 20 g."""

    def setUp(self):
        self.b, self.owner, _s = make_farm()
        self.client.force_login(self.owner)
        self.kg = Unit.objects.get(business=self.b, symbol="kg")
        self.rui = Species.objects.get(business=self.b, name="Rui")
        self.feed = FeedProduct.objects.create(business=self.b, name="Grower", bag_size=25, bag_unit=self.kg)
        self.pond = Pond.objects.create(business=self.b, name="East")
        self.last = self.cycle(self.pond, 200, ended=100)
        self.now = self.cycle(self.pond, 60)
        # day 60 of each: last season 300 g, 100 dead, 400 kg fed; this season 360 g, 50 dead, 450 kg fed
        self.weigh(self.last, 140, "300")
        self.weigh(self.now, 0, "360")
        Mortality.objects.create(business=self.b, cycle=self.last, date=ago(170), species=self.rui, count=100)
        Mortality.objects.create(business=self.b, cycle=self.now, date=ago(30), species=self.rui, count=50)
        FeedUsage.objects.create(business=self.b, cycle=self.last, date=ago(150), product=self.feed, quantity=D("400"), unit=self.kg)
        FeedUsage.objects.create(business=self.b, cycle=self.last, date=ago(120), product=self.feed, quantity=D("900"), unit=self.kg)   # after day 60: not counted
        FeedUsage.objects.create(business=self.b, cycle=self.now, date=ago(10), product=self.feed, quantity=D("450"), unit=self.kg)
        Harvest.objects.create(business=self.b, cycle=self.last, date=ago(100), species=self.rui, quantity=D("700"), unit=self.kg, is_final=True)

    def cycle(self, pond, started, ended=None):
        c = CultureCycle.objects.create(business=self.b, pond=pond, start_date=ago(started), status="finished" if ended else "running",
                                        ended_on=ago(ended) if ended else None)
        Stocking.objects.create(business=self.b, cycle=c, date=ago(started), species=self.rui, count=1000, weight=D("20"), weight_unit=self.kg)
        return c

    def weigh(self, cycle, days_ago, grams):
        SampleWeighing.objects.create(business=self.b, cycle=cycle, date=ago(days_ago), species=self.rui, fish_count=10, total_weight=D(grams) / 100, unit=self.kg)

    def test_snapshot_on_a_day(self):
        s = compare.snapshot(self.last, 60)
        self.assertEqual((s.put_in, s.died, s.alive, s.size_g, s.survival, s.feed_kg), (1000, 100, 900, D("300"), 90, D("400")))
        self.assertEqual(s.fcr, D("1.60"))                  # 400 ÷ (900 × 0.3 − 20)
        self.assertEqual(compare.snapshot(self.last, 10).size_g, None)   # nothing weighed yet by day 10

    def test_this_season_against_the_last(self):
        c = compare.compare(CultureCycle.objects.get(pk=self.now.pk))
        self.assertTrue(c.same_pond)
        self.assertEqual((c.other, c.day, c.other_day), (self.last, 60, 60))
        lines = {l.key: l for l in c.lines}
        self.assertEqual((lines["size"].now, lines["size"].then, lines["size"].tone), ("360 g", "300 g", "good"))
        self.assertEqual((lines["survival"].now, lines["survival"].then, lines["survival"].tone), ("95%", "90%", "good"))
        self.assertEqual(lines["fcr"].tone, "good")         # 450 ÷ (950 × 0.36 − 20) = 1.40, below 1.60
        self.assertEqual(lines["feed"].now, "450 kg")

    def test_falling_behind_shows(self):
        self.weigh(self.now, 0, "240")                       # a later weighing today: 240 g
        SampleWeighing.objects.filter(cycle=self.now, total_weight=D("3.6")).delete()
        lines = {l.key: l for l in compare.compare(CultureCycle.objects.get(pk=self.now.pk)).lines}
        self.assertEqual(lines["size"].tone, "critical")     # 20% behind

    def test_other_pond_with_the_same_fish_and_none_at_all(self):
        west = Pond.objects.create(business=self.b, name="West")
        new = self.cycle(west, 30)
        c = compare.compare(new)
        self.assertFalse(c.same_pond)
        self.assertEqual(c.other, self.last)
        CultureCycle.all_objects.filter(pk=self.last.pk).update(is_deleted=True)      # deleted: nothing left to compare with
        self.assertIsNone(compare.compare(new))

    def test_shorter_last_season_compares_with_its_last_day(self):
        CultureCycle.objects.filter(pk=self.last.pk).update(ended_on=ago(160))      # it ran 40 days
        c = compare.compare(CultureCycle.objects.get(pk=self.now.pk))
        self.assertEqual((c.day, c.other_day, c.other_ended_sooner), (60, 40, True))

    def test_on_the_cycle_page(self):
        r = self.client.get(reverse("business:cycle_detail", args=[self.now.pk]))
        self.assertContains(r, "data-season-compare")
        self.assertContains(r, 'data-compare-line="size"')
        self.assertContains(r, "700 kg harvested")
