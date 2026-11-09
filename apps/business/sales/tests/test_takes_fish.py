"""A sale straight from a pond takes its fish out of the pond's count, so
fish left, weight, FCR and forecasts stay true without a separate harvest."""
from datetime import date, timedelta
from decimal import Decimal as D

from django.test import TestCase
from django.urls import reverse

from apps.business.core.models import Unit
from apps.business.core.testing import make_farm
from apps.business.feed.models import FeedProduct, FeedUsage
from apps.business.finance.models import Account
from apps.business.parties.models import Party
from apps.business.ponds.models import CultureCycle, Harvest, Pond, SampleWeighing, Stocking
from apps.business.ponds.services import count_fish, summarize
from apps.business.species.models import Species

from ..models import FishSale, FishSaleLine


def ago(n):
    return date.today() - timedelta(days=n)


class TakesFishTests(TestCase):
    def setUp(self):
        self.b, self.owner, _ = make_farm()
        self.client.force_login(self.owner)
        self.kg = Unit.objects.get(business=self.b, symbol="kg")
        self.pcs = Unit.objects.get(business=self.b, unit_type="count", is_base=True)
        self.rui = Species.objects.get(business=self.b, name="Rui")
        self.cash = Account.objects.get(business=self.b, name="Cash")
        self.buyer = Party.objects.create(business=self.b, name="Hasan", is_buyer=True)
        self.pond = Pond.objects.create(business=self.b, name="East")
        self.cycle = CultureCycle.objects.create(business=self.b, pond=self.pond, start_date=ago(100))
        Stocking.objects.create(business=self.b, cycle=self.cycle, date=ago(100), species=self.rui, count=1000, weight=D("50"), weight_unit=self.kg)
        SampleWeighing.objects.create(business=self.b, cycle=self.cycle, date=ago(5), species=self.rui, fish_count=10, total_weight=D("5"), unit=self.kg)
        feed = FeedProduct.objects.create(business=self.b, name="Grower", bag_size=25, bag_unit=self.kg)
        FeedUsage.objects.create(business=self.b, cycle=self.cycle, date=ago(10), product=feed, quantity=D("600"), unit=self.kg)

    def post_sale(self, qty="100", take=True, **extra):
        data = {"date": ago(0).isoformat(), "buyer": self.buyer.pk, "cycle": self.cycle.pk, "received_now": str(D(qty) * 200),
                "account": self.cash.pk,
                "lines-TOTAL_FORMS": "1", "lines-INITIAL_FORMS": "0", "lines-MIN_NUM_FORMS": "0", "lines-MAX_NUM_FORMS": "1000",
                "lines-0-species": self.rui.pk, "lines-0-quantity": qty, "lines-0-unit": self.kg.pk, "lines-0-rate": "200",
                "deds-TOTAL_FORMS": "0", "deds-INITIAL_FORMS": "0", "deds-MIN_NUM_FORMS": "0", "deds-MAX_NUM_FORMS": "1000", **extra}
        if take:
            data["takes_fish"] = "on"
        r = self.client.post(reverse("business:sale_add"), data)
        self.assertEqual(r.status_code, 302, getattr(r, "context", None) and r.context["form"].errors)
        return FishSale.objects.latest("id")

    def alive(self):
        return count_fish(self.cycle)[self.rui.pk].alive

    def test_a_sale_from_the_pond_takes_its_fish_out(self):
        sale = self.post_sale("100")   # 100 kg at 500 g each = 200 fish
        self.assertTrue(sale.takes_fish)
        self.assertEqual(self.alive(), 800)
        s = summarize(self.cycle)
        self.assertEqual(s.harvest_kg, D("100"))
        # FCR so far: 600 kg feed ÷ (100 kg sold + 400 kg in the pond − 50 kg fingerlings)
        self.assertEqual(s.fcr_so_far, D("1.33"))

    def test_left_unticked_the_pond_keeps_its_fish(self):
        sale = self.post_sale("100", take=False)
        self.assertFalse(sale.takes_fish)
        self.assertEqual(self.alive(), 1000)

    def test_deleting_or_editing_the_sale_puts_the_count_right(self):
        sale = self.post_sale("100")
        line = sale.lines.get()
        line.quantity = D("50")
        line.save()
        self.assertEqual(self.alive(), 900)
        sale.soft_delete()
        self.assertEqual(self.alive(), 1000)

    def test_a_sale_in_pieces_counts_the_pieces(self):
        sale = FishSale.objects.create(business=self.b, date=ago(0), cycle=self.cycle, takes_fish=True)
        FishSaleLine.objects.create(business=self.b, sale=sale, species=self.rui, quantity=D("30"), unit=self.pcs, rate=D("100"))
        self.assertEqual(self.alive(), 970)

    def test_selling_a_recorded_harvest_never_counts_twice(self):
        h = Harvest.objects.create(business=self.b, cycle=self.cycle, date=ago(0), species=self.rui, quantity=D("100"), unit=self.kg)
        sale = self.post_sale("100", harvest=h.pk)   # the box was ticked, but a harvest is attached
        self.assertFalse(sale.takes_fish)
        self.assertEqual(self.alive(), 800)

    def test_the_box_starts_ticked_for_a_pond(self):
        r = self.client.get(reverse("business:sale_add") + f"?cycle={self.cycle.pk}")
        self.assertTrue(r.context["form"].initial["takes_fish"])
        self.assertContains(r, "Take these fish out of the pond")

    def test_an_unsold_harvest_leaves_the_box_unticked_and_points_to_it(self):
        h = Harvest.objects.create(business=self.b, cycle=self.cycle, date=ago(1), species=self.rui, quantity=D("80"), unit=self.kg)
        r = self.client.get(reverse("business:sale_add") + f"?cycle={self.cycle.pk}")
        self.assertFalse(r.context["form"].initial["takes_fish"])
        self.assertIn(f"?harvest={h.pk}", r.context["unsold_harvests"][str(self.cycle.pk)]["url"])
        # Once it's sold, the hint goes away.
        sale = FishSale.objects.create(business=self.b, date=ago(0), cycle=self.cycle, harvest=h)
        self.assertNotIn(str(self.cycle.pk), self.client.get(reverse("business:sale_add")).context["unsold_harvests"])
        sale.soft_delete()

    def test_old_sales_are_flagged_and_fixed_in_one_tap(self):
        old = FishSale.objects.create(business=self.b, date=ago(3), cycle=self.cycle)   # before this feature: no flag
        FishSaleLine.objects.create(business=self.b, sale=old, species=self.rui, quantity=D("100"), unit=self.kg, rate=D("200"))
        r = self.client.get(reverse("business:cycle_detail", args=[self.cycle.pk]))
        self.assertEqual(r.context["untaken_kg"], D("100"))
        self.assertContains(r, "Take them out")
        self.client.post(reverse("business:cycle_take_out_sold", args=[self.cycle.pk]))
        old.refresh_from_db()
        self.assertTrue(old.takes_fish)
        self.assertEqual(self.alive(), 800)
        self.assertIsNone(self.client.get(reverse("business:cycle_detail", args=[self.cycle.pk])).context["untaken_kg"])

    def test_one_tap_fix_refuses_when_harvests_exist(self):
        Harvest.objects.create(business=self.b, cycle=self.cycle, date=ago(4), species=self.rui, quantity=D("10"), unit=self.kg)
        old = FishSale.objects.create(business=self.b, date=ago(3), cycle=self.cycle)
        FishSaleLine.objects.create(business=self.b, sale=old, species=self.rui, quantity=D("100"), unit=self.kg, rate=D("200"))
        self.client.post(reverse("business:cycle_take_out_sold", args=[self.cycle.pk]))
        old.refresh_from_db()
        self.assertFalse(old.takes_fish)
