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

from . import cards, services
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
