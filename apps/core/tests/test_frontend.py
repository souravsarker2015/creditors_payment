"""The front-end set-up shared by every page: prebuilt CSS, instant page
changes, and live search. These guard the decisions in templates/base.html."""
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

BASE = Path(settings.BASE_DIR)
TEMPLATE_DIRS = [BASE / "templates", *(p for p in (BASE / "apps").rglob("templates") if p.is_dir())]


def all_templates():
    for folder in TEMPLATE_DIRS:
        yield from folder.rglob("*.html")


class TemplateLintTests(TestCase):
    def test_no_multi_line_short_comments(self):
        """Django's {# … #} only works on one line. A multi-line one is printed
        onto the page as plain text (this once put a paragraph under every page)."""
        bad = []
        for path in all_templates():
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "{#" in line and "#}" not in line[line.index("{#"):]:
                    bad.append(f"{path.relative_to(BASE)}:{n}")
        self.assertEqual(bad, [], "Use {% comment %}…{% endcomment %} for comments over several lines")

    def test_live_search_forms_have_a_results_block(self):
        """A form that swaps #results is useless on a page without one."""
        for path in all_templates():
            text = path.read_text(encoding="utf-8")
            if path.name in ("live_search.html", "entity_filters.html"):    # the partials themselves
                continue
            if 'include "partials/live_search.html"' in text or 'include "partials/entity_filters.html"' in text:
                self.assertIn('id="results"', text, f"{path.relative_to(BASE)} has a live search but no #results")


class PrebuiltCssTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("css_probe", password="x")
        self.client.force_login(self.user)

    def page(self):
        return self.client.get(reverse("login"), follow=True).content.decode()

    def test_tailwind_is_prebuilt_not_compiled_in_the_browser(self):
        html = self.page()
        self.assertNotIn("cdn.tailwindcss.com", html)
        self.assertIn("/static/css/tailwind.css", html)

    def test_tailwind_loads_after_app_css(self):
        """The old in-browser compiler added its styles last; the file must too, or the cascade changes."""
        html = self.page()
        self.assertLess(html.index("css/app.css"), html.index("css/tailwind.css"))

    def test_the_built_file_exists_and_has_the_utilities(self):
        css = (BASE / "static" / "css" / "tailwind.css").read_text(encoding="utf-8")
        self.assertGreater(len(css), 5000)
        for used in (".grid", ".hidden", "lg\\:flex", ".gap-5"):
            self.assertIn(used, css, f"{used} is missing: run python manage.py tailwind")

    def test_every_class_name_in_the_templates_that_tailwind_knows_is_built(self):
        """Catches a new class in a template without a rebuild (python manage.py tailwind)."""
        css = (BASE / "static" / "css" / "tailwind.css").read_text(encoding="utf-8")
        built = set(re.findall(r"\.((?:[a-z0-9]+\\:)*-?[a-z][a-z0-9-]*(?:\\\[[^\]]+\\\])?(?:\\/[0-9]+)?)", css))
        built = {b.replace("\\", "") for b in built}
        probes = ["lg:col-span-3", "sm:flex-row", "md:grid-cols-2", "max-w-[18rem]"]
        used = set()
        for path in all_templates():
            for cls in re.findall(r'class="([^"{]+)"', path.read_text(encoding="utf-8")):
                used.update(cls.split())
        for probe in probes:
            if probe in used:
                self.assertIn(probe, built, f"{probe} is used in a template but not built: run python manage.py tailwind")


class InstantNavigationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("nav_probe", password="x")
        self.client.force_login(self.user)

    def rules(self):
        html = self.client.get(reverse("creditor_list")).content.decode()
        m = re.search(r'<script type="speculationrules">(.*?)</script>', html, re.S)
        self.assertIsNotNone(m, "speculation rules missing")
        return m.group(1)

    def test_logout_and_downloads_are_never_fetched_ahead(self):
        rules = self.rules()
        for excluded in ("logout", "/admin", ".ics", "a[href*='?']", "a[download]"):
            self.assertIn(excluded, rules)

    def test_prerender_waits_for_a_press(self):
        """Building a whole page in the background is only worth it once the link is pressed."""
        rules = self.rules()
        prerender = rules[rules.index('"prerender"'):]
        self.assertIn('"eagerness": "conservative"', prerender)

    def test_rules_are_valid_json(self):
        import json

        data = json.loads(self.rules())
        self.assertIn("prefetch", data)
        self.assertIn("prerender", data)

    def test_signed_out_pages_have_no_rules(self):
        self.client.logout()
        html = self.client.get(reverse("login")).content.decode()
        self.assertNotIn("speculationrules", html)


class LiveSearchTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("live_probe", password="x")
        self.client.force_login(self.user)

    def test_htmx_is_pinned_and_checked(self):
        html = self.client.get(reverse("creditor_list")).content.decode()
        tag = re.search(r'<script[^>]+htmx\.org@([\d.]+)[^>]*>', html)
        self.assertIsNotNone(tag)
        self.assertRegex(tag.group(1), r"^2\.\d+\.\d+$")      # an exact version, never "latest"
        self.assertIn('integrity="sha384-', tag.group(0))

    def test_the_creditor_list_searches_live(self):
        html = self.client.get(reverse("creditor_list")).content.decode()
        self.assertIn('hx-select="#results"', html)
        self.assertIn('id="results"', html)

    def test_a_search_request_returns_the_matching_results(self):
        """HTMX asks for the same page; the #results block in it carries the answer."""
        r = self.client.get(reverse("creditor_list"), {"q": "nobody-by-this-name"}, headers={"hx-request": "true"})
        self.assertEqual(r.status_code, 200)
        block = r.content.decode().split('id="results"', 1)[1]
        self.assertIn("No creditors match your filters", block)

    def test_export_still_downloads_a_file(self):
        r = self.client.get(reverse("creditor_list"), {"export": "csv"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r["Content-Type"])


class AppViewTests(TestCase):
    """Phones: app view (bottom tabs, "+" and "More" sheets) or website view,
    as the person chooses. The choice is applied in the browser before the
    page is drawn; the server only says what was chosen."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("app_probe", password="x")
        self.client.force_login(self.user)

    def html(self, name="creditor_list"):
        return self.client.get(reverse(name)).content.decode()

    def choose(self, value):
        return self.client.post(reverse("update_preferences"), {"view_mode": value}, headers={"x-preferences-fetch": "1"})

    def test_automatic_is_the_default(self):
        self.assertEqual(self.user.profile.view_mode, "auto")
        self.assertIn('data-view-pref="auto"', self.html())

    def test_the_choice_is_saved(self):
        self.assertEqual(self.choose("app").status_code, 204)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.view_mode, "app")
        self.assertIn('data-view-pref="app"', self.html())

    def test_an_unknown_choice_is_ignored(self):
        self.choose("tablet")
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.view_mode, "auto")

    def test_the_layout_is_decided_before_the_page_is_drawn(self):
        """The script that picks app or website view runs in <head>, before any stylesheet, so nothing flashes."""
        html = self.html()
        head = html[: html.index("</head>")]
        self.assertIn("display-mode", head)
        self.assertLess(head.index("FTView"), head.index("css/app.css"))

    def test_every_page_carries_the_tab_bar_and_both_sheets(self):
        html = self.html()
        for part in ('class="app-tabbar', "sheet === 'add'", "sheet === 'more'", 'data-view-choice="web"', 'data-app-back'):
            self.assertIn(part, html)

    def test_the_choice_is_offered_in_website_view_too(self):
        """Someone in website view can switch to app view: from the top-bar menu and the phone sidebar."""
        html = self.html()
        menu = html.split('class="preferences-switcher menu-view', 1)[1].split("</div>", 1)[0]
        self.assertIn("Layout on this phone", menu)
        sidebar = html.split('class="preferences-switcher pref-ink', 1)[1]
        self.assertLess(sidebar.index('data-view-choice="app"'), sidebar.index("</nav>"))

    def test_signed_out_pages_have_no_app_shell(self):
        self.client.logout()
        html = self.client.get(reverse("login")).content.decode()
        self.assertNotIn("app-tabbar", html)

    def test_more_sheet_lists_the_same_pages_as_the_sidebar(self):
        html = self.html("networth")
        more = html.split('class="app-more-nav"', 1)[1].split("app-settings", 1)[0]
        for name in ("dashboard", "debtor_dashboard", "shop_dashboard", "expense_dashboard", "household_dashboard", "goal_list"):
            self.assertIn(f'href="{reverse(name)}"', more)


class BusinessAppViewTests(TestCase):
    def setUp(self):
        from apps.business.core.models import Role
        from apps.business.core.testing import make_farm

        self.b, self.owner, self.staff = make_farm(staff_role=Role.DATA_ENTRY)

    def sheet(self, user):
        self.client.force_login(user)
        html = self.client.get(reverse("business:home")).content.decode()
        return html.split('aria-labelledby="app-add-title"', 1)[1].split("</section>", 1)[0]

    def test_the_farm_has_its_own_tabs_and_quick_actions(self):
        add = self.sheet(self.owner)
        for name in ("sale_add", "feed_usage_bulk", "feed_purchases_add", "payment_add", "transaction_add", "calendar_add"):
            self.assertIn(reverse("business:" + name), add)

    def test_money_actions_follow_the_role(self):
        """Data entry can record sales and feed, but money pages are hidden from it in the menu — and here."""
        add = self.sheet(self.staff)
        self.assertIn(reverse("business:sale_add"), add)
        self.assertNotIn(reverse("business:payment_add"), add)
        self.assertNotIn(reverse("business:transaction_add"), add)
