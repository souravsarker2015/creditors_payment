"""A site admin hears about debug mode left on a public site, on every page."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from apps.core.site_health import PUBLIC_KEY, site_warnings

User = get_user_model()
PUBLIC = "paymenttracker.pythonanywhere.com"


@override_settings(ALLOWED_HOSTS=["*"], SECRET_KEY="a-long-random-value-of-its-own", DEBUG=False)
class SiteWarningTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("root", password="pw")
        self.person = User.objects.create_user("rahim", password="pw")

    def warnings(self, user, host=PUBLIC):
        request = RequestFactory().get("/", HTTP_HOST=host)
        request.user = user
        return site_warnings(request).get("site_warnings", [])

    def test_a_site_set_up_properly_says_nothing(self):
        self.assertEqual(self.warnings(self.admin), [])

    def test_an_admin_is_told_about_debug_mode(self):
        with override_settings(DEBUG=True):
            self.assertTrue(any("debug mode" in w for w in self.warnings(self.admin)))

    def test_and_about_the_public_key(self):
        with override_settings(SECRET_KEY=PUBLIC_KEY):
            self.assertTrue(any("secret key" in w for w in self.warnings(self.admin)))

    def test_nobody_else_is(self):
        with override_settings(DEBUG=True):
            self.assertEqual(self.warnings(self.person), [])
            self.assertEqual(self.warnings(AnonymousUser()), [])

    def test_on_your_own_computer_its_normal(self):
        with override_settings(DEBUG=True):
            self.assertEqual(self.warnings(self.admin, "127.0.0.1:8000"), [])

    def test_every_page_shows_it(self):
        self.client.force_login(self.admin)
        with self.settings(SECRET_KEY=PUBLIC_KEY):
            self.client.force_login(self.admin)
            self.assertContains(self.client.get(reverse("wallet_list"), HTTP_HOST=PUBLIC), "role=\"alert\"")
