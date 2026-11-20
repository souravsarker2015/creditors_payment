"""Chapters with sections: an exam chapter's sections (written, pasted, moved, downloaded, read in the Reader), a note's
## headings as its sections, the categories inside a note book as its parts — and the reading reminder and week."""
import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .. import exam, reading
from ..models import ExamNote, ExamSubject, Note, NoteCategory, ReadingDay, WorkSettings

PW = "Str0ng-pass-123"


class Base(TestCase):
    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)
        self.s = ExamSubject.objects.create(owner=self.me, name="DBMS")

    def q(self, question, chapter="", section="", order=0):
        return ExamNote.objects.create(owner=self.me, subject=self.s, question=question, answer="An answer.", chapter=chapter, section=section,
                                       order=order or exam.next_order(self.s))

    def reader(self, url):
        html = self.client.get(url).content.decode()
        return json.loads(html.split('id="read-data" type="application/json">')[1].split("</script>")[0])


class ExamSectionTests(Base):
    def test_pasted_headings_three_levels_deep(self):
        found = exam.parse("# Databases\n## ER model\n### What is an entity?\nA thing.\n### What is a key?\nId.\n## SQL\n### What is a join?\nCombines.\n"
                           "# Networks\n### What is TCP?\nA protocol.")
        self.assertEqual([(n["chapter"], n["section"], n["question"]) for n in found], [
            ("Databases", "ER model", "What is an entity?"), ("Databases", "ER model", "What is a key?"),
            ("Databases", "SQL", "What is a join?"), ("Networks", "", "What is TCP?")])
        old = exam.parse("# Ch1\n## What is A?\nIt.\n## What is B?\nIt.")                 # chapters and questions, as before
        self.assertEqual([(n["chapter"], n["section"]) for n in old], [("Ch1", ""), ("Ch1", "")])

    def test_a_spreadsheet_with_a_section_column(self):
        found = exam.parse("Question,Answer,Chapter,Section\nWhat is X?,An x,Ch1,S1\nWhat is Y?,A y,Ch1,S2\n")
        self.assertEqual([(n["chapter"], n["section"]) for n in found], [("Ch1", "S1"), ("Ch1", "S2")])

    def test_downloaded_and_read_back_the_same(self):
        self.q("What is an entity?", "ER", "Entities")
        self.q("What is a join?", "SQL")
        self.q("What is a key?", "ER", "Keys")
        self.q("What is a weak entity?", "ER", "Entities")
        text = exam.as_text(self.s, list(self.s.notes.all()))
        back = [(n["chapter"], n["section"], n["question"]) for n in exam.parse(text)]
        self.assertEqual(back, [("ER", "Entities", "What is an entity?"), ("ER", "Entities", "What is a weak entity?"), ("ER", "Keys", "What is a key?"),
                                ("SQL", "", "What is a join?")])

    def test_written_changed_picked_and_moved(self):
        api = reverse("work:api_exam_subject", args=[self.s.pk])
        r = self.client.post(api, {"action": "add", "question": "What is 1NF?", "chapter": "Normalization", "section": "Normal forms"}).json()
        n = ExamNote.objects.get(pk=r["note"]["id"])
        self.assertEqual((n.chapter, n.section, r["note"]["section"]), ("Normalization", "Normal forms", "Normal forms"))
        self.assertEqual(r["chapters"][0]["sections"], ["Normal forms"])
        self.client.post(reverse("work:api_exam_note", args=[n.pk]), {"action": "update", "question": n.question, "answer": "", "section": "Anomalies"})
        self.assertEqual(ExamNote.objects.get(pk=n.pk).section, "Anomalies")
        other = self.q("What is 2NF?", "Normalization")
        self.client.post(api, {"action": "bulk", "op": "section", "ids": f"{n.pk},{other.pk}", "section": "Forms"})
        self.assertEqual(set(self.s.notes.values_list("section", flat=True)), {"Forms"})
        third = self.q("What is a lock?", "Transactions", "Locks")
        r = self.client.post(api, {"action": "move", "id": third.pk, "before": n.pk}).json()       # dropped among them: their chapter and section
        self.assertEqual((r["chapter"], r["section"]), ("Normalization", "Forms"))

    def test_a_section_stays_together_in_its_chapter(self):
        a = self.q("A1", "Ch", "Alpha")
        b = self.q("B1", "Ch", "Beta")
        a2 = self.q("A2", "Ch", "Alpha")
        loose = self.q("Plain", "Ch")
        self.assertEqual(list(exam.in_order(self.s.notes.all(), self.s).values_list("pk", flat=True)), [a.pk, a2.pk, b.pk, loose.pk])
        self.assertEqual([n.pk for n in exam.ordered(list(self.s.notes.all()))], [a.pk, a2.pk, b.pk, loose.pk])

    def test_the_reader_shows_sections_and_their_questions(self):
        self.q("What is 1NF?", "Normalization", "Normal forms")
        self.q("What is 2NF?", "Normalization", "Normal forms")
        self.q("What is an anomaly?", "Normalization", "Anomalies")
        ch = self.reader(reverse("work:read_exam", args=[self.s.pk]))["chapters"][0]
        self.assertIn("## Normal forms\n\n### What is 1NF?", ch["md"])
        self.assertEqual([(x["title"], x["level"], x["n"]) for x in ch["sections"]], [("Normal forms", 2, 0), ("Anomalies", 2, 1)])

    def test_search_finds_a_section(self):
        self.q("What is 1NF?", "Normalization", "Normal forms")
        self.assertEqual(exam.matching(self.s.notes.all(), "normal forms").count(), 1)


class NoteSectionTests(Base):
    def test_a_notes_headings_are_its_sections(self):
        s = reading.sections("# Title\n\nIntro.\n\n## One\nwords here\n```\n## not a heading\n```\n## Two **bold**\nmore\n### a part of two\nx")
        self.assertEqual([(x["title"], x["level"], x["n"]) for x in s], [("One", 2, 0), ("Two bold", 2, 1)])
        self.assertEqual(reading.sections("No headings at all."), [])

    def test_the_categories_inside_a_book_are_its_parts(self):
        db = NoteCategory.objects.create(owner=self.me, name="Database")
        sql = NoteCategory.objects.create(owner=self.me, name="SQL", parent=db)
        joins = NoteCategory.objects.create(owner=self.me, name="Joins", parent=sql)
        made = []
        for title, cat in (("Deep joins", joins), ("Intro", db), ("Select", sql)):
            n = Note.objects.create(owner=self.me, title=title, body="## A\nx\n## B\ny")
            n.categories.add(cat)
            made.append(n)
        chapters = self.reader(reverse("work:read_book", args=[db.pk]))["chapters"]
        self.assertEqual([(c["title"], c["part"]) for c in chapters], [("Intro", ""), ("Select", "SQL"), ("Deep joins", "SQL › Joins")])
        self.assertEqual(len(chapters[0]["sections"]), 2)


class ReadingHabitTests(Base):
    def test_a_week_of_reading(self):
        today = timezone.localdate()
        ReadingDay.objects.create(owner=self.me, day=today - timedelta(days=2), seconds=900)
        ReadingDay.objects.create(owner=self.me, day=today, seconds=120)
        stats = reading.day_stats(self.me)
        self.assertEqual(len(stats["week"]), 7)
        self.assertEqual([w["min"] for w in stats["week"]], [0, 0, 0, 0, 15, 0, 2])
        self.assertEqual((stats["week"][4]["met"], stats["week"][-1]["today"], stats["weekMin"]), (True, True, 17))

    def test_the_reminder_is_set_and_asked(self):
        api = reverse("work:api_reading")
        self.assertEqual(self.client.post(api, {"action": "goal", "remind": "20:30"}).json()["stats"]["remind"], "20:30")
        self.assertEqual(WorkSettings.objects.get(owner=self.me).reading_remind_at.strftime("%H:%M"), "20:30")
        self.assertEqual(self.client.post(api, {"action": "goal", "remind": "25:00"}).status_code, 400)
        r = self.client.get(reverse("work:api_read_nudge")).json()
        self.assertTrue(r["due"])
        ReadingDay.objects.create(owner=self.me, day=timezone.localdate(), seconds=11 * 60)       # goal (10 min) reached: no nudge
        self.assertFalse(self.client.get(reverse("work:api_read_nudge")).json()["due"])
        self.client.post(api, {"action": "goal", "remind": ""})
        self.assertIsNone(WorkSettings.objects.get(owner=self.me).reading_remind_at)
        self.assertIn('"readRemind": ""', self.client.get(reverse("work:today")).content.decode())
