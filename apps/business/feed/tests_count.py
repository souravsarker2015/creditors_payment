"""Counting the feed store: shortages, feed already in store, and undoing a count."""
from datetime import date, timedelta
from decimal import Decimal as D

from django.test import TestCase
from django.urls import reverse

from apps.business.core.models import Membership, Role, Unit
from apps.business.core.testing import make_farm
from apps.business.finance.services import statement
from apps.business.parties.models import Party
from apps.business.ponds.models import CultureCycle, Pond
from apps.business.reports.worth import farm_worth

from . import services
from .models import FeedCount, FeedProduct, FeedPurchase, FeedPurchaseLine, FeedUsage

TODAY = date.today()


class StoreCountTests(TestCase):
    def setUp(self):
        self.b, self.owner, self.staff = make_farm()
        self.client.force_login(self.owner)
        self.kg = Unit.objects.get(business=self.b, symbol="kg")
        self.grower = FeedProduct.objects.create(business=self.b, name="Grower", bag_size=D("25"), bag_unit=self.kg, default_price=D("1500"))
        buy = FeedPurchase.objects.create(business=self.b, date=TODAY - timedelta(days=10), supplier=Party.objects.create(business=self.b, name="Dealer", is_supplier=True))
        FeedPurchaseLine.objects.create(business=self.b, purchase=buy, product=self.grower, quantity=D("10"), rate=D("1500"))   # 10 bags
        buy.recalc()
        self.cycle = CultureCycle.objects.create(business=self.b, pond=Pond.objects.create(business=self.b, name="East"), start_date=TODAY - timedelta(days=30))
        FeedUsage.objects.create(business=self.b, cycle=self.cycle, date=TODAY - timedelta(days=2), product=self.grower, quantity=D("2"))   # 2 bags eaten

    def row(self, product=None):
        product = product or self.grower
        return next(r for r in services.stock(self.b) if r.product == product)

    def test_bags_short_put_the_stock_right_and_are_a_farm_cost(self):
        self.assertEqual(self.row().left_bags, D("8.0"))
        r = self.client.post(reverse("business:feed_count"), {"date": TODAY.isoformat(), f"n{self.grower.pk}": "6.5"}, follow=True)
        self.assertContains(r, "1.5 bags short")
        c = FeedCount.objects.get()
        self.assertEqual(c.book_kg, D("200"))
        self.assertEqual(c.difference_kg, D("-37.5"))
        self.assertEqual(c.value, D("-2250"))            # 1.5 bags at ৳1,500
        self.assertFalse(c.opening)
        self.assertEqual(c.created_by, self.owner)
        self.assertEqual(self.row().left_bags, D("6.5"))
        s = statement(self.b, TODAY.replace(day=1), TODAY)
        self.assertEqual({l.key: l.amount for l in s.expense}["feed_lost"], D("2250"))
        owns = {l.key: l.amount for l in farm_worth(self.b).owns}
        self.assertEqual(owns["feed"], D("9750"))         # 6.5 bags at the price paid

    def test_feed_already_in_store_counts_as_bought_at_its_price(self):
        starter = FeedProduct.objects.create(business=self.b, name="Starter", bag_size=D("25"), bag_unit=self.kg, default_price=D("1700"))
        page = self.client.get(reverse("business:feed_count"))
        self.assertContains(page, f'name="p{starter.pk}"')             # asks its price: nothing recorded yet
        self.assertNotContains(page, f'name="p{self.grower.pk}"')
        self.client.post(reverse("business:feed_count"), {"date": TODAY.isoformat(), f"n{starter.pk}": "4", f"p{starter.pk}": "1600"})
        c = FeedCount.objects.get(product=starter)
        self.assertTrue(c.opening)
        self.assertEqual(c.difference_kg, D("100"))
        self.assertEqual(self.row(starter).left_bags, D("4.0"))
        self.assertEqual(services.cost_per_kg(self.b)[starter.pk], D("64"))   # ৳1,600 a 25 kg bag
        s = statement(self.b, TODAY.replace(day=1), TODAY)
        self.assertNotIn("feed_lost", [l.key for l in s.expense])
        self.assertNotIn("feed_found", [l.key for l in s.income])

    def test_more_than_the_records_is_feed_found(self):
        services.save_counts(self.b, TODAY, [(self.grower, D("225"), None)])   # 9 bags, records say 8
        s = statement(self.b, TODAY.replace(day=1), TODAY)
        self.assertEqual({l.key: l.amount for l in s.income}["feed_found"], D("1500"))

    def test_a_count_on_an_earlier_day_compares_with_the_records_of_that_day(self):
        c = services.save_counts(self.b, TODAY - timedelta(days=5), [(self.grower, D("250"), None)])[0]
        self.assertEqual(c.book_kg, D("250"))              # before the 2 bags were eaten
        self.assertEqual(c.difference_kg, 0)
        self.assertEqual(self.row().left_bags, D("8.0"))

    def test_typing_what_the_page_shows_is_a_match(self):
        FeedUsage.objects.create(business=self.b, cycle=self.cycle, date=TODAY, product=self.grower, quantity=D("0.7"), unit=self.kg)
        self.assertEqual(self.row().left_bags, D("8.0"))   # 199.3 kg is 7.97 bags
        c = services.save_counts(self.b, TODAY, [(self.grower, D("200"), None)])[0]
        self.assertEqual(c.difference_kg, 0)
        self.assertEqual(c.counted_kg, D("199.3"))

    def test_removing_a_count_undoes_it(self):
        c = services.save_counts(self.b, TODAY, [(self.grower, D("100"), None)])[0]
        self.assertEqual(self.row().left_bags, D("4.0"))
        r = self.client.post(reverse("business:feed_count_delete", args=[c.pk]), follow=True)
        self.assertContains(r, "Count removed")
        self.assertEqual(self.row().left_bags, D("8.0"))

    def test_needs_at_least_one_feed_and_not_a_future_date(self):
        r = self.client.post(reverse("business:feed_count"), {"date": TODAY.isoformat()})
        self.assertContains(r, "at least one feed")
        r = self.client.post(reverse("business:feed_count"), {"date": (TODAY + timedelta(days=1)).isoformat(), f"n{self.grower.pk}": "3"})
        self.assertContains(r, "in the future")
        self.assertFalse(FeedCount.objects.exists())

    def test_staff_count_without_seeing_money_and_viewers_cannot_count(self):
        self.client.force_login(self.staff)                 # data entry
        r = self.client.post(reverse("business:feed_count"), {"date": TODAY.isoformat(), f"n{self.grower.pk}": "6"}, follow=True)
        self.assertContains(r, "2 bags short")
        self.assertNotContains(r, "৳3,000")
        self.assertEqual(self.client.post(reverse("business:feed_count_delete", args=[FeedCount.objects.get().pk])).status_code, 403)
        Membership.objects.filter(user=self.staff).update(role=Role.VIEWER)
        r = self.client.post(reverse("business:feed_count"), {"date": TODAY.isoformat(), f"n{self.grower.pk}": "1"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(FeedCount.objects.count(), 1)

    def test_stock_page_says_when_the_store_was_last_counted(self):
        self.assertContains(self.client.get(reverse("business:feed_stock")), "hasn't been counted yet")
        services.save_counts(self.b, TODAY, [(self.grower, D("200"), None)])
        r = self.client.get(reverse("business:feed_stock"))
        self.assertContains(r, "Store last counted")
        self.assertContains(r, reverse("business:feed_count"))

    def test_other_farms_counts_are_out_of_reach(self):
        other, other_owner, _ = make_farm("other")
        self.client.force_login(other_owner)
        c = services.save_counts(self.b, TODAY, [(self.grower, D("200"), None)])[0]
        self.assertEqual(self.client.post(reverse("business:feed_count_delete", args=[c.pk])).status_code, 404)
        r = self.client.post(reverse("business:feed_count"), {"date": TODAY.isoformat(), f"n{self.grower.pk}": "1"})
        self.assertContains(r, "No feed products yet")   # not one of their feeds
        self.assertEqual(FeedCount.objects.count(), 1)
