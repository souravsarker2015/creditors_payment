"""Where you're signed in: every device with the account open, signing them
out, and the email when a new device signs in."""
from django.contrib.auth.models import User
from django.contrib.sessions.models import Session
from django.core import mail
from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

from . import signins
from .models import SignIn

PW = "Str0ng-pass-123"
PHONE = "Mozilla/5.0 (Linux; Android 14; SM-A146) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Mobile Safari/537.36"
LAPTOP = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36 Edg/129.0"


class SignInTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("rahim", "rahim@example.com", PW)

    def sign_in(self, ua=PHONE, client=None):
        c = client or Client(HTTP_USER_AGENT=ua)
        r = c.post(reverse("login"), {"username": "rahim", "password": PW, "remember_me": "on"})
        self.assertEqual(r.status_code, 302)
        return c

    def test_describe(self):
        self.assertEqual(signins.describe(PHONE), "Chrome on Android")
        self.assertEqual(signins.describe(LAPTOP), "Edge on Windows")
        self.assertEqual(signins.describe("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605 Version/17.0 Mobile/15E148 Safari/604.1"), "Safari on iPhone")
        self.assertEqual(signins.describe(""), "Unknown device")

    def test_each_sign_in_is_listed(self):
        phone = self.sign_in(PHONE)
        self.sign_in(LAPTOP)
        r = phone.get(reverse("account_settings"))
        rows = r.context["sign_ins"]
        self.assertEqual([s.label for s in rows], ["Chrome on Android", "Edge on Windows"])
        self.assertTrue(rows[0].is_current)
        self.assertTrue(rows[0].phone)
        self.assertContains(r, "Where you're signed in")
        self.assertContains(r, "This device")
        self.assertContains(r, "Sign out everywhere else")

    def test_first_sign_in_sends_no_email_a_new_device_does(self):
        phone = self.sign_in(PHONE)
        self.assertEqual(len(mail.outbox), 0)                      # nothing to compare with yet
        phone.post(reverse("logout"))
        self.sign_in(PHONE, client=phone)                         # same device again: known
        self.assertEqual(len(mail.outbox), 0)
        self.sign_in(LAPTOP)                                      # a device never used before
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, "New sign-in to your FinTrack account")
        self.assertIn("Edge on Windows", mail.outbox[0].body)
        self.assertIn(reverse("account_settings"), mail.outbox[0].body)

    def test_signing_up_sends_no_new_device_email(self):
        c = Client(HTTP_USER_AGENT=PHONE)
        r = c.post(reverse("signup"), {"username": "karim", "email": "karim@example.com", "password1": PW, "password2": PW})
        self.assertRedirects(r, reverse("home"), fetch_redirect_response=False)
        self.assertEqual(SignIn.objects.filter(user__username="karim").count(), 1)
        self.assertIn(signins.DEVICE_COOKIE, r.cookies)
        self.assertEqual(len(mail.outbox), 0)

    def test_sign_out_another_device(self):
        phone = self.sign_in(PHONE)
        laptop = self.sign_in(LAPTOP)
        other = SignIn.objects.get(user_agent=LAPTOP)
        r = phone.post(reverse("sign_out_device", args=[other.pk]), follow=True)
        self.assertContains(r, "That device is signed out")
        self.assertEqual(len(r.context["sign_ins"]), 1)
        self.assertRedirects(laptop.get(reverse("account_settings")), reverse("login") + "?next=" + reverse("account_settings"))
        SignIn.objects.get(pk=other.pk).ended_at                   # kept in the history
        self.assertEqual(len(phone.get(reverse("account_settings")).context["recent_sign_ins"]), 2)

    def test_sign_out_everywhere_else(self):
        phone = self.sign_in(PHONE)
        laptop = self.sign_in(LAPTOP)
        third = self.sign_in(LAPTOP)
        r = phone.post(reverse("sign_out_others"), follow=True)
        self.assertContains(r, "Signed out everywhere else (2)")
        for c in (laptop, third):
            self.assertEqual(c.get(reverse("account_settings")).status_code, 302)
        self.assertEqual(phone.get(reverse("account_settings")).status_code, 200)

    def test_sessions_from_before_are_picked_up_and_signed_out(self):
        old = Client(HTTP_USER_AGENT=LAPTOP)
        old.force_login(self.user)                                 # no row: signed in before rows were kept
        phone = self.sign_in(PHONE)
        self.assertEqual(SignIn.objects.count(), 1)
        old.get(reverse("account_settings"))                       # seen: gets a row, no email
        self.assertEqual(SignIn.objects.count(), 2)
        self.assertEqual(len(mail.outbox), 0)
        r = phone.post(reverse("sign_out_others"), follow=True)
        self.assertContains(r, "Signed out everywhere else (1)")
        self.assertEqual(old.get(reverse("account_settings")).status_code, 302)

    def test_signing_out_ends_the_row(self):
        phone = self.sign_in(PHONE)
        phone.post(reverse("logout"))
        self.assertIsNotNone(SignIn.objects.get().ended_at)

    def test_signing_out_this_device_from_the_list(self):
        phone = self.sign_in(PHONE)
        mine = SignIn.objects.get()
        r = phone.post(reverse("sign_out_device", args=[mine.pk]))
        self.assertRedirects(r, reverse("login"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", phone.session)

    def test_a_password_change_drops_other_devices_from_the_list(self):
        phone = self.sign_in(PHONE)
        self.sign_in(LAPTOP)
        phone.post(reverse("account_settings"), {"action": "password", "pw-old_password": PW,
                                                 "pw-new_password1": "An0ther-pass-456", "pw-new_password2": "An0ther-pass-456"})
        self.assertEqual([s.label for s in phone.get(reverse("account_settings")).context["sign_ins"]], ["Chrome on Android"])

    def test_cannot_touch_someone_elses_sign_in(self):
        self.sign_in(PHONE)
        theirs = SignIn.objects.get()
        intruder = User.objects.create_user("x", "x@example.com", PW)
        c = Client()
        c.force_login(intruder)
        c.post(reverse("sign_out_device", args=[theirs.pk]))
        self.assertIsNone(SignIn.objects.get(pk=theirs.pk).ended_at)
        self.assertTrue(Session.objects.filter(session_key=theirs.session_key).exists())

    def test_get_does_nothing(self):
        phone = self.sign_in(PHONE)
        self.assertEqual(phone.get(reverse("sign_out_others")).status_code, 405)
