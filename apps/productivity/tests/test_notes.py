"""Notes as a board of cards (like Keep), quick notes, colours, and the list
read a page at a time (with infinite scrolling)."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from ..models import Note

PW = "Str0ng-pass-123"


class NotesBoardTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)

    def test_nothing_open_shows_the_board_pinned_first(self):
        Note.objects.create(owner=self.me, title="Plain", body="line one\nline two")
        Note.objects.create(owner=self.me, title="Pinned one", body="x", is_pinned=True, color="amber")
        r = self.client.get(reverse("work:notes"))
        self.assertTrue(r.context["board"])
        html = r.content.decode()
        self.assertLess(html.index("Pinned one"), html.index("Plain"))
        self.assertIn('data-head="pinned"', html)
        self.assertIn('data-head="others"', html)
        self.assertIn('data-color="amber"', html)
        self.assertFalse(self.client.get(reverse("work:notes") + "?view=list").context["board"])
        self.assertFalse(self.client.get(reverse("work:note", args=[Note.objects.first().pk])).context["board"])

    def test_a_card_shows_the_text_under_its_title(self):
        Note.objects.create(owner=self.me, body="Shopping\n- milk\n- **eggs**")
        html = self.client.get(reverse("work:notes")).content.decode()
        self.assertIn(">Shopping</a>", html)
        # the first line is the title, not said twice; then a line each, ** dropped
        self.assertIn('<span class="wnc-line">- milk</span><span class="wnc-line">- eggs</span>', html)
        self.assertEqual(html.count(">Shopping<"), 1)

    def test_pages_of_forty_for_infinite_scrolling(self):
        for i in range(45):
            Note.objects.create(owner=self.me, title=f"N{i}")
        r = self.client.get(reverse("work:notes"))
        self.assertEqual((len(r.context["notes"]), r.context["total"]), (40, 45))
        self.assertContains(r, 'data-next="?page=2"')
        self.assertEqual(len(self.client.get(reverse("work:notes") + "?page=2").context["notes"]), 5)

    def test_quick_note_with_colour_and_pin(self):
        r = self.client.post(reverse("work:api_note_save"), {"title": "", "body": "Idea\nmore", "color": "teal", "pinned": "1"}).json()
        n = Note.objects.get(pk=r["id"])
        self.assertEqual((n.color, n.is_pinned, r["title"]), ("teal", True, "Idea"))
        url = reverse("work:api_note_action", args=[n.pk])
        self.assertEqual(self.client.post(url, {"action": "color", "color": "red"}).json()["color"], "red")
        self.assertEqual(self.client.post(url, {"action": "color", "color": "#fff"}).json()["color"], "")

    def test_someone_elses_note_stays_theirs(self):
        other = User.objects.create_user("other", password=PW)
        n = Note.objects.create(owner=other, title="Secret")
        self.assertEqual(self.client.post(reverse("work:api_note_action", args=[n.pk]), {"action": "color", "color": "red"}).status_code, 404)
        self.assertNotContains(self.client.get(reverse("work:notes")), "Secret")


class EditInPreviewTests(TestCase):
    """The preview can be changed where it's read (static/js/work.js: Work.live)."""

    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)

    def test_a_note_offers_write_split_and_an_editable_preview(self):
        note = Note.objects.create(owner=self.me, title="Plan", body="# Plan")
        page = self.client.get(reverse("work:note", args=[note.pk])).content.decode()
        self.assertIn("wn-split-btn", page)
        self.assertIn("Work.live($el, { text: body", page)

    def test_the_board_editor_preview_is_editable_too(self):
        page = self.client.get(reverse("work:notes")).content.decode()
        self.assertIn("Work.live($el, { text: ed.body", page)

    def test_an_exam_answer_can_be_changed_in_its_preview(self):
        from ..models import ExamSubject

        subject = ExamSubject.objects.create(owner=self.me, name="Physics")
        page = self.client.get(reverse("work:exam_subject", args=[subject.pk])).content.decode()
        self.assertIn("Work.live($el, { text: edit.answer", page)
        self.assertIn("Work.live($el, { text: draft.answer", page)

    def test_its_words_come_in_the_page_settings(self):
        page = self.client.get(reverse("work:notes")).content.decode()
        for key in ("liveTurn", "liveBelow", "liveDeleted"):
            self.assertIn(f'"{key}"', page)
