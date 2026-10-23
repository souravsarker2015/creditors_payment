"""Exam notes: subjects with plain questions and answers, added one by one or
pasted as a list, flipped through, and downloaded."""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import exam
from .models import ExamNote, ExamSubject

PW = "Str0ng-pass-123"


class Base(TestCase):
    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)
        self.s = ExamSubject.objects.create(owner=self.me, name="Physics")

    def note(self, question="What is a force?", answer="A push or a pull.", **kw):
        return ExamNote.objects.create(owner=self.me, subject=self.s, question=question, answer=answer, **kw)


class ParseTests(TestCase):
    def test_q_and_a_markers(self):
        text = "Q: What is X?\nA: X is Y.\nmore\n\nstill X\nQ2. Next one?\n\nAnswer: yes"
        self.assertEqual(exam.parse(text), [("What is X?", "X is Y.\nmore\n\nstill X"), ("Next one?", "yes")])

    def test_blocks_split_by_empty_lines(self):
        text = "1. What is osmosis?\nWater moving through a membrane.\n\nNo answer yet\n\n\n"
        self.assertEqual(exam.parse(text), [("What is osmosis?", "Water moving through a membrane."), ("No answer yet", "")])

    def test_two_columns_from_a_spreadsheet(self):
        self.assertEqual(exam.parse("Capital of France\tParis\r\nH2O\tWater"), [("Capital of France", "Paris"), ("H2O", "Water")])

    def test_bangla_markers(self):
        self.assertEqual(exam.parse("প্রশ্ন: সূর্য কী?\nউত্তর: একটি তারা।"), [("সূর্য কী?", "একটি তারা।")])

    def test_download_reads_back_in(self):
        s = ExamSubject(name="Bio")
        notes = [ExamNote(question="Q one?", answer="line 1\n\nline 2"), ExamNote(question="Q two?", answer="")]
        self.assertEqual(exam.parse(exam.as_text(s, notes)), [("Q one?", "line 1\n\nline 2"), ("Q two?", "")])

    def test_empty(self):
        self.assertEqual(exam.parse("  \n\n"), [])


class PageTests(Base):
    def test_home_lists_subjects_and_creates_one(self):
        self.note()
        r = self.client.get(reverse("work:exam"))
        self.assertContains(r, "Physics")
        self.assertContains(r, "1 question")
        r = self.client.post(reverse("work:exam"), {"name": "Chemistry", "exam_date": (timezone.localdate() + timedelta(days=3)).isoformat(), "color": "teal"})
        s = ExamSubject.objects.get(name="Chemistry")
        self.assertRedirects(r, reverse("work:exam_subject", args=[s.pk]))
        self.assertEqual(s.days_left, 3)
        self.assertContains(self.client.get(reverse("work:exam")), "Exam in 3 days")

    def test_same_name_twice_is_refused(self):
        r = self.client.post(reverse("work:exam"), {"name": "physics", "color": "teal"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(ExamSubject.objects.count(), 1)

    def test_search_finds_questions_and_answers(self):
        self.note()
        self.note("Newton's first law?", "Inertia.")
        r = self.client.get(reverse("work:exam"), {"q": "inertia"})
        self.assertContains(r, "Newton&#x27;s first law?")
        self.assertNotContains(r, "What is a force?")

    def test_subject_review_and_download(self):
        self.note()
        self.assertContains(self.client.get(reverse("work:exam_subject", args=[self.s.pk])), "What is a force?")
        r = self.client.get(reverse("work:exam_review", args=[self.s.pk]))
        self.assertEqual(r.context["data"]["which"], "unknown")
        r = self.client.get(reverse("work:exam_export", args=[self.s.pk]))
        self.assertIn("attachment", r["Content-Disposition"])
        self.assertIn("Q: What is a force?\nA: A push or a pull.", r.content.decode())

    def test_review_shows_all_once_everything_is_known(self):
        self.note(is_known=True)
        r = self.client.get(reverse("work:exam_review", args=[self.s.pk]))
        self.assertEqual(r.context["data"]["which"], "all")

    def test_edit_and_delete_subject(self):
        self.note()
        url = reverse("work:exam_subject", args=[self.s.pk])
        self.client.post(url, {"name": "Physics II", "color": "red"})
        self.s.refresh_from_db()
        self.assertEqual((self.s.name, self.s.color), ("Physics II", "red"))
        self.client.post(url, {"action": "delete"})
        self.assertFalse(ExamSubject.objects.exists())
        self.assertFalse(ExamNote.objects.exists())

    def test_someone_elses_subject_is_hidden(self):
        other = User.objects.create_superuser("other", "o@example.com", PW)
        theirs = ExamSubject.objects.create(owner=other, name="Secret")
        n = ExamNote.objects.create(owner=other, subject=theirs, question="?")
        self.assertEqual(self.client.get(reverse("work:exam_subject", args=[theirs.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("work:api_exam_note", args=[n.pk]), {"action": "delete"}).status_code, 404)
        self.assertEqual(self.client.post(reverse("work:api_exam_subject", args=[theirs.pk]), {"action": "add", "question": "x"}).status_code, 404)
        self.assertNotContains(self.client.get(reverse("work:exam"), {"q": "?"}), "Secret")


class ApiTests(Base):
    def test_add_one(self):
        self.note()
        r = self.client.post(reverse("work:api_exam_subject", args=[self.s.pk]), {"action": "add", "question": "  Speed of light?  ", "answer": "3e8 m/s"}).json()
        self.assertTrue(r["ok"])
        self.assertEqual((r["note"]["question"], r["note"]["number"]), ("Speed of light?", 2))
        r = self.client.post(reverse("work:api_exam_subject", args=[self.s.pk]), {"action": "add", "question": " "})
        self.assertEqual(r.status_code, 400)

    def test_add_many(self):
        self.note()
        r = self.client.post(reverse("work:api_exam_subject", args=[self.s.pk]), {"action": "add_many", "text": "Q: a?\nA: 1\nQ: b?\nA: 2"}).json()
        self.assertEqual([(n["question"], n["number"]) for n in r["notes"]], [("a?", 2), ("b?", 3)])
        self.assertEqual(r["message"], "2 questions added.")
        self.assertEqual(list(self.s.notes.values_list("question", flat=True)), ["What is a force?", "a?", "b?"])
        r = self.client.post(reverse("work:api_exam_subject", args=[self.s.pk]), {"action": "add_many", "text": "\n\n"})
        self.assertEqual(r.status_code, 400)

    def test_star_known_update_reset(self):
        n = self.note()
        url = reverse("work:api_exam_note", args=[n.pk])
        self.assertTrue(self.client.post(url, {"action": "star"}).json()["value"])
        self.assertTrue(self.client.post(url, {"action": "known", "value": "1"}).json()["value"])
        self.assertTrue(self.client.post(url, {"action": "known", "value": "1"}).json()["value"])     # setting, not flipping
        self.client.post(url, {"action": "update", "question": "What is force?", "answer": "F = ma"})
        n.refresh_from_db()
        self.assertEqual((n.question, n.answer, n.is_starred, n.is_known), ("What is force?", "F = ma", True, True))
        self.assertEqual(self.client.post(url, {"action": "update", "question": ""}).status_code, 400)
        self.client.post(reverse("work:api_exam_subject", args=[self.s.pk]), {"action": "reset"})
        n.refresh_from_db()
        self.assertFalse(n.is_known)

    def test_delete_and_undo(self):
        n = self.note()
        r = self.client.post(reverse("work:api_exam_note", args=[n.pk]), {"action": "delete"}).json()
        self.assertFalse(ExamNote.objects.exists())
        self.client.post(r["undo"])
        self.assertEqual(ExamNote.objects.get().question, "What is a force?")


class BackupTests(Base):
    def test_backup_round_trip(self):
        import io
        import json
        import zipfile

        from . import services

        self.note()
        r = self.client.get(reverse("work:export"))
        rows = json.loads(zipfile.ZipFile(io.BytesIO(r.content)).read("data.json"))
        self.assertIn("productivity.examnote", {row["model"] for row in rows})
        ExamSubject.objects.all().delete()
        services.restore(self.me, rows)
        self.assertEqual(ExamNote.objects.get().subject.name, "Physics")


class SearchTests(Base):
    def test_found_by_both_searches(self):
        n = self.note("What is entropy?", "Disorder.")
        res = self.client.get(reverse("work:api_search") + "?q=entropy").json()
        self.assertEqual([(x["kind"], x["url"]) for x in res["results"]], [("exam", reverse("work:exam_subject", args=[self.s.pk]) + f"#q{n.pk}")])
        self.assertContains(self.client.get(reverse("search") + "?q=entropy"), "What is entropy?")
