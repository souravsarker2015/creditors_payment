"""Addresses and values that can't mean anything: never a crash, and never quietly hiding a real fault."""

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.business.core.models import Dashboard, UserDashboardAccess
from apps.core.dates import parse_date
from apps.productivity.access import CODE
from apps.productivity.models import Goal, GoalStatus

User = get_user_model()


class BadAddressTests(TestCase):
    def setUp(self):
        self.client.raise_request_exception = False
        self.user = User.objects.create_user("rahim", password="pw")
        self.client.force_login(self.user)

    def test_impossible_filters_are_a_page_not_found(self):
        for url in ("/expense/expenses/?year=99999", "/income/dashboard/?year=99999"):
            with self.subTest(url=url):
                self.assertContains(self.client.get(url), "couldn't find that page", status_code=404)

    def test_impossible_months_stay_on_the_report(self):
        for month in ("0001-01", "9999-12", "2026-13", "abc"):
            with self.subTest(month=month):
                self.assertEqual(self.client.get(reverse("money_report"), {"month": month}).status_code, 200)

    def test_a_month_with_an_impossible_year(self):
        self.assertEqual(self.client.get("/household/purchases/1/1/").status_code, 404)

    def test_an_impossible_date_is_no_date(self):
        self.assertIsNone(parse_date("2026-13-45"))
        self.assertIsNone(parse_date(None))
        self.assertEqual(str(parse_date("2026-02-03")), "2026-02-03")

    def test_the_api_answers_in_json(self):
        UserDashboardAccess.objects.get_or_create(user=self.user, dashboard=Dashboard.objects.get(code=CODE))
        goal = Goal.objects.create(owner=self.user, title="Run", start_value=0, target_value=10)
        r = self.client.post(reverse("work:api_goal_value", args=[goal.pk]), {"value": "NaN"})
        self.assertEqual((r.status_code, r.json()["ok"]), (400, False))

    def test_a_goal_with_no_number_has_a_progress(self):
        self.assertEqual(Goal(owner=self.user, title="Read", status=GoalStatus.ACTIVE).progress(), 0)

    def test_nothing_is_swallowed_without_a_trace(self):
        with self.assertLogs("django.request", "WARNING") as logs:
            self.client.get("/expense/expenses/?year=99999")
        self.assertIn("Couldn't read a request", logs.output[0])

    @override_settings(ROOT_URLCONF="apps.core.tests.test_bad_input")
    def test_a_fault_on_a_plain_page_is_still_a_fault(self):
        self.assertEqual(self.client.get("/boom/").status_code, 500)

    @override_settings(ROOT_URLCONF="apps.core.tests.test_bad_input")
    def test_only_reading_errors_are_excused(self):
        self.assertEqual(self.client.get("/oops/?a=1").status_code, 500)


def _boom(request):
    raise ValueError("a real fault")


def _oops(request):
    raise KeyError("a real fault")


from django.urls import path  # noqa: E402

urlpatterns = [path("boom/", _boom), path("oops/", _oops)]
