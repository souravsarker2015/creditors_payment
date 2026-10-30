"""Notes and exam notes held up against what they're used for: nothing written is lost (a sign-in that
ran out, a save that failed, a second device), a pasted list reads as it was meant, a subject of
thousands stays quick, links survive a rename, and exams reach the calendar, Today and the morning email."""
import io
import json
import uuid
import zipfile
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings
from django.contrib.auth.models import User
from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from . import emails, exam, linked, notes_import, services
from .models import ExamCategory, ExamNote, ExamSubject, Note, NoteVersion, Project, Tag

PW = "Str0ng-pass-123"


class Base(TestCase):
    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)
        self.today = timezone.localdate()

    def note(self, title, body="", **kw):
        return Note.objects.create(owner=self.me, title=title, body=body, **kw)

    def subject(self, name="Physics", **kw):
        return ExamSubject.objects.create(owner=self.me, name=name, **kw)

    def question(self, s, q, a="", **kw):
        return ExamNote.objects.create(owner=self.me, subject=s, question=q, answer=a, **kw)

    def save(self, **fields):
        return self.client.post(reverse("work:api_note_save"), fields).json()

    def action(self, note, **fields):
        return self.client.post(reverse("work:api_note_action", args=[note.pk]), fields).json()


class PastedListsTests(SimpleTestCase):
    def one(self, text):
        return [(n["question"], n["answer"]) for n in exam.parse(text)]

    def test_words_that_look_like_labels(self):
        self.assertEqual(self.one("## What is RL?\nQ-learning is a method.\n\n## What is SARSA?\nOn-policy."),
                         [("What is RL?", "Q-learning is a method."), ("What is SARSA?", "On-policy.")])
        self.assertEqual(self.one("## Proof?\nQ.E.D. means proved.\n\n## Other?\nYes."), [("Proof?", "Q.E.D. means proved."), ("Other?", "Yes.")])
        self.assertEqual(self.one("## Best search?\nA-star finds the path.\n\n## Other?\nDijkstra."),
                         [("Best search?", "A-star finds the path."), ("Other?", "Dijkstra.")])

    def test_labels_still_read(self):
        for text in ("Q: One?\nA: Yes", "Q1. One?\nA1. Yes", "**Q1:** One?\n**A:** Yes", "Q.1 One?\nAns: Yes", "Q - One?\nA - Yes", "Q1-One?\nAnswer: Yes"):
            self.assertEqual(self.one(text), [("One?", "Yes")], text)
        self.assertEqual(self.one("প্রশ্ন ১: কোষ কী?\nউত্তর: জীবের একক।"), [("কোষ কী?", "জীবের একক।")])

    def test_multiple_choice_keeps_its_choices_with_the_question(self):
        for options in ("a) 4\nb) 7\nc) 9", "A) 4\nB) 7\nC) 9", "A. 4\nB. 7\nC. 9", "(a) 4\n(b) 7\n(c) 9", "ক) ৪\nখ) ৭\nগ) ৯"):
            (q, a), = self.one(f"Q1. Which is prime?\n{options}\nAnswer: b")
            self.assertEqual(q, f"Which is prime?\n{options}")
            self.assertEqual(a, "b")

    def test_a_list_as_the_answer_stays_the_answer(self):
        self.assertEqual(self.one("Q: What types?\na) Static\nb) Dynamic\n\nQ: Next?\nA: Yes"),
                         [("What types?", "a) Static\nb) Dynamic"), ("Next?", "Yes")])

    def test_a_question_on_several_lines(self):
        self.assertEqual(self.one("Q: First line\nof the question\nA: The answer"), [("First line\nof the question", "The answer")])

    def test_an_answer_in_code_after_its_label(self):
        self.assertEqual(self.one("Q: Show it\nA: ```\nQ: not a question\n```\n\nQ: Next\nA: Yes"),
                         [("Show it", "```\nQ: not a question\n```"), ("Next", "Yes")])

    def test_a_numbered_list_of_questions(self):
        self.assertEqual(self.one("1. What is a cell?\n2. What is a tissue?\n3. What is an organ?"),
                         [("What is a cell?", ""), ("What is a tissue?", ""), ("What is an organ?", "")])
        self.assertEqual(self.one("১. কোষ কী?\n২. টিস্যু কী?"), [("কোষ কী?", ""), ("টিস্যু কী?", "")])

    def test_numbers_inside_answers_dont_split_them(self):
        found = self.one("What are the steps?\n1. one\n2. two\n\nWhat else?\n1. three")
        self.assertEqual(found, [("What are the steps?", "1. one\n2. two"), ("What else?", "1. three")])

    def test_csv_and_exports(self):
        self.assertEqual(self.one("question,answer\nCapital of France,Paris\n\"Japan, capital\",\"Tokyo, big\""),
                         [("Capital of France", "Paris"), ("Japan, capital", "Tokyo, big")])
        self.assertEqual(self.one("Capital of France,Paris\nCapital of Japan,Tokyo\nCapital of Peru,Lima"),
                         [("Capital of France", "Paris"), ("Capital of Japan", "Tokyo"), ("Capital of Peru", "Lima")])
        self.assertEqual(exam.parse("Chapter,Front,Back\nGeo,France,Paris")[0], {"question": "France", "answer": "Paris", "chapter": "Geo"})
        self.assertEqual(self.one("Question\tAnswer\nFrance\tParis"), [("France", "Paris")])
        self.assertEqual(self.one("#separator:tab\n#html:false\nFrance\tParis\nJapan\tTokyo"), [("France", "Paris"), ("Japan", "Tokyo")])

    def test_prose_with_commas_is_not_a_table(self):
        self.assertEqual(self.one("What is a cell, really?\nThe smallest unit, of life."), [("What is a cell, really?", "The smallest unit, of life.")])

    def test_the_text_download_reads_back(self):
        class S:
            name = "Bio"

        class N:
            def __init__(self, q, a, chapter, order):
                self.question, self.answer, self.chapter, self.order, self.pk = q, a, chapter, order, order

        text = exam.as_text(S(), [N("Two\nlines", "Yes", "Ch", 1), N("Code", "```\nx = 1\n```", "Ch", 2), N("Alone", "- a\n- b", "", 3)])
        self.assertNotIn("## \n", text)
        self.assertEqual([(n["chapter"], n["question"], n["answer"]) for n in exam.parse(text)],
                         [("", "Alone", "- a\n- b"), ("Ch", "Two\nlines", "Yes"), ("Ch", "Code", "```\nx = 1\n```")])


class BigSubjectTests(Base):
    def test_the_order_is_worked_out_once_not_for_each_row(self):
        s = self.subject()
        ExamNote.objects.bulk_create([ExamNote(owner=self.me, subject=s, question=f"Q{i}", chapter=f"C{i % 5}", order=i) for i in range(400)])
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(reverse("work:api_exam_notes", args=[s.pk]), {"pinned": "1"})
        self.assertFalse([q for q in ctx.captured_queries if "U0" in q["sql"]], "a query per row")
        self.assertEqual(exam.numbers(s)[ExamNote.objects.get(subject=s, question="Q0").pk], 1)

    def test_chapters_keep_the_order_of_their_first_question(self):
        s = self.subject()
        b1 = self.question(s, "b1", chapter="B", order=1)
        a1 = self.question(s, "a1", chapter="A", order=2)
        b2 = self.question(s, "b2", chapter="B", order=3)
        self.assertEqual(list(exam.in_order(s.notes.all(), s)), [b1, b2, a1])

    def test_moving_a_card_gives_the_new_numbers_of_those_on_screen(self):
        s = self.subject()
        a, b = self.question(s, "a", order=1), self.question(s, "b", order=2)
        r = self.client.post(reverse("work:api_exam_subject", args=[s.pk]), {"action": "move", "id": b.pk, "before": a.pk, "ids": f"{a.pk},{b.pk}"}).json()
        self.assertEqual(r["numbers"], {str(b.pk): 1, str(a.pk): 2})


class FindingThingsTests(Base):
    def test_notes_by_any_words_in_any_order_and_tags(self):
        a = self.note("Redis cache", "fast store")
        a.tags.set(services.tags_named(self.me, ["backend"]))
        self.note("Other", "redis, but no c-word")
        url = reverse("work:notes")
        self.assertContains(self.client.get(url, {"q": "cache redis"}), "Redis cache")
        self.assertNotContains(self.client.get(url, {"q": "cache redis"}), ">Other<")
        self.assertContains(self.client.get(url, {"q": "#backend"}), "Redis cache")
        self.assertNotContains(self.client.get(url, {"q": "#nope"}), "Redis cache")
        self.assertContains(self.client.get(url, {"q": "backend fast"}), "Redis cache")
        self.assertNotContains(self.client.get(url, {"q": '"store fast"'}), "Redis cache")

    def test_notes_of_one_project(self):
        p = Project.objects.create(owner=self.me, name="Payments")
        self.note("In it", project=p)
        self.note("Not in it")
        r = self.client.get(reverse("work:notes"), {"project": p.pk})
        self.assertContains(r, "In it")
        self.assertNotContains(r, "Not in it")

    def test_exam_search_by_words(self):
        s = self.subject()
        self.question(s, "What is osmosis?", "Water moves through a membrane")
        self.assertContains(self.client.get(reverse("work:exam"), {"q": "membrane osmosis"}), "What is osmosis?")

    def test_flip_through_what_the_overview_showed(self):
        s = self.subject()
        self.question(s, "Osmosis?", "water", order=1)
        self.question(s, "Force?", "newtons", chapter="Physics", order=2)
        self.question(s, "Cell?", "unit", chapter="Biology", order=3)
        url = reverse("work:exam_review", args=[s.pk])
        titles = lambda r: [n["question"] for n in r.context["data"]["notes"]]      # noqa: E731
        self.assertEqual(titles(self.client.get(url, {"which": "all", "q": "newtons"})), ["Force?"])
        self.assertEqual(titles(self.client.get(url, {"which": "all", "nochapter": "1"})), ["Osmosis?"])
        self.assertEqual(len(titles(self.client.get(url, {"which": "all"}))), 3)


class SavingTests(Base):
    def test_tags_follow_the_text_as_it_is_typed(self):
        n = self.note("x", "")
        self.save(id=n.pk, body="about #back")
        self.save(id=n.pk, body="about #backend")
        self.assertEqual(list(n.tags.values_list("name", flat=True)), ["backend"])

    def test_pasted_c_isnt_tags(self):
        self.assertEqual(services.hashtags("#include <stdio.h>\n#define X 1\n  #ifdef Y\nabout #real"), ["real"])

    def test_tags_given_by_hand_stay(self):
        n = self.note("x", "")
        n.tags.set(services.tags_named(self.me, ["keep"]))
        self.save(id=n.pk, body="about #gone")
        self.save(id=n.pk, body="about nothing")
        self.assertEqual(list(n.tags.values_list("name", flat=True)), ["keep"])

    def test_line_ends_are_kept_one_way(self):
        n = self.note("x", "")
        self.save(id=n.pk, body="## Heading\r\n\r\ntext")
        n.refresh_from_db()
        self.assertEqual(n.body, "## Heading\n\ntext")
        old = self.note("Older", "## Heading\r\ntext")      # saved before: read as if it had been written the same way
        self.assertEqual(self.client.get(reverse("work:api_note_get", args=[old.pk])).json()["body"], "## Heading\ntext")
        s = self.subject()
        r = self.client.post(reverse("work:api_exam_subject", args=[s.pk]), {"action": "add", "question": "Q?\r\nmore", "answer": "a\r\nb"}).json()
        self.assertEqual((r["note"]["question"], r["note"]["answer"]), ("Q?\nmore", "a\nb"))

    def test_a_save_over_a_change_made_elsewhere_keeps_that_change(self):
        n = self.note("x", "one")
        rev = self.client.get(reverse("work:api_note_get", args=[n.pk])).json()["rev"]
        first = self.save(id=n.pk, body="from the phone", rev=rev)
        self.assertFalse(first["conflict"])
        late = self.save(id=n.pk, body="from the laptop", rev=rev)           # still working from "one"
        self.assertTrue(late["conflict"])
        self.assertTrue(NoteVersion.objects.filter(note=n, body="from the phone").exists())
        n.refresh_from_db()
        self.assertEqual(n.body, "from the laptop")

    def test_saving_on_from_the_last_save_is_no_conflict(self):
        n = self.note("x", "one")
        rev = self.client.get(reverse("work:api_note_get", args=[n.pk])).json()["rev"]
        rev = self.save(id=n.pk, body="two", rev=rev)["rev"]
        self.action(n, action="color", color="teal")                         # not the words: nothing to warn about
        self.assertFalse(self.save(id=n.pk, body="three", rev=rev)["conflict"])

    def test_the_same_text_saved_again_is_no_conflict(self):
        n = self.note("x", "same")
        self.assertFalse(self.save(id=n.pk, body="same", rev="stale")["conflict"])


class FrontEndTests(SimpleTestCase):
    def read(self, path):
        return (Path(settings.BASE_DIR) / path).read_text()

    def test_a_sign_in_that_ran_out_isnt_taken_for_a_save(self):
        js = self.read("static/js/work.js")
        self.assertIn("function signedOut(res)", js)
        self.assertIn('if (signedOut(res)) return { ok: false, why: "signin" };', js)      # the outbox waits too

    def test_a_draft_stays_until_the_server_has_that_text(self):
        self.assertIn("if (self.title === sent[0] && self.body === sent[1]) store(key, null);", self.read("static/js/work.js"))
        board = self.read("static/js/notes-board.js")
        self.assertIn("Work.noteDraftKey(this.ed.id)", board)
        self.assertIn("Work.noteDraftKey(n.id)", board)

    def test_the_exam_editor_saves_as_you_type_and_comes_back_when_it_cant(self):
        js = self.read("static/js/exam.js")
        for piece in ("editChanged: function", "saveEditing: function", 'self.editState = "error"; self.editing = q;', 'recall(EDIT, null)'):
            self.assertIn(piece, js)

    def test_a_subject_is_read_from_the_phone_with_no_signal(self):
        self.assertIn('"X-FT-Keep": "1"', self.read("static/js/exam.js"))
        self.assertIn('req.headers.get("X-FT-Keep")', self.read("apps/core/pwa.py"))

    def test_formulas_are_for_notes_too(self):
        self.assertIn("katex.renderToString", self.read("static/js/work.js"))
        self.assertNotIn("katex.renderToString", self.read("static/js/exam.js"))
        self.assertIn("katex.min.js", self.read("apps/productivity/templates/work/notes.html"))


class LinkTests(Base):
    def test_a_link_to_a_heading_or_with_other_words(self):
        n = self.note("Runbook", "## Deploy\nx")
        go = reverse("work:note_go")
        self.assertRedirects(self.client.get(go, {"title": "Runbook#Deploy"}), reverse("work:note", args=[n.pk]) + "?heading=Deploy", fetch_redirect_response=False)
        self.assertRedirects(self.client.get(go, {"title": "Runbook"}), reverse("work:note", args=[n.pk]), fetch_redirect_response=False)
        self.assertRedirects(self.client.get(go, {"title": "Runbook|the deploy notes"}), reverse("work:note", args=[n.pk]), fetch_redirect_response=False)

    def test_a_title_with_a_hash_and_a_note_not_written_yet(self):
        n = self.note("C# notes", "x")
        go = reverse("work:note_go")
        self.assertRedirects(self.client.get(go, {"title": "C# notes"}), reverse("work:note", args=[n.pk]), fetch_redirect_response=False)
        self.assertIn("title=New+one", self.client.get(go, {"title": "New one#Part"}).url)

    def test_links_with_other_words_count_as_links(self):
        n = self.note("Runbook")
        other = self.note("Board", "see [[Runbook|the deploy notes]]")
        self.assertEqual(services.backlinks(n), [other])

    def test_a_rename_takes_the_links_along(self):
        n = self.note("New name")
        a = self.note("A", "[[Old name]], ![[Old name#Part]], [[old name|shown]] and `[[Old name]]`")
        count = self.action(n, action="relink", old="Old name")["count"]
        a.refresh_from_db()
        self.assertEqual(count, 1)
        self.assertEqual(a.body, "[[New name]], ![[New name#Part]], [[New name|shown]] and `[[Old name]]`")
        self.assertTrue(NoteVersion.objects.filter(note=a, body__contains="[[Old name]],").exists())

    def test_links_stay_when_another_note_has_that_title(self):
        n = self.note("New name")
        self.note("Old name")
        a = self.note("A", "[[Old name]]")
        self.assertEqual(linked.relink(n, "Old name"), 0)
        a.refresh_from_db()
        self.assertEqual(a.body, "[[Old name]]")

    def test_only_my_notes(self):
        other = User.objects.create_user("other", "o@example.com", PW)
        theirs = Note.objects.create(owner=other, title="T", body="[[Old name]]")
        linked.relink(self.note("New name"), "Old name")
        theirs.refresh_from_db()
        self.assertEqual(theirs.body, "[[Old name]]")


class NoteToExamTests(Base):
    BODY = "# Networks\n\n## What is TCP?\nReliable.\n\n## What is UDP?\nFast."

    def test_headings_become_questions_in_a_new_subject(self):
        n = self.note("Notes", self.BODY)
        r = self.action(n, action="to_exam", name="Networking")
        s = ExamSubject.objects.get(owner=self.me, name="Networking")
        self.assertEqual((r["count"], r["url"]), (2, reverse("work:exam_subject", args=[s.pk])))
        self.assertEqual(list(s.notes.order_by("order").values_list("chapter", "question", "answer")),
                         [("Networks", "What is TCP?", "Reliable."), ("Networks", "What is UDP?", "Fast.")])

    def test_into_a_subject_leaving_out_what_is_there(self):
        s = self.subject()
        self.question(s, "What is TCP?", "old", order=1)
        r = self.action(self.note("Notes", self.BODY), action="to_exam", subject=s.pk)
        self.assertEqual((r["count"], r["skipped"]), (1, 1))
        self.assertEqual(s.notes.count(), 2)

    def test_question_answer_lines(self):
        r = self.action(self.note("Notes", "Capital of France :: Paris"), action="to_exam", name="Geo")
        self.assertEqual(r["count"], 1)

    def test_plain_paragraphs_arent_questions(self):
        n = self.note("Notes", "Just thinking aloud.\n\nAnother thought.")
        r = self.client.post(reverse("work:api_note_action", args=[n.pk]), {"action": "to_exam", "name": "New"})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(ExamSubject.objects.filter(name="New").exists())

    def test_not_into_someone_elses_subject(self):
        other = User.objects.create_user("other", "o@example.com", PW)
        s = ExamSubject.objects.create(owner=other, name="Theirs")
        r = self.client.post(reverse("work:api_note_action", args=[self.note("Notes", self.BODY).pk]), {"action": "to_exam", "subject": s.pk})
        self.assertEqual(r.status_code, 404)

    def test_the_note_page_offers_my_subjects(self):
        self.subject("Chemistry")
        for url in (reverse("work:note", args=[self.note("n").pk]), reverse("work:notes") + "?new=1"):
            self.assertContains(self.client.get(url), "Chemistry")


class DownloadTests(Base):
    def test_one_note_as_markdown_reads_back_with_its_tags(self):
        n = self.note("পদার্থ / নোট", "Text")
        n.tags.set(services.tags_named(self.me, ["exam", "bio"]))
        r = self.client.get(reverse("work:note_export", args=[n.pk]))
        self.assertIn("filename*=utf-8''", r["Content-Disposition"])
        back = notes_import.parse("x.md", r.content)
        self.assertEqual(back["title"], "পদার্থ / নোট")
        self.assertEqual(back["body"].strip(), "Text")
        self.assertEqual(set(back["tags"]), {"exam", "bio"})

    def test_not_someone_elses(self):
        other = User.objects.create_user("other", "o@example.com", PW)
        n = Note.objects.create(owner=other, title="T")
        self.assertEqual(self.client.get(reverse("work:note_export", args=[n.pk])).status_code, 404)

    def test_a_subject_with_a_bangla_name(self):
        r = self.client.get(reverse("work:exam_export", args=[self.subject("পদার্থবিজ্ঞান ১ম পত্র").pk]))
        self.assertIn("filename*=utf-8''", r["Content-Disposition"])
        self.assertNotIn("=?utf-8?", r["Content-Disposition"])

    def test_everything_at_once_has_the_exam_notes_as_text(self):
        s = self.subject("Biology")
        self.question(s, "A cell?", "Unit of life")
        n = self.note("Tagged", "x")
        n.tags.set(services.tags_named(self.me, ["keep"]))
        names = zipfile.ZipFile(io.BytesIO(self.client.get(reverse("work:export")).content))
        exam_file = next(x for x in names.namelist() if x.startswith("exam-notes/"))
        self.assertIn("Q: A cell?", names.read(exam_file).decode())
        note_file = next(x for x in names.namelist() if x.startswith("notes/") and x.endswith(".md"))
        self.assertIn("tags: [keep]", names.read(note_file).decode())


class ExamDaysTests(Base):
    def test_on_the_calendar(self):
        s = self.subject("Chemistry", exam_date=self.today)
        r = self.client.get(reverse("work:calendar"), {"month": self.today.strftime("%Y-%m")})
        self.assertContains(r, "📝 Chemistry")
        self.assertContains(r, reverse("work:exam_subject", args=[s.pk]))

    def test_in_the_calendar_feed(self):
        s = self.subject("Chemistry", exam_date=self.today + timedelta(days=3))
        self.subject("Long gone", exam_date=self.today - timedelta(days=60))
        feed = services.calendar_feed(self.me)
        self.assertIn(f"UID:exam-{s.pk}@fintrack-work", feed)
        self.assertIn(f"DTSTART;VALUE=DATE:{s.exam_date:%Y%m%d}", feed)
        self.assertIn("TRIGGER:-PT15H", feed)
        self.assertNotIn("Long gone", feed)

    def test_in_the_morning_email(self):
        s = self.subject("Chemistry", exam_date=self.today + timedelta(days=2))
        self.question(s, "Due?", is_known=True, due_on=self.today)
        b = emails.brief(self.me, self.today)
        self.assertTrue(b.worth_sending)
        self.assertEqual(b.exams, [s])
        self.assertEqual(b.exam_due[0].n, 1)
        self.assertIn("1 exam question", b.headline())

    def test_what_came_due_is_on_today(self):
        s = self.subject("Chemistry")                  # with no exam date, too
        self.question(s, "Due?", is_known=True, due_on=self.today)
        self.question(s, "Later", is_known=True, due_on=self.today + timedelta(days=4))
        r = self.client.get(reverse("work:today"))
        self.assertContains(r, "1 exam question to revise today")
        self.assertContains(r, reverse("work:exam_review", args=[s.pk]) + "?which=due")

    def test_nothing_due_nothing_shown(self):
        self.assertNotContains(self.client.get(reverse("work:today")), "to revise today")

    def test_kept_on_the_phone(self):
        s = self.subject()
        n = self.note("Read me on the bus")
        more = self.client.get(reverse("offline_pages")).json()["more"]
        for url in (reverse("work:exam_review", args=[s.pk]), reverse("work:exam_subject", args=[s.pk]), reverse("work:exam_overview", args=[s.pk]), reverse("work:note", args=[n.pk])):
            self.assertIn(url, more)

    def test_a_practice_test_starts_from_the_review_page(self):
        s = self.subject()
        self.question(s, "One?")
        url = reverse("work:exam_review", args=[s.pk])
        self.assertTrue(self.client.get(url, {"test": "1"}).context["data"]["test"])
        self.assertFalse(self.client.get(url).context["data"]["test"])
        self.assertContains(self.client.get(reverse("work:exam_subject", args=[s.pk])), url + "?test=1")


class NothingLeftBehindTests(Base):
    def test_no_stale_tags_count_on_the_chips(self):
        n = self.note("x", "")
        self.save(id=n.pk, body="#back")
        self.save(id=n.pk, body="#backend")
        names = [t.name for t in self.client.get(reverse("work:notes")).context["tags"]]
        self.assertEqual(names, ["backend"])
        self.assertTrue(Tag.objects.filter(owner=self.me, name="back").exists())     # (the row stays; it just has no notes)

    def test_exam_data_json_is_valid_for_a_phone_copy(self):
        s = self.subject()
        self.question(s, "Q", "**A**", chapter="C")
        html = self.client.get(reverse("work:exam_review", args=[s.pk])).content.decode()
        raw = html.split('id="exam-data" type="application/json">')[1].split("</script>")[0]
        self.assertEqual(json.loads(raw)["notes"][0]["answer"], "**A**")


class ReviewPageTests(SimpleTestCase):
    def test_the_review_page_can_name_a_question_with_no_chapter(self):
        js = (Path(settings.BASE_DIR) / "static/js/exam.js").read_text()
        review = js[js.index('Alpine.data("examReview"'):]
        self.assertIn("t: t, all: D.notes", review)          # (the practice test's result says "No chapter")


class BanglaWordsTests(SimpleTestCase):
    def test_saved_in_an_editor_is_not_savings(self):
        from django.utils import translation
        from django.utils.translation import gettext, pgettext

        with translation.override("bn"):
            self.assertNotEqual(pgettext("state", "Saved"), gettext("Saved"))


class SyncSafetyTests(Base):
    """What was written offline: one save per note, nothing lost, and the queue never stuck behind one bad item."""
    def replay(self, url, **fields):
        return self.client.post(url, {**fields, "_ft_key": uuid.uuid4().hex, "_ft_user": str(self.me.pk)}, HTTP_X_FT_REPLAY="1").json()

    def test_a_save_for_something_deleted_is_not_retried_for_ever(self):
        self.assertEqual(self.replay(reverse("work:api_note_save"), id="99999999", title="x", body="y")["why"], "gone")
        self.assertEqual(self.replay(reverse("work:api_exam_note", args=[99999999]), action="update", question="q")["why"], "gone")

    def test_a_refused_save_is_not_retried_for_ever(self):
        note = self.note("t", "no to-dos")
        answer = self.replay(reverse("work:api_note_action", args=[note.pk]), action="tick", index="5", done="1")
        self.assertEqual((answer["ok"], answer["why"]), (False, "fix"))

    def test_a_queued_new_note_tells_the_page_where_it_went_and_at_what_version(self):
        answer = self.replay(reverse("work:api_note_save"), id="", title="Written offline", body="text")
        note = Note.objects.get(title="Written offline")
        self.assertEqual(answer["location"], reverse("work:note", args=[note.pk]))
        self.assertEqual(answer["rev"], services.note_rev(note))

    def test_a_queued_exam_save_gives_its_version(self):
        q = self.question(self.subject(), "q", "a")
        answer = self.replay(reverse("work:api_exam_note", args=[q.pk]), action="update", question="q", answer="b")
        q.refresh_from_db()
        self.assertEqual(answer["rev"], exam.rev(q))

    def test_a_title_past_the_column_is_cut_not_a_server_error(self):
        self.assertEqual(len(Note.objects.get(pk=self.save(title="t" * 500, body="b")["id"]).title), 200)

    def test_the_outbox_keeps_one_save_per_note_and_what_it_cannot_send_yet(self):
        work = (settings.BASE_DIR / "static/js/work.js").read_text()
        self.assertIn("x.fields._ft_same !== fields._ft_same", work)
        self.assertIn("res.status >= 500", work)
        self.assertIn("_ft_same: this.same", work)


class ExamHistoryTests(Base):
    def update(self, q, **fields):
        return self.client.post(reverse("work:api_exam_note", args=[q.pk]), {"action": "update", "question": q.question, **fields})

    def test_text_written_over_unseen_stays_in_history(self):
        q = self.question(self.subject(), "q", "first")
        rev = exam.rev(q)
        self.update(q, answer="from the laptop", rev=rev)
        answer = self.update(q, answer="from the phone", rev=rev).json()
        self.assertTrue(answer["conflict"])
        self.assertEqual([v.answer for v in q.versions.all()], ["from the laptop", "first"])

    def test_saving_on_from_the_same_editor_is_no_conflict(self):
        q = self.question(self.subject(), "q", "first")
        answer = self.update(q, answer="second", rev=exam.rev(q)).json()
        self.assertFalse(self.update(q, answer="third", rev=answer["rev"]).json()["conflict"])
        self.assertEqual(q.versions.count(), 1)         # one round of writing, one copy

    def test_an_earlier_version_comes_back_and_what_was_there_is_kept(self):
        q = self.question(self.subject(), "q", "first")
        self.update(q, answer="second")
        version = q.versions.get()
        out = self.client.post(reverse("work:api_exam_note", args=[q.pk]), {"action": "restore", "version": version.pk}).json()
        self.assertEqual(out["note"]["answer"], "first")
        self.assertIn("second", [v.answer for v in q.versions.all()])

    def test_history_stays_short(self):
        q = self.question(self.subject(), "q", "0")
        for i in range(1, exam.VERSION_KEEP + 5):
            q.answer = str(i)
            exam.remember(q, force=True)
        self.assertEqual(q.versions.count(), exam.VERSION_KEEP)

    def test_only_the_owner_sees_it(self):
        q = self.question(self.subject(), "q", "secret")
        self.update(q, answer="second")
        self.client.force_login(User.objects.create_superuser("other", "o@example.com", PW))
        self.assertEqual(self.client.get(reverse("work:api_exam_note_versions", args=[q.pk])).status_code, 404)

    def test_a_long_answer_is_saved_whole(self):
        q = self.question(self.subject(), "q", "a")
        self.update(q, answer="x" * 25000 + " THE END")
        q.refresh_from_db()
        self.assertTrue(q.answer.endswith("THE END"))

    def test_an_answer_past_the_limit_is_refused_not_cut(self):
        q = self.question(self.subject(), "q", "a")
        response = self.update(q, answer="x" * (exam.MAX_ANSWER + 1))
        q.refresh_from_db()
        self.assertEqual((response.status_code, q.answer), (400, "a"))

    def test_a_new_question_past_the_limit_is_refused_not_cut(self):
        s = self.subject()
        r = self.client.post(reverse("work:api_exam_subject", args=[s.pk]), {"action": "add", "question": "q", "answer": "x" * (exam.MAX_ANSWER + 1)})
        self.assertEqual((r.status_code, s.notes.count()), (400, 0))


class OutsideTheAppTests(Base):
    def test_a_pair_starting_with_q1_is_not_a_q1_label(self):
        found = exam.parse_note("## First?\nOne\n\n## Second?\nTwo\n\nq1 :: a1\n")
        self.assertEqual([n["question"] for n in found], ["First?", "Second?"])

    def test_q1_labels_still_work(self):
        self.assertEqual([n["question"] for n in exam.parse("Q1: What?\nA1: That\n\nQ2: Why?\nA2: So\n")], ["What?", "Why?"])

    def test_a_title_with_quotes_survives_download_and_import(self):
        note = self.note('He said "hi": part \\ two', "body")
        fields, _body = notes_import.front_matter(services.note_file(note))
        self.assertEqual(fields["title"], note.title)

    def test_a_downloaded_note_keeps_its_pictures_address(self):
        note = self.note("pic", "![shot](/work/images/5/)")
        text = self.client.get(reverse("work:note_export", args=[note.pk])).content.decode()
        self.assertIn("(http://testserver/work/images/5/)", text)

    def test_the_export_points_at_the_pictures_beside_the_notes(self):
        self.assertEqual(services.image_links("![a](/work/images/5/) ![b](/work/images/6/)", "images/", {5: ".png"}), "![a](images/5.png) ![b](/work/images/6/)")


class CategoryTests(Base):
    """Any number on a question or none, a tree of any depth, shared by the subjects, and safe in every restore."""
    def post(self, **fields):
        return self.client.post(reverse("work:api_exam_categories"), fields)

    def tree(self):
        return [c["path"] for c in exam.category_tree(self.me)]

    def cat(self, path):
        return exam.add_category(self.me, None, path)

    def notes(self, s, **params):
        return [n["question"] for n in self.client.get(reverse("work:api_exam_notes", args=[s.pk]), params).json()["notes"]]

    def test_a_path_makes_the_tree_and_goes_through_what_is_there(self):
        first = self.post(action="add", name="Backend > Databases > Indexing").json()
        self.post(action="add", name="backend > caching")
        self.assertEqual(self.tree(), ["Backend", "Backend › caching", "Backend › Databases", "Backend › Databases › Indexing"])
        self.assertEqual(ExamCategory.objects.get(pk=first["id"]).name, "Indexing")

    def test_a_name_is_needed(self):
        self.assertEqual(self.post(action="add", name="  ").status_code, 400)

    def test_a_question_needs_none(self):
        s = self.subject()
        r = self.client.post(reverse("work:api_exam_subject", args=[s.pk]), {"action": "add", "question": "q"}).json()
        self.assertEqual(r["note"]["categories"], [])

    def test_a_question_can_have_several_and_can_lose_them(self):
        s, a, b = self.subject(), self.cat("A"), self.cat("B > C")
        r = self.client.post(reverse("work:api_exam_subject", args=[s.pk]), {"action": "add", "question": "q", "categories": f"{a.pk},{b.pk}"}).json()
        self.assertEqual(set(r["note"]["categories"]), {a.pk, b.pk})
        q = ExamNote.objects.get(pk=r["note"]["id"])
        self.client.post(reverse("work:api_exam_note", args=[q.pk]), {"action": "update", "question": "q", "categories": str(b.pk)})
        self.assertEqual(list(q.categories.all()), [b])
        self.client.post(reverse("work:api_exam_note", args=[q.pk]), {"action": "update", "question": "q", "categories": ""})
        self.assertEqual(q.categories.count(), 0)

    def test_a_save_that_does_not_mention_them_leaves_them(self):
        q = self.question(self.subject(), "q", "a")
        q.categories.add(self.cat("A"))
        self.client.post(reverse("work:api_exam_note", args=[q.pk]), {"action": "update", "question": "q", "answer": "b"})
        self.assertEqual(q.categories.count(), 1)

    def test_somebody_elses_category_is_not_taken(self):
        other = User.objects.create_user("other", "o@example.com", PW)
        theirs = ExamCategory.objects.create(owner=other, name="Theirs")
        q = self.question(self.subject(), "q")
        self.client.post(reverse("work:api_exam_note", args=[q.pk]), {"action": "update", "question": "q", "categories": str(theirs.pk)})
        self.assertEqual(q.categories.count(), 0)
        self.assertEqual(self.post(action="delete", id=theirs.pk).status_code, 404)
        self.assertEqual(self.post(action="add", name="x", parent=theirs.pk).status_code, 404)

    def test_a_category_shows_what_is_inside_it_each_question_once(self):
        s, top = self.subject(), self.cat("Backend")
        deep, side = self.cat("Backend > Databases > Indexing"), self.cat("Backend > Caching")
        both, plain = self.question(s, "both", order=1), self.question(s, "plain", order=2)
        both.categories.add(deep, side)
        self.assertEqual(self.notes(s, category=top.pk), ["both"])
        self.assertEqual(self.notes(s, category="none"), ["plain"])
        self.assertEqual(exam.category_counts(s)[top.pk], 1)
        self.assertEqual(exam.category_counts(s)["none"], 1)
        self.assertEqual(self.notes(s), ["both", "plain"])

    def test_a_review_can_be_of_a_category(self):
        s, top, deep = self.subject(), self.cat("Backend"), self.cat("Backend > Databases")
        self.question(s, "in", order=1).categories.add(deep)
        self.question(s, "out", order=2)
        page = self.client.get(reverse("work:exam_review", args=[s.pk]), {"category": top.pk})
        self.assertEqual([n["question"] for n in page.context["data"]["notes"]], ["in"])

    def test_the_same_category_works_across_subjects_and_goes_with_a_move(self):
        one, two, cat = self.subject("One"), self.subject("Two"), self.cat("Shared")
        q = self.question(one, "q")
        q.categories.add(cat)
        self.question(two, "r").categories.add(cat)
        page = self.client.get(reverse("work:exam"), {"category": cat.pk})
        self.assertEqual({n.question for n in page.context["found"]}, {"q", "r"})
        self.client.post(reverse("work:api_exam_note", args=[q.pk]), {"action": "update", "question": "q", "subject": two.pk})
        self.assertEqual(list(ExamNote.objects.get(pk=q.pk).categories.all()), [cat])

    def test_picked_questions_get_it_added_to_what_they_have(self):
        s, a, b = self.subject(), self.cat("A"), self.cat("B")
        q, r = self.question(s, "q"), self.question(s, "r")
        q.categories.add(a)
        ids = f"{q.pk},{r.pk}"
        for _time in (1, 2):
            self.client.post(reverse("work:api_exam_subject", args=[s.pk]), {"action": "bulk", "op": "categories", "ids": ids, "categories": str(b.pk)})
        self.assertEqual({c.name for c in q.categories.all()}, {"A", "B"})
        self.assertEqual(list(r.categories.all()), [b])

    def test_a_pasted_list_can_all_go_in_one(self):
        s, a = self.subject(), self.cat("A")
        self.client.post(reverse("work:api_exam_subject", args=[s.pk]), {"action": "add_many", "text": "Q: one?\nA: 1\n\nQ: two?\nA: 2\n", "categories": str(a.pk)})
        self.assertEqual(a.notes.count(), 2)

    def test_a_category_cannot_go_inside_itself_or_what_is_inside_it(self):
        top, low = self.cat("A"), self.cat("A > B > C")
        self.assertEqual(self.post(action="change", id=top.pk, name="A", parent=low.pk).status_code, 400)
        self.assertEqual(self.post(action="change", id=top.pk, name="A", parent=top.pk).status_code, 400)
        self.assertEqual(self.tree(), ["A", "A › B", "A › B › C"])

    def test_moving_takes_what_is_inside_along(self):
        self.cat("A > B > C")
        other = self.cat("Z")
        b = ExamCategory.objects.get(name="B")
        self.post(action="change", id=b.pk, name="B", parent=other.pk)
        self.assertEqual(self.tree(), ["A", "Z", "Z › B", "Z › B › C"])

    def test_two_with_one_name_in_one_place_are_refused(self):
        self.cat("A > B")
        c = self.cat("A > C")
        self.assertEqual(self.post(action="change", id=c.pk, name="b", parent=c.parent_id).status_code, 400)

    def test_deleting_keeps_the_questions_and_undo_brings_it_all_back(self):
        q = self.question(self.subject(), "q")
        deep = self.cat("A > B")
        q.categories.add(deep)
        undo = self.post(action="delete", id=deep.parent_id).json()["undo"]
        self.assertEqual((ExamCategory.objects.count(), q.categories.count()), (0, 0))
        self.assertTrue(ExamNote.objects.filter(pk=q.pk).exists())
        self.client.post(undo)
        self.assertEqual(self.tree(), ["A", "A › B"])
        self.assertEqual(q.categories.count(), 1)

    def test_a_deleted_question_comes_back_with_its_categories(self):
        q, a = self.question(self.subject(), "q"), self.cat("A")
        q.categories.add(a)
        pk, undo = q.pk, self.client.post(reverse("work:api_exam_note", args=[q.pk]), {"action": "delete"}).json()["undo"]
        self.client.post(undo)
        self.assertEqual(list(ExamNote.objects.get(pk=pk).categories.all()), [a])

    def test_a_deleted_question_still_comes_back_when_its_category_has_gone_for_good(self):
        q, a, b = self.question(self.subject(), "q"), self.cat("A"), self.cat("B")
        q.categories.add(a, b)
        pk, undo = q.pk, self.client.post(reverse("work:api_exam_note", args=[q.pk]), {"action": "delete"}).json()["undo"]
        a.delete()
        self.client.post(undo)
        self.assertEqual(list(ExamNote.objects.get(pk=pk).categories.all()), [b])

    def test_the_board_asks_once_for_all_the_categories(self):
        s, a = self.subject(), self.cat("A")
        for i in range(25):
            self.question(s, f"q{i}", order=i).categories.add(a)
        url = reverse("work:api_exam_notes", args=[s.pk])
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(url, {"show": "all"})
        self.assertLess(sum("productivity_examcategory" in q["sql"] and "INNER JOIN" in q["sql"] for q in ctx), 6)

    def deep_tree(self):
        """A child made before its parent: the order a tree is in after moving things about."""
        low = ExamCategory.objects.create(owner=self.me, name="Low")
        mid = ExamCategory.objects.create(owner=self.me, name="Mid")
        top = ExamCategory.objects.create(owner=self.me, name="Top")
        ExamCategory.objects.filter(pk=low.pk).update(parent=mid)
        ExamCategory.objects.filter(pk=mid.pk).update(parent=top)
        q = self.question(self.subject(), "q")
        q.categories.add(low, top)

    def test_a_deep_tree_survives_the_work_backup(self):
        self.deep_tree()
        rows, _files = services.backup_rows(self.me)
        other = User.objects.create_superuser("other", "o@example.com", PW)
        services.restore(other, rows)
        self.assertEqual([c["path"] for c in exam.category_tree(other)], ["Top", "Top › Mid", "Top › Mid › Low"])
        self.assertEqual({c.name for c in ExamNote.objects.get(owner=other).categories.all()}, {"Low", "Top"})

    def test_restoring_the_work_backup_twice_makes_no_second_tree(self):
        self.deep_tree()
        rows, _files = services.backup_rows(self.me)
        services.restore(self.me, rows)
        self.assertEqual(ExamCategory.objects.filter(owner=self.me).count(), 3)

    def test_a_deep_tree_survives_my_data(self):
        from apps.core import personal_backup as pb
        from apps.core.my_data import build_zip

        self.deep_tree()
        data, _made = build_zip(self.me)
        with TemporaryDirectory() as folder:
            path = Path(folder) / "mine.zip"
            path.write_bytes(data)
            other = User.objects.create_superuser("other", "o@example.com", PW)
            pb.restore(other, pb.read(path), keep_copy=False)
        self.assertEqual([c["path"] for c in exam.category_tree(other)], ["Top", "Top › Mid", "Top › Mid › Low"])
        self.assertEqual({c.name for c in ExamNote.objects.get(owner=other).categories.all()}, {"Low", "Top"})
