"""Phase 3: cycles, pond entries, feed stock and fish sales."""
from datetime import date, timedelta
from decimal import Decimal as D

from django.test import TestCase
from django.urls import reverse

from apps.business.core.models import Unit
from apps.business.core.testing import make_farm
from apps.business.feed.models import FeedProduct, FeedPurchase, FeedUsage
from apps.business.feed.services import stock
from apps.business.markets.models import DeductionType, Market, MarketDeduction
from apps.business.parties.models import Party
from apps.business.sales.models import FishSale
from apps.business.species.models import Species

from .models import CultureCycle, Harvest, Pond, PondStatus
from .services import summarize


def ago(n):
    return (date.today() - timedelta(days=n)).isoformat()


def rows(prefix, items):
    data = {f"{prefix}-TOTAL_FORMS": str(len(items)), f"{prefix}-INITIAL_FORMS": "0", f"{prefix}-MIN_NUM_FORMS": "0", f"{prefix}-MAX_NUM_FORMS": "1000"}
    for i, item in enumerate(items):
        data.update({f"{prefix}-{i}-{k}": v for k, v in item.items()})
    return data


class Phase3Base(TestCase):
    def setUp(self):
        self.b, self.owner, self.staff = make_farm()
        self.client.force_login(self.owner)
        self.u = {s: Unit.objects.get(business=self.b, symbol=s) for s in ("kg", "mon", "g", "pcs")}
        self.rui = Species.objects.get(business=self.b, name="Rui")
        self.katla = Species.objects.get(business=self.b, name="Katla")
        self.pond = Pond.objects.create(business=self.b, name="East", status=PondStatus.EMPTY)
        self.supplier = Party.objects.create(business=self.b, name="Mollah Feed", is_supplier=True)
        self.feed = FeedProduct.objects.create(business=self.b, name="Grower", bag_size=25, bag_unit=self.u["kg"], default_price=1450)

    def start(self, days_ago=60):
        self.client.post(reverse("business:cycle_start", args=[self.pond.pk]), {"cycle-start_date": ago(days_ago), "cycle-name": "Carp"})
        return CultureCycle.objects.get(pond=self.pond)

    def add(self, cycle, kind, **data):
        return self.client.post(reverse("business:entry_add", args=[cycle.pk, kind]), {f"{kind}-{k}": v for k, v in data.items()})

    def buy(self, lines, **extra):
        data = {"supplier": self.supplier.pk, "date": ago(50), **extra, **rows("rows", lines)}
        return self.client.post(reverse("business:feed_purchases_add"), data)


class CycleTests(Phase3Base):
    def test_starting_a_cycle_marks_the_pond_in_use_and_only_one_can_run(self):
        cycle = self.start()
        self.pond.refresh_from_db()
        self.assertEqual(self.pond.status, PondStatus.IN_USE)
        self.start()
        self.assertEqual(CultureCycle.objects.filter(pond=self.pond).count(), 1)

    def test_entries_cannot_predate_the_cycle_or_be_in_the_future(self):
        cycle = self.start(10)
        r = self.add(cycle, "mortality", date=ago(20), count=5)
        self.assertIn("date", r.context["form"].errors)
        r = self.add(cycle, "mortality", date=ago(-2), count=5)
        self.assertIn("date", r.context["form"].errors)

    def test_stocking_needs_a_count_or_weight_and_dues_need_a_supplier(self):
        cycle = self.start()
        r = self.add(cycle, "stocking", date=ago(59), species=self.rui.pk, cost="100")
        self.assertTrue(r.context["form"].non_field_errors())
        self.add(cycle, "stocking", date=ago(59), species=self.rui.pk, count="100", cost="5000", paid_now="1000")
        self.assertEqual(cycle.stockings.get().due, 0)   # no supplier: counted as paid
        self.add(cycle, "stocking", date=ago(59), species=self.katla.pk, count="100", cost="5000", paid_now="1000", supplier=self.supplier.pk)
        self.assertEqual(cycle.stockings.get(species=self.katla).due, 4000)

    def test_summary(self):
        cycle = self.start()
        self.add(cycle, "stocking", date=ago(59), species=self.rui.pk, count="1000", weight="20", weight_unit=self.u["kg"].pk, cost="12000")
        self.add(cycle, "mortality", date=ago(30), species=self.rui.pk, count="50")
        self.add(cycle, "weighing", date=ago(10), species=self.rui.pk, fish_count="10", total_weight="2.5", unit=self.u["kg"].pk)
        s = summarize(cycle)
        rui = s.species[0]
        self.assertEqual((rui.stocked, rui.died, rui.alive, rui.avg_g), (1000, 50, 950, D("250.0")))
        self.assertEqual(s.biomass_kg, D("237.5"))
        self.assertEqual(s.stocking_cost, 12000)

    def test_final_harvest_finishes_the_cycle_and_empties_the_pond(self):
        cycle = self.start()
        self.add(cycle, "harvest", date=ago(1), species=self.rui.pk, quantity="5", unit=self.u["mon"].pk, is_final="on")
        cycle.refresh_from_db()
        self.pond.refresh_from_db()
        self.assertFalse(cycle.is_running)
        self.assertEqual(self.pond.status, PondStatus.EMPTY)
        self.assertEqual(Harvest.objects.get().base_quantity, 200)

    def test_harvest_then_sell_opens_a_prefilled_sale(self):
        cycle = self.start()
        r = self.client.post(reverse("business:entry_add", args=[cycle.pk, "harvest"]),
                             {"harvest-date": ago(1), "harvest-species": self.katla.pk, "harvest-quantity": "3", "harvest-unit": self.u["mon"].pk, "then": "sell"})
        h = Harvest.objects.get()
        self.assertRedirects(r, reverse("business:sale_add") + f"?harvest={h.pk}")
        form = self.client.get(r.url).context["lines"].forms[0]
        self.assertEqual(form.initial["species"], self.katla.pk)

    def test_fcr(self):
        cycle = self.start()
        self.add(cycle, "stocking", date=ago(59), species=self.rui.pk, count="1000", weight="100", weight_unit=self.u["kg"].pk)
        self.buy([{"product": self.feed.pk, "quantity": "20", "unit": "", "rate": "1450"}])
        FeedUsage.objects.create(business=self.b, cycle=cycle, date=date.today(), product=self.feed, quantity=12)   # 300 kg
        Harvest.objects.create(business=self.b, cycle=cycle, date=date.today(), species=self.rui, quantity=5, unit=self.u["mon"])  # 200 kg
        self.assertEqual(summarize(cycle).fcr, D("3.00"))   # 300 kg feed for 100 kg gained

    def test_data_entry_staff_can_record_but_not_delete(self):
        cycle = self.start()
        self.client.force_login(self.staff)
        self.add(cycle, "mortality", date=ago(1), count="3")
        m = cycle.mortalities.get()
        r = self.client.post(reverse("business:entry_delete", args=["mortality", m.pk]))
        self.assertEqual(r.status_code, 403)


class FeedTests(Phase3Base):
    def test_purchase_totals_bags_and_other_units(self):
        self.buy([{"product": self.feed.pk, "quantity": "10", "unit": "", "rate": "1450"},
                  {"product": self.feed.pk, "quantity": "2", "unit": self.u["mon"].pk, "rate": "2400"}],
                 transport="300", discount="100", paid_now="10000")
        p = FeedPurchase.objects.get()
        self.assertEqual((p.subtotal, p.total, p.due), (D("19300"), D("19500"), D("9500")))
        self.assertEqual(sum(line.kg for line in p.lines.all()), 330)   # 10 bags × 25 kg + 2 mon × 40 kg

    def test_purchase_needs_a_line(self):
        r = self.buy([])
        self.assertEqual(r.status_code, 200)
        self.assertFalse(FeedPurchase.objects.exists())

    def test_stock_goes_down_with_feeding_and_warns_when_low(self):
        self.feed.low_stock_bags = 5
        self.feed.save()
        self.buy([{"product": self.feed.pk, "quantity": "10", "unit": "", "rate": "1450"}])
        cycle = self.start()
        r = self.client.post(reverse("business:feed_usage_bulk"), {"date": ago(0), "product": self.feed.pk, "unit": self.u["kg"].pk, f"c{cycle.pk}": "150"})
        self.assertRedirects(r, reverse("business:feed_usage"))
        row = next(r for r in stock(self.b) if r.product == self.feed)
        self.assertEqual((row.left_kg, row.left_bags, row.is_low), (D("100"), D("4.0"), True))

    def test_deleted_purchase_leaves_stock(self):
        self.buy([{"product": self.feed.pk, "quantity": "10", "unit": "", "rate": "1450"}])
        FeedPurchase.objects.get().soft_delete()
        self.assertEqual(next(r for r in stock(self.b) if r.product == self.feed).bought_kg, 0)

    def test_bulk_feeding_prefills_last_amounts(self):
        cycle = self.start()
        FeedUsage.objects.create(business=self.b, cycle=cycle, date=date.today() - timedelta(days=1), product=self.feed, quantity=D("1.5"))
        form = self.client.get(reverse("business:feed_usage_bulk")).context["form"]
        self.assertEqual(form.initial[f"c{cycle.pk}"], "1.5")
        self.assertEqual(form.initial["product"], self.feed.pk)


class SaleTests(Phase3Base):
    def setUp(self):
        super().setUp()
        self.market = Market.objects.create(business=self.b, name="Mesua")
        self.commission = DeductionType.objects.get(business=self.b, name="Aarot commission")
        self.labour = DeductionType.objects.get(business=self.b, name="Labour")
        MarketDeduction.objects.create(business=self.b, market=self.market, deduction_type=self.commission, method="percent", value=3)
        self.buyer = Party.objects.create(business=self.b, name="Hasan", is_buyer=True)

    def sell(self, lines, deds, **extra):
        data = {"date": ago(1), "market": self.market.pk, "buyer": self.buyer.pk, **extra, **rows("lines", lines), **rows("deds", deds)}
        return self.client.post(reverse("business:sale_add"), data)

    def test_net_after_percent_per_unit_and_fixed_deductions(self):
        self.sell([{"species": self.katla.pk, "quantity": "6", "unit": self.u["mon"].pk, "rate": "11200"},
                   {"species": self.rui.pk, "quantity": "40", "unit": self.u["kg"].pk, "rate": "250"}],
                  [{"deduction_type": self.commission.pk, "method": "percent", "value": "3"},
                   {"deduction_type": self.labour.pk, "method": "per_unit", "value": "20", "unit": self.u["mon"].pk},
                   {"deduction_type": self.labour.pk, "method": "fixed", "value": "100"}],
                  received_now="50000")
        s = FishSale.objects.get()
        # gross 67,200 + 10,000 = 77,200; 3% = 2,316; labour 20 × (240+40)/40 mon = 140; fixed 100
        self.assertEqual((s.gross, s.deductions_total, s.net, s.due), (D("77200"), D("2556"), D("74644"), D("24644")))

    def test_per_piece_charge_ignores_fish_sold_by_weight(self):
        self.sell([{"species": self.rui.pk, "quantity": "10", "unit": self.u["kg"].pk, "rate": "250"}],
                  [{"deduction_type": self.labour.pk, "method": "per_unit", "value": "1", "unit": self.u["pcs"].pk}])
        self.assertEqual(FishSale.objects.get().deductions_total, 0)

    def test_new_sale_starts_with_the_market_deductions(self):
        FishSale.objects.create(business=self.b, date=date.today(), market=self.market)
        deds = self.client.get(reverse("business:sale_add")).context["deds"]
        self.assertEqual(deds.forms[0].initial["deduction_type"], self.commission.pk)

    def test_a_sale_needs_fish(self):
        r = self.sell([], [])
        self.assertEqual(r.status_code, 200)
        self.assertFalse(FishSale.objects.exists())

    def test_sales_count_in_the_cycle(self):
        cycle = self.start()
        self.sell([{"species": self.rui.pk, "quantity": "100", "unit": self.u["kg"].pk, "rate": "200"}], [], cycle=cycle.pk)
        self.assertEqual(summarize(cycle).sales_net, D("20000"))

    def test_edit_and_soft_delete(self):
        self.sell([{"species": self.rui.pk, "quantity": "10", "unit": self.u["kg"].pk, "rate": "200"}], [])
        s = FishSale.objects.get()
        line = s.lines.get()
        data = {"date": ago(1), "market": self.market.pk, "buyer": self.buyer.pk, "received_now": "",
                "lines-TOTAL_FORMS": "1", "lines-INITIAL_FORMS": "1", "lines-MIN_NUM_FORMS": "0", "lines-MAX_NUM_FORMS": "1000",
                "lines-0-id": line.pk, "lines-0-species": self.rui.pk, "lines-0-quantity": "20", "lines-0-unit": self.u["kg"].pk, "lines-0-rate": "200",
                **rows("deds", [])}
        self.client.post(reverse("business:sale_edit", args=[s.pk]), data)
        s.refresh_from_db()
        self.assertEqual(s.net, 4000)
        self.client.post(reverse("business:sale_delete", args=[s.pk]))
        self.assertFalse(FishSale.objects.exists())

    def test_pages_render(self):
        cycle = self.start()
        self.sell([{"species": self.rui.pk, "quantity": "10", "unit": self.u["kg"].pk, "rate": "200"}], [], cycle=cycle.pk)
        s = FishSale.objects.get()
        for url in [reverse("business:sales"), reverse("business:sale_add"), reverse("business:sale_detail", args=[s.pk]),
                    reverse("business:pond_detail", args=[self.pond.pk]), reverse("business:cycle_detail", args=[cycle.pk]),
                    reverse("business:feed_stock"), reverse("business:feed_usage"), reverse("business:feed_usage_bulk"),
                    reverse("business:feed_purchases"), reverse("business:feed_purchases_add"), reverse("business:home")]:
            self.assertEqual(self.client.get(url).status_code, 200, url)
