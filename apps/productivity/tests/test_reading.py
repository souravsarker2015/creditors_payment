"""The Reader: a note category or an exam subject read as a book, a chapter at a time — where you stopped, chapters
done, time read towards a daily goal and its streak, one line to remember, chapters in your own order, and the way
back ("Continue reading") — and nobody else's."""
import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .. import reading
from ..models import ExamNote, ExamSubject, Note, NoteCategory, ReadingDay, ReadingProgress, WorkSettings

PW = "Str0ng-pass-123"


class Base(TestCase):
    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)
        self.db = NoteCategory.objects.create(owner=self.me, name="Database")
        self.sql = NoteCategory.objects.create(owner=self.me, name="SQL", parent=self.db)
        self.n1 = self.note("Introduction", "word " * 450, self.db)
        self.n2 = self.note("Joins", "word " * 100, self.sql)                    # in a category inside it: a chapter too
        self.s = ExamSubject.objects.create(owner=self.me, name="DBMS")
        for i, (ch, q) in enumerate([("ER", "What is an entity?"), ("SQL", "What is a join?"), ("ER", "What is a key?")]):
            ExamNote.objects.create(owner=self.me, subject=self.s, chapter=ch, question=q, answer="An answer.", order=i)

    def note(self, title, body, cat):
        n = Note.objects.create(owner=self.me, title=title, body=body)
        n.categories.add(cat)
        return n

    def page(self, url):
        html = self.client.get(url).content.decode()
        return json.loads(html.split('id="read-data" type="application/json">')[1].split("</script>")[0])

    def post(self, **data):
        return self.client.post(reverse("work:api_reading"), data).json()


class BookTests(Base):
    def test_a_category_is_a_book_its_notes_the_chapters(self):
        d = self.page(reverse("work:read_book", args=[self.db.pk]))
        self.assertEqual([c["title"] for c in d["chapters"]], ["Introduction", "Joins"])
        self.assertEqual((d["chapters"][0]["words"], d["chapters"][0]["minutes"]), (450, 2))       # ≈ 200 words a minute
        self.assertEqual(d["start"], str(self.n1.pk))
        self.assertTrue(d["canOrder"])

    def test_an_exam_subject_is_a_book_its_chapters_in_question_order(self):
        d = self.page(reverse("work:read_exam", args=[self.s.pk]))
        self.assertEqual([c["key"] for c in d["chapters"]], ["ER", "SQL"])
        self.assertIn("### What is an entity?", d["chapters"][0]["md"])
        self.assertIn("### What is a key?", d["chapters"][0]["md"])
        self.assertTrue(d["review"].endswith(reverse("work:exam_review", args=[self.s.pk])))

    def test_an_empty_book_says_so_instead(self):
        empty = NoteCategory.objects.create(owner=self.me, name="Empty")
        r = self.client.get(reverse("work:read_book", args=[empty.pk]))
        self.assertRedirects(r, reverse("work:notes") + f"?category={empty.pk}")

    def test_one_note_on_its_own_offers_its_book(self):
        d = self.page(reverse("work:read_note", args=[self.n2.pk]))
        self.assertEqual([c["title"] for c in d["chapters"]], ["Joins"])
        self.assertIn(reverse("work:read_book", args=[self.sql.pk]), d["asBook"])

    def test_chapters_in_your_own_order(self):
        self.post(action="order", ids=f"{self.n2.pk},{self.n1.pk}")
        d = self.page(reverse("work:read_book", args=[self.db.pk]))
        self.assertEqual([c["title"] for c in d["chapters"]], ["Joins", "Introduction"])

    def test_the_pages_lead_to_it(self):
        self.assertContains(self.client.get(reverse("work:notes") + f"?category={self.db.pk}"), reverse("work:read_book", args=[self.db.pk]))
        self.assertContains(self.client.get(reverse("work:exam_subject", args=[self.s.pk])), reverse("work:read_exam", args=[self.s.pk]))
        self.assertContains(self.client.get(reverse("work:exam")), reverse("work:read_exam", args=[self.s.pk]))
        self.assertContains(self.client.get(reverse("work:note", args=[self.n1.pk])), "work/read/note/")


class ProgressTests(Base):
    def test_where_you_stopped_is_kept_and_you_come_back_to_it(self):
        self.post(kind="book", book=self.db.pk, chapter=self.n2.pk, position="0.4", seconds="30")
        d = self.page(reverse("work:read_book", args=[self.db.pk]))
        self.assertEqual(d["start"], str(self.n2.pk))                              # the chapter last read
        self.assertEqual(d["progress"][str(self.n2.pk)]["position"], 0.4)
        cr = reading.keep_going(self.me)
        self.assertEqual((cr["title"], cr["chapter"], cr["done"], cr["total"]), ("Database", "Joins", 0, 2))
        self.assertIn(f"?ch={self.n2.pk}", cr["url"])
        self.assertContains(self.client.get(reverse("work:notes")), "Continue reading")
        self.assertContains(self.client.get(reverse("work:today")), cr["url"].replace("&", "&amp;").split("?")[0])

    def test_a_chapter_done_and_one_line_to_remember(self):
        self.post(kind="exam", book=self.s.pk, chapter="ER", position="1", done="1")
        self.post(kind="exam", book=self.s.pk, chapter="ER", takeaway="  Entities are things we keep data about. ")
        row = ReadingProgress.objects.get(subject=self.s, chapter="ER")
        self.assertTrue(row.done and row.done_at)
        self.assertEqual(row.takeaway, "Entities are things we keep data about.")
        d = self.page(reverse("work:read_exam", args=[self.s.pk]))
        self.assertEqual(d["start"], "ER")                                          # (the one last read)
        self.assertEqual(reading.keep_going(self.me, "exam")["done"], 1)
        self.post(kind="exam", book=self.s.pk, chapter="SQL", done="1")
        self.assertIsNone(reading.keep_going(self.me, "exam"))                      # the whole book read: nothing to go on with

    def test_time_read_counts_a_daily_goal_and_its_streak(self):
        today = timezone.localdate()
        for back in (1, 2):
            ReadingDay.objects.create(owner=self.me, day=today - timedelta(days=back), seconds=700)
        stats = self.post(kind="book", book=self.db.pk, chapter=self.n1.pk, seconds="120")["stats"]
        self.assertEqual((stats["today"], stats["goal"], stats["streak"], stats["reached"]), (2.0, 10, 2, False))     # today still counts until it's over
        for _i in range(4):
            stats = self.post(kind="book", book=self.db.pk, chapter=self.n1.pk, seconds="120")["stats"]
        self.assertEqual((stats["today"], stats["streak"], stats["reached"]), (10.0, 3, True))
        self.assertEqual(self.post(kind="book", book=self.db.pk, chapter=self.n1.pk, seconds="99999")["stats"]["today"], 12.0)    # at most 2 min a report
        self.assertEqual(self.post(action="goal", goal="15")["stats"]["goal"], 15)
        self.assertEqual(WorkSettings.for_user(self.me).reading_goal, 15)

    def test_words_dont_count_code_or_marks(self):
        self.assertEqual(reading.words("# Title\n\nSome **bold** words [link](http://x.y)\n\n```\ncode code code\n```"), 5)


class ListeningTests(Base):
    def test_bangla_and_english_voices_can_be_chosen(self):
        r = self.client.get(reverse("work:read_note", args=[self.n1.pk]))
        self.assertContains(r, "js/speech.js")              # each part read by a voice of its own language
        self.assertContains(r, "Bangla voice")
        self.assertContains(r, "English voice")
        self.assertContains(r, "Microsoft Edge")            # what to do on a device with no Bangla voice
        self.assertIn("noBangla", r.context["texts"])


class OnlyMineTests(Base):
    def test_someone_else_cant_read_or_change_them(self):
        other = User.objects.create_superuser("other", "o@example.com", PW)
        self.client.force_login(other)
        for url in (reverse("work:read_book", args=[self.db.pk]), reverse("work:read_note", args=[self.n1.pk]), reverse("work:read_exam", args=[self.s.pk])):
            self.assertEqual(self.client.get(url).status_code, 404, url)
        self.assertEqual(self.client.post(reverse("work:api_reading"), {"kind": "book", "chapter": self.n1.pk, "position": "1"}).status_code, 404)
        self.assertEqual(self.client.post(reverse("work:api_reading"), {"kind": "exam", "book": self.s.pk, "chapter": "ER"}).status_code, 404)
        self.client.post(reverse("work:api_reading"), {"action": "order", "ids": f"{self.n2.pk},{self.n1.pk}"})
        self.assertEqual(Note.objects.get(pk=self.n2.pk).book_order, 0)
        self.assertFalse(ReadingProgress.objects.exists())
