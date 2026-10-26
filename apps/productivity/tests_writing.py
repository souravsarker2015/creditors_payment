"""Writing and code for software work: #tags written in notes, the Markdown
boxes' editor keys (static/js/writing.js), snippets with blanks to fill in
(read a page at a time), an exam question opened straight from search, and
the front-end libraries pinned to one version."""
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from . import services
from .models import ExamNote, ExamSubject, Note, Snippet, Task

PW = "Str0ng-pass-123"


class HashtagTests(SimpleTestCase):
    def test_words_after_a_hash_are_tags(self):
        self.assertEqual(services.hashtags("Caching #redis and #system-design, then #k8s."), ["redis", "system-design", "k8s"])

    def test_not_headings_code_links_numbers_or_colours(self):
        text = ("# Heading\n##also-heading\n`#inline` see [docs](https://x.dev/page#anchor) issue #42\n"
                "```css\n#main { color: #fff }\n```\ncolour #e6edf3 <a href=\"#top\">top</a> word#notag")
        self.assertEqual(services.hashtags(text), [])

    def test_bangla_tags_keep_their_vowel_signs(self):
        self.assertEqual(services.hashtags("বাংলা #ডেটাবেস নোট"), ["ডেটাবেস"])


class NoteHashtagTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)

    def save(self, **fields):
        return self.client.post(reverse("work:api_note_save"), fields).json()

    def test_a_quick_note_is_tagged_from_its_text(self):
        res = self.save(body="Redis eviction #redis #caching\n- allkeys-lru")
        self.assertEqual(res["tags"], ["caching", "redis"])
        self.assertEqual(sorted(Note.objects.get(pk=res["id"]).tags.values_list("name", flat=True)), ["caching", "redis"])

    def test_the_editors_tags_and_the_texts_go_together(self):
        res = self.save(body="Kafka #queues", tags="backend")
        self.assertEqual(res["tags"], ["backend", "queues"])
        res = self.save(id=res["id"], body="Kafka, tag taken out", tags="backend")   # gone from the text: gone from the note
        self.assertEqual(res["tags"], ["backend"])

    def test_saving_only_the_title_keeps_the_tags(self):
        res = self.save(body="x #keep")
        self.assertEqual(self.save(id=res["id"], title="New title")["tags"], ["keep"])


class EditorTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)

    def test_every_work_page_has_the_editor_keys(self):
        html = self.client.get(reverse("work:today")).content.decode()
        self.assertIn("js/writing.js", html)
        self.assertRegex(html, r'<textarea x-ref="note" x-model="text" data-md')       # quick capture (n)

    def test_markdown_boxes_are_marked(self):
        for name in ("work:journal", "work:wrapup", "work:learning_new"):
            self.assertIn(" data-md ", self.client.get(reverse(name)).content.decode(), name)
        self.assertIn("data-code", self.client.get(reverse("work:snippet_new")).content.decode())

    def test_the_shortcut_sheet_lists_the_writing_keys(self):
        self.assertContains(self.client.get(reverse("work:help")), "Writing (notes, answers, cards)")


class SnippetTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)

    def test_pages_of_thirty_for_infinite_scrolling(self):
        for i in range(35):
            Snippet.objects.create(owner=self.me, title=f"S{i:02d}", code=f"echo {i}")
        r = self.client.get(reverse("work:snippets"))
        self.assertEqual(len(r.context["snippets"]), 30)
        self.assertContains(r, 'data-next="?page=2"')
        self.assertContains(r, "data-infinite-items")
        self.assertEqual(len(self.client.get(reverse("work:snippets") + "?page=2").context["snippets"]), 5)

    def test_blanks_are_left_in_the_code_for_the_page_to_fill(self):
        Snippet.objects.create(owner=self.me, title="Shell", language="bash", code="docker exec -it {{container}} bash")
        r = self.client.get(reverse("work:snippets"))
        self.assertContains(r, "docker exec -it {{container}} bash")
        self.assertContains(r, 'class="wsn-fill"')
        self.assertContains(self.client.get(reverse("work:snippet_new")), "{{branch:main}}")

    def test_search_finds_code_and_tags_page_and_palette(self):
        sn = Snippet.objects.create(owner=self.me, title="Restart", code="kubectl rollout restart deploy/api")
        sn.tags.set(services.tags_named(self.me, ["k8s"]))
        self.assertEqual(list(self.client.get(reverse("work:snippets") + "?q=k8s").context["snippets"]), [sn])
        found = self.client.get(reverse("work:api_search") + "?q=rollout").json()["results"]
        self.assertIn("snippet", [x["kind"] for x in found])


class ExamOpenTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)
        self.s = ExamSubject.objects.create(owner=self.me, name="Databases")

    def test_the_board_keeps_its_own_keys(self):
        # c on the board is a new question, not the app-wide "quick add a task"
        self.assertContains(self.client.get(reverse("work:exam_subject", args=[self.s.pk])), 'data-page-keys="c a r o j k x s e"')

    def test_one_question_by_id_wherever_it_is_in_the_list(self):
        for i in range(40):
            ExamNote.objects.create(owner=self.me, subject=self.s, question=f"Q{i}", order=i)
        last = ExamNote.objects.get(question="Q39")
        res = self.client.get(reverse("work:api_exam_notes", args=[self.s.pk]) + f"?id={last.pk}").json()
        self.assertEqual([(n["id"], n["number"]) for n in res["notes"]], [(last.pk, 40)])
        self.assertIsNone(res["next"])

    def test_not_a_question_of_this_subject(self):
        other = ExamSubject.objects.create(owner=self.me, name="Other")
        n = ExamNote.objects.create(owner=self.me, subject=other, question="Elsewhere")
        self.assertEqual(self.client.get(reverse("work:api_exam_notes", args=[self.s.pk]) + f"?id={n.pk}").status_code, 404)

    def test_search_and_the_home_page_link_to_the_question(self):
        n = ExamNote.objects.create(owner=self.me, subject=self.s, question="What is a B-tree index?")
        url = reverse("work:exam_subject", args=[self.s.pk]) + f"?open={n.pk}"
        self.assertIn(url, [x["url"] for x in self.client.get(reverse("work:api_search") + "?q=B-tree").json()["results"]])
        self.assertContains(self.client.get(reverse("work:exam") + "?q=B-tree"), url)


class PinnedLibraryTests(SimpleTestCase):
    """A library loaded without an exact version changes under the app the day a new one comes out."""

    def test_every_cdn_script_and_stylesheet_names_its_version(self):
        loose = []
        for path in list(Path(settings.BASE_DIR, "templates").rglob("*.html")) + list(Path(settings.BASE_DIR, "apps").rglob("*.html")):
            for url in re.findall(r'(?:src|href)="(https://cdn\.jsdelivr\.net/npm/[^"]+)"', path.read_text()):
                name = re.match(r"https://cdn\.jsdelivr\.net/npm/((?:@[^/]+/)?[^/@]+)(@[^/]+)?", url)
                if not name.group(2) or not re.fullmatch(r"@\d+\.\d+\.\d+", name.group(2)):
                    loose.append(f"{path.name}: {url}")
        self.assertEqual(loose, [])


class NoteTickTests(TestCase):
    """To-dos ticked right on a note's card or in its preview, without opening it to write."""

    BODY = "Ship it:\n- [ ] migrate\n> - [x] tag\n```\n- [ ] in code, not a to-do\n```\n1. [ ] changelog"

    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)
        self.note = Note.objects.create(owner=self.me, title="Release", body=self.BODY)

    def tick(self, **fields):
        return self.client.post(reverse("work:api_note_action", args=[self.note.pk]), {"action": "tick", **fields}).json()

    def test_the_lines_markdown_draws_as_boxes_not_code(self):
        self.assertEqual(services.todo_lines(self.BODY), [1, 2, 6])

    def test_ticking_turns_over_the_nth_box(self):
        res = self.tick(index=2)
        self.assertTrue(res["done"])
        self.note.refresh_from_db()
        self.assertIn("1. [x] changelog", self.note.body)
        self.assertIn("- [ ] in code, not a to-do", self.note.body)        # the code block is left alone
        self.assertFalse(self.tick(index=1, done="0")["done"])
        self.note.refresh_from_db()
        self.assertIn("> - [ ] tag", self.note.body)

    def test_a_box_that_isnt_there(self):
        self.assertFalse(self.tick(index=9)["ok"])
        self.assertFalse(self.tick(index="x")["ok"])

    def test_a_line_made_into_a_task_ticks_the_task(self):
        self.client.post(reverse("work:api_note_action", args=[self.note.pk]), {"action": "todos"})
        task = Task.objects.get(title="migrate")
        self.tick(index=0)
        task.refresh_from_db()
        self.assertTrue(task.is_done)

    def test_the_card_comes_back_drawn_again(self):
        res = self.tick(index=0, card="1")
        self.assertIn('data-note-card="%d"' % self.note.pk, res["card"])
        self.assertEqual(res["card"].count('class="wnc-todo is-done"'), 2)

    def test_cards_show_boxes_to_tick(self):
        html = self.client.get(reverse("work:notes")).content.decode()
        self.assertEqual(len(re.findall(r'class="wnc-todo[^"]*"[^>]*@click\.stop="tick\((\d)', html)), 3)
        self.assertIn("tick(2, $el)", html)


class NoteBoardEditTests(TestCase):
    """A note opened and written on the board (like Keep), and today's note in one click."""

    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)

    def test_one_note_to_edit_on_the_board(self):
        n = Note.objects.create(owner=self.me, title="T", body="b", color="amber", is_pinned=True)
        res = self.client.get(reverse("work:api_note_get", args=[n.pk])).json()
        self.assertEqual((res["title"], res["body"], res["color"], res["pinned"]), ("T", "b", "amber", True))
        other = User.objects.create_user("other", "o@example.com", PW)
        theirs = Note.objects.create(owner=other, title="Secret")
        self.assertEqual(self.client.get(reverse("work:api_note_get", args=[theirs.pk])).status_code, 404)

    def test_saving_from_the_board_returns_its_card(self):
        n = Note.objects.create(owner=self.me, title="T", body="b")
        res = self.client.post(reverse("work:api_note_save"), {"id": n.pk, "title": "New", "body": "- [ ] x", "card": "1"}).json()
        self.assertIn(">New</a>", res["card"])
        self.assertIn("wnc-todo", res["card"])
        self.assertNotIn("card", self.client.post(reverse("work:api_note_save"), {"id": n.pk, "body": "y"}).json())

    def test_pinning_on_the_board_returns_its_card(self):
        n = Note.objects.create(owner=self.me, title="T")
        res = self.client.post(reverse("work:api_note_action", args=[n.pk]), {"action": "pin", "card": "1"}).json()
        self.assertTrue(res["pinned"])
        self.assertIn('data-note-card="%d"' % n.pk, res["card"])

    def test_todays_note_is_made_once_a_day(self):
        r = self.client.get(reverse("work:note_today"))
        n = Note.objects.get()
        self.assertRedirects(r, reverse("work:note", args=[n.pk]))
        self.assertIn("## Top 3 today", n.body)
        self.assertEqual(list(n.tags.values_list("name", flat=True)), ["daily"])
        self.assertRedirects(self.client.get(reverse("work:note_today")), reverse("work:note", args=[n.pk]))
        self.assertEqual(Note.objects.count(), 1)

    def test_the_board_has_the_editor_and_search_as_you_type(self):
        Note.objects.create(owner=self.me, title="T")
        html = self.client.get(reverse("work:notes")).content.decode()
        self.assertIn("wnb-editor", html)
        self.assertIn('@input.debounce.300ms="find($el)"', html)
        self.assertIn(reverse("work:note_today"), html)

    def test_the_palette_offers_todays_note(self):
        html = self.client.get(reverse("work:today")).content.decode()
        self.assertIn(reverse("work:note_today"), html)
