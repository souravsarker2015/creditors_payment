"""The job search (jobs.py, views_jobs.py): applications on a board by stage, their interview rounds
(and the questions asked, into the question bank), what's coming up on Today, the funnel, the skills a
job asks for, and STAR stories with what they cover."""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from . import jobs
from .models import JobApplication, JobRound, JobStage, PrepTopic, Question, Story

PW = "Str0ng-pass-123"


class Base(TestCase):
    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)
        self.today = timezone.localdate()

    def app(self, company="Acme", role="Backend Engineer", **kw):
        return JobApplication.objects.create(owner=self.me, company=company, role=role, **kw)


class BoardTests(Base):
    def test_quick_add_then_the_page(self):
        r = self.client.post(reverse("work:jobs"), {"company": "Pathao", "role": "Software Engineer", "stage": "applied", "url": "https://jobs.example/1"})
        a = JobApplication.objects.get(company="Pathao")
        self.assertRedirects(r, reverse("work:job", args=[a.pk]))
        self.assertEqual((a.stage, a.applied_on, a.url), (JobStage.APPLIED, self.today, "https://jobs.example/1"))
        page = self.client.get(reverse("work:jobs"))
        self.assertContains(page, "Pathao")
        self.assertContains(page, 'data-column="interview"', html=False)
        self.assertNotContains(page, 'data-column="closed"', html=False)        # closed ones only when asked

    def test_company_and_role_are_needed(self):
        self.client.post(reverse("work:jobs"), {"company": "", "role": "x"})
        self.assertFalse(JobApplication.objects.exists())

    def test_drag_to_another_stage_and_order(self):
        a, b = self.app(stage=JobStage.WISHLIST), self.app(company="Bkash", stage=JobStage.APPLIED)
        r = self.client.post(reverse("work:api_job_move", args=[a.pk]), {"stage": "applied", "order": f"{a.pk},{b.pk}"}).json()
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual((r["stage"], a.stage, a.applied_on, a.order, b.order), ("applied", "applied", self.today, 0, 1))
        self.assertEqual(self.client.post(reverse("work:api_job_move", args=[a.pk]), {"stage": "nope"}).status_code, 400)

    def test_only_mine(self):
        other = User.objects.create_user("o", "o@example.com", PW)
        theirs = JobApplication.objects.create(owner=other, company="Secret", role="x")
        self.assertEqual(self.client.get(reverse("work:job", args=[theirs.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("work:jobs")), "Secret")


class ApplicationTests(Base):
    def test_a_round_moves_it_on_and_its_questions_go_to_the_bank(self):
        a = self.app(stage=JobStage.APPLIED)
        url = reverse("work:job", args=[a.pk])
        self.client.post(url, {"action": "round", "round-kind": "technical", "round-at": "2026-11-02T10:30",
                               "round-questions": "- Reverse a linked list\n- Design a URL shortener\n"})
        a.refresh_from_db()
        self.assertEqual(a.stage, JobStage.INTERVIEW)
        rnd = a.rounds.get()
        self.assertEqual(rnd.question_list, ["Reverse a linked list", "Design a URL shortener"])
        self.client.post(url, {"action": "to_bank", "round": rnd.pk})
        self.client.post(url, {"action": "to_bank", "round": rnd.pk})         # not twice
        qs = Question.objects.filter(owner=self.me, topic__name=jobs.BANK_TOPIC)
        self.assertEqual(qs.count(), 2)
        self.assertEqual(set(qs.values_list("companies", flat=True)), {"Acme"})
        page = self.client.get(url)
        self.assertContains(page, "Practise 2 questions")
        self.assertContains(page, "?company=Acme")

    def test_a_recruiter_call_is_screening(self):
        a = self.app(stage=JobStage.APPLIED)
        self.client.post(reverse("work:job", args=[a.pk]), {"action": "round", "round-kind": "recruiter"})
        a.refresh_from_db()
        self.assertEqual(a.stage, JobStage.SCREEN)

    def test_save_details_and_delete_to_recently_deleted(self):
        from apps.trash.models import DeletedItem

        a = self.app()
        url = reverse("work:job", args=[a.pk])
        self.client.post(url, {"action": "save", "app-company": "Acme", "app-role": "Senior Backend Engineer", "app-stage": "offer",
                               "app-interest": 5, "app-description": "We use Python, Django, PostgreSQL and Kubernetes."})
        a.refresh_from_db()
        self.assertEqual((a.role, a.stage, a.interest), ("Senior Backend Engineer", JobStage.OFFER, 5))
        self.assertIsNotNone(a.applied_on)
        self.client.post(url, {"action": "delete"})
        self.assertFalse(JobApplication.objects.exists())
        self.assertTrue(DeletedItem.objects.filter(user=self.me).exists())

    def test_skills_next_to_what_is_prepared(self):
        topic = PrepTopic.objects.create(owner=self.me, name="Python")
        Question.objects.create(owner=self.me, topic=topic, prompt="What is the GIL?")
        a = self.app(description="Strong Python and Django; Kubernetes is a plus.")
        page = self.client.get(reverse("work:job", args=[a.pk]))
        skills = {s["skill"]: s["questions"] for s in page.context["skills"]}
        self.assertEqual(skills["Python"], 1)
        self.assertEqual(skills["Kubernetes"], 0)


class SkillTests(SimpleTestCase):
    def test_each_skill_once_and_not_inside_other_words(self):
        self.assertEqual(jobs.skills_in("Python, python3? Go and Golang, Django. React/Node.js, C# and C++. AWS + k8s; good English"),
                         ["Python", "Go", "Django", "React", "Node.js", "C#", "C++", "AWS", "Kubernetes"])
        self.assertEqual(jobs.skills_in("going to the cargo docks"), [])


class ComingUpTests(Base):
    def test_interviews_next_steps_and_quiet_ones(self):
        a = self.app(stage=JobStage.INTERVIEW, next_step="Send the take-home", next_on=self.today)
        JobRound.objects.create(application=a, kind="design", at=timezone.now() + timedelta(days=2))
        JobRound.objects.create(application=a, kind="technical", at=timezone.now() + timedelta(days=20))     # too far
        quiet = self.app(company="Quiet Co", stage=JobStage.APPLIED)
        JobApplication.objects.filter(pk=quiet.pk).update(stage_changed_at=timezone.now() - timedelta(days=20))
        c = jobs.coming_up(self.me, self.today)
        self.assertEqual((len(c["rounds"]), [x.pk for x in c["due"]], [x.pk for x in c["quiet"]]), (1, [a.pk], [quiet.pk]))
        page = self.client.get(reverse("work:today"))
        self.assertContains(page, "Send the take-home")
        self.assertContains(page, "Follow up with Quiet Co")

    def test_the_funnel(self):
        self.app(stage=JobStage.WISHLIST)
        self.app(stage=JobStage.APPLIED)
        self.app(stage=JobStage.SCREEN)
        b = self.app(stage=JobStage.APPLIED)
        JobRound.objects.create(application=b, kind="technical")
        self.app(stage=JobStage.OFFER)
        f = jobs.funnel(self.me)
        self.assertEqual((f["applied"], f["answered"], f["interviews"], f["offers"]), (4, 3, 2, 1))
        self.assertEqual(f["offer_rate"], 25)


class StoryTests(Base):
    def test_write_a_story_and_see_the_gaps(self):
        r = self.client.post(reverse("work:story_new"), {"title": "The payments outage", "situation": "Checkout down", "action": "I rolled back",
                                                          "result": "Back in 9 minutes", "shows": ["ownership", "failure"]})
        s = Story.objects.get()
        self.assertRedirects(r, reverse("work:stories") + f"#story-{s.pk}")
        self.assertEqual(s.competencies, ["ownership", "failure"])
        cover = {c["key"]: len(c["stories"]) for c in jobs.coverage(self.me)}
        self.assertEqual((cover["ownership"], cover["conflict"]), (1, 0))
        page = self.client.get(reverse("work:stories"))
        self.assertContains(page, "?shows=conflict")                         # a gap: write one
        self.assertContains(page, "The payments outage")

    def test_a_gap_link_ticks_what_it_shows(self):
        page = self.client.get(reverse("work:story_new") + "?shows=conflict")
        self.assertRegex(page.content.decode(), r'value="conflict"[^>]* checked')

    def test_told_it(self):
        s = Story.objects.create(owner=self.me, title="x")
        r = self.client.post(reverse("work:stories"), {"action": "practised", "story": s.pk}).json()
        self.assertEqual(r["practised"], 1)

    def test_every_question_says_what_it_is_after(self):
        deck = jobs.practice_deck()
        self.assertGreaterEqual(len(deck), 20)
        self.assertTrue(all(d["key"] in jobs.COMPETENCIES for d in deck))


class FindItTests(Base):
    def test_palette_search_and_shortcuts(self):
        self.app(company="Grameenphone")
        Story.objects.create(owner=self.me, title="Hardest bug: the memory leak")
        kinds = {r["kind"] for r in self.client.get(reverse("work:api_search"), {"q": "grameen"}).json()["results"]}
        self.assertIn("job", kinds)
        kinds = {r["kind"] for r in self.client.get(reverse("work:api_search"), {"q": "memory leak"}).json()["results"]}
        self.assertIn("story", kinds)
        from apps.core import launcher

        self.assertIn("jobs", [s["key"] for s in launcher.available(self.me)])
