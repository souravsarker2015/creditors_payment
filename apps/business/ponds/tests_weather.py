"""Tonight's low-oxygen risk from the weather forecast."""
from datetime import date, datetime, timedelta
from decimal import Decimal as D
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.business.core.models import Business, Membership
from apps.business.core.testing import make_farm

from . import weather
from .models import CultureCycle, Pond, WaterTest

NOW = datetime(2026, 7, 10, 14, 0)


def hourly(temp=29.0, cloud=90, wind=4.0, rain=0.0, start=date(2026, 7, 10), days=2):
    """The same weather every hour, as Open-Meteo sends it."""
    n = 24 * days
    times = [datetime(start.year, start.month, start.day) + timedelta(hours=h) for h in range(n)]
    return {"time": [t.strftime("%Y-%m-%dT%H:%M") for t in times], "temperature_2m": [temp] * n,
            "cloud_cover": [cloud] * n, "wind_speed_10m": [wind] * n, "precipitation": [rain] * n}


class RiskTests(TestCase):
    def night(self, **kw):
        return weather.assess(weather._night(hourly(**kw), NOW))

    def test_hot_cloudy_still_night_is_high(self):
        n = self.night()
        self.assertEqual(n.level, "high")
        self.assertEqual(len(n.reasons), 3)
        self.assertIn("aerators", weather.advice(n))

    def test_two_signs_is_medium_and_none_is_low(self):
        self.assertEqual(self.night(wind=15).level, "medium")
        self.assertEqual(self.night(temp=24, cloud=20, wind=15).level, "low")

    def test_heavy_rain_counts(self):
        self.assertEqual(self.night(temp=24, cloud=90, wind=15, rain=2).level, "medium")   # 12 h × 2 mm

    def test_low_oxygen_this_morning_counts(self):
        from .models import PondAlerts

        n = weather._night(hourly(temp=24, wind=15), NOW)        # cloudy only
        limits = PondAlerts(oxygen_min=D("4"))
        weather.assess(n, limits, [("East", D("4.5")), ("West", D("7"))])
        self.assertEqual(n.level, "medium")
        self.assertEqual(n.low_oxygen_ponds, ["East"])

    def test_the_night_after_midnight_is_the_one_we_are_in(self):
        h = hourly(start=date(2026, 7, 9))
        n = weather._night(h, datetime(2026, 7, 10, 3, 0))
        self.assertEqual(n.starts, datetime(2026, 7, 9, 18, 0))


class FarmWeatherTests(TestCase):
    def setUp(self):
        cache.clear()
        self.b, self.owner, self.staff = make_farm()
        self.client.force_login(self.owner)
        self.cycle = CultureCycle.objects.create(business=self.b, pond=Pond.objects.create(business=self.b, name="East"), start_date=date(2026, 6, 1))

    def locate(self):
        Business.objects.filter(pk=self.b.pk).update(latitude=D("23.17"), longitude=D("89.21"))
        self.b.refresh_from_db()

    def test_no_location_no_forecast(self):
        with mock.patch.object(weather, "urlopen") as op:
            self.assertIsNone(weather.tonight(self.b))
            op.assert_not_called()

    def test_forecast_is_fetched_once_and_kept(self):
        self.locate()
        with mock.patch.object(weather, "urlopen") as op:
            op.return_value.__enter__.return_value.read.return_value = ('{"hourly": %s}' % __import__("json").dumps(hourly())).encode()
            n1 = weather.tonight(self.b, now=NOW)
            n2 = weather.tonight(self.b, now=NOW)
        self.assertEqual(n1.level, "high")
        self.assertEqual(n2.level, "high")
        self.assertEqual(op.call_count, 1)
        url = op.call_args[0][0]
        self.assertIn("latitude=23.1700", url)
        self.assertTrue(url.startswith("https://api.open-meteo.com/"))

    def test_a_failed_fetch_means_no_warning_and_no_retry_storm(self):
        self.locate()
        with mock.patch.object(weather, "urlopen", side_effect=OSError("offline")) as op:
            self.assertIsNone(weather.tonight(self.b, now=NOW))
            self.assertIsNone(weather.tonight(self.b, now=NOW))
        self.assertEqual(op.call_count, 1)

    def test_morning_oxygen_from_running_ponds(self):
        self.locate()
        WaterTest.objects.create(business=self.b, cycle=self.cycle, date=NOW.date(), oxygen=D("3.8"))
        with mock.patch.object(weather, "fetch", return_value=hourly(temp=24, wind=15)):
            n = weather.tonight(self.b, now=NOW)
        self.assertEqual(n.low_oxygen_ponds, ["East"])
        self.assertEqual(n.level, "medium")

    def test_home_card(self):
        url = reverse("business:pond_weather")
        self.assertContains(self.client.get(url), "Get low-oxygen warnings")          # owner can set the location
        self.client.force_login(self.staff)
        self.assertNotContains(self.client.get(url), "Get low-oxygen warnings")       # data entry can't
        self.client.force_login(self.owner)
        self.locate()
        around_now = hourly(start=date.today() - timedelta(days=1), days=3)
        with mock.patch.object(weather, "fetch", return_value=around_now):
            r = self.client.get(url)
        self.assertContains(r, "High risk of low oxygen tonight")
        self.assertContains(r, "Run the aerators")
        self.assertContains(self.client.get(reverse("business:home")), url)

    def test_location_on_the_profile(self):
        url = reverse("business:profile")
        self.assertContains(self.client.get(url), "Use my current location")
        r = self.client.post(url, {"name": "Farm", "latitude": "23.1712345", "longitude": ""})
        self.assertContains(r, "Give both latitude and longitude")
        self.client.post(url, {"name": "Farm", "latitude": "23.1712347", "longitude": "89.2101"})
        self.b.refresh_from_db()
        self.assertEqual(self.b.latitude, D("23.171235"))
        self.assertEqual(self.b.longitude, D("89.2101"))
        r = self.client.post(url, {"name": "Farm", "latitude": "123", "longitude": "89"})
        self.assertContains(r, "between −90 and 90")
