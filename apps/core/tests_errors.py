"""Friendly pages when something goes wrong (not found, no access, a form
open too long, a fault on our side), and Django's own messages in Bangla."""
from django.contrib.auth.models import User
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from django.utils import translation
from django.views.defaults import server_error


class ErrorPageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="err_user", password="secret123")

    def test_page_not_found_is_friendly_in_both_languages(self):
        r = self.client.get("/no-such-page/")
        self.assertContains(r, "couldn't find that page", status_code=404)
        self.client.force_login(self.user)
        r = self.client.get("/no-such-page/")
        self.assertContains(r, "couldn't find that page", status_code=404)
        self.assertContains(r, f'href="{reverse("home")}"', status_code=404)
        self.client.post(reverse("update_preferences"), {"language": "bn"})
        self.assertContains(self.client.get("/no-such-page/"), "পাতাটি খুঁজে পাওয়া যায়নি", status_code=404)

    def test_page_not_found_inside_the_farm(self):
        from apps.business.core.testing import make_farm

        _b, owner, _staff = make_farm()
        self.client.force_login(owner)
        self.assertContains(self.client.get("/business/no-such-page/"), "couldn't find that page", status_code=404)

    def test_no_access_page(self):
        self.client.force_login(self.user)
        r = self.client.get(reverse("backup_home"))
        self.assertContains(r, "isn't open to you", status_code=403)

    def test_a_form_open_too_long_explains_what_to_do(self):
        browser = Client(enforce_csrf_checks=True)
        r = browser.post(reverse("login"), {"username": "err_user", "password": "secret123"})
        self.assertContains(r, "refresh the page, and save once more", status_code=403)
        with translation.override("bn"):
            r = browser.post(reverse("login"), {"username": "x"}, HTTP_ACCEPT_LANGUAGE="bn")
        self.assertEqual(r.status_code, 403)

    def test_server_error_page_stands_alone(self):
        request = RequestFactory().get("/")
        with translation.override("en"):
            r = server_error(request)
        self.assertEqual(r.status_code, 500)
        self.assertIn("Something went wrong on our side", r.content.decode())
        with translation.override("bn"):
            self.assertIn("আমাদের দিকে কিছু একটা সমস্যা হয়েছে", server_error(request).content.decode())


class DjangoMessagesInBanglaTests(TestCase):
    def test_sign_in_and_password_messages(self):
        from django import forms
        from django.contrib.auth import password_validation
        from django.contrib.auth.forms import AuthenticationForm
        from django.core.exceptions import ValidationError

        with translation.override("bn"):
            self.assertIn("সঠিক", str(AuthenticationForm.error_messages["invalid_login"]))
            with self.assertRaises(ValidationError) as caught:
                password_validation.validate_password("123")
            self.assertIn("পাসওয়ার্ডটি খুব ছোট। অন্তত 8 অক্ষর হতে হবে।", caught.exception.messages)
            with self.assertRaises(ValidationError) as caught:
                forms.DecimalField(max_digits=5, decimal_places=2).clean("123456")
            self.assertEqual(caught.exception.messages, ["মোট 5 অঙ্কের বেশি লেখা যাবে না।"])

    def test_wrong_password_in_bangla(self):
        User.objects.create_user(username="bn_user", password="secret123")
        self.client.cookies["django_language"] = "bn"
        r = self.client.post(reverse("login"), {"username": "bn_user", "password": "wrong"})
        self.assertContains(r, "ও পাসওয়ার্ড দিন")
