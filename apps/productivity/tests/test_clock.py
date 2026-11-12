"""The focus page's own settings (lengths, sounds, ringing, ticking — saved as they change, back to the defaults in one
go), and the page's three tabs: focus, timers and the stopwatch (those run in the browser: static/js/clock.js)."""
import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from ..models import WorkSettings

PW = "Str0ng-pass-123"


class FocusSettingsTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)
        self.url = reverse("work:api_focus_settings")

    def test_the_defaults_are_the_lengths_people_had(self):
        s = WorkSettings.for_user(self.me)
        self.assertEqual((s.focus_minutes, s.short_break_minutes, s.long_break_minutes, s.long_break_every, s.ring, s.break_sound, s.timer_sound),
                         (25, 5, 15, 4, 1, "", ""))

    def test_one_change_is_saved_and_the_rest_stay(self):
        r = self.client.post(self.url, {"focus_minutes": "50", "short_break_minutes": "10"}).json()
        self.assertEqual((r["cfg"]["focus"], r["cfg"]["short"], r["cfg"]["long"]), (50, 10, 15))
        s = WorkSettings.for_user(self.me)
        self.assertEqual((s.focus_minutes, s.short_break_minutes, s.long_break_minutes, s.sound_enabled), (50, 10, 15, True))
        r = self.client.post(self.url, {"break_sound": "gong", "ring": "0", "tick_sound": "true", "tick_style": "wood", "volume": "40"}).json()
        self.assertEqual((r["cfg"]["breakSound"], r["cfg"]["timerSound"], r["cfg"]["ring"], r["cfg"]["tick"], r["cfg"]["tickStyle"]),
                         ("gong", "chime", 0, True, "wood"))                    # a timer: the same sound as focus, when none is picked
        r = self.client.post(self.url, {"sound_enabled": "false"}).json()
        self.assertEqual((r["cfg"]["sound"], r["cfg"]["breakSound"], r["cfg"]["timerSound"]), ("", "", ""))     # sounds off: none at all

    def test_nonsense_is_refused_and_nothing_changes(self):
        r = self.client.post(self.url, {"focus_minutes": "0", "sound": "trumpet"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("focus_minutes", r.json()["errors"])
        self.assertEqual(WorkSettings.for_user(self.me).focus_minutes, 25)

    def test_back_to_defaults_keeps_the_notifications_choice(self):
        self.client.post(self.url, {"focus_minutes": "90", "long_break_every": "6", "tick_sound": "true", "ring": "3", "notifications": "false"})
        r = self.client.post(self.url, {"action": "defaults"}).json()
        s = WorkSettings.for_user(self.me)
        self.assertEqual((s.focus_minutes, s.long_break_every, s.tick_sound, s.ring), (25, 4, False, 1))
        self.assertFalse(s.notifications)
        self.assertEqual(r["values"]["focus_minutes"], 25)

    def test_the_page_has_its_tabs_settings_and_every_page_its_timers(self):
        html = self.client.get(reverse("work:focus")).content.decode()
        for bit in ('x-data="clockPage"', 'x-data="timersPanel"', 'x-data="stopwatchPanel"', "focusSettings(", 'data-keys-page="clock"', "Kitchen timer", "Until I stop it"):
            self.assertIn(bit, html)
        values = json.loads(html.split('id="focus-values" type="application/json">')[1].split("</script>")[0])
        self.assertEqual(values["focus_minutes"], 25)
        today = self.client.get(reverse("work:today")).content.decode()
        self.assertIn("js/clock.js", today)
        self.assertIn('class="wrg"', today)                                        # "Time's up", over any page
        self.assertIn('"tickStyle": "clock"', today)

    def test_someone_signed_out_cant_change_them(self):
        self.client.logout()
        self.assertNotEqual(self.client.post(self.url, {"focus_minutes": "60"}).status_code, 200)
        self.assertEqual(WorkSettings.for_user(self.me).focus_minutes, 25)
