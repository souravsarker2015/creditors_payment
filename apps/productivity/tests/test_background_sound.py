"""Background sound (rain, the sea, a fire, brown noise… made in the browser: static/js/ambient.js): a mix for focus, one
for breaks and one for reading, each saved as the mixer changes it; the volume; whether timers bring it too; the
ticking sounds — and the mixer on the pages that set them."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .. import ambient
from ..models import NoteCategory, Note, TickStyle, WorkSettings

PW = "Str0ng-pass-123"


class MixTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)
        self.url = reverse("work:api_sound")

    def test_quiet_until_chosen(self):
        s = WorkSettings.for_user(self.me)
        self.assertEqual((s.focus_mix, s.break_mix, s.reading_mix, s.mix_volume, s.sound_with_timers), ("", "", "", 40, False))

    def test_a_mix_is_saved_and_the_others_stay(self):
        self.client.post(self.url, {"break_mix": "stream:55,birds:35"})
        r = self.client.post(self.url, {"focus_mix": "rain:70,brown:20"}).json()
        self.assertTrue(r["ok"])
        self.assertEqual(r["cfg"]["mixes"], {"focus": "rain:70,brown:20", "break": "stream:55,birds:35", "reading": ""})
        self.client.post(self.url, {"reading_mix": "fire:60,rain:35", "mix_volume": "25"})
        s = WorkSettings.for_user(self.me)
        self.assertEqual((s.focus_mix, s.break_mix, s.reading_mix, s.mix_volume), ("rain:70,brown:20", "stream:55,birds:35", "fire:60,rain:35", 25))
        self.client.post(self.url, {"focus_mix": ""})                                  # Quiet
        self.assertEqual(WorkSettings.objects.get(owner=self.me).focus_mix, "")

    def test_nonsense_is_refused(self):
        for bad in ({"focus_mix": "rain"}, {"focus_mix": "<script>:1"}, {"mix_volume": "300"}, {}):
            self.assertEqual(self.client.post(self.url, bad).status_code, 400, bad)
        self.assertEqual(WorkSettings.objects.get(owner=self.me).focus_mix, "")

    def test_every_ready_made_mix_is_made_of_known_sounds(self):
        known = {i for i, *_ in ambient.LAYERS}
        for _id, _name, mix, good_for, _why in ambient.PRESETS:
            self.assertTrue({part.split(":")[0] for part in mix.split(",")} <= known, mix)
            self.assertTrue(set(good_for) <= {"focus", "break", "reading"})
        for where in ("focus", "break", "reading"):
            self.assertTrue(any(where in p[3] for p in ambient.PRESETS), where)

    def test_timers_and_new_ticking_sounds_from_the_focus_panel(self):
        r = self.client.post(reverse("work:api_focus_settings"), {"sound_with_timers": "true", "tick_style": "heart"}).json()
        self.assertEqual((r["cfg"]["withTimers"], r["cfg"]["tickStyle"]), (True, "heart"))
        self.assertEqual({v for v, _ in TickStyle.choices}, {"clock", "soft", "wood", "grand", "watch", "metro", "heart"})


class PagesTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)

    def test_the_mixer_is_where_it_is_set(self):
        for url in (reverse("work:focus"), reverse("work:settings")):
            r = self.client.get(url)
            self.assertContains(r, 'x-data="mixer(\'focus\', false)"')
            self.assertContains(r, "js/ambient.js")
        cat = NoteCategory.objects.create(owner=self.me, name="Database")
        n = Note.objects.create(owner=self.me, title="Intro", body="Some words.")
        n.categories.add(cat)
        r = self.client.get(reverse("work:read_book", args=[cat.pk]))
        self.assertContains(r, 'x-data="mixer(\'reading\', true)"')                   # the Reader: only what to read with

    def test_every_page_knows_what_to_play(self):
        s = WorkSettings.for_user(self.me)
        s.reading_mix = "fire:60,rain:35"
        s.save()
        r = self.client.get(reverse("work:today"))
        self.assertContains(r, '"reading": "fire:60,rain:35"')
        self.assertContains(r, '"mixVolume": 40')

    def test_saving_settings_keeps_the_mixes(self):
        s = WorkSettings.for_user(self.me)
        s.focus_mix = "brown:70"
        s.save()
        page = self.client.get(reverse("work:settings"))
        form = page.context["form"]
        data = {}
        for name, field in form.fields.items():
            value = form[name].value()
            if value is None:
                continue
            data[form.add_prefix(name)] = value
        self.client.post(reverse("work:settings"), data)
        self.assertEqual(WorkSettings.objects.get(owner=self.me).focus_mix, "brown:70")
