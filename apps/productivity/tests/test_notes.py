"""Notes as a board of cards (like Keep), quick notes, colours, and the list
read a page at a time (with infinite scrolling)."""
from django.contrib.auth.models import User
from django.test import TestCase, TransactionTestCase
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
        from ..models import NoteCategory

        backend = NoteCategory.objects.create(owner=self.me, name="Backend")
        db = NoteCategory.objects.create(owner=self.me, name="Databases", parent=backend)
        other = NoteCategory.objects.create(owner=User.objects.create_user("x", password=PW), name="Theirs")
        note = Note.objects.create(owner=self.me, title="Indexes")
        Note.objects.create(owner=self.me, title="Elsewhere")
        r = self.client.post(reverse("work:api_note_save"), {"id": note.pk, "categories": f"{db.pk},{other.pk}"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(list(note.categories.all()), [db])                 # someone else's category is never added
        shown = self.client.get(reverse("work:notes"), {"category": backend.pk}).context["notes"]
        self.assertEqual([n.title for n in shown], ["Indexes"])               # the parent shows its child's notes
        none = self.client.get(reverse("work:notes"), {"category": "none"}).context["notes"]
        self.assertEqual([n.title for n in none], ["Elsewhere"])
        counts = self.client.get(reverse("work:api_note_categories")).json()["counts"]
        self.assertEqual((counts[str(backend.pk)], counts[str(db.pk)], counts["none"]), (1, 1, 1))

    def test_a_note_opened_on_the_board_brings_its_categories(self):
        from ..models import NoteCategory

        c = NoteCategory.objects.create(owner=self.me, name="Ideas")
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
        from ..models import NoteCategory, Tag

        note = Note.objects.create(owner=self.me, title="Plan", body="# Plan", color="amber")
        note.tags.add(Tag.objects.create(owner=self.me, name="work"))
        note.categories.add(NoteCategory.objects.create(owner=self.me, name="Ideas"))
        r = self.client.post(reverse("work:api_note_action", args=[note.pk]), {"action": "duplicate"}).json()
        copy = Note.objects.get(pk=r["id"])
        self.assertEqual((copy.title, copy.body, copy.color), ("Plan (copy)", "# Plan", "amber"))
        self.assertEqual([t.name for t in copy.tags.all()], ["work"])
        self.assertEqual([c.name for c in copy.categories.all()], ["Ideas"])

    def test_picked_notes_are_pinned_archived_and_filed_together(self):
        from ..models import NoteCategory

        a, b = Note.objects.create(owner=self.me, title="A"), Note.objects.create(owner=self.me, title="B")
        self.assertTrue(self.bulk(a, b, action="pin", on="1").json()["ok"])
        self.assertEqual(Note.objects.filter(is_pinned=True).count(), 2)
        c = NoteCategory.objects.create(owner=self.me, name="Ideas")
        self.bulk(a, b, action="categories", categories=str(c.pk))
        self.bulk(a, action="categories", categories=str(c.pk))         # already in it: no harm
        self.assertEqual(c.notes.count(), 2)
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


class NoteCategoriesApartTests(TestCase):
    """Notes have their own tree of categories; the exam pages keep theirs. Neither shows the other's."""

    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)

    def test_each_tree_is_its_own(self):
        from ..models import ExamCategory, NoteCategory

        r = self.client.post(reverse("work:api_note_categories"), {"action": "add", "name": "Ideas > Books"}).json()
        books = NoteCategory.objects.get(pk=r["id"])
        self.assertEqual((books.name, books.parent.name), ("Books", "Ideas"))
        self.assertEqual([c["path"] for c in r["categories"]], ["Ideas", "Ideas › Books"])
        self.assertFalse(ExamCategory.objects.exists())                       # the exam tree hasn't got them
        self.client.post(reverse("work:api_exam_categories"), {"action": "add", "name": "Physics"})
        self.assertEqual([c["path"] for c in self.client.get(reverse("work:api_exam_categories")).json()["categories"]], ["Physics"])
        self.assertEqual([c["path"] for c in self.client.get(reverse("work:api_note_categories")).json()["categories"]], ["Ideas", "Ideas › Books"])
        page = self.client.get(reverse("work:notes"))
        self.assertEqual([c["name"] for c in page.context["cat_data"]["categories"]], ["Ideas", "Books"])
        self.assertIn(reverse("work:api_note_categories"), page.context["work_config"]["urls"]["noteCategories"])

    def test_renamed_moved_and_deleted_in_the_notes_tree(self):
        from apps.trash.models import DeletedItem

        from ..models import ExamCategory, NoteCategory

        a = NoteCategory.objects.create(owner=self.me, name="A")
        b = NoteCategory.objects.create(owner=self.me, name="B", parent=a)
        exam_c = ExamCategory.objects.create(owner=self.me, name="Exam")
        url = reverse("work:api_note_categories")
        bad = self.client.post(url, {"action": "change", "id": a.pk, "name": "A", "parent": b.pk})
        self.assertEqual(bad.status_code, 400)                                # not inside itself
        theirs = NoteCategory.objects.create(owner=User.objects.create_user("x", password=PW), name="Theirs")
        self.assertEqual(self.client.post(url, {"action": "change", "id": b.pk, "name": "B", "parent": theirs.pk}).status_code, 400)
        self.assertEqual(self.client.post(url, {"action": "change", "id": theirs.pk, "name": "X"}).status_code, 404)
        self.assertEqual(self.client.post(url, {"action": "change", "id": 99999, "name": "X"}).status_code, 404)
        note = Note.objects.create(owner=self.me, title="Kept")
        note.categories.add(b)
        r = self.client.post(url, {"action": "delete", "id": a.pk}).json()
        self.assertEqual(list(NoteCategory.objects.values_list("name", flat=True)), ["Theirs"])
        self.assertTrue(Note.objects.filter(pk=note.pk).exists() and ExamCategory.objects.filter(pk=exam_c.pk).exists())
        item = DeletedItem.objects.get(user=self.me)
        self.assertEqual(item.back_url, reverse("work:notes"))
        self.client.post(r["undo"])
        self.assertEqual([c.name for c in Note.objects.get(pk=note.pk).categories.all()], ["B"])

    def test_a_backup_brings_the_notes_tree_back(self):
        from .. import services
        from ..models import NoteCategory

        ideas = NoteCategory.objects.create(owner=self.me, name="Ideas")
        books = NoteCategory.objects.create(owner=self.me, name="Books", parent=ideas)
        note = Note.objects.create(owner=self.me, title="Read")
        note.categories.add(books)
        rows, _files = services.backup_rows(self.me)
        other = User.objects.create_user("other", password=PW)
        services.restore(other, rows)
        mine = Note.objects.get(owner=other, title="Read")
        self.assertEqual([(c.name, c.parent.name, c.owner_id) for c in mine.categories.all()], [("Books", "Ideas", other.pk)])
        services.restore(other, rows)                                          # again: the same categories, not copies
        self.assertEqual(NoteCategory.objects.filter(owner=other).count(), 2)

    def test_a_backup_from_when_notes_used_exam_categories(self):
        from .. import services
        from ..models import ExamCategory, NoteCategory

        rows = [
            {"model": "productivity.examcategory", "pk": 7, "fields": {"owner": 1, "parent": None, "name": "Backend", "created_at": "2026-11-01T00:00:00Z"}},
            {"model": "productivity.examcategory", "pk": 8, "fields": {"owner": 1, "parent": 7, "name": "Databases", "created_at": "2026-11-01T00:00:00Z"}},
            {"model": "productivity.note", "pk": 3, "fields": {"owner": 1, "title": "Indexes", "body": "", "categories": [8], "tags": [],
                                                                "created_at": "2026-11-01T00:00:00Z", "updated_at": "2026-11-01T00:00:00Z"}},
        ]
        services.restore(self.me, rows)
        note = Note.objects.get(owner=self.me, title="Indexes")
        self.assertEqual([(c.name, c.parent.name) for c in note.categories.all()], [("Databases", "Backend")])
        self.assertTrue(all(isinstance(c, NoteCategory) for c in note.categories.all()))
        self.assertEqual(ExamCategory.objects.filter(owner=self.me).count(), 2)       # (the exam ones come back as they were)


class NoteCategoriesMigrationTests(TransactionTestCase):
    """0038: the categories notes were in (exam ones until then) are copied into the notes' own tree."""

    before, after = ("productivity", "0037_note_categories"), ("productivity", "0038_note_categories_apart")

    def migrate(self, target):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate([target])
        return executor.loader.project_state([target]).apps

    def tearDown(self):
        from django.core.management import call_command

        call_command("migrate", verbosity=0)

    def test_notes_keep_their_categories_and_the_exam_tree_keeps_its_questions(self):
        old = self.migrate(self.before)
        User_ = old.get_model("auth", "User")
        me = User_.objects.create(username="me")
        Cat, ExamNote_, Subject = old.get_model("productivity", "ExamCategory"), old.get_model("productivity", "ExamNote"), old.get_model("productivity", "ExamSubject")
        Note_ = old.get_model("productivity", "Note")
        backend = Cat.objects.create(owner=me, name="Backend")
        db = Cat.objects.create(owner=me, name="Databases", parent=backend)
        ideas = Cat.objects.create(owner=me, name="Ideas")                 # only ever held notes
        books = Cat.objects.create(owner=me, name="Books", parent=ideas)
        physics = Cat.objects.create(owner=me, name="Physics")             # only questions
        subject = Subject.objects.create(owner=me, name="S")
        q = ExamNote_.objects.create(owner=me, subject=subject, question="Q?")
        q.categories.add(db, physics)
        n1 = Note_.objects.create(owner=me, title="Indexes")
        n1.categories.add(db)
        n2 = Note_.objects.create(owner=me, title="To read")
        n2.categories.add(books, ideas)

        new = self.migrate(self.after)
        NoteCat, Note2, Cat2 = new.get_model("productivity", "NoteCategory"), new.get_model("productivity", "Note"), new.get_model("productivity", "ExamCategory")
        paths = sorted((c.parent.name + " › " if c.parent_id else "") + c.name for c in NoteCat.objects.filter(owner_id=me.pk))
        self.assertEqual(paths, ["Backend", "Backend › Databases", "Ideas", "Ideas › Books"])
        self.assertEqual(sorted(c.name for c in Note2.objects.get(pk=n1.pk).categories.all()), ["Databases"])
        self.assertEqual(sorted(c.name for c in Note2.objects.get(pk=n2.pk).categories.all()), ["Books", "Ideas"])
        # the exam tree: what holds questions stays; what only held notes has gone over to the notes
        self.assertEqual(sorted(Cat2.objects.values_list("name", flat=True)), ["Backend", "Databases", "Physics"])


class NoteIconAndSideListTests(TestCase):
    """A note's icon (Notion's page icon) and the categories beside the board (Keep's labels)."""

    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)

    def test_an_icon_is_saved_shown_and_copied(self):
        note = Note.objects.create(owner=self.me, title="Plan")
        r = self.client.post(reverse("work:api_note_save"), {"id": note.pk, "icon": " 🧠 ", "card": "1"}).json()
        note.refresh_from_db()
        self.assertEqual(note.icon, "🧠")
        self.assertIn("🧠", r["card"])
        self.assertEqual(self.client.get(reverse("work:api_note_get", args=[note.pk])).json()["icon"], "🧠")
        self.assertIn("🧠", self.client.get(reverse("work:notes"), {"view": "list"}).content.decode())
        copy = self.client.post(reverse("work:api_note_action", args=[note.pk]), {"action": "duplicate"}).json()
        self.assertEqual(Note.objects.get(pk=copy["id"]).icon, "🧠")
        self.client.post(reverse("work:api_note_save"), {"id": note.pk, "icon": "x" * 40})
        note.refresh_from_db()
        self.assertEqual(len(note.icon), 16)                                   # kept short
        self.client.post(reverse("work:api_note_save"), {"id": note.pk, "icon": ""})
        note.refresh_from_db()
        self.assertEqual(note.icon, "")                                        # taken off
        self.client.post(reverse("work:api_note_save"), {"id": note.pk, "title": "Plan again"})
        note.refresh_from_db()
        self.assertEqual((note.title, note.icon), ("Plan again", ""))          # a save without it leaves it be

    def test_the_board_has_the_categories_beside_it(self):
        from ..models import NoteCategory

        work = NoteCategory.objects.create(owner=self.me, name="Work")
        Note.objects.create(owner=self.me, title="A").categories.add(work)
        Note.objects.create(owner=self.me, title="B")
        Note.objects.create(owner=self.me, title="Old", is_archived=True)
        r = self.client.get(reverse("work:notes"))
        html = r.content.decode()
        self.assertIn('class="wnb-side"', html)
        self.assertIn('class="chip-row wnb-chips"', html)
        self.assertEqual(r.context["cat_data"]["all"], 2)                     # archived ones aren't counted
        self.assertEqual(r.context["cat_data"]["counts"][work.pk], 1)
        self.assertIn(reverse("trash_list"), html)
