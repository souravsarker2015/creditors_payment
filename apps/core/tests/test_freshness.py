"""Lists never show a copy from before your last save: the data-version cookie and page stamp."""
from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.expense.models import ExpenseCategory


class FreshnessTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("me", password="pw12345!")
        self.client.force_login(self.user)
        self.cat = ExpenseCategory.objects.create(user=self.user, name="Food")

    def add(self, **extra):
        data = {"category": self.cat.pk, "amount": "120", "date": date.today().isoformat()}
        data.update(extra)
        return self.client.post(reverse("expense_create"), data)

    def test_a_save_bumps_the_version_and_drops_prefetched_pages(self):
        r = self.add()
        self.assertEqual(r.status_code, 302)
        self.assertIn("ftv", r.cookies)
        self.assertEqual(r["Clear-Site-Data"], '"prefetchCache", "prerenderCache"')
        first = r.cookies["ftv"].value
        second = self.add().cookies["ftv"].value
        self.assertNotEqual(first, second)

    def test_a_form_shown_again_with_errors_changes_nothing(self):
        r = self.add(amount="")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("ftv", r.cookies)
        self.assertFalse(r.has_header("Clear-Site-Data"))

    def test_reading_never_bumps_it(self):
        r = self.client.get(reverse("expense_list"))
        self.assertNotIn("ftv", r.cookies)

    def test_every_page_is_stamped_with_the_version_it_was_built_from(self):
        version = self.add().cookies["ftv"].value
        r = self.client.get(reverse("expense_list"))
        self.assertContains(r, f'var page = "{version}"')

    def test_background_saves_count_too(self):
        r = self.client.post(reverse("trash_empty"))          # a redirect
        self.assertIn("ftv", r.cookies)
