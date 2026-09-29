"""Water tests, the farm's alert levels, death spikes and the daily WhatsApp report."""
from datetime import date, timedelta
from decimal import Decimal as D
from urllib.parse import unquote

from django.test import TestCase
from django.urls import reverse

from apps.business.core.models import Unit
from apps.business.core.testing import make_farm
from apps.business.sales.models import FishSale, FishSaleLine
from apps.business.species.models import Species

from .models import CultureCycle, Mortality, Pond, PondAlerts, Stocking, WaterTest
from .services import farm_tasks


def ago(n):
    return date.today() - timedelta(days=n)


class WaterBase(TestCase):
    def setUp(self):
        self.b, self.owner, self.staff = make_farm()
        self.client.force_login(self.owner)
        self.rui = Species.objects.get(business=self.b, name="Rui")
        self.kg = Unit.objects.get(business=self.b, symbol="kg")
        self.pond = Pond.objects.create(business=self.b, name="East")
        self.cycle = CultureCycle.objects.create(business=self.b, pond=self.pond, start_date=ago(60))
        self.limits = PondAlerts.for_business(self.b)

    def water(self, **readings):
        return WaterTest.objects.create(business=self.b, cycle=self.cycle, date=readings.pop("on", date.today()), **readings)


class WaterRuleTests(WaterBase):
    def test_good_water_has_no_problems(self):
        t = self.water(oxygen=D("6"), ph=D("7.5"), temperature=D("28"), ammonia=D("0.1"), transparency=D("30"))
        self.assertEqual(t.problems(self.limits), [])

    def test_each_reading_is_checked_against_the_limits(self):
        t = self.water(oxygen=D("2.5"), ph=D("9.2"), temperature=D("35"), ammonia=D("1.2"), transparency=D("15"))
        found = {p.reading for p in t.problems(self.limits)}
        self.assertEqual(found, {"oxygen", "ph", "temperature", "ammonia", "transparency"})
        self.assertTrue(next(p for p in t.problems(self.limits) if p.reading == "oxygen").urgent)

    def test_empty_readings_are_not_problems(self):
        self.assertEqual(self.water(ph=D("7")).problems(self.limits), [])

    def test_the_farm_sets_its_own_limits(self):
        t = self.water(oxygen=D("4.5"))
        self.assertEqual(t.problems(self.limits), [])
        self.limits.oxygen_min = D("5")
        self.assertEqual([p.reading for p in t.problems(self.limits)], ["oxygen"])

    def test_each_farm_gets_its_own_levels(self):
        other, _o, _s = make_farm(owner_name="other")
        self.limits.oxygen_min = D("6")
        self.limits.save()
        self.assertEqual(PondAlerts.for_business(other).oxygen_min, D("4"))


class WaterEntryTests(WaterBase):
    def add(self, **data):
        post = {f"water-{k}": v for k, v in data.items()}
        post.setdefault("water-date", date.today().isoformat())
        return self.client.post(reverse("business:entry_add", args=[self.cycle.pk, "water"]), post)

    def test_a_water_test_is_saved_from_the_cycle_page(self):
        r = self.add(oxygen="5.2", ph="7.4", time_of_day="dawn")
        self.assertRedirects(r, reverse("business:cycle_detail", args=[self.cycle.pk]) + "?tab=water", fetch_redirect_response=False)
        t = WaterTest.objects.get()
        self.assertEqual((t.oxygen, t.ph, t.time_of_day), (D("5.2"), D("7.4"), "dawn"))

    def test_at_least_one_reading_is_needed(self):
        r = self.add(time_of_day="dawn")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(WaterTest.objects.exists())

    def test_ph_cannot_be_over_14(self):
        self.add(ph="15")
        self.assertFalse(WaterTest.objects.exists())

    def test_cycle_page_warns_about_the_last_test(self):
        self.water(oxygen=D("2"))
        r = self.client.get(reverse("business:cycle_detail", args=[self.cycle.pk]))
        self.assertContains(r, "water-problems")
        self.assertEqual(len(r.context["water"]), 1)

    def test_a_good_last_test_means_no_warning(self):
        self.water(oxygen=D("2"), on=ago(3))
        self.water(oxygen=D("6"))
        r = self.client.get(reverse("business:cycle_detail", args=[self.cycle.pk]))
        self.assertNotContains(r, "water-problems")

    def test_water_tests_can_be_edited_and_deleted(self):
        t = self.water(ph=D("7"))
        r = self.client.post(reverse("business:entry_edit", args=["water", t.pk]), {"date": date.today().isoformat(), "ph": "6.8"})
        self.assertEqual(r.status_code, 302)
        t.refresh_from_db()
        self.assertEqual(t.ph, D("6.8"))
        self.client.post(reverse("business:entry_delete", args=["water", t.pk]))
        self.assertFalse(WaterTest.objects.filter(pk=t.pk).exists())

    def test_an_unknown_entry_kind_is_404(self):
        r = self.client.get(reverse("business:entry_add", args=[self.cycle.pk, "nonsense"]))
        self.assertEqual(r.status_code, 404)

    def test_another_farm_cannot_touch_our_tests(self):
        t = self.water(ph=D("7"))
        other, owner, _s = make_farm(owner_name="other")
        self.client.force_login(owner)
        r = self.client.post(reverse("business:entry_delete", args=["water", t.pk]))
        self.assertEqual(r.status_code, 404)


class AlertLevelPageTests(WaterBase):
    def test_owner_can_change_the_levels(self):
        r = self.client.get(reverse("business:pond_alerts"))
        self.assertEqual(r.status_code, 200)
        data = {k: str(getattr(self.limits, k)) for k in ("oxygen_min", "ph_min", "ph_max", "temperature_min", "temperature_max",
                                                          "ammonia_max", "transparency_min", "transparency_max", "deaths_pct")}
        data["oxygen_min"] = "5"
        self.assertEqual(self.client.post(reverse("business:pond_alerts"), data).status_code, 302)
        self.assertEqual(PondAlerts.for_business(self.b).oxygen_min, D("5"))

    def test_low_must_be_below_high(self):
        data = {"oxygen_min": "4", "ph_min": "9", "ph_max": "8", "temperature_min": "20", "temperature_max": "32",
                "ammonia_max": "0.5", "transparency_min": "25", "transparency_max": "40", "deaths_pct": "1"}
        r = self.client.post(reverse("business:pond_alerts"), data)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(PondAlerts.for_business(self.b).ph_min, D("6.5"))

    def test_data_entry_staff_cannot_change_them(self):
        self.client.force_login(self.staff)
        self.assertNotEqual(self.client.get(reverse("business:pond_alerts")).status_code, 200)

    def test_setup_page_links_to_them(self):
        self.assertContains(self.client.get(reverse("business:setup_hub")), reverse("business:pond_alerts"))


class AlertTaskTests(WaterBase):
    def kinds(self):
        return [t.kind for t in farm_tasks(self.b)]

    def test_bad_recent_water_is_a_task(self):
        self.water(ammonia=D("2"))
        tasks = farm_tasks(self.b)
        self.assertEqual(tasks[0].kind, "water")      # urgent: first
        self.assertIn("Ammonia", tasks[0].detail)

    def test_old_bad_water_is_not(self):
        self.water(ammonia=D("2"), on=ago(10))
        self.assertNotIn("water", self.kinds())

    def test_deaths_over_the_warning_level(self):
        Stocking.objects.create(business=self.b, cycle=self.cycle, date=ago(60), species=self.rui, count=1000)
        Mortality.objects.create(business=self.b, cycle=self.cycle, date=ago(1), count=5)   # 0.5%
        self.assertNotIn("deaths", self.kinds())
        Mortality.objects.create(business=self.b, cycle=self.cycle, date=date.today(), count=10)  # 1.5% in 3 days
        self.assertIn("deaths", self.kinds())

    def test_old_deaths_do_not_count_as_a_spike(self):
        Stocking.objects.create(business=self.b, cycle=self.cycle, date=ago(60), species=self.rui, count=1000)
        Mortality.objects.create(business=self.b, cycle=self.cycle, date=ago(20), count=300)
        self.assertNotIn("deaths", self.kinds())

    def test_home_shows_the_alert(self):
        self.water(oxygen=D("2"))
        self.assertContains(self.client.get(reverse("business:home")), "Water problem in East")


class DailyReportTests(WaterBase):
    def setUp(self):
        super().setUp()
        sale = FishSale.objects.create(business=self.b, date=date.today(), cycle=self.cycle, received_now=D("0"))
        FishSaleLine.objects.create(business=self.b, sale=sale, species=self.rui, quantity=D("50"), unit=self.kg, rate=D("300"))
        sale.recalc()
        Mortality.objects.create(business=self.b, cycle=self.cycle, date=date.today(), count=7)

    def report(self):
        return unquote(self.client.get(reverse("business:home")).context["share_url"])

    def test_owner_report_has_sales_money_and_deaths(self):
        text = self.report()
        self.assertTrue(text.startswith("https://wa.me/?text="))
        self.assertIn("50 kg", text)
        self.assertIn("15,000", text)
        self.assertIn("Deaths: 7 fish", text)
        self.assertIn("Still to do:", text)      # no feeding recorded today

    def test_staff_report_leaves_money_out(self):
        self.client.force_login(self.staff)
        text = self.report()
        self.assertIn("50 kg", text)
        self.assertNotIn("15,000", text)
        self.assertNotIn("Money in", text)
