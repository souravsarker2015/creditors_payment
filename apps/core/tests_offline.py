"""Works without internet: saves sent again are never saved twice, the phone's
queue gets short answers, and only safe pages are kept on the phone."""
import json
from datetime import date

from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from apps.core.models import OfflineReceipt
from apps.expense.models import Expense

REPLAY = {"HTTP_X_FT_REPLAY": "1"}


class KeyedSaveTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="off_user", password="secret123")
        self.client.force_login(self.user)
        self.url = reverse("expense_create")

    def data(self, key, **extra):
        return {"amount": "120", "date": "2026-10-07", "_ft_key": key, "_ft_user": str(self.user.pk), **extra}

    def test_the_same_entry_sent_twice_is_saved_once(self):
        first = self.client.post(self.url, self.data("k-1"))
        second = self.client.post(self.url, self.data("k-1"))
        self.assertEqual(Expense.objects.filter(user=self.user).count(), 1)
        self.assertEqual(first.status_code, 302)
        self.assertRedirects(second, first["Location"], fetch_redirect_response=False)
        # A new key is a new entry.
        self.client.post(self.url, self.data("k-2"))
        self.assertEqual(Expense.objects.filter(user=self.user).count(), 2)

    def test_the_queue_gets_short_answers(self):
        r = self.client.post(self.url, self.data("q-1"), **REPLAY)
        self.assertEqual(r.json()["ok"], True)
        self.assertEqual(r.json()["why"], "saved")
        r = self.client.post(self.url, self.data("q-1"), **REPLAY)
        self.assertEqual((r.json()["ok"], r.json()["why"]), (True, "already"))
        self.assertEqual(Expense.objects.filter(user=self.user).count(), 1)
        # The "Expense added" message isn't left waiting for the next page.
        self.assertEqual(len(list(get_messages(r.wsgi_request))), 0)

    def test_an_entry_with_a_mistake_can_be_fixed_and_sent_again(self):
        r = self.client.post(self.url, self.data("bad", amount=""), **REPLAY)
        self.assertEqual(r.json(), {"ok": False, "why": "fix", "location": ""})
        self.assertFalse(OfflineReceipt.objects.filter(key="bad").exists())
        r = self.client.post(self.url, self.data("bad", amount="55"), **REPLAY)
        self.assertTrue(r.json()["ok"])
        self.assertTrue(Expense.objects.filter(user=self.user, amount=55).exists())

    def test_an_entry_made_by_another_account_is_never_saved_here(self):
        r = self.client.post(self.url, {**self.data("x-1"), "_ft_user": "99999"}, **REPLAY)
        self.assertEqual(r.json()["why"], "other-user")
        self.assertFalse(Expense.objects.filter(user=self.user).exists())

    def test_signed_out_entries_wait_for_sign_in(self):
        self.client.logout()
        r = self.client.post(self.url, self.data("s-1"), **REPLAY)
        # Not signed in: the key isn't checked; the sign-in page answers and the phone keeps the entry.
        self.assertIn(r.status_code, (302, 403))
        self.assertFalse(Expense.objects.exists())

    def test_a_background_save_counts_as_saved(self):
        from apps.business.calendar.models import CalendarEvent
        from apps.business.core.testing import make_farm

        b, owner, _staff = make_farm()
        self.client.force_login(owner)
        e = CalendarEvent.objects.create(business=b, title="Lime", date=date(2026, 10, 7), category="task")
        url = reverse("business:calendar_done", args=[e.pk])
        fields = {"_ft_key": "tick-1", "_ft_user": str(owner.pk), "_ft_page": "/business/calendar/"}
        self.assertTrue(self.client.post(url, fields, **REPLAY).json()["ok"])
        self.assertTrue(self.client.post(url, fields, **REPLAY).json()["ok"])
        e.refresh_from_db()
        self.assertTrue(e.done)   # ticked once, not ticked and unticked


class KeptPagesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="kept_user", password="secret123")
        self.client.force_login(self.user)

    def test_pages_are_marked_safe_to_keep_but_not_sign_in_or_downloads(self):
        self.assertEqual(self.client.get(reverse("home"))["X-FT-Offline"], "1")
        self.assertEqual(self.client.get(reverse("expense_list"), HTTP_HX_REQUEST="true").get("X-FT-Offline"), "1")
        self.assertIsNone(self.client.get(reverse("expense_list"), {"export": "csv"}).get("X-FT-Offline"))
        self.client.logout()
        self.assertIsNone(self.client.get(reverse("login")).get("X-FT-Offline"))

    def test_the_page_list_covers_the_whole_app(self):
        data = self.client.get(reverse("offline_pages")).json()
        everyday = [p["url"] for p in data["pages"]]
        self.assertIn(reverse("expense_create"), everyday)
        self.assertIn(reverse("pick", args=["borrow"]), everyday)
        more = data["more"]
        for name in ("income_dashboard", "goal_list", "wallet_list", "zakat", "help", "budget_list"):
            self.assertIn(reverse(name), more)
        for name in ("logout", "creditor_import", "my_data", "trash_empty", "backup_home"):
            self.assertNotIn(reverse(name), more + everyday)
        # No farm pages for someone without the farm.
        self.assertFalse([u for u in more if u.startswith("/business/")])
        # Every page on the list opens and may be kept.
        for url in everyday + more:
            r = self.client.get(url)
            self.assertEqual((url, r.status_code, r.get("X-FT-Offline")), (url, 200, "1"))

    def test_farm_staff_get_the_farm_pages(self):
        from apps.business.core.access import PERSONAL
        from apps.business.core.models import UserDashboardAccess
        from apps.business.core.testing import make_farm

        _b, _owner, staff = make_farm()
        UserDashboardAccess.objects.filter(user=staff, dashboard__code=PERSONAL).delete()
        self.client.force_login(staff)
        data = self.client.get(reverse("offline_pages")).json()
        urls = [p["url"] for p in data["pages"]] + data["more"]
        self.assertIn(reverse("business:feed_usage_bulk"), urls)
        self.assertNotIn(reverse("home"), urls)

    def test_signing_out_clears_kept_pages(self):
        r = self.client.get(reverse("logout"))
        self.assertIn('"cache"', r["Clear-Site-Data"])

    def test_settings_page_and_menu_link(self):
        r = self.client.get(reverse("offline_settings"))
        self.assertContains(r, "Save everything now")
        self.assertContains(self.client.get(reverse("home")), reverse("offline_settings"))
        self.client.logout()
        self.assertEqual(self.client.get(reverse("offline_settings")).status_code, 302)

    def test_service_worker_keeps_pages_and_the_outbox(self):
        sw = self.client.get(reverse("service_worker")).content.decode()
        for part in ("ftpages-v1", "fintrack-offline", "Response.redirect", "X-FT-Offline", "ft-cached", "warm"):
            self.assertIn(part, sw)
        page = self.client.get(reverse("home")).content.decode()
        self.assertIn("js/offline.js", page)
        self.assertIn(f'data-user="{self.user.pk}"', page)
        self.assertIn("window.FT_OFFLINE_TEXT", page)

    def test_offline_page_lists_what_is_ready(self):
        r = self.client.get(reverse("offline"))
        self.assertContains(r, "ft-offline-index")
        self.assertContains(r, "Ready to use without signal")
        json.dumps({})  # keep the import used
