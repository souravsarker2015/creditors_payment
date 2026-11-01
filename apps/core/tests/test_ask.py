"""The app asks with its own box (templates/partials/ask.html), never the browser's, in every part of the app;
a delete says truthfully what it leaves you with; and the side menu keeps its place from page to page."""
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase
from django.utils.translation import override


ROOT = Path(settings.BASE_DIR)
BROWSER_BOX = re.compile(r"(?<![\w.])(?:window\.)?(?:confirm|prompt|alert)\(")


def files(*patterns):
    for pattern in patterns:
        yield from ROOT.glob(pattern)


class NoBrowserBoxesTests(SimpleTestCase):
    def test_no_page_uses_the_browsers_own_box(self):
        found = []
        for path in files("static/js/*.js", "templates/**/*.html", "apps/**/templates/**/*.html"):
            if path.name == "ask.html":       # (its comment names them)
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if BROWSER_BOX.search(line):
                    found.append(f"{path.relative_to(ROOT)}:{number}")
        self.assertEqual(found, [], "use FT.ask() or data-confirm instead")

    def test_a_template_comment_is_not_spread_over_lines(self):
        """{# … #} is one line only: over several it's printed on the page."""
        found = [str(path.relative_to(ROOT)) for path in files("templates/**/*.html", "apps/**/templates/**/*.html")
                 if re.search(r"\{#(?:(?!#\}).)*\n", path.read_text(encoding="utf-8"))]
        self.assertEqual(found, [])

    def test_every_delete_form_asks_first(self):
        found = []
        for path in files("templates/**/*.html", "apps/**/templates/**/*.html"):
            text = path.read_text(encoding="utf-8")
            for m in re.finditer(r"<form\b[^>]*action=\"[^\"]*_delete[^\"]*\"[^>]*>", text):
                if "data-confirm" not in m.group(0):
                    found.append(f"{path.relative_to(ROOT)}: {m.group(0)[:80]}")
        self.assertEqual(found, [])


class DeleteWarningTests(SimpleTestCase):
    def menu(self, dashboard):
        return render_to_string("partials/row_menu.html", {"edit_url": "/e/", "delete_url": "/d/", "confirm": "Delete this?", "active_dashboard": dashboard})

    def test_a_personal_record_can_come_back(self):
        self.assertIn('data-confirm-after="back"', self.menu("personal"))

    def test_a_business_entry_has_no_restore_screen_and_says_so(self):
        self.assertIn('data-confirm-after="gone"', self.menu("business"))

    def test_the_box_is_in_bangla_too(self):
        with override("bn"):
            html = render_to_string("partials/ask.html", {"active_dashboard": "personal"})
        self.assertIn("ফিরিয়ে আনতে পারবেন", html)
        self.assertNotIn("This can", html)


class PagesTests(TestCase):
    def setUp(self):
        self.me = get_user_model().objects.create_superuser("me", "me@example.com", "Str0ng-pass-123")
        self.client.force_login(self.me)

    def test_each_app_has_the_box_and_keeps_the_menus_place(self):
        for url in ("/", "/work/", "/core/shortcuts/"):
            html = self.client.get(url).content.decode()
            self.assertIn('id="ft-ask"', html, url)
            self.assertIn("ft-nav-place:", html, url)
            self.assertNotIn("Keeps the side menu where it was", html, url)
