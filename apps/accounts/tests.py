from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import BackgroundTheme, UserProfile


class BackgroundPreferenceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("owner", password="pw12345!")
        self.client.login(username="owner", password="pw12345!")

    def save(self, **data):
        return self.client.post(reverse("update_preferences"), data, HTTP_X_PREFERENCES_FETCH="1")

    def test_defaults_to_warm_paper(self):
        self.assertEqual(UserProfile.objects.get(user=self.user).background, BackgroundTheme.PAPER)

    def test_saves_a_valid_background(self):
        response = self.save(background="notepad")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(UserProfile.objects.get(user=self.user).background, "notepad")

    def test_ignores_an_unknown_background(self):
        self.save(background="neon")
        self.assertEqual(UserProfile.objects.get(user=self.user).background, BackgroundTheme.PAPER)

    def test_page_carries_the_choice_and_offers_every_option(self):
        self.save(background="honeydew")
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, 'data-bg="honeydew"')
        for value in BackgroundTheme.values:
            self.assertContains(response, f'data-bg-choice="{value}"')


class BanglaTranslationTests(TestCase):
    def test_tooltips_render_in_bangla(self):
        User.objects.create_user("owner", password="pw12345!")
        self.client.login(username="owner", password="pw12345!")
        self.client.post(reverse("update_preferences"), {"language": "bn"})
        response = self.client.get(reverse("creditor_list"))
        # data-tip tooltip, ⓘ explainer, and a background option label
        self.assertContains(response, "একসাথে অনেকগুলো যোগ করতে একটি .csv ফাইল আপলোড করুন।")
        self.assertContains(response, "এই মোট হিসাব আপনার অনুসন্ধান")
        self.assertContains(response, "নোটপ্যাড হলুদ")
        # module-level sort labels are lazy, so they follow the language too
        self.assertContains(response, "নাম (A–Z)")
