"""Dropdowns, multi-selects and dates use the shared pickers (static/js/pickers.js)."""
from django.contrib.auth.models import User
from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import reverse


class PickerSetupTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="picker_user", password="secret123")
        self.client.force_login(self.user)

    def test_every_page_loads_the_pickers_and_their_words(self):
        html = self.client.get(reverse("expense_create")).content.decode()
        self.assertIn("js/pickers.js", html)
        self.assertIn("window.FT_PICK_TEXT", html)
        self.assertIn('yesterday: "Yesterday"', html)
        # Tom Select is gone: the pickers do multi-selects too.
        self.assertNotIn("tom-select", html)
        # Bangla month names only load for Bangla.
        self.assertNotIn("l10n/bn.js", html)

    def test_bangla_gets_bangla_calendar_and_words(self):
        self.client.post(reverse("update_preferences"), {"language": "bn"})
        html = self.client.get(reverse("expense_create")).content.decode()
        self.assertIn("flatpickr/dist/l10n/bn.js", html)
        self.assertIn('yesterday: "গতকাল"', html)
        self.assertIn('last7: "গত ৭ দিন"', html)

    def test_picker_script_is_served_and_keeps_the_page_helpers(self):
        path = finders.find("js/pickers.js")
        self.assertIsNotNone(path)
        src = open(path, encoding="utf-8").read()
        # Pages call these by name (FT.multiSelect / FT.rangePicker / FT.datePicker).
        for name in ("datePicker: datePicker", "rangePicker: rangePicker", "multiSelect: function", "labelAlt: labelAlt"):
            self.assertIn(name, src)
        # The real field keeps its value; forms, Alpine and htmx hear the change.
        self.assertIn('fire(select, "change")', src)
