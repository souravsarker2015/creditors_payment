"""Long notes: read in parts (each ≈ 5–10 minutes, its place and tick kept), sent light (Bangla as it is, compressed),
and brought into exam notes whole (a note in headings with one "প্রশ্ন:" line in it, a chapter's opening words)."""
import gzip
import re

from django.contrib.auth.models import User
from django.template import Context, Template
from django.test import TestCase
from django.urls import reverse

from .. import exam, reading
from ..models import ExamNote, ExamSubject, Note, NoteCategory, ReadingProgress

PW = "Str0ng-pass-123"


def para(n, word="শব্দ"):
    return " ".join([word] * n)


def long_note():
    """A note like a real guide: a title with an intro, parts (#), topics (##), sub-topics (###), code, a table."""
    out = ["# গাইড", "", "> " + para(30), ""]
    for p in range(1, 5):
        out += [f"# পর্ব {p}", "", para(40), ""]
        for t in range(1, 5):
            out += [f"## {p}.{t} বিষয়", "", para(260), "", "```python", "# not a heading", "x = 1", "```", "",
                    f"### {p}.{t}.1 খুঁটিনাটি", "", para(120), "", "| a | b |", "|---|---|", "| 1 | 2 |", ""]
    return "\n".join(out)


def norm(text):
    return re.sub(r"\s+", " ", text).strip()


class SplitTests(TestCase):
    def test_a_short_note_stays_one_chapter(self):
        self.assertEqual(reading.split("# Title\n\n" + para(300)), [("", "# Title\n\n" + para(300))])

    def test_a_long_note_in_parts_of_minutes_nothing_lost(self):
        md = long_note()
        parts = reading.split(md)
        self.assertGreaterEqual(len(parts), 4)                              # (its four parts: ≈ 8 min each)
        for title, text in parts:
            self.assertTrue(title)                                            # each part named by its first heading
            self.assertLessEqual(reading.words(text), reading.MOST * 1.25)
            self.assertEqual(text.count("```") % 2, 0, title)                 # never cut inside a code block
        self.assertEqual(norm(" ".join(t for _h, t in parts)), norm(md))     # every word still there, in order

    def test_no_headings_cut_between_paragraphs(self):
        md = "\n\n".join(para(300) for _ in range(12))
        parts = reading.split(md)
        self.assertGreater(len(parts), 2)
        self.assertEqual(norm(" ".join(t for _h, t in parts)), norm(md))


class ReaderInPartsTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)
        self.note = Note.objects.create(owner=self.me, title="গাইড", body=long_note())
        self.short = Note.objects.create(owner=self.me, title="Short", body="# Short\n\nA few words.")
        self.book = NoteCategory.objects.create(owner=self.me, name="Banking")
        self.note.categories.set([self.book])
        self.short.categories.set([self.book])

    def page(self, url):
        return self.client.get(url).context["data"]

    def api(self, **fields):
        return self.client.post(reverse("work:api_reading"), fields)

    def test_the_parts_are_the_chapters_and_each_keeps_its_place(self):
        d = self.page(reverse("work:read_note", args=[self.note.pk]))
        keys = [c["key"] for c in d["chapters"]]
        self.assertEqual(keys[:2], [f"{self.note.pk}.1", f"{self.note.pk}.2"])
        self.assertTrue(all(c["minutes"] <= 15 for c in d["chapters"]))
        self.assertTrue(all(c["note"] == self.note.pk for c in d["chapters"]))      # (Edit this note: the note itself)
        self.assertEqual(self.api(kind="note", chapter=keys[2], position="0.5", seconds="30").status_code, 200)
        self.api(kind="note", chapter=keys[0], position="1", done="1")
        rows = {r.chapter: r for r in ReadingProgress.objects.filter(owner=self.me, note=self.note)}
        self.assertEqual((rows["3"].position, rows["1"].done), (0.5, True))
        d = self.page(reverse("work:read_note", args=[self.note.pk]))
        self.assertEqual(d["progress"][keys[2]]["position"], 0.5)
        self.assertEqual(d["start"], keys[0])                       # the last one touched (finished) → … reopened at the latest
        cr = reading.keep_going(self.me)
        self.assertIn("গাইড ·", cr["chapter"])
        self.assertEqual(cr["total"], len(keys))
        self.assertEqual(cr["done"], 1)

    def test_in_a_book_the_note_heads_its_parts_and_moves_with_them(self):
        d = self.page(reverse("work:read_book", args=[self.book.pk]))
        parts = [c for c in d["chapters"] if c.get("note") == self.note.pk and c.get("pieces")]
        self.assertTrue(parts and all(c["part"] == "গাইড" for c in parts))
        d = self.page(reverse("work:read_book", args=[self.book.pk]) + f"?ch={self.note.pk}")     # asked for by the note: its first part
        self.assertEqual(d["start"], f"{self.note.pk}.1")
        self.client.post(reverse("work:api_reading"), {"action": "order", "ids": f"{self.short.pk},{self.note.pk}"})
        d = self.page(reverse("work:read_book", args=[self.book.pk]))
        self.assertEqual(d["chapters"][0]["key"], str(self.short.pk))

    def test_a_long_exam_chapter_is_read_in_parts_never_inside_a_question(self):
        s = ExamSubject.objects.create(owner=self.me, name="Banking")
        for i in range(40):
            ExamNote.objects.create(owner=self.me, subject=s, chapter="Loans", question=f"Question {i}?", answer=para(150), order=i)
        chapters = reading.exam_chapters(s)
        self.assertGreater(len(chapters), 1)
        self.assertTrue(all(c["part"] == "Loans" for c in chapters))
        for c in chapters:
            self.assertTrue(c["md"].lstrip().startswith("#"))               # each part starts at a question (or section)
        self.assertEqual(sum(c["md"].count("### Question") for c in chapters), 40)
        self.api(kind="exam", book=s.pk, chapter=chapters[1]["key"], position="0.3")
        self.assertEqual(reading.progress(self.me, "exam", chapters, subject=s)[chapters[1]["key"]]["position"], 0.3)


class ExamFromLongNoteTests(TestCase):
    def test_headings_win_over_one_stray_question_line_and_nothing_is_lost(self):
        md = long_note().replace("## 2.3 বিষয়\n\n", "## 2.3 বিষয়\n\n**প্রশ্ন:** কোনো গ্রাহকের কি আগের লোন আছে?\n\n", 1)
        found = exam.parse(md)
        topics = [x for x in found if re.match(r"\d\.\d বিষয়", x["question"])]
        self.assertEqual(len(topics), 16)                                    # every ## topic a question
        self.assertTrue(all(x["chapter"].startswith("পর্ব") for x in topics))  # its part the chapter
        blob = norm(" ".join(x["question"] + " " + x["answer"] for x in found))
        self.assertIn(norm(para(40)), blob)                                 # a part's opening words: kept
        self.assertIn("প্রশ্ন", blob)

    def test_a_filler_line_under_a_title_isnt_a_question(self):
        found = exam.parse("# Python questions\n\nHere they are:\n\n## What is the GIL?\n\nA lock.\n\n## What is a list?\n\nA sequence.")
        self.assertEqual([x["question"] for x in found], ["What is the GIL?", "What is a list?"])


class LightPagesTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)

    def test_bangla_is_sent_as_it_is_and_a_script_end_cant_break_out(self):
        html = Template("{% load work %}{{ v|json_page:'x' }}").render(Context({"v": {"t": "বাংলা </script><b>&"}}))
        self.assertIn("বাংলা", html)
        self.assertNotIn("\\u09", html)
        self.assertNotIn("</script><b>", html)
        self.assertEqual(html.count("</script>"), 1)

    def test_pages_are_compressed(self):
        note = Note.objects.create(owner=self.me, title="Big", body=long_note())
        r = self.client.get(reverse("work:note", args=[note.pk]), HTTP_ACCEPT_ENCODING="gzip")
        self.assertEqual(r.get("Content-Encoding"), "gzip")
        self.assertLess(len(r.content), len(gzip.decompress(r.content)) / 4)
