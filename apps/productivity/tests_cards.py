"""Flashcards: when cards come back (spaced repetition), what's due, adding
cards one at a time or many at once, from notes and mind maps, the review
page, and keeping everything to its owner."""
import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import cards
from .models import Card, CardReview, Deck, Diagram, DiagramKind, LearningItem, Note

PW = "Str0ng-pass-123"


class SchedulingTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_user("me", "me@example.com", PW)
        self.deck = Deck.objects.create(owner=self.me, name="System design")

    def card(self, **kw):
        return Card.objects.create(owner=self.me, deck=self.deck, front=kw.pop("front", "Q"), back="A", **kw)

    def test_a_new_card_learns_then_waits_longer_each_time(self):
        c = self.card()
        today = timezone.localdate()
        cards.answer(c, cards.GOOD)
        self.assertEqual((c.interval, c.reps, c.due), (1, 1, today + timedelta(days=1)))
        cards.answer(c, cards.GOOD)
        self.assertEqual(c.interval, 3)                       # 1 × 2.5, rounded up past the last wait
        cards.answer(c, cards.GOOD)
        self.assertEqual(c.interval, 8)
        cards.answer(c, cards.EASY)
        self.assertGreater(c.interval, 20)
        self.assertGreater(c.ease, 2.5)
        self.assertEqual(CardReview.objects.filter(card=c).count(), 4)

    def test_forgetting_starts_it_again_and_makes_it_harder(self):
        c = self.card(interval=30, reps=4, last_reviewed=timezone.now() - timedelta(days=30))
        cards.answer(c, cards.AGAIN)
        self.assertEqual((c.interval, c.reps, c.lapses), (0, 0, 1))
        self.assertAlmostEqual(c.ease, 2.3)
        self.assertEqual(c.due, timezone.localdate())          # again today
        cards.answer(c, cards.HARD)                             # still learning it: later today
        self.assertEqual(c.interval, 0)
        cards.answer(c, cards.GOOD)
        self.assertEqual(c.interval, 1)

    def test_buttons_say_what_they_will_do(self):
        fresh = self.card()
        self.assertEqual(cards.previews(fresh), {1: "now", 2: "today", 3: "1 day", 4: "4 days"})
        old = self.card(front="Old", interval=40, reps=5, last_reviewed=timezone.now())
        p = cards.previews(old)
        self.assertEqual(p[3], "3 mo")
        self.assertEqual(cards.wait_label(400), "1.1 yr")
        self.assertEqual(cards.wait_label(20), "3 wk")

    def test_what_is_due_today(self):
        today = timezone.localdate()
        due = self.card(front="due", interval=3, reps=1, due=today - timedelta(days=1), last_reviewed=timezone.now() - timedelta(days=4))
        self.card(front="later", interval=3, reps=1, due=today + timedelta(days=2), last_reviewed=timezone.now())
        self.card(front="paused", is_suspended=True)
        self.deck.new_per_day = 2
        self.deck.save()
        for i in range(4):
            self.card(front=f"new {i}")
        session = cards.due_cards(self.me)
        self.assertEqual([c.front for c in session][:1], ["due"])
        self.assertEqual(sorted(c.front for c in session), ["due", "new 0", "new 1"])
        self.assertEqual(cards.due_count(self.me), 3)
        cards.answer(Card.objects.get(front="new 0"), cards.GOOD)    # one new card started today: one more allowed
        self.assertEqual(cards.new_left(self.deck), 1)
        self.assertIn(due, cards.due_cards(self.me, self.deck))
        self.deck.is_archived = True
        self.deck.save()
        self.assertEqual(cards.due_cards(self.me), [])

    def test_streak_and_numbers(self):
        c = self.card()
        now = timezone.now()
        for days_ago, rating in ((0, 3), (1, 1), (2, 3)):
            CardReview.objects.create(owner=self.me, card=c, rating=rating, reviewed_at=now - timedelta(days=days_ago))
        st = cards.stats(self.me)
        self.assertEqual((st["streak"], st["today"], st["retention"]), (3, 1, 67))
        self.assertEqual(len(st["heat"]), 91)

    def test_reading_cards_from_text(self):
        pairs = cards.parse_pairs("CAP :: pick two\n- Idempotent :: same result twice\nnot a card\nQ\tA in a spreadsheet\n :: no question")
        self.assertEqual(pairs, [("CAP", "pick two"), ("Idempotent", "same result twice"), ("Q", "A in a spreadsheet")])
        data = {"root": {"id": "r", "text": "Caching", "children": [
            {"id": "a", "text": "Where", "children": [{"id": "b", "text": "CDN", "children": []}, {"id": "c", "text": "Redis", "children": []}]},
            {"id": "d", "text": "Lonely", "children": []}]}}
        pairs = cards.mindmap_pairs(data)
        self.assertEqual(pairs[0], ("**Caching**", "- Where\n- Lonely"))
        self.assertEqual(pairs[1], ("_Caching_\n\n**Where**", "- CDN\n- Redis"))
        self.assertEqual(cards.add_cards(self.me, self.deck, pairs + pairs), 2)     # the same question isn't added twice
        self.assertEqual(cards.add_cards(self.me, self.deck, pairs), 0)


class FlashcardPageTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)

    def test_making_a_deck_and_adding_cards(self):
        r = self.client.get(reverse("work:cards"))
        self.assertContains(r, "Make your first deck")
        r = self.client.post(reverse("work:deck_new"), {"name": "AWS", "color": "teal", "new_per_day": 20})
        deck = Deck.objects.get()
        self.assertRedirects(r, reverse("work:deck", args=[deck.pk]))
        res = self.client.post(reverse("work:api_card_add"), {"deck": deck.pk, "front": "What is S3?", "back": "Object storage"}).json()
        self.assertEqual((res["added"], res["card"]["dueText"]), (1, "new"))
        res = self.client.post(reverse("work:api_card_add"), {"deck": deck.pk, "text": "EC2 :: servers\nWhat is S3? :: again\nLambda :: functions"}).json()
        self.assertEqual((res["added"], res["skipped"]), (2, 1))
        self.assertFalse(self.client.post(reverse("work:api_card_add"), {"deck": deck.pk, "text": "nothing here"}).json()["ok"])
        r = self.client.get(reverse("work:deck", args=[deck.pk]))
        self.assertEqual(len(r.context["cards"]), 3)
        r = self.client.get(reverse("work:cards"))
        self.assertContains(r, "3 cards to review")
        self.assertContains(self.client.get(reverse("work:today")), "3 flashcards to review")

    def test_a_review_session(self):
        deck = Deck.objects.create(owner=self.me, name="Go")
        c = Card.objects.create(owner=self.me, deck=deck, front="goroutine?", back="a light thread")
        r = self.client.get(reverse("work:card_review"))
        session = r.context["review"]
        self.assertEqual([x["id"] for x in session["cards"]], [c.pk])
        self.assertEqual(session["cards"][0]["previews"][3], "1 day")
        url = reverse("work:api_card_action", args=[c.pk])
        res = self.client.post(url, {"action": "answer", "rating": 1}).json()
        self.assertTrue(res["again"])
        res = self.client.post(url, {"action": "answer", "rating": 3}).json()
        self.assertFalse(res["again"])
        self.assertFalse(self.client.post(url, {"action": "answer", "rating": 9}).json()["ok"])
        self.assertEqual(self.client.get(reverse("work:card_review")).context["review"]["cards"], [])
        r = self.client.get(reverse("work:card_review") + f"?deck={deck.pk}&practice=1")
        self.assertEqual(len(r.context["review"]["cards"]), 1)              # practising shows it anyway

    def test_editing_pausing_moving_deleting(self):
        a, b = Deck.objects.create(owner=self.me, name="A"), Deck.objects.create(owner=self.me, name="B")
        c = Card.objects.create(owner=self.me, deck=a, front="Q", back="A")
        url = reverse("work:api_card_action", args=[c.pk])
        self.assertEqual(self.client.post(url, {"action": "save", "front": "Q2", "back": "A2"}).json()["card"]["front"], "Q2")
        self.assertTrue(self.client.post(url, {"action": "pause"}).json()["card"]["paused"])
        self.assertEqual(cards.due_count(self.me), 0)
        self.client.post(url, {"action": "move", "deck": b.pk})
        c.refresh_from_db()
        self.assertEqual(c.deck, b)
        res = self.client.post(url, {"action": "delete"}).json()
        self.assertFalse(Card.objects.exists())
        self.client.post(res["undo"])
        self.assertTrue(Card.objects.filter(pk=c.pk).exists())
        res = self.client.post(reverse("work:api_deck_action", args=[b.pk]), {"action": "delete"}).json()
        self.assertFalse(Card.objects.exists())                               # a deck takes its cards with it
        self.client.post(res["undo"])
        self.assertEqual(Card.objects.get().deck_id, b.pk)

    def test_cards_from_a_note_a_mind_map_and_a_book(self):
        note = Note.objects.create(owner=self.me, title="HTTP", body="# HTTP\n\n- 200 :: OK\n- 404 :: Not found\n")
        res = self.client.post(reverse("work:api_note_action", args=[note.pk]), {"action": "cards"}).json()
        self.assertEqual(res["count"], 2)
        self.assertEqual(Deck.objects.get().name, "HTTP")
        self.assertFalse(self.client.post(reverse("work:api_note_action", args=[Note.objects.create(owner=self.me, body="plain").pk]), {"action": "cards"}).json()["ok"])
        d = Diagram.objects.create(owner=self.me, kind=DiagramKind.MINDMAP, title="Caching", data={"root": {"id": "r", "text": "Caching", "children": [
            {"id": "a", "text": "Kinds", "children": [{"id": "b", "text": "Write-through", "children": []}]}]}})
        res = self.client.post(reverse("work:api_diagram_action", args=[d.pk]), {"action": "cards"}).json()
        self.assertEqual(res["count"], 2)
        self.assertEqual(res["url"], reverse("work:deck", args=[Deck.objects.get(name="Caching").pk]))
        book = LearningItem.objects.create(owner=self.me, title="DDIA")
        r = self.client.post(reverse("work:deck_new"), {"learning": book.pk, "from_learning": "1"})
        deck = Deck.objects.get(learning=book)
        self.assertRedirects(r, reverse("work:deck", args=[deck.pk]))
        self.client.post(reverse("work:deck_new"), {"learning": book.pk, "from_learning": "1"})
        self.assertEqual(Deck.objects.filter(learning=book).count(), 1)       # the same deck the second time

    def test_found_by_search_and_in_the_export(self):
        deck = Deck.objects.create(owner=self.me, name="Rust")
        Card.objects.create(owner=self.me, deck=deck, front="What is borrowing?", back="Using a value without owning it")
        res = self.client.get(reverse("work:api_search") + "?q=borrowing").json()
        self.assertEqual([x["kind"] for x in res["results"]], ["card"])
        self.assertContains(self.client.get(reverse("search") + "?q=borrowing"), "What is borrowing?")
        import io
        import zipfile
        z = zipfile.ZipFile(io.BytesIO(self.client.get(reverse("work:export")).content))
        self.assertIn("What is borrowing?\tUsing a value without owning it", z.read(next(n for n in z.namelist() if n.startswith("flashcards/"))).decode())
        self.assertTrue(any(r["model"] == "productivity.card" for r in json.loads(z.read("data.json"))))

    def test_nobody_else_can_see_or_change_them(self):
        deck = Deck.objects.create(owner=self.me, name="Mine")
        c = Card.objects.create(owner=self.me, deck=deck, front="secret", back="")
        other = User.objects.create_superuser("other", "o@example.com", PW)
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("work:deck", args=[deck.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("work:api_card_action", args=[c.pk]), {"action": "answer", "rating": 3}).status_code, 404)
        self.assertEqual(self.client.post(reverse("work:api_card_add"), {"deck": deck.pk, "front": "x"}).status_code, 404)
        self.assertEqual(self.client.post(reverse("work:api_deck_action", args=[deck.pk]), {"action": "delete"}).status_code, 404)
        self.assertEqual(self.client.get(reverse("work:card_review")).context["review"]["cards"], [])
        self.assertEqual(self.client.get(reverse("work:card_review") + f"?deck={deck.pk}&practice=1").context["review"]["cards"], [])
