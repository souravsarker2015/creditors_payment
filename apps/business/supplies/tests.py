"""Pond supplies store: stock, the price a pond is charged, money and baki."""
from datetime import date, timedelta
from decimal import Decimal as D

from django.test import TestCase
from django.urls import reverse

from apps.business.core.models import Unit
from apps.business.core.testing import make_farm
from apps.business.credit import services as baki
from apps.business.finance import services as money
from apps.business.finance.models import Account
from apps.business.parties.models import Party
from apps.business.ponds.models import CultureCycle, Pond, Treatment

from . import services
from .models import SupplyItem, SupplyPurchase

TODAY = date.today()


class StoreTests(TestCase):
    def setUp(self):
        self.b, self.owner, self.staff = make_farm()
        self.client.force_login(self.owner)
        self.cash = Account.objects.get(business=self.b, name="Cash")
        self.kg = Unit.objects.get(business=self.b, symbol="kg")
        self.mon = Unit.objects.get(business=self.b, symbol="mon")           # 40 kg
        self.lime = SupplyItem.objects.create(business=self.b, name="Dolomite lime", kind="lime", unit=self.kg, low_stock=D("20"),
                                              dose_per_decimal=D("1"))
        self.pond = Pond.objects.create(business=self.b, name="East")
        self.cycle = CultureCycle.objects.create(business=self.b, pond=self.pond, name="Carp", start_date=TODAY - timedelta(days=30))

    def buy(self, qty, unit, cost, **kw):
        kw.setdefault("paid_now", cost)
        kw.setdefault("account", self.cash)
        return SupplyPurchase.objects.create(business=self.b, item=self.lime, date=TODAY - timedelta(days=5), quantity=D(qty), unit=unit,
                                             cost=D(cost), **kw)

    def use(self, qty, **extra):
        data = {"date": TODAY.isoformat(), "kind": "other", "item": self.lime.pk, "product": "", "quantity": qty, "unit": self.kg.pk}
        data.update(extra)
        return self.client.post(reverse("business:entry_add", args=[self.cycle.pk, "treatment"]),
                                {f"treatment-{k}": v for k, v in data.items()})

    def test_stock_in_mixed_units(self):
        self.buy("2", self.mon, "1200")                     # 80 kg at ৳15
        Treatment.objects.create(business=self.b, cycle=self.cycle, date=TODAY, item=self.lime, product="Lime", quantity=D("30"), unit=self.kg)
        st = services.stock_for(self.lime)
        self.assertEqual((st.left, st.unit_price, st.value), (D("50"), D("15"), D("750")))

    def test_using_from_the_store_prices_the_pond_and_moves_no_money(self):
        self.buy("100", self.kg, "1500")
        before = money.balances(self.b)[self.cash.pk]
        r = self.use("40", cost="999", account=self.cash.pk)
        self.assertEqual(r.status_code, 302, r.context and r.context["form"].errors)
        t = Treatment.objects.get(cycle=self.cycle)
        self.assertEqual((t.product, t.kind, t.cost, t.account_id), ("Dolomite lime", "lime", D("600"), None))
        self.assertEqual(money.balances(self.b)[self.cash.pk], before)
        self.assertEqual(services.stock_for(self.lime).left, D("60"))

    def test_store_unit_has_to_match(self):
        litre = Unit.objects.filter(business=self.b, unit_type="volume").first()
        r = self.use("2", unit=litre.pk)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Treatment.objects.exists())

    def test_purchase_is_money_out_and_credit_goes_to_baki(self):
        shop = Party.objects.create(business=self.b, name="Krishi Ghor", is_supplier=True)
        before = money.balances(self.b)[self.cash.pk]
        r = self.client.post(reverse("business:supply_buy", args=[self.lime.pk]),
                             {"date": TODAY.isoformat(), "quantity": "50", "unit": self.kg.pk, "supplier": shop.pk,
                              "cost": "800", "paid_now": "500", "account": self.cash.pk})
        self.assertRedirects(r, reverse("business:supply_detail", args=[self.lime.pk]))
        self.assertEqual(money.balances(self.b)[self.cash.pk], before - D("500"))
        self.assertEqual(baki.ledger(shop).balance, D("-300"))           # we owe the shop ৳300

    def test_without_a_shop_it_is_paid_in_full(self):
        r = self.client.post(reverse("business:supply_buy", args=[self.lime.pk]),
                             {"date": TODAY.isoformat(), "quantity": "10", "unit": self.kg.pk, "cost": "150", "account": self.cash.pk})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(SupplyPurchase.objects.get().paid_now, D("150"))

    def test_running_low_on_the_farm_list_and_store_page(self):
        self.buy("25", self.kg, "375")
        Treatment.objects.create(business=self.b, cycle=self.cycle, date=TODAY, item=self.lime, product="Lime", quantity=D("10"), unit=self.kg)
        self.assertContains(self.client.get(reverse("business:home")), "Dolomite lime is running low")
        r = self.client.get(reverse("business:supplies"))
        self.assertContains(r, "Running low")
        r = self.client.get(reverse("business:supply_detail", args=[self.lime.pk]))
        self.assertContains(r, "into East")

    def test_data_entry_uses_but_cannot_buy(self):
        self.buy("100", self.kg, "1500")
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("business:supply_buy", args=[self.lime.pk])).status_code, 403)
        r = self.client.get(reverse("business:supply_detail", args=[self.lime.pk]))
        self.assertNotContains(r, "1,500")
        self.assertEqual(self.use("10").status_code, 302)

    def test_care_form_without_a_store_still_needs_a_product(self):
        data = {"date": TODAY.isoformat(), "kind": "salt", "product": "", "quantity": "5", "unit": self.kg.pk}
        r = self.client.post(reverse("business:entry_add", args=[self.cycle.pk, "treatment"]), {f"treatment-{k}": v for k, v in data.items()})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Treatment.objects.exists())
