"""Recording feeding for every pond at once when ponds eat different feeds."""
from datetime import date, timedelta
from decimal import Decimal as D

from django.test import TestCase
from django.urls import reverse

from apps.business.core.models import Unit
from apps.business.core.testing import make_farm
from apps.business.ponds.models import CultureCycle, Pond

from .models import FeedProduct, FeedUsage

TODAY = date.today()


class PerPondFeedTests(TestCase):
    def setUp(self):
        self.b, self.owner, _staff = make_farm()
        self.client.force_login(self.owner)
        self.kg = Unit.objects.get(business=self.b, symbol="kg")
        self.grower = FeedProduct.objects.create(business=self.b, name="Grower", bag_size=25, bag_unit=self.kg)
        self.starter = FeedProduct.objects.create(business=self.b, name="Starter", bag_size=25, bag_unit=self.kg)
        self.big = [CultureCycle.objects.create(business=self.b, pond=Pond.objects.create(business=self.b, name=n), start_date=TODAY - timedelta(days=90))
                    for n in ("North", "South")]
        self.nursery = CultureCycle.objects.create(business=self.b, pond=Pond.objects.create(business=self.b, name="Nursery"), start_date=TODAY - timedelta(days=20))
        self.url = reverse("business:feed_usage_bulk")

    def fed(self, cycle, product, kg, days=1):
        FeedUsage.objects.create(business=self.b, cycle=cycle, date=TODAY - timedelta(days=days), product=product, quantity=D(kg), unit=self.kg)

    def test_each_pond_keeps_its_own_feed_and_amount(self):
        self.fed(self.big[0], self.grower, "40", 2)
        self.fed(self.big[1], self.grower, "30", 2)
        self.fed(self.nursery, self.starter, "5")          # the latest feeding of all, but the odd one out
        form = self.client.get(self.url).context["form"]
        self.assertEqual(form.initial["product"], self.grower.pk)          # what most ponds eat
        self.assertNotIn(f"f{self.big[0].pk}", form.initial)               # "Same as above"
        self.assertEqual(form.initial[f"f{self.nursery.pk}"], self.starter.pk)
        self.assertEqual((form.initial[f"c{self.big[0].pk}"], form.initial[f"c{self.nursery.pk}"]), ("40", "5"))

    def test_saves_each_pond_with_its_feed(self):
        r = self.client.post(self.url, {"date": TODAY.isoformat(), "product": self.grower.pk, "unit": self.kg.pk,
                                        f"c{self.big[0].pk}": "40", f"c{self.big[1].pk}": "30",
                                        f"c{self.nursery.pk}": "5", f"f{self.nursery.pk}": self.starter.pk})
        self.assertRedirects(r, reverse("business:feed_usage"))
        got = {u.cycle_id: (u.product_id, u.kg) for u in FeedUsage.objects.filter(date=TODAY)}
        self.assertEqual(got[self.big[0].pk], (self.grower.pk, D("40")))
        self.assertEqual(got[self.nursery.pk], (self.starter.pk, D("5")))

    def test_no_feed_at_the_top_needs_one_per_pond(self):
        r = self.client.post(self.url, {"date": TODAY.isoformat(), "unit": self.kg.pk, f"c{self.big[0].pk}": "40",
                                        f"c{self.nursery.pk}": "5", f"f{self.nursery.pk}": self.starter.pk})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Choose the feed this pond ate.")
        self.assertFalse(FeedUsage.objects.exists())
        r = self.client.post(self.url, {"date": TODAY.isoformat(), "unit": self.kg.pk, f"c{self.nursery.pk}": "5", f"f{self.nursery.pk}": self.starter.pk})
        self.assertEqual(FeedUsage.objects.get().product, self.starter)
