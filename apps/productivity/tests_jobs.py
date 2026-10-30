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


class EverywhereTests(Base):
    """An interview shows wherever the day is planned: the calendar, the calendar feed and the morning email."""

    def setUp(self):
        super().setUp()
        self.a = self.app(company="Shopify", stage=JobStage.INTERVIEW, next_step="Send thank-you note", next_on=self.today)
        self.at = timezone.localtime(timezone.now()).replace(hour=23, minute=0, second=0, microsecond=0)
        self.r = JobRound.objects.create(application=self.a, kind="design", at=self.at, with_whom="Staff engineer")

    def test_on_the_calendar(self):
        page = self.client.get(reverse("work:calendar"))
        self.assertContains(page, "💼 Shopify")
        self.assertContains(page, reverse("work:job", args=[self.a.pk]) + "#rounds")

    def test_in_the_calendar_feed_with_an_alarm_an_hour_before(self):
        from . import services

        ics = services.calendar_feed(self.me)
        self.assertIn(f"UID:interview-{self.r.pk}@fintrack-work", ics)
        self.assertIn("TRIGGER:-PT1H", ics)
        self.assertIn(f"UID:job-next-{self.a.pk}@fintrack-work", ics)

    def test_in_the_morning_email(self):
        from . import emails

        b = emails.brief(self.me, self.today)
        self.assertEqual(([r.pk for r in b.interviews], [a.pk for a in b.job_steps]), ([self.r.pk], [self.a.pk]))
        self.assertTrue(b.worth_sending)
        self.assertIn("1 interview", b.headline())

    def test_found_by_name_in_search(self):
        r = self.client.get(reverse("search"), {"q": "job search"})
        self.assertContains(r, reverse("work:jobs"))


class ShortSkillTests(Base):
    def test_go_is_not_in_google(self):
        topic = PrepTopic.objects.create(owner=self.me, name="Algorithms")
        Question.objects.create(owner=self.me, topic=topic, prompt="Why did Google pick this?")
        Question.objects.create(owner=self.me, topic=topic, prompt="What is a goroutine in Go?")
        counts = {s["skill"]: s["questions"] for s in jobs.skill_readiness(self.me, ["Go", "Data structures & algorithms"])}
        self.assertEqual(counts, {"Go": 1, "Data structures & algorithms": 2})


class SafetyNetTests(Base):
    def test_a_deleted_application_comes_back_with_its_rounds(self):
        from apps.trash.models import DeletedItem
        from apps.trash.services import restore

        a = self.app(company="Undo Inc")
        JobRound.objects.create(application=a, kind="technical", questions="Two sum")
        self.client.post(reverse("work:job", args=[a.pk]), {"action": "delete"})
        self.assertFalse(JobApplication.objects.exists())
        restore(DeletedItem.objects.get(user=self.me))
        back = JobApplication.objects.get(company="Undo Inc")
        self.assertEqual(back.rounds.get().questions, "Two sum")

    def test_an_interview_reminder_an_hour_before(self):
        a = self.app(company="Remind Co")
        r = JobRound.objects.create(application=a, kind="design", at=timezone.now() + timedelta(hours=3))
        page = self.client.get(reverse("work:jobs"))
        self.assertContains(page, f"interview-{r.pk}")
        self.assertContains(page, "Remind Co")

    def test_open_applications_are_kept_for_offline(self):
        from apps.core.offline import _detail_pages

        a = self.app(stage=JobStage.INTERVIEW)
        closed = self.app(company="Old", stage=JobStage.CLOSED)
        urls = _detail_pages(self.me, False, None, work=True)
        self.assertIn(reverse("work:job", args=[a.pk]), urls)
        self.assertNotIn(reverse("work:job", args=[closed.pk]), urls)


class CarefulReadingTests(Base):
    def test_everyday_words_are_not_technologies(self):
        text = "Ready to go! The rest of the team will react quickly in the spring. We use Go, REST, React, unit testing and algorithms."
        self.assertEqual(jobs.skills_in(text), ["Go", "REST APIs", "React", "Testing", "Data structures & algorithms"])

    def test_a_closed_one_that_says_no_offer_is_not_an_offer(self):
        self.app(stage=JobStage.CLOSED, closed_reason="Rejected — no offer")
        self.assertEqual(jobs.funnel(self.me)["offers"], 0)

    def test_the_same_job_twice_opens_the_first(self):
        a = self.app(company="Pathao", role="Backend Engineer")
        r = self.client.post(reverse("work:jobs"), {"company": "pathao", "role": "backend engineer"})
        self.assertRedirects(r, reverse("work:job", args=[a.pk]))
        self.assertEqual(JobApplication.objects.count(), 1)


class OfferTests(Base):
    def offer(self, company, base, currency="BDT", **kw):
        return self.app(company=company, stage=JobStage.OFFER, offer_base=base, offer_currency=currency, **kw)

    def test_ranked_on_a_normal_year_a_joining_bonus_only_counts_once(self):
        a = self.offer("Steady", 3000000, offer_bonus=300000)
        b = self.offer("Signing", 2800000, offer_signing=1000000)
        self.assertEqual((a.yearly_pay, b.yearly_pay, b.first_year_pay), (3300000, 2800000, 3800000))
        rows, comparable = jobs.offers(self.me)
        self.assertTrue(comparable)
        self.assertEqual([r.company for r in rows], ["Steady", "Signing"])
        self.assertTrue(rows[0].best)
        self.assertEqual(rows[1].behind, 500000)
        self.assertTrue(rows[1].best_first_year)                        # … but it's said which pays more in the first year
        self.assertFalse(rows[0].best_first_year)

    def test_different_currencies_are_not_ranked(self):
        self.offer("Local", 3000000, "BDT")
        self.offer("Remote", 90000, "USD")
        rows, comparable = jobs.offers(self.me)
        self.assertFalse(comparable)
        self.assertFalse(any(r.best for r in rows))
        page = self.client.get(reverse("work:offers"))
        self.assertContains(page, "can't be ranked")
        self.assertNotContains(page, "Pays most")

    def test_an_offer_without_numbers_is_listed_not_counted(self):
        self.offer("Numbers", 3000000)
        self.app(company="Blank", stage=JobStage.OFFER)
        rows, comparable = jobs.offers(self.me)
        self.assertEqual(({r.company for r in rows}, comparable), ({"Numbers", "Blank"}, False))
        page = self.client.get(reverse("work:offers"))
        self.assertContains(page, "Write in the numbers")
        self.assertContains(page, "3,000,000")

    def test_two_with_numbers_are_ranked_and_a_blank_one_goes_last(self):
        self.offer("Blank first", None, "")
        self.offer("Lower", 2000000)
        self.offer("Higher", 3000000)
        rows, comparable = jobs.offers(self.me)
        self.assertTrue(comparable)
        self.assertEqual([r.company for r in rows], ["Higher", "Lower", "Blank first"])
        self.assertEqual(self.client.get(reverse("work:offers")).status_code, 200)

    def test_thousands_are_marked_in_bangla_too(self):
        from django.utils import translation

        self.offer("Figures", 3600000, offer_bonus=360000.5)
        with translation.override("bn"):
            page = self.client.get(reverse("work:offers"), HTTP_ACCEPT_LANGUAGE="bn")
        self.assertContains(page, "3,600,000")
        self.assertContains(page, "360,000.50")

    def test_numbers_saved_from_the_application(self):
        a = self.app(stage=JobStage.OFFER, description="x")
        url = reverse("work:job", args=[a.pk])
        self.assertContains(self.client.get(url), "app-offer_base")
        self.client.post(url, {"action": "save", "app-company": a.company, "app-role": a.role, "app-stage": "offer", "app-interest": 3,
                               "app-offer_base": "2400000", "app-offer_currency": "BDT", "app-offer_deadline": self.today.isoformat()})
        a.refresh_from_db()
        self.assertEqual((a.offer_base, a.offer_deadline), (2400000, self.today))

    def test_the_answer_by_date_shows_wherever_days_are_planned(self):
        from . import emails, services

        a = self.offer("Deadline Co", 1000000, offer_deadline=self.today + timedelta(days=2))
        self.assertEqual([x.pk for x in jobs.coming_up(self.me, self.today)["deadlines"]], [a.pk])
        self.assertContains(self.client.get(reverse("work:today")), "Answer Deadline Co's offer")
        self.assertIn(f"UID:offer-{a.pk}@fintrack-work", services.calendar_feed(self.me))
        self.assertEqual([x.pk for x in emails.brief(self.me, self.today).offer_deadlines], [a.pk])
        self.assertEqual(jobs.coming_up(self.me, self.today + timedelta(days=3))["deadlines"], [])       # gone once it's past


class PatternTests(Base):
    def log(self, **kw):
        data = {"title": "Two Sum", "url": "https://leetcode.com/problems/two-sum/", "pattern": "Arrays & hashing", "difficulty": 1, "outcome": "alone", "minutes": 12}
        data.update(kw)
        return self.client.post(reverse("work:patterns"), data)

    def test_a_problem_goes_into_the_bank_under_its_pattern_and_is_scheduled(self):
        from . import patterns

        self.log()
        q = Question.objects.get(owner=self.me, topic__name=patterns.TOPIC)
        self.assertEqual((q.title, q.section.name, q.difficulty, q.status), ("Two Sum", "Arrays & hashing", 1, "learning"))
        self.assertIn("leetcode.com/problems/two-sum", q.prompt)         # to open it when it comes back
        self.assertGreater(q.due, self.today)

    def test_solving_it_again_is_another_try_not_a_second_problem(self):
        self.log()
        self.log(title="two sum again", outcome="stuck")                # the same link
        self.log(url="", title="Two Sum", outcome="hints")              # the same name
        q = Question.objects.get(owner=self.me)
        self.assertEqual((q.attempts, q.last_rating), (3, 2))

    def test_the_roadmap_shows_weak_and_not_started_patterns(self):
        from . import patterns

        self.log()
        self.log(title="Min Window", url="", pattern="Sliding window", outcome="stuck")
        m = patterns.roadmap(self.me, self.today)
        rows = {r["name"]: r for r in m["rows"]}
        self.assertEqual((rows["Arrays & hashing"]["solved"], rows["Sliding window"]["weak"], rows["Graphs"]["total"]), (1, 1, 0))
        self.assertEqual(m["next"]["name"], "Sliding window")
        self.assertEqual(len(m["rows"]), len(patterns.PATTERNS))
        page = self.client.get(reverse("work:patterns"))
        self.assertContains(page, "Weakest now")
        self.assertContains(page, f"section={rows['Sliding window']['section']}")

    def test_nothing_logged_without_a_name_and_a_pattern(self):
        self.log(title="  ")
        self.log(pattern="Nope")
        self.assertFalse(Question.objects.exists())
        self.assertContains(self.client.get(reverse("work:patterns")), "Not started")

    def test_mine_only(self):
        from . import patterns

        self.log()
        other = User.objects.create_user("o", "o@example.com", PW)
        self.assertEqual(patterns.roadmap(other, self.today)["total"], 0)


class DevToolsPageTests(Base):
    def test_the_page_and_nothing_sent(self):
        page = self.client.get(reverse("work:tools"))
        for key in ("json", "jwt", "base64", "regex", "cron", "uuid", "hash", "diff"):
            self.assertContains(page, f'data-tool="{key}"')
        from pathlib import Path

        from django.conf import settings

        js = (Path(settings.BASE_DIR) / "static/js/devtools.js").read_text()
        self.assertNotIn("fetch(", js)                                  # the promise on the page: nothing leaves the browser
        self.assertNotIn("Work.api", js)
        self.assertNotIn("XMLHttpRequest", js)

    def test_found_from_every_door(self):
        from apps.core import launcher

        keys = [s["key"] for s in launcher.available(self.me)]
        self.assertTrue({"tools", "patterns"} <= set(keys))
        for url in ("work:tools", "work:patterns"):
            self.assertContains(self.client.get(reverse("work:today")), reverse(url))
