"""Interview prep: the question bank, practice with spaced repetition, timed
mock exams, starter packs, and bringing questions in and out."""
import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.trash.models import DeletedItem
from apps.trash.services import restore

from . import prep
from .models import PrepAttempt, PrepExam, PrepTopic, Question, QuestionKind, WorkSettings
from .prep_packs import PACKS

PW = "Str0ng-pass-123"
TODAY = timezone.localdate()


class Base(TestCase):
    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)
        self.topic = PrepTopic.objects.create(owner=self.me, name="Python")

    def q(self, prompt="What is the GIL?", **kw):
        kw.setdefault("topic", self.topic)
        return Question.objects.create(owner=self.me, prompt=prompt, **kw)

    def mcq(self, **kw):
        return self.q("Which is immutable?", kind=QuestionKind.CHOICE,
                      options=[{"text": "list", "correct": False}, {"text": "tuple", "correct": True}, {"text": "dict", "correct": False}], **kw)


class PackTests(Base):
    def test_packs_are_well_formed(self):
        for key, pack in PACKS.items():
            self.assertTrue(pack["questions"], key)
            for x in pack["questions"]:
                self.assertIn(x["kind"], QuestionKind.values, x["prompt"])
                if x["kind"] == QuestionKind.CHOICE:
                    self.assertTrue(any(o["correct"] for o in x["options"]), x["prompt"])
                else:
                    self.assertTrue(x.get("answer"), x["prompt"])

    def test_install_once_with_choices_kept_right(self):
        n = prep.install_pack(self.me, "python")
        self.assertEqual(n, len(PACKS["python"]["questions"]))
        self.assertEqual(prep.install_pack(self.me, "python"), 0)            # not twice
        q = Question.objects.get(prompt__startswith="Which of these is immutable")
        self.assertEqual([o["text"] for o in q.options if o["correct"]], ["tuple"])
        r = self.client.post(reverse("work:prep"), {"action": "pack", "pack": ["sql", "design", "nope"]})
        self.assertRedirects(r, reverse("work:prep"))
        self.assertEqual(set(PrepTopic.objects.filter(owner=self.me).values_list("name", flat=True)),
                         {"Python", "SQL & databases", "System design"})


class SchedulingTests(Base):
    def test_answers_move_the_next_review(self):
        q = self.q()
        self.assertEqual(q.status, "new")
        prep.answer(q, prep.AGAIN)
        self.assertEqual((q.status, q.due, q.attempts, q.right), ("weak", TODAY, 1, 0))
        prep.answer(q, prep.GOOD)
        self.assertEqual((q.status, q.interval), ("learning", 1))
        for _ in range(4):
            prep.answer(q, prep.GOOD)
        self.assertEqual(q.status, "mastered")
        self.assertEqual(q.accuracy, 83)
        self.assertEqual(PrepAttempt.objects.filter(question=q).count(), 6)

    def test_multiple_choice_marking(self):
        q = self.mcq()
        self.assertTrue(prep.chosen_right(q, [1]))
        self.assertFalse(prep.chosen_right(q, [0, 1]))
        q.options[0]["correct"] = True
        self.assertTrue(prep.chosen_right(q, [1, 0]))
        self.assertFalse(prep.chosen_right(q, [1]))

    def test_todays_queue_and_new_per_day(self):
        s = WorkSettings.for_user(self.me)
        s.prep_new_per_day = 2
        s.save()
        due = self.q("Old one")
        prep.answer(due, prep.AGAIN, now=timezone.now() - timedelta(days=1))      # first seen yesterday
        news = [self.q(f"New {i}") for i in range(4)]
        self.assertEqual([x.prompt for x in prep.today_queue(self.me)], ["Old one", "New 0", "New 1"])
        prep.answer(news[0], prep.GOOD)
        prep.answer(news[0], prep.AGAIN)      # answered twice today: still one new seen
        self.assertEqual(prep.new_left(self.me), 1)

    def test_practice_puts_weak_first(self):
        fine = self.q("Fine")
        prep.answer(fine, prep.GOOD)
        weak = self.q("Weak")
        prep.answer(weak, prep.AGAIN)
        self.q("New")
        self.assertEqual([x.prompt for x in prep.practice_queue(self.me, {}, count=3)], ["Weak", "New", "Fine"])
        self.assertEqual([x.prompt for x in prep.practice_queue(self.me, {"status": "weak"})], ["Weak"])


class ApiTests(Base):
    def test_choice_marked_on_the_server(self):
        q = self.mcq()
        r = self.client.post(reverse("work:api_prep_answer", args=[q.pk]), {"choice": "0", "seconds": "12"}).json()
        self.assertEqual((r["right"], r["status"]), (False, "weak"))
        r = self.client.post(reverse("work:api_prep_answer", args=[q.pk]), {"choice": "1"}).json()
        self.assertTrue(r["right"])
        a = PrepAttempt.objects.filter(question=q).last()
        self.assertEqual((a.seconds, a.score, a.response), (12, 0, {"choice": [0]}))

    def test_written_answer_rated(self):
        q = self.q(key_points="one\ntwo")
        r = self.client.post(reverse("work:api_prep_answer", args=[q.pk]), {"rating": "2", "score": "0.5", "text": "my answer"})
        self.assertEqual(r.json()["status"], "learning")
        a = PrepAttempt.objects.get(question=q)
        self.assertEqual((a.rating, a.score, a.response["text"]), (2, 0.5, "my answer"))
        self.assertEqual(self.client.post(reverse("work:api_prep_answer", args=[q.pk]), {"rating": "9"}).status_code, 400)

    def test_star_notes_reset_and_owner_only(self):
        q = self.q()
        url = reverse("work:api_question_action", args=[q.pk])
        self.assertTrue(self.client.post(url, {"action": "star"}).json()["starred"])
        self.client.post(url, {"action": "notes", "notes": "remember refcount"})
        prep.answer(q, prep.GOOD)
        self.client.post(url, {"action": "reset"})
        q.refresh_from_db()
        self.assertEqual((q.is_starred, q.notes, q.status), (True, "remember refcount", "new"))
        other = User.objects.create_superuser("o", "o@example.com", PW)
        self.client.force_login(other)
        self.assertEqual(self.client.post(url, {"action": "star"}).status_code, 404)
        self.assertEqual(self.client.get(reverse("work:question", args=[q.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("work:api_prep_answer", args=[q.pk]), {"rating": "3"}).status_code, 404)


class FormTests(Base):
    def post(self, url=None, **data):
        base = {"topic": self.topic.pk, "kind": "short", "difficulty": 2, "prompt": "Q?", "options_json": "[]"}
        base.update(data)
        return self.client.post(url or reverse("work:question_new"), base)

    def test_multiple_choice_needs_two_choices_and_a_right_one(self):
        r = self.post(kind="choice", options_json=json.dumps([{"text": "a", "correct": True}]))
        self.assertContains(r, "at least two choices")
        r = self.post(kind="choice", options_json=json.dumps([{"text": "a"}, {"text": "b"}]))
        self.assertContains(r, "Tick the right choice")
        r = self.post(kind="choice", options_json=json.dumps([{"text": "a", "correct": True}, {"text": " "}, {"text": "b"}]), tags_text="core py")
        q = Question.objects.get()
        self.assertRedirects(r, reverse("work:question", args=[q.pk]))
        self.assertEqual(q.options, [{"text": "a", "correct": True}, {"text": "b", "correct": False}])
        self.assertEqual(sorted(q.tags.values_list("name", flat=True)), ["core", "py"])

    def test_new_topic_typed_in_place_and_save_another(self):
        r = self.post(topic="", new_topic="Kubernetes", then="another", answer="A pod is…")
        t = PrepTopic.objects.get(name="Kubernetes")
        self.assertRedirects(r, reverse("work:question_new") + f"?topic={t.pk}&kind=short")
        r = self.post(topic="", new_topic="")
        self.assertContains(r, "Pick a topic, or type a new one")

    def test_options_dropped_for_other_kinds_edit_and_delete(self):
        q = self.mcq()
        self.post(reverse("work:question_edit", args=[q.pk]), kind="long", options_json=json.dumps([{"text": "x", "correct": True}]), answer="Because")
        q.refresh_from_db()
        self.assertEqual((q.kind, q.options), ("long", []))
        self.client.post(reverse("work:question_edit", args=[q.pk]), {"action": "delete"})
        self.assertFalse(Question.objects.exists())
        restore(DeletedItem.objects.get())
        self.assertTrue(Question.objects.filter(pk=q.pk).exists())

    def test_topic_delete_takes_its_questions_and_comes_back(self):
        self.q()
        self.client.post(reverse("work:prep_topic", args=[self.topic.pk]), {"action": "delete"})
        self.assertFalse(Question.objects.exists())
        restore(DeletedItem.objects.get())
        self.assertEqual(Question.objects.get().topic, self.topic)


class ExamTests(Base):
    def make(self):
        self.a = self.mcq()
        self.b = self.q("Explain the GIL", kind=QuestionKind.LONG, answer="One thread at a time.")
        self.c = self.q("Empty one", kind=QuestionKind.SHORT, answer="x")
        r = self.client.post(reverse("work:exam_new"), {"topic": self.topic.pk, "count": 10, "minutes": 20, "title": "Mock 1"})
        exam = PrepExam.objects.get()
        self.assertRedirects(r, reverse("work:exam", args=[exam.pk]))
        return exam

    def test_taking_it_shows_no_right_answers(self):
        exam = self.make()
        r = self.client.get(reverse("work:exam", args=[exam.pk]))
        data = r.context["data"]
        self.assertEqual(len(data["questions"]), 3)
        self.assertTrue(all("correct" not in q and "answer" not in q for q in data["questions"]))

    def test_hand_in_mark_and_score(self):
        exam = self.make()
        save = reverse("work:api_exam_save", args=[exam.pk])
        answers = {str(self.a.pk): {"choice": [1]}, str(self.b.pk): {"text": "Only one thread runs bytecode", "flag": True, "seconds": 40}}
        self.assertTrue(self.client.post(save, {"answers": json.dumps(answers)}).json()["ok"])
        self.client.post(reverse("work:exam", args=[exam.pk]), {"action": "submit", "answers": json.dumps(answers)})
        exam.refresh_from_db()
        self.assertEqual(exam.marks, {str(self.a.pk): 1.0, str(self.c.pk): 0.0})       # the empty one is wrong; the written one waits
        self.assertIsNone(exam.score)
        self.assertEqual(self.client.post(save, {"answers": "{}"}).status_code, 409)      # closed
        r = self.client.get(reverse("work:exam", args=[exam.pk]))
        self.assertEqual(len(r.context["report"]["to_mark"]), 1)
        self.client.post(reverse("work:exam", args=[exam.pk]), {"action": "mark", f"mark-{self.b.pk}": "0.5"})
        exam.refresh_from_db()
        self.assertEqual(exam.score, 50.0)
        self.assertIsNotNone(exam.graded_at)
        self.b.refresh_from_db(); self.c.refresh_from_db(); self.a.refresh_from_db()
        self.assertEqual((self.a.status, self.b.attempts, self.c.status), ("learning", 1, "weak"))
        self.assertEqual(PrepAttempt.objects.get(question=self.b).seconds, 40)
        r = self.client.get(reverse("work:exam", args=[exam.pk]))
        self.assertEqual(r.context["wrong"].split(","), [str(i) for i in exam.question_ids if i != self.a.pk])

    def test_time_runs_out_while_away(self):
        exam = self.make()
        PrepExam.objects.filter(pk=exam.pk).update(started_at=timezone.now() - timedelta(minutes=30))
        r = self.client.get(reverse("work:exam", args=[exam.pk]))
        self.assertTemplateUsed(r, "work/prep/exam_result.html")
        exam.refresh_from_db()
        self.assertIsNotNone(exam.finished_at)

    def test_no_questions(self):
        r = self.client.post(reverse("work:exam_new"), {"topic": self.topic.pk})
        self.assertRedirects(r, reverse("work:prep"))
        self.assertFalse(PrepExam.objects.exists())


class ImportExportTests(Base):
    def test_markdown_format(self):
        items = prep.parse_markdown(prep.EXAMPLE)
        self.assertEqual([(x["topic"], x["kind"], x["difficulty"]) for x in items],
                         [("Python", "choice", 1), ("Python", "long", 2), ("Python", "code", 2)])
        self.assertEqual([o["correct"] for o in items[0]["options"]], [False, True, False])
        self.assertIn("__eq__", items[0]["explanation"])
        self.assertEqual(items[1]["key_points"].splitlines()[0], "hash() of the key")
        self.assertEqual((items[2]["language"], items[2]["starter"]), ("python", "def reverse(head): ..."))
        self.assertIn("```python", items[2]["answer"])

    def test_preview_then_add_and_round_trip(self):
        r = self.client.post(reverse("work:prep_import"), {"text": prep.EXAMPLE})
        self.assertEqual(len(r.context["items"]), 3)
        self.client.post(reverse("work:prep_import"), {"action": "add"})
        self.assertEqual(Question.objects.filter(topic=self.topic).count(), 3)       # into the topic of that name
        data = self.client.get(reverse("work:prep_export")).content.decode()
        md = self.client.get(reverse("work:prep_export"), {"format": "md"}).content.decode()
        other = User.objects.create_superuser("o", "o@example.com", PW)
        self.assertEqual(prep.add_many(other, prep.parse_json(data)), 3)
        again = prep.parse_markdown(md)
        self.assertEqual([x["kind"] for x in again], ["choice", "long", "code"])
        self.assertEqual(Question.objects.filter(owner=other, kind="choice").get().options[1]["correct"], True)

    def test_nothing_found(self):
        r = self.client.post(reverse("work:prep_import"), {"text": "just some words"})
        self.assertContains(r, "No questions found")
        r = self.client.post(reverse("work:prep_import"), {"action": "add"})
        self.assertRedirects(r, reverse("work:prep_import"))


class PageTests(Base):
    def test_first_visit_offers_packs_then_the_dashboard(self):
        Question.objects.all().delete()
        self.assertContains(self.client.get(reverse("work:prep")), "wpq-pack")
        prep.install_pack(self.me, "dsa")
        q = Question.objects.filter(topic__name="Data structures & algorithms").first()
        prep.answer(q, prep.AGAIN)
        r = self.client.get(reverse("work:prep"))
        self.assertEqual(r.context["o"]["weak"], 1)
        self.assertContains(r, "wfc-hero")
        self.client.post(reverse("work:prep"), {"action": "goal", "goal-prep_exam": "Google onsite", "goal-prep_exam_date": (TODAY + timedelta(days=10)).isoformat(),
                                                "goal-prep_new_per_day": "5"})
        r = self.client.get(reverse("work:prep"))
        self.assertContains(r, "Google onsite")
        self.assertEqual(r.context["days_left"], 10)

    def test_pages_load(self):
        q = self.mcq()
        for url in (reverse("work:questions"), reverse("work:questions") + "?status=new&difficulty=2&q=immutable",
                    reverse("work:question", args=[q.pk]), reverse("work:question_edit", args=[q.pk]), reverse("work:question_new"),
                    reverse("work:prep_practice") + "?set=today", reverse("work:prep_practice") + f"?ids={q.pk}",
                    reverse("work:prep_practice") + f"?topic={self.topic.pk}&count=5&order=random", reverse("work:prep_topic", args=[self.topic.pk]),
                    reverse("work:prep_import")):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        r = self.client.get(reverse("work:prep_practice") + "?set=today")
        self.assertEqual(r.context["session"]["questions"][0]["correct"], [1])

    def test_today_page_shows_what_to_practise(self):
        self.assertNotContains(self.client.get(reverse("work:today")), "set=today")
        self.mcq()
        self.assertContains(self.client.get(reverse("work:today")), "1 question to practise today")

    def test_search_finds_questions(self):
        self.mcq(companies="Google")
        found = self.client.get(reverse("work:api_search"), {"q": "immutable"}).json()["results"]
        self.assertEqual([x["kind"] for x in found], ["question"])
