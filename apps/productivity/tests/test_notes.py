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
        # the first line is the title, not said twice; then a line each, as a list, ** dropped
        self.assertIn('<span class="wnc-line" data-kind="li">milk</span><span class="wnc-line" data-kind="li">eggs</span>', html)
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


class NoteShapeAndCategoryTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)

    def test_a_card_keeps_headings_quotes_and_code_apart(self):
        Note.objects.create(owner=self.me, title="Shape", body="## Plan\n> careful\n1. first\n```\nx = 1\n```")
        html = self.client.get(reverse("work:notes")).content.decode()
        for line in ('data-kind="h">Plan<', 'data-kind="q">careful<', 'data-kind="ol">1. first<', 'data-kind="code">x = 1<'):
            self.assertIn(line, html)

    def test_a_note_goes_in_categories_and_a_category_shows_what_is_inside_it(self):
        from ..models import ExamCategory

        backend = ExamCategory.objects.create(owner=self.me, name="Backend")
        db = ExamCategory.objects.create(owner=self.me, name="Databases", parent=backend)
        other = ExamCategory.objects.create(owner=User.objects.create_user("x", password=PW), name="Theirs")
        note = Note.objects.create(owner=self.me, title="Indexes")
        Note.objects.create(owner=self.me, title="Elsewhere")
        r = self.client.post(reverse("work:api_note_save"), {"id": note.pk, "categories": f"{db.pk},{other.pk}"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(list(note.categories.all()), [db])                 # someone else's category is never added
        shown = self.client.get(reverse("work:notes"), {"category": backend.pk}).context["notes"]
        self.assertEqual([n.title for n in shown], ["Indexes"])               # the parent shows its child's notes
        none = self.client.get(reverse("work:notes"), {"category": "none"}).context["notes"]
        self.assertEqual([n.title for n in none], ["Elsewhere"])
        counts = self.client.get(reverse("work:api_exam_categories"), {"for": "notes"}).json()["counts"]
        self.assertEqual((counts[str(backend.pk)], counts[str(db.pk)], counts["none"]), (1, 1, 1))

    def test_a_note_opened_on_the_board_brings_its_categories(self):
        from ..models import ExamCategory

        c = ExamCategory.objects.create(owner=self.me, name="Ideas")
        note = Note.objects.create(owner=self.me, title="One")
        note.categories.add(c)
        self.assertEqual(self.client.get(reverse("work:api_note_get", args=[note.pk])).json()["categories"], [c.pk])

    def test_the_list_has_an_edit_button_per_note(self):
        note = Note.objects.create(owner=self.me, title="Listed")
        html = self.client.get(reverse("work:notes"), {"view": "list"}).content.decode()
        self.assertIn(reverse("work:note", args=[note.pk]) + "?mode=write", html)
        self.assertIn(reverse("work:note", args=[note.pk]) + "?mode=view", html)


class ManyNotesAtOnceTests(TestCase):
    """Duplicate, sort, and several cards picked at once (as in Keep)."""

    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)

    def bulk(self, *notes, **fields):
        return self.client.post(reverse("work:api_notes_bulk"), {"ids": ",".join(str(n.pk) for n in notes), **fields})

    def test_duplicate_copies_text_tags_and_categories(self):
        from ..models import ExamCategory, Tag

        note = Note.objects.create(owner=self.me, title="Plan", body="# Plan", color="amber")
        note.tags.add(Tag.objects.create(owner=self.me, name="work"))
        note.categories.add(ExamCategory.objects.create(owner=self.me, name="Ideas"))
        r = self.client.post(reverse("work:api_note_action", args=[note.pk]), {"action": "duplicate"}).json()
        copy = Note.objects.get(pk=r["id"])
        self.assertEqual((copy.title, copy.body, copy.color), ("Plan (copy)", "# Plan", "amber"))
        self.assertEqual([t.name for t in copy.tags.all()], ["work"])
        self.assertEqual([c.name for c in copy.categories.all()], ["Ideas"])

    def test_picked_notes_are_pinned_archived_and_filed_together(self):
        from ..models import ExamCategory

        a, b = Note.objects.create(owner=self.me, title="A"), Note.objects.create(owner=self.me, title="B")
        self.assertTrue(self.bulk(a, b, action="pin", on="1").json()["ok"])
        self.assertEqual(Note.objects.filter(is_pinned=True).count(), 2)
        c = ExamCategory.objects.create(owner=self.me, name="Ideas")
        self.bulk(a, b, action="categories", categories=str(c.pk))
        self.bulk(a, action="categories", categories=str(c.pk))         # already in it: no harm
        self.assertEqual(c.work_notes.count(), 2)
        self.bulk(a, b, action="archive", on="1")
        self.assertEqual(Note.objects.filter(is_archived=True).count(), 2)

    def test_picked_notes_go_to_recently_deleted(self):
        from apps.trash.models import DeletedItem

        a, b = Note.objects.create(owner=self.me, title="A"), Note.objects.create(owner=self.me, title="B")
        self.bulk(a, b, action="delete")
        self.assertFalse(Note.objects.exists())
        self.assertEqual(DeletedItem.objects.filter(user=self.me).count(), 2)

    def test_someone_elses_notes_are_never_touched(self):
        theirs = Note.objects.create(owner=User.objects.create_user("x", password=PW), title="Theirs")
        r = self.bulk(theirs, action="delete")
        self.assertEqual(r.status_code, 400)
        self.assertTrue(Note.objects.filter(pk=theirs.pk).exists())

    def test_the_board_can_be_sorted(self):
        Note.objects.create(owner=self.me, title="Banana")
        Note.objects.create(owner=self.me, title="Apple")
        pinned = Note.objects.create(owner=self.me, title="Zebra", is_pinned=True)
        shown = [n.title for n in self.client.get(reverse("work:notes"), {"sort": "title"}).context["notes"]]
        self.assertEqual(shown, [pinned.title, "Apple", "Banana"])            # pinned stay first
        shown = [n.title for n in self.client.get(reverse("work:notes"), {"sort": "created"}).context["notes"]]
        self.assertEqual(shown, ["Zebra", "Apple", "Banana"])


class WritingOnAPhoneTests(TestCase):
    """The keyboard row, find and replace and Keep's to-do tools (static/js/writing.js) get their
    words from the page, and the page lets a phone's keyboard make room (interactive-widget)."""

    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)

    def test_the_page_gives_the_scripts_their_words_and_the_keyboard_room(self):
        note = Note.objects.create(owner=self.me, title="Shop", body="- [x] milk\n- [ ] eggs")
        r = self.client.get(reverse("work:note", args=[note.pk]))
        html = r.content.decode()
        self.assertIn("interactive-widget=resizes-content", html)
        text = r.context["work_config"]["text"]
        for group, keys in {"kbar": ("undo", "slash", "todo", "find", "done"), "find": ("find", "replace", "one", "all", "none", "replaced")}.items():
            for key in keys:
                self.assertTrue(text[group][key], (group, key))
        self.assertIn("%(n)s", str(text["find"]["replaced"]))
        for key in ("todoSunk", "todoUnticked", "todoDropped", "todoNothing", "undo"):
            self.assertTrue(text[key], key)
        # the ⋯ menu: find and replace, and the to-do tools (shown when something is ticked)
        self.assertIn("openFind(true)", html)
        for how in ("sink", "untick", "drop"):
            self.assertIn("todoTool('%s')" % how, html)
