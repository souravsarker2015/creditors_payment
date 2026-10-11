"""Signing in (remember me, username or email), signing up with an email,
the account page, and resetting a forgotten password by email."""
import re

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

PW = "Str0ng-pass-123"


class LoginTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("rahim", "rahim@example.com", PW)

    def test_remember_me_keeps_the_sign_in_for_30_days(self):
        self.client.post(reverse("login"), {"username": "rahim", "password": PW, "remember_me": "on"})
        self.assertFalse(self.client.session.get_expire_at_browser_close())
        self.assertEqual(self.client.session.get_expiry_age(), 60 * 60 * 24 * 30)

    def test_without_remember_me_it_ends_with_the_browser(self):
        self.client.post(reverse("login"), {"username": "rahim", "password": PW})
        self.assertIn("_auth_user_id", self.client.session)
        self.assertTrue(self.client.session.get_expire_at_browser_close())

    def test_the_box_is_ticked_by_default(self):
        r = self.client.get(reverse("login"))
        self.assertContains(r, 'name="remember_me"')
        self.assertRegex(r.content.decode(), r'name="remember_me"[^>]*checked')
        self.assertContains(r, reverse("password_reset"))

    def test_sign_in_with_email_any_case(self):
        r = self.client.post(reverse("login"), {"username": "Rahim@Example.com", "password": PW})
        self.assertRedirects(r, reverse("home"), fetch_redirect_response=False)

    def test_email_shared_by_two_accounts_cant_sign_in(self):
        User.objects.create_user("rahim2", "rahim@example.com", PW)
        r = self.client.post(reverse("login"), {"username": "rahim@example.com", "password": PW})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        # The usernames still work.
        self.assertEqual(self.client.post(reverse("login"), {"username": "rahim2", "password": PW}).status_code, 302)

    def test_goes_back_to_the_page_that_asked(self):
        r = self.client.post(reverse("login") + "?next=/wallets/", {"username": "rahim", "password": PW, "next": "/wallets/"})
        self.assertRedirects(r, "/wallets/", fetch_redirect_response=False)
        self.client.logout()
        r = self.client.post(reverse("login"), {"username": "rahim", "password": PW, "next": "https://evil.example/"})
        self.assertRedirects(r, reverse("home"), fetch_redirect_response=False)


class SignupTests(TestCase):
    def test_email_is_needed_and_must_be_free(self):
        User.objects.create_user("taken", "used@example.com", PW)
        data = {"username": "karim", "password1": PW, "password2": PW}
        self.assertEqual(self.client.post(reverse("signup"), data).status_code, 200)
        r = self.client.post(reverse("signup"), {**data, "email": "USED@example.com"})
        self.assertContains(r, "already exists")
        r = self.client.post(reverse("signup"), {**data, "email": "karim@example.com"})
        self.assertRedirects(r, reverse("home"), fetch_redirect_response=False)
        self.assertEqual(User.objects.get(username="karim").email, "karim@example.com")


class AccountPageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("rahim", "", PW)
        self.client.force_login(self.user)

    def test_adding_an_email_needs_the_password(self):
        url = reverse("account_settings")
        self.assertContains(self.client.get(url), "Add your email")
        r = self.client.post(url, {"action": "email", "email-email": "r@example.com", "email-password": "wrong"})
        self.assertContains(r, "That password isn")
        self.client.post(url, {"action": "email", "email-email": "r@example.com", "email-password": PW})
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "r@example.com")

    def test_email_used_by_another_account(self):
        User.objects.create_user("other", "x@example.com", PW)
        r = self.client.post(reverse("account_settings"), {"action": "email", "email-email": "X@example.com", "email-password": PW})
        self.assertContains(r, "Another account already uses this email")

    def test_change_password_stays_signed_in_and_sends_a_notice(self):
        self.user.email = "r@example.com"
        self.user.save()
        new = "N3w-pass-456!"
        r = self.client.post(reverse("account_settings"), {"action": "password", "pw-old_password": PW, "pw-new_password1": new, "pw-new_password2": new})
        self.assertRedirects(r, reverse("account_settings") + "#password", fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(new))
        self.assertEqual(self.client.get(reverse("account_settings")).status_code, 200)   # still signed in
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("account was changed on", mail.outbox[0].body)

    def test_needs_sign_in(self):
        self.client.logout()
        r = self.client.get(reverse("account_settings"))
        self.assertRedirects(r, reverse("login") + "?next=" + reverse("account_settings"), fetch_redirect_response=False)


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "reset-tests"}})
class PasswordResetTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("rahim", "rahim@example.com", PW)

    def _link(self, message):
        return re.search(r"https?://[^/\s]+(/accounts/password/reset/\S+/)", message.body).group(1)

    def test_full_reset_by_email(self):
        r = self.client.post(reverse("password_reset"), {"email": "RAHIM@example.com"})
        self.assertRedirects(r, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ["rahim@example.com"])
        self.assertIn("rahim", msg.body)          # it reminds them of the username too
        self.assertTrue(msg.alternatives)          # and has an HTML version
        r = self.client.get(self._link(msg), follow=True)
        self.assertContains(r, "Set a new password")
        new = "N3w-pass-456!"
        r = self.client.post(r.redirect_chain[-1][0], {"new_password1": new, "new_password2": new})
        self.assertRedirects(r, reverse("password_reset_complete"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(new))
        self.assertEqual(len(mail.outbox), 2)      # the "password was changed" notice
        # The link works only once.
        self.assertContains(self.client.get(self._link(msg), follow=True), "doesn't work any more")

    def test_unknown_email_looks_the_same_and_sends_nothing(self):
        r = self.client.post(reverse("password_reset"), {"email": "nobody@example.com"})
        self.assertRedirects(r, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)

    def test_at_most_three_emails_an_hour_to_one_address(self):
        for _ in range(5):
            self.client.post(reverse("password_reset"), {"email": "rahim@example.com"})
        self.assertEqual(len(mail.outbox), 3)

    def test_bangla_email(self):
        self.client.cookies["django_language"] = "bn"
        self.client.post(reverse("password_reset"), {"email": "rahim@example.com"}, HTTP_ACCEPT_LANGUAGE="bn")
        self.assertIn("পাসওয়ার্ড", mail.outbox[0].subject)
