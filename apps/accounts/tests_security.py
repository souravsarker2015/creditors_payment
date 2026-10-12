"""Two-step sign-in (authenticator app), the admin's security rule, the
profile, and admins managing people."""
import re

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from apps.business.core.models import Dashboard, UserDashboardAccess

from . import totp
from .models import SecuritySettings, TwoFactor, TwoFactorPolicy

PW = "Str0ng-pass-123"


def current_code(secret, offset=0):
    return totp.code_at(secret, totp.current_step() + offset)


class TwoFactorSetupTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("rahim", "rahim@example.com", PW)
        self.client.force_login(self.user)

    def _turn_on(self):
        self.client.get(reverse("two_factor_setup"))
        secret = self.client.session["2fa_setup_secret"]
        r = self.client.post(reverse("two_factor_setup"), {"code": current_code(secret)})
        return secret, r

    def test_setup_shows_a_qr_and_turns_on_with_a_right_code(self):
        r = self.client.get(reverse("two_factor_setup"))
        self.assertContains(r, "otpauth://totp/FinTrack:rahim%40example.com?secret=")
        secret = self.client.session["2fa_setup_secret"]
        r = self.client.post(reverse("two_factor_setup"), {"code": "000000" if current_code(secret) != "000000" else "111111"})
        self.assertContains(r, "That code isn")
        self.assertFalse(TwoFactor.objects.filter(user=self.user, enabled=True).exists())
        secret, r = self._turn_on()
        codes = re.findall(r"<code>([a-z2-9]{5}-[a-z2-9]{5})</code>", r.content.decode())
        self.assertEqual(len(codes), 10)
        tf = TwoFactor.objects.get(user=self.user)
        self.assertTrue(tf.enabled)
        self.assertEqual(tf.recovery_left, 10)
        self.assertNotIn(codes[0], str(tf.recovery_codes))      # only hashes are kept
        self.assertIn("Two-step sign-in is on", mail.outbox[-1].subject)

    def test_sign_in_needs_the_code_after_the_password(self):
        secret, _r = self._turn_on()
        self.client.logout()
        r = self.client.post(reverse("login"), {"username": "rahim", "password": PW, "remember_me": "on", "next": "/wallets/"})
        self.assertRedirects(r, reverse("two_factor_verify"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)      # not signed in yet
        self.assertEqual(self.client.get(reverse("home")).status_code, 302)
        r = self.client.post(reverse("two_factor_verify"), {"code": "12345"})
        self.assertContains(r, "That code isn")
        # The code from the step just used for setup can't be used again; the next one works.
        r = self.client.post(reverse("two_factor_verify"), {"code": current_code(secret, 1)})
        self.assertRedirects(r, "/wallets/", fetch_redirect_response=False)
        self.assertIn("_auth_user_id", self.client.session)
        self.assertFalse(self.client.session.get_expire_at_browser_close())   # remember me carried through

    def test_recovery_code_works_once(self):
        _secret, r = self._turn_on()
        code = re.findall(r"<code>([a-z2-9]{5}-[a-z2-9]{5})</code>", r.content.decode())[0]
        self.client.logout()
        self.client.post(reverse("login"), {"username": "rahim", "password": PW})
        r = self.client.post(reverse("two_factor_verify"), {"code": code.upper()})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(TwoFactor.objects.get(user=self.user).recovery_left, 9)
        self.assertIn("recovery code was used", mail.outbox[-1].subject)
        self.client.logout()
        self.client.post(reverse("login"), {"username": "rahim", "password": PW})
        self.assertContains(self.client.post(reverse("two_factor_verify"), {"code": code}), "That code isn")

    def test_too_many_wrong_codes_starts_again(self):
        self._turn_on()
        self.client.logout()
        self.client.post(reverse("login"), {"username": "rahim", "password": PW})
        for _ in range(5):
            r = self.client.post(reverse("two_factor_verify"), {"code": "999999"})
        self.assertRedirects(r, reverse("login"), fetch_redirect_response=False)
        self.assertRedirects(self.client.get(reverse("two_factor_verify")), reverse("login"), fetch_redirect_response=False)

    def test_trusted_device_skips_the_code_until_forgotten(self):
        secret, _r = self._turn_on()
        self.client.logout()
        self.client.post(reverse("login"), {"username": "rahim", "password": PW})
        self.client.post(reverse("two_factor_verify"), {"code": current_code(secret, 1), "trust": "on"})
        trust = self.client.cookies["ft_2fa_trust"].value

        def sign_out():   # the test client's logout() drops every cookie; a browser keeps this one
            self.client.logout()
            self.client.cookies["ft_2fa_trust"] = trust

        sign_out()
        r = self.client.post(reverse("login"), {"username": "rahim", "password": PW})
        self.assertRedirects(r, reverse("home"), fetch_redirect_response=False)   # no code asked
        self.client.post(reverse("two_factor_forget_devices"))
        sign_out()
        r = self.client.post(reverse("login"), {"username": "rahim", "password": PW})
        self.assertRedirects(r, reverse("two_factor_verify"), fetch_redirect_response=False)

    def test_turning_off_needs_password_and_code(self):
        secret, _r = self._turn_on()
        r = self.client.post(reverse("two_factor_disable"), {"password": "wrong", "code": current_code(secret, 1)})
        self.assertContains(r, "That password isn")
        r = self.client.post(reverse("two_factor_disable"), {"password": PW, "code": current_code(secret, 1)})
        self.assertFalse(TwoFactor.objects.filter(user=self.user).exists())
        self.client.logout()
        r = self.client.post(reverse("login"), {"username": "rahim", "password": PW})
        self.assertRedirects(r, reverse("home"), fetch_redirect_response=False)

    def test_new_recovery_codes_replace_the_old(self):
        secret, r = self._turn_on()
        old = re.findall(r"<code>([a-z2-9]{5}-[a-z2-9]{5})</code>", r.content.decode())
        r = self.client.post(reverse("two_factor_recovery"), {"code": current_code(secret, 1)})
        new = re.findall(r"<code>([a-z2-9]{5}-[a-z2-9]{5})</code>", r.content.decode())
        self.assertEqual(len(new), 10)
        self.assertFalse(set(old) & set(new))
        tf = TwoFactor.objects.get(user=self.user)
        self.assertNotIn(totp.hash_code(old[0]), tf.recovery_codes)

    def test_django_admin_login_goes_through_the_app(self):
        self.client.logout()
        r = self.client.get("/admin/login/?next=/admin/")
        self.assertRedirects(r, reverse("login") + "?next=%2Fadmin%2F", fetch_redirect_response=False)


class PolicyTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("boss", "boss@example.com", PW)
        self.member = User.objects.create_user("worker", "w@example.com", PW)

    def test_required_for_admins_sends_them_to_set_up(self):
        SecuritySettings.objects.create(pk=1, two_factor=TwoFactorPolicy.ADMINS)
        self.client.force_login(self.admin)
        r = self.client.get(reverse("home"))
        self.assertRedirects(r, reverse("two_factor_setup") + "?required=1", fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse("two_factor_setup") + "?required=1"), "Your admin requires two-step sign-in")
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)   # not required for others

    def test_only_admins_change_the_rule(self):
        self.client.force_login(self.member)
        self.assertNotContains(self.client.get(reverse("account_settings")), 'name="policy-two_factor"')
        self.client.post(reverse("account_settings"), {"action": "policy", "policy-two_factor": "everyone"})
        self.assertEqual(SecuritySettings.load().two_factor, TwoFactorPolicy.OPTIONAL)
        self.client.force_login(self.admin)
        self.client.post(reverse("account_settings"), {"action": "policy", "policy-two_factor": "everyone"})
        self.assertEqual(SecuritySettings.load().two_factor, TwoFactorPolicy.EVERYONE)


class ProfileTests(TestCase):
    def test_name_username_and_phone(self):
        user = User.objects.create_user("rahim", "", PW)
        User.objects.create_user("taken", "", PW)
        self.client.force_login(user)
        r = self.client.post(reverse("account_settings"), {"action": "profile", "profile-first_name": "Rahim", "profile-last_name": "Uddin",
                                                           "profile-username": "TAKEN", "profile-phone": ""})
        self.assertContains(r, "That username is taken")
        self.client.post(reverse("account_settings"), {"action": "profile", "profile-first_name": "Rahim", "profile-last_name": "Uddin",
                                                       "profile-username": "rahim.uddin", "profile-phone": "01711000000"})
        user.refresh_from_db()
        self.assertEqual((user.get_full_name(), user.username, user.profile.phone), ("Rahim Uddin", "rahim.uddin", "01711000000"))


class PeopleAdminTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("boss", "boss@example.com", PW)
        self.client.force_login(self.admin)

    def test_only_admins(self):
        member = User.objects.create_user("worker", "", PW)
        self.client.force_login(member)
        self.assertEqual(self.client.get(reverse("user_list")).status_code, 302)
        self.assertEqual(self.client.post(reverse("user_create"), {}).status_code, 302)

    def test_admin_creates_another_admin(self):
        r = self.client.post(reverse("user_create"), {
            "username": "second", "first_name": "Second", "last_name": "Admin", "email": "s@example.com", "is_active": "on",
            "is_admin": "on", "dashboards": ["personal"], "password_mode": "set", "password1": PW, "password2": PW})
        new = User.objects.get(username="second")
        self.assertRedirects(r, reverse("user_edit", args=[new.pk]), fetch_redirect_response=False)
        self.assertTrue(new.is_superuser and new.is_staff and new.check_password(PW))
        self.assertTrue(UserDashboardAccess.objects.filter(user=new, dashboard__code="personal", is_default=True).exists())

    def test_create_with_an_emailed_link(self):
        self.client.post(reverse("user_create"), {
            "username": "karim", "email": "k@example.com", "is_active": "on", "dashboards": ["business"], "password_mode": "email"})
        karim = User.objects.get(username="karim")
        self.assertFalse(karim.has_usable_password())
        self.assertFalse(karim.is_superuser)
        self.assertEqual(mail.outbox[-1].to, ["k@example.com"])
        link = re.search(r"https?://[^/\s]+(/accounts/password/reset/\S+/)", mail.outbox[-1].body).group(1)
        r = self.client.get(link, follow=True)
        self.assertContains(r, "Set a new password")
        self.client.post(r.redirect_chain[-1][0], {"new_password1": PW, "new_password2": PW})
        karim.refresh_from_db()
        self.assertTrue(karim.check_password(PW))

    def test_cant_demote_or_lock_yourself(self):
        self.client.post(reverse("user_edit", args=[self.admin.pk]), {
            "action": "details", "u-username": "boss", "u-email": "boss@example.com", "u-dashboards": ["personal"]})
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_superuser and self.admin.is_active)

    def test_dashboards_and_reset_two_factor(self):
        member = User.objects.create_user("worker", "w@example.com", PW)
        TwoFactor.objects.create(user=member, secret=totp.new_secret(), enabled=True)
        self.client.post(reverse("user_edit", args=[member.pk]), {
            "action": "details", "u-username": "worker", "u-email": "w@example.com", "u-is_active": "on", "u-dashboards": ["business"]})
        self.assertEqual(list(member.dashboard_access.values_list("dashboard__code", flat=True)), ["business"])
        self.client.post(reverse("user_edit", args=[member.pk]), {"action": "reset_2fa"})
        self.assertFalse(TwoFactor.objects.filter(user=member).exists())

    def test_every_dashboard_can_be_given(self):
        r = self.client.get(reverse("user_create"))
        for d in Dashboard.objects.filter(is_active=True):
            self.assertContains(r, f'value="{d.code}"')


class SignInLockoutTests(TestCase):
    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        self.addCleanup(cache.clear)
        self.user = User.objects.create_user("rahim", "rahim@example.com", PW)

    def wrong(self, n, **extra):
        for _i in range(n):
            self.client.post(reverse("login"), {"username": "rahim", "password": "not-it"}, **extra)

    def test_five_wrong_passwords_pause_signing_in_from_that_place(self):
        self.wrong(5)
        r = self.client.post(reverse("login"), {"username": "rahim", "password": PW})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Too many wrong passwords")
        self.assertNotIn("_auth_user_id", self.client.session)
        # somewhere else, the right password still works
        r = self.client.post(reverse("login"), {"username": "rahim", "password": PW}, REMOTE_ADDR="10.0.0.9")
        self.assertEqual(r.status_code, 302)

    def test_a_right_password_clears_the_count(self):
        self.wrong(4)
        self.assertEqual(self.client.post(reverse("login"), {"username": "rahim", "password": PW}).status_code, 302)
        self.client.logout()
        self.wrong(4)
        self.assertEqual(self.client.post(reverse("login"), {"username": "rahim", "password": PW}).status_code, 302)

    def test_guessing_from_many_places_locks_the_account_and_emails_the_owner(self):
        from django.core import mail

        for i in range(20):
            self.client.post(reverse("login"), {"username": "rahim", "password": "x"}, REMOTE_ADDR=f"10.1.0.{i}")
        r = self.client.post(reverse("login"), {"username": "rahim", "password": PW}, REMOTE_ADDR="10.2.0.1")
        self.assertContains(r, "Too many wrong passwords")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("rahim@example.com", mail.outbox[0].to)
