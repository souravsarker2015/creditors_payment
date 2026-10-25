"""Exam notes: subjects with plain questions and answers, added one by one or
pasted as a list, flipped through, and downloaded."""
import json
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


def qa(notes):
    return [(n["question"], n["answer"]) for n in notes]


class ParseTests(TestCase):
    def test_q_and_a_markers(self):
        text = "Q: What is X?\nA: X is Y.\nmore\n\nstill X\nQ2. Next one?\n\nAnswer: yes"
        self.assertEqual(qa(exam.parse(text)), [("What is X?", "X is Y.\nmore\n\nstill X"), ("Next one?", "yes")])

    def test_bold_labels(self):
        text = "**Q1: What is TCP?**\n**Answer:** A reliable protocol.\n\n- ordered\n\n**Q2: What is UDP?**\n\n**Answer:**\n\nFast."
        self.assertEqual(qa(exam.parse(text)), [("What is TCP?", "A reliable protocol.\n\n- ordered"), ("What is UDP?", "Fast.")])

    def test_blocks_split_by_empty_lines(self):
        text = "1. What is osmosis?\nWater moving through a membrane.\n\nNo answer yet\n\n\n"
        self.assertEqual(qa(exam.parse(text)), [("What is osmosis?", "Water moving through a membrane."), ("No answer yet", "")])

    def test_two_columns_from_a_spreadsheet(self):
        self.assertEqual(qa(exam.parse("Capital of France\tParis\r\nH2O\tWater")), [("Capital of France", "Paris"), ("H2O", "Water")])

    def test_bangla_markers(self):
        self.assertEqual(qa(exam.parse("প্রশ্ন: সূর্য কী?\nউত্তর: একটি তারা।")), [("সূর্য কী?", "একটি তারা।")])

    def test_markdown_headings_as_written_by_an_ai(self):
        text = ("# Python questions\n\nHere they are:\n\n## 1. What is the GIL?\n\nA **lock**.\n\n### Example\n\n"
                "```python\nimport threading\n\n# not a question\n```\n\n---\n\n## 2. What is a decorator?\nA wrapper.\n\n---\n")
        self.assertEqual(qa(exam.parse(text)), [
            ("What is the GIL?", "A **lock**.\n\n### Example\n\n```python\nimport threading\n\n# not a question\n```"),
            ("What is a decorator?", "A wrapper."),
        ])

    def test_chapters_from_headings(self):
        text = "# Basics\n## What is a list?\nMutable.\n## What is a tuple?\nImmutable.\n# OOP\n## What is a class?\nA blueprint."
        self.assertEqual([(n["chapter"], n["question"]) for n in exam.parse(text, chapter="Ignored")],
                         [("Basics", "What is a list?"), ("Basics", "What is a tuple?"), ("OOP", "What is a class?")])

    def test_one_heading_above_the_questions_is_their_chapter(self):
        self.assertEqual({n["chapter"] for n in exam.parse("# Waves\n## What is a wave?\nA disturbance.\n## Frequency?\n$f = 1/T$")}, {"Waves"})

    def test_chapter_given_when_the_text_has_none(self):
        self.assertEqual({n["chapter"] for n in exam.parse("## A?\na\n## B?\nb", chapter="Ch 2")}, {"Ch 2"})

    def test_bold_questions(self):
        text = "Sure!\n\n**1. What is inertia?**\nResistance.\n\n**Example:** a book.\n\n**2. What is mass?**\nAmount of matter."
        self.assertEqual(qa(exam.parse(text)), [("What is inertia?", "Resistance.\n\n**Example:** a book."), ("What is mass?", "Amount of matter.")])

    def test_code_with_empty_lines_stays_whole(self):
        text = "What is DNA?\n```\na\n\nb\n```\n\nWhat is RNA?\nA molecule."
        self.assertEqual(qa(exam.parse(text)), [("What is DNA?", "```\na\n\nb\n```"), ("What is RNA?", "A molecule.")])

    def test_formulas_are_kept(self):
        self.assertEqual(qa(exam.parse("## Pythagoras?\n\\[ a^2 + b^2 = c^2 \\]")), [("Pythagoras?", "\\[ a^2 + b^2 = c^2 \\]")])

    def test_download_reads_back_in(self):
        s = ExamSubject(name="Bio")
        notes = [ExamNote(pk=1, question="Q one?", answer="line 1\n\nline 2"), ExamNote(pk=2, question="Q two?", answer="", chapter="Cells"),
                 ExamNote(pk=3, question="Q three?", answer="```\nx\n```", chapter="Cells")]
        self.assertEqual([(n["question"], n["answer"], n["chapter"]) for n in exam.parse(exam.as_text(s, notes))],
                         [("Q one?", "line 1\n\nline 2", ""), ("Q two?", "", "Cells"), ("Q three?", "```\nx\n```", "Cells")])

    def test_ordered_by_chapter(self):
        notes = [ExamNote(pk=1, question="a", chapter="B", order=2), ExamNote(pk=2, question="b", order=1), ExamNote(pk=3, question="c", chapter="A", order=3),
                 ExamNote(pk=4, question="d", chapter="B", order=4)]
        self.assertEqual([n.question for n in exam.ordered(notes)], ["b", "a", "d", "c"])

    def test_plain_snippet(self):
        self.assertEqual(exam.plain("## Hi\n- **bold** and `code` $x$ [link](http://x)"), "Hi bold and code x link")

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

    def test_first_visit_explains_how_it_works(self):
        self.s.delete()
        r = self.client.get(reverse("work:exam"))
        self.assertContains(r, "Add a subject")
        self.assertContains(r, "Write questions and answers")

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


class OverviewTests(Base):
    def test_every_question_in_order_for_reading(self):
        self.note("Late?", chapter="B")
        self.note("Loose?")
        r = self.client.get(reverse("work:exam_overview", args=[self.s.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual([n["question"] for n in r.context["data"]["notes"]], ["Late?", "Loose?"])
        self.assertEqual(r.context["data"]["review"], reverse("work:exam_review", args=[self.s.pk]))
        self.assertContains(self.client.get(reverse("work:exam_subject", args=[self.s.pk])), reverse("work:exam_overview", args=[self.s.pk]))
        self.assertContains(self.client.get(reverse("work:exam")), reverse("work:exam_overview", args=[self.s.pk]))

    def test_empty_subject_says_so(self):
        self.assertContains(self.client.get(reverse("work:exam_overview", args=[self.s.pk])), "Add some questions first.")

    def test_someone_elses_is_hidden(self):
        theirs = ExamSubject.objects.create(owner=User.objects.create_superuser("o2", "o2@example.com", PW), name="X")
        self.assertEqual(self.client.get(reverse("work:exam_overview", args=[theirs.pk])).status_code, 404)


class ApiTests(Base):
    def test_add_one(self):
        self.note()
        r = self.client.post(reverse("work:api_exam_subject", args=[self.s.pk]), {"action": "add", "question": "  Speed of light?  ", "answer": "3e8 m/s"}).json()
        self.assertTrue(r["ok"])
        self.assertEqual((r["note"]["question"], r["note"]["chapter"]), ("Speed of light?", ""))
        r = self.client.post(reverse("work:api_exam_subject", args=[self.s.pk]), {"action": "add", "question": " "})
        self.assertEqual(r.status_code, 400)

    def test_add_many(self):
        self.note()
        url = reverse("work:api_exam_subject", args=[self.s.pk])
        text = "Q: a?\nA: 1\nQ: b?\nA: 2\nQ: **What is a FORCE?**\nA: again\nQ: b?\nA: twice"
        r = self.client.post(url, {"action": "add_many", "text": text, "preview": "1"}).json()
        self.assertEqual([(n["question"], n["dupe"]) for n in r["found"]], [("a?", False), ("b?", False), ("What is a FORCE?", True), ("b?", True)])
        self.assertEqual(r["new"], 2)
        self.assertEqual(self.s.notes.count(), 1)                       # a preview adds nothing
        r = self.client.post(url, {"action": "add_many", "text": text, "chapter": "Ch 1"}).json()
        self.assertEqual([(n["question"], n["chapter"]) for n in r["notes"]], [("a?", "Ch 1"), ("b?", "Ch 1")])
        self.assertEqual(r["message"], "2 questions added. 2 were already there.")
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


class RevisionTests(Base):
    def test_review_answers_count_misses(self):
        n = self.note()
        url = reverse("work:api_exam_note", args=[n.pk])
        self.client.post(url, {"action": "review", "knew": "0"})
        self.client.post(url, {"action": "review", "knew": "0"})
        self.assertEqual(self.client.post(url, {"action": "review", "knew": "1"}).json()["misses"], 2)
        n.refresh_from_db()
        self.assertTrue(n.is_known and n.reviewed_at)
        r = self.client.get(reverse("work:exam"))
        self.assertContains(r, "1 missed in reviews")
        self.assertContains(r, "Revised")

    def test_review_page_by_chapter_and_missed(self):
        self.note(chapter="Motion")
        self.note("Another?", misses=2)
        r = self.client.get(reverse("work:exam_review", args=[self.s.pk]), {"which": "missed", "chapter": "Motion"})
        self.assertEqual((r.context["data"]["which"], r.context["data"]["chapter"], r.context["data"]["chapters"]), ("missed", "Motion", ["Motion"]))
        r = self.client.get(reverse("work:exam_review", args=[self.s.pk]), {"chapter": "Nope"})
        self.assertEqual(r.context["data"]["chapter"], "")

    def test_chapters_rename_and_move(self):
        a, b = self.note(chapter="Old"), self.note("Two?", chapter="Old")
        self.client.post(reverse("work:api_exam_subject", args=[self.s.pk]), {"action": "rename_chapter", "old": "Old", "chapter": "New"})
        self.assertEqual(set(self.s.notes.values_list("chapter", flat=True)), {"New"})
        other = ExamSubject.objects.create(owner=self.me, name="Maths")
        r = self.client.post(reverse("work:api_exam_note", args=[a.pk]), {"action": "update", "question": "One?", "answer": "", "chapter": " Ch ", "subject": other.pk}).json()
        self.assertEqual((r["note"]["chapter"], ExamNote.objects.get(pk=a.pk).subject), ("Ch", other))
        stranger = ExamSubject.objects.create(owner=User.objects.create_superuser("x", "x@example.com", PW), name="Theirs")
        r = self.client.post(reverse("work:api_exam_note", args=[b.pk]), {"action": "update", "question": "Two?", "subject": stranger.pk})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(ExamNote.objects.get(pk=b.pk).subject, self.s)

    def test_subject_page_lists_chapters_in_order(self):
        self.note("Late?", chapter="B")
        self.note("Loose?")
        self.note("Early?", chapter="A")
        notes = self.client.get(reverse("work:exam_subject", args=[self.s.pk])).context["data"]["notes"]
        self.assertEqual([(n["number"], n["question"]) for n in notes], [(1, "Late?"), (2, "Loose?"), (3, "Early?")])
        self.note("More B?", chapter="B")                   # joins its chapter, not the end
        notes = self.client.get(reverse("work:exam_subject", args=[self.s.pk])).context["data"]["notes"]
        self.assertEqual([n["question"] for n in notes], ["Late?", "More B?", "Loose?", "Early?"])


class OrganiseTests(Base):
    def api(self, **data):
        return self.client.post(reverse("work:api_exam_subject", args=[self.s.pk]), data)

    def test_new_questions_go_last(self):
        a = self.note(order=5)
        self.api(action="add", question="Second?")
        self.api(action="add_many", text="Q: Third?\nA: x\nQ: Fourth?\nA: y")
        self.assertEqual(list(self.s.notes.values_list("question", flat=True)), [a.question, "Second?", "Third?", "Fourth?"])

    def test_only_the_ticked_ones_are_added(self):
        r = self.api(action="add_many", text="Q: A?\nA: 1\nQ: B?\nA: 2\nQ: C?\nA: 3", pick="0,2").json()
        self.assertEqual([n["question"] for n in r["notes"]], ["A?", "C?"])

    def test_drag_order_and_chapter(self):
        a, b, c = self.note("A?"), self.note("B?", chapter="X"), self.note("C?")
        other = ExamNote.objects.create(owner=User.objects.create_superuser("o", "o@example.com", PW),
                                        subject=ExamSubject.objects.create(owner=User.objects.get(username="o"), name="Theirs"), question="?")
        self.api(action="order", rows=json.dumps([[c.pk, "X"], [a.pk, ""], [b.pk, "X"], [other.pk, "hack"]]))
        self.assertEqual([(n.question, n.chapter) for n in self.s.notes.all()], [("C?", "X"), ("A?", ""), ("B?", "X")])
        other.refresh_from_db()
        self.assertEqual((other.order, other.chapter), (0, ""))
        self.assertEqual(self.api(action="order", rows="nope").status_code, 400)

    def test_bulk(self):
        a, b, c = self.note("A?"), self.note("B?"), self.note("C?")
        ids = f"{a.pk},{b.pk}"
        self.api(action="bulk", op="known", ids=ids)
        self.assertEqual(set(self.s.notes.filter(is_known=True).values_list("pk", flat=True)), {a.pk, b.pk})
        self.api(action="bulk", op="chapter", ids=ids, chapter="Ch")
        self.assertEqual(set(self.s.notes.filter(chapter="Ch").values_list("pk", flat=True)), {a.pk, b.pk})
        maths = ExamSubject.objects.create(owner=self.me, name="Maths")
        r = self.api(action="bulk", op="move", ids=str(c.pk), subject=maths.pk).json()
        self.assertEqual((r["message"], ExamNote.objects.get(pk=c.pk).subject), ("1 question moved to Maths.", maths))
        r = self.api(action="bulk", op="delete", ids=ids).json()
        self.assertEqual((len(r["undo"]), self.s.notes.count()), (2, 0))
        for url in r["undo"]:
            self.client.post(url)
        self.assertEqual(self.s.notes.count(), 2)
        self.assertEqual(self.api(action="bulk", op="weird", ids=ids).status_code, 400)

    def test_undo_a_review_answer(self):
        n = self.note(misses=1)
        url = reverse("work:api_exam_note", args=[n.pk])
        self.client.post(url, {"action": "review", "knew": "0"})
        self.client.post(url, {"action": "unreview", "known": "0", "misses": "1"})
        n.refresh_from_db()
        self.assertEqual((n.misses, n.is_known), (1, False))

    def test_moving_one_puts_it_last_in_the_other_subject(self):
        maths = ExamSubject.objects.create(owner=self.me, name="Maths")
        ExamNote.objects.create(owner=self.me, subject=maths, question="Old?", order=7)
        n = self.note()
        self.client.post(reverse("work:api_exam_note", args=[n.pk]), {"action": "update", "question": n.question, "subject": maths.pk})
        self.assertEqual(list(maths.notes.values_list("question", flat=True)), ["Old?", n.question])

    def test_today_shows_a_close_exam(self):
        self.s.exam_date = timezone.localdate() + timedelta(days=3)
        self.s.save()
        self.note()
        r = self.client.get(reverse("work:today"))
        self.assertContains(r, "Exam in 3 days")
        self.assertContains(r, "1 question to learn")
        self.s.exam_date = timezone.localdate() + timedelta(days=30)
        self.s.save()
        self.assertNotContains(self.client.get(reverse("work:today")), "Exam in 30 days")


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
