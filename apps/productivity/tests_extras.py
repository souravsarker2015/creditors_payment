"""The pieces that tie the newer features into the rest: taking a flashcard
answer back, note history, the export coming back in with diagrams and decks,
the weekly review, earnings in Reports, a deck's download and the daily
flashcard reminder."""
import io
import json
import zipfile
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import cards, diagrams, services
from .models import Card, CardReview, Deck, Diagram, DiagramKind, LearningItem, Note, NoteVersion, Project, TimeEntry, WorkSettings

PW = "Str0ng-pass-123"


class ExtrasTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)

    def test_taking_an_answer_back(self):
        deck = Deck.objects.create(owner=self.me, name="Go")
        c = Card.objects.create(owner=self.me, deck=deck, front="Q", back="A")
        url = reverse("work:api_card_action", args=[c.pk])
        res = self.client.post(url, {"action": "answer", "rating": 3}).json()
        c.refresh_from_db()
        self.assertEqual((c.interval, c.reps), (1, 1))
        res = self.client.post(url, {"action": "undo", "review": res["review"]}).json()
        self.assertTrue(res["ok"])
        c.refresh_from_db()
        self.assertEqual((c.interval, c.reps, c.last_reviewed, c.due), (0, 0, None, timezone.localdate()))
        self.assertFalse(CardReview.objects.exists())
        self.assertFalse(self.client.post(url, {"action": "undo"}).json()["ok"])        # nothing left to take back

    def test_a_note_keeps_its_earlier_versions(self):
        note = Note.objects.create(owner=self.me, title="Plan", body="first draft")
        save = reverse("work:api_note_save")
        self.client.post(save, {"id": note.pk, "body": "second draft"})
        self.assertEqual(NoteVersion.objects.get().body, "first draft")
        self.client.post(save, {"id": note.pk, "body": "third draft"})            # same sitting: no new copy
        self.assertEqual(NoteVersion.objects.count(), 1)
        NoteVersion.objects.update(created_at=timezone.now() - services.NOTE_EVERY)
        self.client.post(save, {"id": note.pk, "body": "fourth draft"})
        self.assertEqual(NoteVersion.objects.count(), 2)
        listed = self.client.get(reverse("work:api_note_versions", args=[note.pk])).json()["versions"]
        self.assertEqual([v["body"] for v in listed], ["third draft", "first draft"])
        act = reverse("work:api_note_action", args=[note.pk])
        self.client.post(act, {"action": "restore", "version": listed[1]["id"]})
        note.refresh_from_db()
        self.assertEqual(note.body, "first draft")
        self.assertTrue(NoteVersion.objects.filter(body="fourth draft").exists())     # what was there is kept
        self.client.post(act, {"action": "forget", "version": listed[0]["id"]})
        self.assertFalse(NoteVersion.objects.filter(pk=listed[0]["id"]).exists())
        other = User.objects.create_superuser("other", "o@example.com", PW)
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("work:api_note_versions", args=[note.pk])).status_code, 404)

    def test_the_export_comes_back_with_diagrams_and_flashcards(self):
        book = LearningItem.objects.create(owner=self.me, title="DDIA")
        project = Project.objects.create(owner=self.me, name="Launch")
        Diagram.objects.create(owner=self.me, kind=DiagramKind.MINDMAP, title="Ideas", project=project,
                               data={"root": {"id": "r", "text": "Ideas", "children": []}})
        deck = Deck.objects.create(owner=self.me, name="Storage", learning=book)
        Card.objects.create(owner=self.me, deck=deck, front="B-tree?", back="A balanced tree", interval=12, reps=3)
        blob = self.client.get(reverse("work:export")).content
        other = User.objects.create_superuser("other", "o@example.com", PW)
        self.client.force_login(other)
        upload = io.BytesIO(blob)
        upload.name = "backup.zip"
        self.client.post(reverse("work:settings"), {"action": "restore", "backup": upload})
        d = Diagram.objects.get(owner=other)
        self.assertEqual((d.title, d.project.name, d.data["root"]["text"]), ("Ideas", "Launch", "Ideas"))
        c = Card.objects.get(owner=other)
        self.assertEqual((c.front, c.deck.name, c.deck.learning.title, c.interval), ("B-tree?", "Storage", "DDIA", 12))
        self.assertEqual(c.deck.owner, other)

    def test_the_weekly_review_counts_practice_and_diagrams(self):
        deck = Deck.objects.create(owner=self.me, name="Go")
        c = Card.objects.create(owner=self.me, deck=deck, front="Q", back="A")
        cards.answer(c, cards.GOOD)
        cards.answer(c, cards.AGAIN)
        Diagram.objects.create(owner=self.me, kind=DiagramKind.FLOWCHART, title="Sign-in flow", source="flowchart TD\n A-->B")
        r = self.client.get(reverse("work:review"))
        self.assertEqual(r.context["d"]["practice"]["answers"], 2)
        self.assertEqual(r.context["d"]["practice"]["remembered"], 50)
        self.assertContains(r, "Sign-in flow")
        md = self.client.get(reverse("work:review") + "?export=md").content.decode()
        self.assertIn("2 answers on 1 cards over 1 days, 50% remembered", md)
        self.assertIn("- Sign-in flow (Flowchart)", md)

    def test_reports_show_what_the_time_is_worth(self):
        p = Project.objects.create(owner=self.me, name="Client", hourly_rate=1500)
        now = timezone.now()
        TimeEntry.objects.create(owner=self.me, project=p, started_at=now - timedelta(hours=2), ended_at=now)
        r = self.client.get(reverse("work:reports") + "?preset=week")
        self.assertAlmostEqual(r.context["earned"], 3000, places=0)
        self.assertContains(r, "Worth at your rates")

    def test_a_deck_downloads_for_anki(self):
        deck = Deck.objects.create(owner=self.me, name="HTTP codes")
        Card.objects.create(owner=self.me, deck=deck, front="404", back="Not found\nThe page isn't there")
        r = self.client.get(reverse("work:deck_export", args=[deck.pk]))
        self.assertEqual(r.content.decode(), "404\tNot found<br>The page isn't there\n")
        self.assertIn('filename="HTTP-codes.tsv"', r["Content-Disposition"])

    def test_reminder_setting_and_share_to_a_flashcard(self):
        s = WorkSettings.for_user(self.me)
        s.cards_remind_at = timezone.datetime(2026, 1, 1, 19, 30).time()
        s.save()
        self.assertContains(self.client.get(reverse("work:today")), '"cardsRemind": "19:30"')
        self.assertEqual(self.client.get(reverse("work:api_cards_due")).json()["due"], 0)
        res = self.client.post(reverse("work:api_card_add"), {"front": "What is a CDN?", "back": "https://example.com/cdn"}).json()
        self.assertEqual(Deck.objects.get().name, "My cards")
        self.assertEqual(res["url"], reverse("work:deck", args=[Deck.objects.get().pk]))
        self.assertEqual(self.client.get(reverse("work:api_cards_due")).json()["due"], 1)
        self.assertContains(self.client.get(reverse("work:wrapup")), "1 flashcard still waiting")

    def test_a_notes_outline_becomes_a_mind_map(self):
        body = ("# Trip\n\nSome words that aren't a list.\n\n## Where\n- Sylhet\n  - Tea gardens\n- [x] Cox's Bazar\n\n"
                "## Budget\n1. **Hotel**\n2. [Bus](https://example.com)\n\n```\n- not in a code block\n```\n")
        data = diagrams.outline_map("Trip", body)
        root = data["root"]
        self.assertEqual(root["text"], "Trip")
        self.assertEqual([k["text"] for k in root["children"]], ["Where", "Budget"])
        where = root["children"][0]
        self.assertEqual([k["text"] for k in where["children"]], ["Sylhet", "Cox's Bazar"])
        self.assertEqual(where["children"][0]["children"][0]["text"], "Tea gardens")
        self.assertTrue(where["children"][1]["done"])
        self.assertEqual([k["text"] for k in root["children"][1]["children"]], ["Hotel", "Bus"])
        self.assertIsNone(diagrams.outline_map("Plain", "Just a sentence."))
        project = Project.objects.create(owner=self.me, name="Holiday")
        note = Note.objects.create(owner=self.me, title="Trip", body=body, project=project)
        res = self.client.post(reverse("work:api_note_action", args=[note.pk]), {"action": "mindmap"}).json()
        d = Diagram.objects.get()
        self.assertEqual((res["url"], d.kind, d.project, d.title), (reverse("work:diagram", args=[d.pk]), DiagramKind.MINDMAP, project, "Trip"))
        plain = Note.objects.create(owner=self.me, title="Plain", body="Just words.")
        self.assertFalse(self.client.post(reverse("work:api_note_action", args=[plain.pk]), {"action": "mindmap"}).json()["ok"])

    def test_study_notes_template_and_translated_trash_labels(self):
        r = self.client.get(reverse("work:notes") + "?new=1&template=study")
        self.assertContains(r, "Question :: Answer")
        from django.utils import translation
        deck = Deck.objects.create(owner=self.me, name="Words")
        c = Card.objects.create(owner=self.me, deck=deck, front="Q")
        from apps.trash.services import trash
        with translation.override("bn"):
            item = trash(self.me, c, "x")
        self.assertEqual(item.kind, "ফ্ল্যাশকার্ড")


class EmailTests(TestCase):
    """“Your day” and emailed reminders (apps/productivity/emails.py)."""

    def setUp(self):
        from django.core import mail  # noqa: F401  (the test runner's outbox)

        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.s = WorkSettings.for_user(self.me)
        self.s.daily_email = self.s.reminder_emails = True
        self.s.work_days = "0123456"
        self.s.day_start = timezone.datetime(2026, 1, 1, 9, 0).time()
        self.s.save()

    def at(self, hour, minute=0, days=0):
        today = timezone.localdate() + timedelta(days=days)
        return timezone.make_aware(timezone.datetime.combine(today, timezone.datetime.min.time()).replace(hour=hour, minute=minute))

    def test_your_day_goes_once_when_the_day_starts(self):
        from django.core import mail

        from . import emails
        from .models import Task
        today = timezone.localdate()
        Task.objects.create(owner=self.me, title="Ship the release", due_date=today)
        Task.objects.create(owner=self.me, title="Old bug", due_date=today - timedelta(days=2))
        Task.objects.create(owner=self.me, title="Design review", scheduled_at=self.at(14))
        self.assertEqual(emails.run(self.at(8))["briefs"], 0)                 # before the work day starts
        self.assertEqual(emails.run(self.at(9, 5))["briefs"], 1)
        self.assertEqual(emails.run(self.at(10))["briefs"], 0)                # once a day
        msg = mail.outbox[0]
        self.assertIn("1 late", msg.subject)
        body = msg.body
        self.assertIn("Ship the release", body)
        self.assertIn("Old bug", body)
        self.assertIn("14:00 Design review", body)
        self.assertIn("Your day", msg.alternatives[0][0])

    def test_nothing_to_say_and_days_off(self):
        from django.core import mail

        from . import emails
        self.assertEqual(emails.run(self.at(9, 30))["quiet"], 1)               # a clear day: no email
        self.assertEqual(len(mail.outbox), 0)
        self.s.daily_email_sent_on = None
        self.s.work_days = ""                                                   # not a work day
        self.s.save()
        self.assertEqual(emails.briefs_due(self.at(10)), [])

    def test_a_reminder_is_emailed_once(self):
        from django.core import mail

        from . import emails
        from .models import Task
        t = Task.objects.create(owner=self.me, title="Call the bank", remind_at=self.at(11), due_date=timezone.localdate())
        Task.objects.create(owner=self.me, title="Later", remind_at=self.at(16))
        Task.objects.create(owner=self.me, title="Done already", remind_at=self.at(11), status="done")
        self.assertEqual(emails.run(self.at(10, 50))["reminders"], 0)
        self.assertEqual(emails.run(self.at(11, 5))["reminders"], 1)
        self.assertEqual(emails.run(self.at(11, 20))["reminders"], 0)           # not twice
        reminder = [m for m in mail.outbox if "Reminder" in m.subject]
        self.assertEqual(reminder[0].subject, "Reminder: Call the bank")
        t.remind_at = self.at(15)                                               # moved: it reminds again at the new time
        t.save()
        self.assertEqual(emails.run(self.at(15, 1))["reminders"], 1)
        self.s.reminder_emails = False
        self.s.save()
        Task.objects.create(owner=self.me, title="Quiet", remind_at=self.at(16, 30))
        self.assertEqual(emails.run(self.at(16, 40))["reminders"], 0)           # turned off: nothing more is emailed
        self.assertFalse([m for m in mail.outbox if "Quiet" in m.subject])

    def test_settings_send_a_test(self):
        from django.core import mail

        self.client.force_login(self.me)
        r = self.client.post(reverse("work:settings"), {"action": "test_brief"})
        self.assertRedirects(r, reverse("work:settings") + "#emails", fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 1)


class NoteImageTests(TestCase):
    PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64

    def setUp(self):
        import tempfile

        from django.test import override_settings
        self.media = override_settings(MEDIA_ROOT=tempfile.mkdtemp())
        self.media.enable()
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)

    def tearDown(self):
        self.media.disable()

    def upload(self, content, name="shot.png", **extra):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return self.client.post(reverse("work:api_image_upload"), {"image": SimpleUploadedFile(name, content), **extra}).json()

    def test_a_picture_goes_in_and_only_its_owner_sees_it(self):
        note = Note.objects.create(owner=self.me, title="Bug")
        res = self.upload(self.PNG, note=note.pk)
        self.assertTrue(res["ok"])
        self.assertTrue(res["markdown"].startswith("![shot]("))
        from .models import NoteImage
        img = NoteImage.objects.get()
        self.assertEqual((img.note, img.file.name.endswith(".png")), (note, True))
        r = self.client.get(res["url"])
        self.assertEqual((r.status_code, r["Content-Type"]), (200, "image/png"))
        self.assertIn("sandbox", r["Content-Security-Policy"])
        other = User.objects.create_superuser("other", "o@example.com", PW)
        self.client.force_login(other)
        self.assertEqual(self.client.get(res["url"]).status_code, 404)

    def test_only_real_pictures(self):
        self.assertFalse(self.upload(b"<svg onload=alert(1)>", "x.svg")["ok"])
        self.assertFalse(self.upload(b"<html>", "x.png")["ok"])                  # the name doesn't make it a picture
        self.assertTrue(self.upload(b"\xff\xd8\xff\xe0" + b"\x00" * 32, "photo.heic")["ok"])   # a JPEG whatever its name
        self.assertTrue(self.upload(b"RIFF\x00\x00\x00\x00WEBPVP8 ", "a.webp")["ok"])
