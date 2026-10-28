"""All shortcuts (apps/core/launcher.py): every part of the app as tiles — only what the person may
open — and the app icon's shortcuts, chosen per person and served in the manifest."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.business.core.models import Dashboard, UserDashboardAccess

from . import launcher

PW = "Str0ng-pass-123"


class LauncherTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", "a@example.com", PW)
        self.member = User.objects.create_user("member", "m@example.com", PW)
        UserDashboardAccess.objects.get_or_create(user=self.member, dashboard=Dashboard.objects.get(code="personal"))

    def keys(self, user):
        return [s["key"] for s in launcher.available(user)]

    def test_only_what_the_person_may_open(self):
        self.assertIn("exam", self.keys(self.admin))
        self.assertIn("farm", self.keys(self.admin))
        mine = self.keys(self.member)
        self.assertIn("creditors", mine)
        self.assertNotIn("exam", mine)
        self.assertNotIn("farm", mine)

    def test_the_usual_ones_then_the_persons_own(self):
        self.assertEqual(launcher.chosen(self.member), list(launcher.DEFAULT))
        self.client.force_login(self.member)
        r = self.client.post(reverse("launcher"), {"slot1": "creditors", "slot2": "all", "slot3": "exam", "slot4": "creditors"})
        self.assertRedirects(r, reverse("launcher"))
        self.member.profile.refresh_from_db()
        self.assertEqual(self.member.profile.app_shortcuts, ["creditors", "all"])        # (Exam notes isn't theirs; no repeats)
        self.assertEqual(launcher.chosen(self.member), ["creditors", "all"])

    def test_the_page(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse("launcher"))
        self.assertContains(r, reverse("work:exam"))
        self.assertContains(r, reverse("dashboard"))
        self.assertContains(r, 'name="slot4"')
        self.assertContains(r, '<option value="all" selected>', html=False)

    def test_the_manifest_carries_them(self):
        self.admin.profile.app_shortcuts = ["notes", "exam", "creditors", "all"]
        self.admin.profile.save()
        self.client.force_login(self.admin)
        urls = [s["url"] for s in self.client.get(reverse("manifest")).json()["shortcuts"]]
        self.assertEqual(urls, [reverse("work:notes"), reverse("work:exam"), reverse("dashboard"), reverse("launcher")])

    def test_signed_out_the_usual_ones(self):
        names = [s["name"] for s in self.client.get(reverse("manifest")).json()["shortcuts"]]
        self.assertEqual(names, ["All shortcuts", "New Expense", "Household (Bazar)", "Budgets"])

    def test_the_manifest_is_asked_for_with_the_sign_in(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("launcher")), 'rel="manifest" href="/manifest.webmanifest" crossorigin="use-credentials"', html=False)


class PageSwitchTests(TestCase):
    def test_the_phone_menu_closes_as_soon_as_a_page_is_picked(self):
        from pathlib import Path

        from django.conf import settings

        html = (Path(settings.BASE_DIR) / "templates/base.html").read_text()
        self.assertIn("data-nav-overlay", html)
        self.assertIn('a.closest("[data-nav-overlay], .app-sheet-root")', html)
