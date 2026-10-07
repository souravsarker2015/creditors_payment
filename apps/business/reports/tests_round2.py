"""Financial year, what the farm is worth, fingerling sellers and the morning water check."""
from datetime import date, timedelta
from decimal import Decimal as D

from django.test import TestCase
from django.urls import reverse

from apps.business.assets.models import Equipment
from apps.business.core.models import Membership, Role, Unit
from apps.business.core.periods import fy_end, fy_label, fy_start, last_fy
from apps.business.core.testing import make_farm
from apps.business.feed.models import FeedProduct, FeedPurchase, FeedPurchaseLine
from apps.business.finance.models import Account
from apps.business.loans.models import Lender, Loan
from apps.business.parties.models import Party
from apps.business.ponds.models import CultureCycle, Mortality, Pond, SampleWeighing, Stocking, WaterTest
from apps.business.species.models import Species

from . import services
from .worth import farm_worth

TODAY = date.today()


def ago(n):
    return TODAY - timedelta(days=n)


class FinancialYearTests(TestCase):
    def test_july_to_june(self):
        self.assertEqual(fy_start(date(2026, 10, 7)), date(2026, 7, 1))
        self.assertEqual(fy_start(date(2026, 3, 1)), date(2025, 7, 1))
        self.assertEqual(fy_end(date(2026, 3, 1)), date(2026, 6, 30))
        self.assertEqual(last_fy(date(2026, 10, 7)), (date(2025, 7, 1), date(2026, 6, 30)))
        self.assertEqual(fy_label(date(2026, 10, 7)), "FY 2026–27")

    def test_pages_offer_it(self):
        b, owner, _ = make_farm()
        self.client.force_login(owner)
        r = self.client.get(reverse("business:report", args=["money"]) + "?period=fy")
        self.assertContains(r, "This financial year")
        r = self.client.get(reverse("business:statement") + "?period=fy&month=2026-10")
        self.assertContains(r, "FY 2026–27")
        self.assertContains(self.client.get(reverse("business:partner_sharing") + "?period=lastfy"), "Last financial year")
        self.assertContains(self.client.get(reverse("business:transactions") + "?period=fy"), "This financial year")


class Base(TestCase):
    def setUp(self):
        self.b, self.owner, self.staff = make_farm()
        self.client.force_login(self.owner)
        self.kg = Unit.objects.get(business=self.b, symbol="kg")
        self.rui = Species.objects.get(business=self.b, name="Rui")
        self.cash = Account.objects.get(business=self.b, name="Cash")
        self.pond = Pond.objects.create(business=self.b, name="East")
        self.cycle = CultureCycle.objects.create(business=self.b, pond=self.pond, start_date=ago(60))


class WorthTests(Base):
    def test_owns_and_owes(self):
        Account.objects.filter(pk=self.cash.pk).update(opening_balance=D("50000"))
        Stocking.objects.create(business=self.b, cycle=self.cycle, date=ago(60), species=self.rui, count=1000,
                                weight=D("20"), weight_unit=self.kg, cost=D("30000"), paid_now=D("30000"))
        SampleWeighing.objects.create(business=self.b, cycle=self.cycle, date=ago(1), species=self.rui, fish_count=10, total_weight=D("3"), unit=self.kg)
        Equipment.objects.create(business=self.b, name="Aerator", cost=D("25000"))
        Equipment.objects.create(business=self.b, name="Old pump", cost=D("9000"), condition="out")
        dealer = Party.objects.create(business=self.b, name="Feed dealer", is_supplier=True, opening_balance=D("12000"), opening_type="payable")
        w = farm_worth(self.b)
        owns = {l.key: l.amount for l in w.owns}
        owes = {l.key: l.amount for l in w.owes}
        self.assertEqual(owns["cash"], D("50000"))
        self.assertEqual(owns["fish"], D("30000"))          # at cost so far
        self.assertEqual(owns["equipment"], D("25000"))     # the broken-down pump is left out
        self.assertEqual(owes["payable"], D("12000"))
        self.assertEqual(w.net, D("50000") + D("30000") + D("25000") - D("12000"))
        self.assertIsNone(w.fish_at_price)                  # no sales yet to price them

    def test_accounts_below_zero_are_owed_not_owned(self):
        from apps.business.finance.models import Category, Transaction

        cat = Category.objects.filter(business=self.b, type="expense").first()
        Transaction.objects.create(business=self.b, date=TODAY, amount=D("5000"), category=cat, account=self.cash)
        w = farm_worth(self.b)
        self.assertNotIn("cash", [l.key for l in w.owns])
        self.assertEqual({l.key: l.amount for l in w.owes}["cash"], D("5000"))

    def test_loans_count_as_owed(self):
        lender = Lender.objects.create(business=self.b, name="Krishi Bank")
        Loan.objects.create(business=self.b, lender=lender, principal=D("100000"), taken_on=ago(10))
        owes = {l.key: l.amount for l in farm_worth(self.b).owes}
        self.assertGreater(owes.get("loans", 0), 0)

    def test_page_print_and_csv_for_money_people_only(self):
        r = self.client.get(reverse("business:worth"))
        self.assertContains(r, "What the farm owns")
        self.assertEqual(self.client.get(reverse("business:worth") + "?export=csv")["Content-Type"], "text/csv")
        self.assertContains(self.client.get(reverse("business:reports")), reverse("business:worth"))
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("business:worth")).status_code, 403)


class FingerlingReportTests(Base):
    def test_survival_and_growth_by_seller(self):
        good = Party.objects.create(business=self.b, name="Good Hatchery", is_supplier=True)
        bad = Party.objects.create(business=self.b, name="Cheap Hatchery", is_supplier=True)
        other = CultureCycle.objects.create(business=self.b, pond=Pond.objects.create(business=self.b, name="West"), start_date=ago(60))
        Stocking.objects.create(business=self.b, cycle=self.cycle, date=ago(60), species=self.rui, count=1000, weight=D("10"),
                                weight_unit=self.kg, supplier=good, cost=D("3000"), paid_now=D("3000"))
        Stocking.objects.create(business=self.b, cycle=other, date=ago(60), species=self.rui, count=1000, weight=D("10"),
                                weight_unit=self.kg, supplier=bad, cost=D("2000"), paid_now=D("2000"))
        Mortality.objects.create(business=self.b, cycle=other, date=ago(5), species=self.rui, count=300)
        SampleWeighing.objects.create(business=self.b, cycle=self.cycle, date=ago(0), species=self.rui, fish_count=10, total_weight=D("1.3"), unit=self.kg)
        rows = services.fingerling_rows(self.b, ago(90), TODAY)
        self.assertEqual([str(r["supplier"]) for r in rows], ["Good Hatchery", "Cheap Hatchery"])
        self.assertEqual(rows[0]["survival"], 100)
        self.assertEqual(rows[1]["survival"], 70)
        self.assertEqual(rows[0]["per_1000"], D("3000"))
        self.assertEqual(rows[0]["growth"], D("2.0"))       # 10 g → 130 g in 60 days
        r = self.client.get(reverse("business:report", args=["fingerlings"]) + "?period=3m")
        self.assertContains(r, "Good Hatchery")
        self.assertEqual(self.client.get(reverse("business:report", args=["fingerlings"]) + "?period=3m&export=csv").status_code, 200)


class WaterCheckTests(Base):
    def setUp(self):
        super().setUp()
        self.west = Pond.objects.create(business=self.b, name="West")
        self.other = CultureCycle.objects.create(business=self.b, pond=self.west, start_date=ago(30))

    def post(self, **readings):
        data = {"date": TODAY.isoformat(), "time_of_day": "dawn"}
        data.update(readings)
        return self.client.post(reverse("business:water_check"), data, follow=True)

    def test_saves_only_ponds_with_readings_and_warns(self):
        r = self.post(**{f"c{self.cycle.pk}_oxygen": "2.5", f"c{self.cycle.pk}_ph": "7.5"})
        self.assertEqual(WaterTest.objects.count(), 1)
        t = WaterTest.objects.get()
        self.assertEqual((t.cycle, t.oxygen, t.time_of_day), (self.cycle, D("2.5"), "dawn"))
        self.assertContains(r, "Needs attention")
        self.assertContains(r, "East")

    def test_all_fine(self):
        r = self.post(**{f"c{self.cycle.pk}_oxygen": "6", f"c{self.other.pk}_oxygen": "5.5"})
        self.assertEqual(WaterTest.objects.count(), 2)
        self.assertContains(r, "All readings are within your levels")

    def test_nothing_entered_or_bad_ph(self):
        r = self.post()
        self.assertContains(r, "Enter at least one reading")
        r = self.post(**{f"c{self.cycle.pk}_ph": "15"})
        self.assertContains(r, "pH goes from 0 to 14")
        self.assertFalse(WaterTest.objects.exists())

    def test_data_entry_staff_use_it_from_home(self):
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(reverse("business:home")), reverse("business:water_check"))
        self.assertEqual(self.client.get(reverse("business:water_check")).status_code, 200)
