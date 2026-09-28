"""Phase 6: the dashboard, the reports and the CSV exports."""
from datetime import date, timedelta
from decimal import Decimal as D

from django.test import TestCase
from django.urls import reverse

from apps.business.core.models import Role, Unit
from apps.business.core.testing import make_farm
from apps.business.credit.models import Direction, PartyPayment
from apps.business.feed.models import FeedProduct, FeedPurchase, FeedPurchaseLine, FeedUsage
from apps.business.finance.models import Account, Category, Transaction
from apps.business.markets.models import Market
from apps.business.parties.models import Party
from apps.business.ponds.models import CultureCycle, Harvest, Pond, Stocking
from apps.business.sales.models import FishSale, FishSaleLine
from apps.business.species.models import Species

from . import services


def ago(n):
    return date.today() - timedelta(days=n)


class ReportBase(TestCase):
    def setUp(self):
        self.b, self.owner, self.staff = make_farm()
        self.client.force_login(self.owner)
        self.kg = Unit.objects.get(business=self.b, symbol="kg")
        self.mon = Unit.objects.get(business=self.b, symbol="mon")
        self.rui = Species.objects.get(business=self.b, name="Rui")
        self.katla = Species.objects.get(business=self.b, name="Katla")
        self.cash = Account.objects.get(business=self.b, name="Cash")
        self.market = Market.objects.create(business=self.b, name="Jessore Aarot")
        self.buyer = Party.objects.create(business=self.b, name="Hasan", is_buyer=True, phone="01712-345678")
        self.dec = Unit.objects.get(business=self.b, symbol="dec")
        self.pond = Pond.objects.create(business=self.b, name="East", area=D("60"), area_unit=self.dec)
        self.cycle = CultureCycle.objects.create(business=self.b, pond=self.pond, name="Carp 2026", start_date=ago(120))

    def sell(self, amount, days=0, species=None, qty="5", market=None, cycle=None):
        sale = FishSale.objects.create(business=self.b, date=ago(days), buyer=self.buyer, market=market or self.market,
                                       cycle=cycle or self.cycle, received_now=D(amount), account=self.cash)
        FishSaleLine.objects.create(business=self.b, sale=sale, species=species or self.rui, quantity=D(qty),
                                    unit=self.kg, rate=D(amount) / D(qty))
        sale.recalc()
        return sale

    def spend(self, amount, name="Daily labour", days=0, cycle=None):
        return Transaction.objects.create(business=self.b, date=ago(days), amount=D(amount), account=self.cash,
                                          category=Category.objects.get(business=self.b, name=name), cycle=cycle)


class DashboardTests(ReportBase):
    def test_headline_adds_up_sales_and_costs(self):
        self.sell(10000, days=2)
        self.spend(3000, days=1)
        d = services.dashboard(self.b)
        self.assertEqual(d["month"]["income"], D("10000"))
        self.assertEqual(d["month"]["expense"], D("3000"))
        self.assertEqual(d["month"]["profit"], D("7000"))

    def test_fish_income_is_split_from_other_income(self):
        self.sell(10000, days=2)
        Transaction.objects.create(business=self.b, date=ago(1), amount=D("4500"), account=self.cash,
                                   category=Category.objects.get(business=self.b, name="Other income"))
        d = services.dashboard(self.b)
        self.assertEqual(d["month"]["fish"], D("10000"))
        self.assertEqual(d["month"]["other_income"], D("4500"))
        self.assertEqual(d["month"]["income"], D("14500"))

    def test_today_only_counts_today(self):
        self.sell(5000, days=0)
        self.sell(9000, days=3)
        d = services.dashboard(self.b)
        self.assertEqual(d["today"]["income"], D("5000"))
        self.assertEqual(d["today"]["sale_count"], 1)

    def test_trend_has_one_row_per_month(self):
        rows = services.monthly_trend(self.b, months=6)
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[-1]["month"], date.today().replace(day=1))

    def test_kg_sold_counts_only_weight_units(self):
        self.sell(10000, qty="40")
        sale = FishSale.objects.create(business=self.b, date=date.today(), buyer=self.buyer)
        pcs = Unit.objects.get(business=self.b, symbol="pcs")
        FishSaleLine.objects.create(business=self.b, sale=sale, species=self.rui, quantity=D("20"), unit=pcs, rate=D("50"))
        d = services.dashboard(self.b)
        self.assertEqual(d["month"]["kg"], D("40"))

    def test_dashboard_page_loads_with_no_data(self):
        b2, owner2, _s = make_farm("empty")
        self.client.force_login(owner2)
        r = self.client.get(reverse("business:dashboard"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["d"]["month"]["profit"], 0)

    def test_dashboard_shows_running_ponds(self):
        Stocking.objects.create(business=self.b, cycle=self.cycle, date=ago(120), species=self.rui, count=3000, cost=D("20000"))
        r = self.client.get(reverse("business:dashboard"))
        self.assertEqual([row.cycle.pk for row in r.context["d"]["running"]], [self.cycle.pk])


class SalesReportTests(ReportBase):
    def test_sales_by_species(self):
        self.sell(10000, species=self.rui)
        self.sell(6000, species=self.katla)
        rows = services.sales_by(self.b, ago(30), date.today(), "species")
        self.assertEqual([(r.label, r.value) for r in rows], [("Rui", D("10000")), ("Katla", D("6000"))])

    def test_sales_by_market(self):
        other = Market.objects.create(business=self.b, name="Local bazar")
        self.sell(10000)
        self.sell(4000, market=other)
        rows = services.sales_by(self.b, ago(30), date.today(), "market")
        self.assertEqual([(r.label, r.value) for r in rows], [("Jessore Aarot", D("10000")), ("Local bazar", D("4000"))])

    def test_species_totals_match_the_net_after_deductions(self):
        from apps.business.markets.models import DeductionType
        from apps.business.sales.models import SaleDeduction

        sale = self.sell(10000)
        SaleDeduction.objects.create(business=self.b, sale=sale, method="percent", value=D("10"),
                                     deduction_type=DeductionType.objects.filter(business=self.b).first())
        sale.recalc()
        rows = services.sales_by(self.b, ago(30), date.today(), "species")
        self.assertEqual(sum(r.value for r in rows), sale.net)
        self.assertEqual(rows[0].value, D("9000"))

    def test_sales_by_buyer_links_to_the_statement(self):
        self.sell(7000)
        rows = services.sales_by(self.b, ago(30), date.today(), "buyer")
        self.assertEqual(rows[0].url, reverse("business:party_statement", args=[self.buyer.pk]))

    def test_deleted_sales_are_left_out(self):
        sale = self.sell(10000)
        sale.soft_delete()
        self.assertEqual(services.sales_by(self.b, ago(30), date.today(), "species"), [])


class PondReportTests(ReportBase):
    def test_pond_row_adds_cost_sales_and_profit(self):
        Stocking.objects.create(business=self.b, cycle=self.cycle, date=ago(120), species=self.rui, count=3000, cost=D("20000"))
        self.spend(5000, cycle=self.cycle)
        self.sell(50000, days=1)
        rows = services.pond_rows(self.b)
        row = rows[0]
        self.assertEqual(row["sales"], D("50000"))
        self.assertEqual(row["cost"], D("25000"))
        self.assertEqual(row["profit"], D("25000"))

    def test_profit_per_decimal_uses_the_pond_area(self):
        self.sell(60000, days=1)
        row = services.pond_rows(self.b)[0]
        self.assertEqual(row["per_decimal"], D("1000"))  # 60,000 over 60 decimals

    def test_fcr_comes_from_feed_and_harvest(self):
        product = FeedProduct.objects.create(business=self.b, name="Float", bag_size=25, bag_unit=self.kg)
        FeedUsage.objects.create(business=self.b, cycle=self.cycle, date=ago(10), product=product, quantity=D("300"), unit=self.kg)
        Harvest.objects.create(business=self.b, cycle=self.cycle, date=ago(2), species=self.rui, quantity=D("100"), unit=self.kg)
        row = services.pond_rows(self.b)[0]
        self.assertEqual(row["fcr"], D("3"))

    def test_pond_fcr_matches_the_cycle_fcr(self):
        # Fingerling weight isn't growth: 300 kg of feed for 100 − 20 = 80 kg gained.
        product = FeedProduct.objects.create(business=self.b, name="Float", bag_size=25, bag_unit=self.kg)
        Stocking.objects.create(business=self.b, cycle=self.cycle, date=ago(120), species=self.rui, count=2000,
                                weight=D("20"), weight_unit=self.kg)
        FeedUsage.objects.create(business=self.b, cycle=self.cycle, date=ago(10), product=product, quantity=D("300"), unit=self.kg)
        Harvest.objects.create(business=self.b, cycle=self.cycle, date=ago(2), species=self.rui, quantity=D("100"), unit=self.kg)
        pond_fcr = services.pond_rows(self.b)[0]["fcr"]
        cycle_fcr = services.cycle_rows(self.b)[0].summary.fcr
        self.assertEqual(cycle_fcr, D("3.75"))
        self.assertEqual(pond_fcr, cycle_fcr)

    def test_a_pond_with_nothing_still_appears(self):
        Pond.objects.create(business=self.b, name="West")
        names = {r["pond"].name for r in services.pond_rows(self.b)}
        self.assertEqual(names, {"East", "West"})

    def test_cycle_rows_carry_their_summary(self):
        Stocking.objects.create(business=self.b, cycle=self.cycle, date=ago(120), species=self.rui, count=3000, cost=D("20000"))
        rows = services.cycle_rows(self.b)
        self.assertEqual(rows[0].summary.stocked, 3000)
        self.assertEqual(rows[0].days, 120)


class FeedReportTests(ReportBase):
    def test_bought_against_eaten(self):
        supplier = Party.objects.create(business=self.b, name="Mollah", is_supplier=True)
        product = FeedProduct.objects.create(business=self.b, name="Float", bag_size=25, bag_unit=self.kg)
        purchase = FeedPurchase.objects.create(business=self.b, date=ago(20), supplier=supplier)
        FeedPurchaseLine.objects.create(business=self.b, purchase=purchase, product=product, quantity=D("10"), rate=D("1000"))
        purchase.recalc()
        FeedUsage.objects.create(business=self.b, cycle=self.cycle, date=ago(5), product=product, quantity=D("100"), unit=self.kg)
        rows = services.feed_report(self.b, ago(30), date.today())
        row = rows[0]
        self.assertEqual(row["bought_kg"], D("250"))
        self.assertEqual(row["used_kg"], D("100"))
        self.assertEqual(row["used_cost"], D("4000"))  # 100 kg at ৳40/kg


class ReportPageTests(ReportBase):
    def setUp(self):
        super().setUp()
        Stocking.objects.create(business=self.b, cycle=self.cycle, date=ago(120), species=self.rui, count=3000, cost=D("20000"))
        self.sell(50000, days=2)
        self.spend(4000, days=1)
        PartyPayment.objects.create(business=self.b, party=self.buyer, direction=Direction.IN, date=ago(1),
                                    amount=D("1000"), account=self.cash)

    def test_every_report_page_loads(self):
        for kind, *_rest in __import__("apps.business.reports.views", fromlist=["REPORTS"]).REPORTS:
            with self.subTest(kind=kind):
                r = self.client.get(reverse("business:report", args=[kind]) + "?period=year")
                self.assertEqual(r.status_code, 200)

    def test_every_report_exports_a_csv(self):
        for kind, *_rest in __import__("apps.business.reports.views", fromlist=["REPORTS"]).REPORTS:
            with self.subTest(kind=kind):
                r = self.client.get(reverse("business:report", args=[kind]) + "?period=year&export=csv")
                self.assertEqual(r["Content-Type"], "text/csv")
                self.assertIn("attachment", r["Content-Disposition"])
                body = r.content.decode("utf-8-sig")
                self.assertIn(self.b.name, body)

    def test_csv_starts_with_the_excel_bom(self):
        r = self.client.get(reverse("business:report", args=["pond"]) + "?export=csv")
        self.assertTrue(r.content.startswith(b"\xef\xbb\xbf"))

    def test_pond_csv_has_the_figures(self):
        r = self.client.get(reverse("business:report", args=["pond"]) + "?period=year&export=csv")
        body = r.content.decode("utf-8-sig")
        self.assertIn("East", body)
        self.assertIn("50000", body)

    def test_an_unknown_report_is_404(self):
        self.assertEqual(self.client.get(reverse("business:report", args=["nonsense"])).status_code, 404)

    def test_custom_dates_are_used(self):
        r = self.client.get(reverse("business:report", args=["species"]) + f"?from={ago(3)}&to={date.today()}")
        self.assertEqual(r.context["period"].key, "custom")
        self.assertEqual(r.context["period"].start, ago(3))

    def test_backwards_dates_are_swapped(self):
        r = self.client.get(reverse("business:report", args=["species"]) + f"?from={date.today()}&to={ago(10)}")
        self.assertEqual((r.context["period"].start, r.context["period"].end), (ago(10), date.today()))

    def test_period_limits_what_is_counted(self):
        self.sell(9000, days=200)
        month = self.client.get(reverse("business:report", args=["species"]) + "?period=month")
        every = self.client.get(reverse("business:report", args=["species"]) + "?period=all")
        self.assertLess(month.context["r"]["total_value"], every.context["r"]["total_value"])

    def test_money_report_splits_farm_and_household(self):
        self.spend(2000, name="Groceries (bazar)")
        farm = self.client.get(reverse("business:report", args=["money"]) + "?period=month")
        home = self.client.get(reverse("business:report", args=["money"]) + "?period=month&scope=household")
        self.assertEqual(home.context["r"]["s"].total_expense, D("2000"))
        self.assertNotEqual(farm.context["r"]["s"].total_expense, D("2000"))

    def test_reports_index_loads(self):
        r = self.client.get(reverse("business:reports"))
        self.assertEqual(len(r.context["reports"]), 7)

    def test_other_farms_see_nothing(self):
        _b2, owner2, _s = make_farm("other")
        self.client.force_login(owner2)
        r = self.client.get(reverse("business:report", args=["pond"]) + "?period=year")
        self.assertEqual(r.context["r"]["sales"], 0)


class AccessTests(TestCase):
    def test_viewer_can_see_reports(self):
        _b, _owner, viewer = make_farm(staff_role=Role.VIEWER)
        self.client.force_login(viewer)
        self.assertEqual(self.client.get(reverse("business:dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("business:reports")).status_code, 200)

    def test_data_entry_staff_cannot(self):
        _b, _owner, staff = make_farm()
        self.client.force_login(staff)
        self.assertEqual(self.client.get(reverse("business:dashboard")).status_code, 403)
        self.assertEqual(self.client.get(reverse("business:report", args=["pond"])).status_code, 403)


class QueryCountTests(ReportBase):
    """The reports must not run one query per pond: a farm with 20 ponds
    should cost the same as a farm with two."""

    made = 0

    def _make_ponds(self, n):
        for _ in range(n):
            i = QueryCountTests.made = QueryCountTests.made + 1
            pond = Pond.objects.create(business=self.b, name=f"P{i}", area=D("40"), area_unit=self.dec)
            cycle = CultureCycle.objects.create(business=self.b, pond=pond, name=f"C{i}", start_date=ago(100))
            Stocking.objects.create(business=self.b, cycle=cycle, date=ago(100), species=self.rui, count=500, cost=D("5000"))
            Transaction.objects.create(business=self.b, date=ago(5), amount=D("100"), cycle=cycle,
                                       category=Category.objects.get(business=self.b, name="Daily labour"))

    def test_cycle_report_queries_do_not_grow_with_ponds(self):
        self._make_ponds(2)
        few = self._count_queries()
        self._make_ponds(8)
        many = self._count_queries()
        self.assertEqual(few, many, f"queries grew from {few} to {many} when ponds were added")

    def _count_queries(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            services.cycle_rows(self.b)
        return len(ctx.captured_queries)

    def test_pond_report_queries_do_not_grow_with_ponds(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self._make_ponds(2)
        with CaptureQueriesContext(connection) as ctx:
            services.pond_rows(self.b)
        few = len(ctx.captured_queries)
        self._make_ponds(8)
        with CaptureQueriesContext(connection) as ctx:
            services.pond_rows(self.b)
        self.assertEqual(few, len(ctx.captured_queries))

    def test_a_summary_still_works_on_its_own(self):
        """One pond's page doesn't prefetch, so summarize must still fetch."""
        from apps.business.ponds.services import summarize

        self._make_ponds(1)
        cycle = CultureCycle.objects.filter(name=f"C{QueryCountTests.made}").get()
        s = summarize(cycle)
        self.assertEqual(s.stocked, 500)
        self.assertEqual(s.other_cost, D("100"))

    def test_prefetched_and_plain_summaries_agree(self):
        self._make_ponds(1)
        from apps.business.ponds.services import summarize

        name = f"C{QueryCountTests.made}"
        plain = summarize(CultureCycle.objects.filter(name=name).get())
        via_report = next(r for r in services.cycle_rows(self.b) if r.cycle.name == name).summary
        self.assertEqual((plain.stocked, plain.cost, plain.sales_net),
                         (via_report.stocked, via_report.cost, via_report.sales_net))
