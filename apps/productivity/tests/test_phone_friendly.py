"""Words that fit the device: no "press s" on a phone, "2 hours ago" rather than "2 hours, 50 minutes"."""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from ..templatetags.work import ago


class AgoTests(TestCase):
    def test_one_unit_and_ago(self):
        now = timezone.now()
        self.assertEqual(ago(now - timedelta(hours=2, minutes=50)), "2\xa0hours ago")
        self.assertEqual(ago(now - timedelta(days=3, hours=5)), "3\xa0days ago")
        self.assertEqual(ago(None), "")


class KeyboardHintsTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", "pw-12345!")
        self.client.force_login(self.me)

    def test_shortcut_words_are_marked_for_keyboards_only(self):
        today = self.client.get(reverse("work:today")).content.decode()
        self.assertIn('<span class="keys-only"> Or press S.</span>', today)
        tasks = self.client.get(reverse("work:tasks")).content.decode()
        self.assertNotIn("( / )", tasks)                       # the search box says what it is for, not a key
        self.assertNotIn("Press c to add a task", tasks)
        self.assertIn('<span class="keys-only"> Or press C.</span>', tasks)
