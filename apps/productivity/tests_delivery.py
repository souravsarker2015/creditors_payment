"""For software work: the "In review" step (a pull request waiting on code
review), the standup that says what Git saw yesterday, the Delivery report
(cycle and lead time, tasks finished each week) and a pull request's text
copied from its task."""
import hashlib
import hmac
import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import dev, importer, services
from .models import Status, Task, TaskActivity, TaskKind, TimeEntry, WorkSettings

PW = "Str0ng-pass-123"


class Base(TestCase):
    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)
        self.ws = WorkSettings.for_user(self.me)

    def task(self, title, **kw):
        return Task.objects.create(owner=self.me, title=title, **kw)


class ReviewStatusTests(Base):
    def test_board_has_an_in_review_column_between_in_progress_and_done(self):
        self.task("Waiting on Ana", status=Status.REVIEW)
        cols = self.client.get(reverse("work:tasks") + "?view=board").context["columns"]
        self.assertEqual([c["status"] for c in cols], ["backlog", "todo", "doing", "review", "done"])
        self.assertEqual([t.title for t in cols[3]["tasks"]], ["Waiting on Ana"])

    def test_the_list_keeps_it_in_its_own_group_even_when_late(self):
        self.task("PR open", status=Status.REVIEW, due_date=timezone.localdate() - timedelta(days=2))
        groups = {key: [t.title for t in items] for key, _l, items, _n in self.client.get(reverse("work:tasks")).context["groups"]}
        self.assertEqual(groups["review"], ["PR open"])
        self.assertNotIn("overdue", groups)                # (empty groups aren't shown)

    def test_imported_review_states(self):
        self.assertEqual(importer._status("In Review"), Status.REVIEW)
        self.assertEqual(importer._status("Code review"), Status.REVIEW)
        self.assertEqual(importer._status("In Progress"), Status.DOING)


class WebhookReviewTests(Base):
    def setUp(self):
        super().setUp()
        self.token = self.ws.new_git_token()
        self.url = reverse("work:git_hook", args=[self.token])
        self.client.logout()

    def github(self, event, data):
        body = json.dumps(data).encode()
        sig = "sha256=" + hmac.new(self.token.encode(), body, hashlib.sha256).hexdigest()
        return self.client.post(self.url, body, content_type="application/json", HTTP_X_GITHUB_EVENT=event, HTTP_X_HUB_SIGNATURE_256=sig).json()

    def pr(self, t, **kw):
        return {"number": 9, "title": f"T-{t.pk} dark mode", "html_url": "https://github.com/me/app/pull/9", "head": {"ref": "feat/x"}, **kw}

    def test_a_draft_is_in_progress_then_ready_is_in_review(self):
        t = self.task("Dark mode")
        self.assertEqual(self.github("pull_request", {"action": "opened", "pull_request": self.pr(t, draft=True)})["started"], 1)
        t.refresh_from_db()
        self.assertEqual(t.status, Status.DOING)
        self.assertEqual(self.github("pull_request", {"action": "ready_for_review", "pull_request": self.pr(t)})["review"], 1)
        t.refresh_from_db()
        self.assertEqual(t.status, Status.REVIEW)
        self.github("pull_request", {"action": "converted_to_draft", "pull_request": self.pr(t, draft=True)})
        t.refresh_from_db()
        self.assertEqual(t.status, Status.DOING)

    def test_git_activity_is_marked_for_the_standup(self):
        t = self.task("Dark mode")
        self.github("push", {"ref": "refs/heads/main", "commits": [{"id": "abc1234", "message": f"T-{t.pk} colours"}, {"id": "def5678", "message": f"T-{t.pk} more"}]})
        self.github("pull_request", {"action": "opened", "pull_request": self.pr(t)})
        kinds = sorted(a.data.get("git") for a in TaskActivity.objects.filter(task=t, kind=TaskActivity.Kind.COMMENT))
        self.assertEqual(kinds, ["commit", "commit", "pr"])


class StandupGitTests(Base):
    def yesterday(self, activity):
        when = timezone.now() - timedelta(days=1)
        TaskActivity.objects.filter(pk=activity.pk).update(created_at=when)

    def test_commits_and_pull_requests_without_tracked_time(self):
        self.ws.work_days = "0123456"
        self.ws.save()
        t = self.task("Dark mode")
        for i, (git, ref) in enumerate([("commit", "a1"), ("commit", "b2"), ("pr", "PR #9")]):
            self.yesterday(TaskActivity.objects.create(task=t, kind=TaskActivity.Kind.COMMENT, text=str(i), data={"git": git, "ref": ref}))
        TaskActivity.objects.create(task=t, kind=TaskActivity.Kind.COMMENT, text="a plain comment, today")
        data = services.standup(self.me)
        self.assertIn("Dark mode — 2 commits · PR #9 opened", data["yesterday"])

    def test_merged_wins_over_opened_and_tasks_in_review_are_waiting(self):
        self.ws.work_days = "0123456"
        self.ws.save()
        t = self.task("API", status=Status.REVIEW, link="https://github.com/me/app/pull/3")
        for git in ("pr", "merged"):
            self.yesterday(TaskActivity.objects.create(task=t, kind=TaskActivity.Kind.COMMENT, data={"git": git, "ref": "PR #3"}))
        data = services.standup(self.me)
        self.assertIn("API — PR #3 merged", data["yesterday"])
        self.assertIn("Waiting on review: API (PR #3)", data["today"])


class DeliveryTests(Base):
    def test_cycle_and_lead_time_and_weeks(self):
        now = timezone.now()
        t = self.task("Feature", kind=TaskKind.FEATURE, points=3)
        Task.objects.filter(pk=t.pk).update(created_at=now - timedelta(days=10))
        t.refresh_from_db()
        t.status = Status.DOING
        t.save()                                          # the move to in progress is in its history
        TaskActivity.objects.filter(task=t, data__field="status").update(created_at=now - timedelta(days=4))
        services.set_done(t, True)
        b = self.task("Bug", kind=TaskKind.BUG)           # time tracked on it: that's when it started
        Task.objects.filter(pk=b.pk).update(created_at=now - timedelta(days=1))
        b.refresh_from_db()
        TimeEntry.objects.create(owner=self.me, task=b, started_at=now - timedelta(hours=6), ended_at=now - timedelta(hours=5))
        services.set_done(b, True)
        self.task("Waiting", status=Status.REVIEW)
        today = timezone.localdate()
        d = services.delivery(self.me, today - timedelta(days=6), today)
        self.assertEqual((d["done"], d["points"], d["review"], d["cycle_n"]), (2, 3, 1, 2))
        self.assertAlmostEqual(d["cycle"] / 3600, (4 * 24 + 6) / 2, delta=0.2)          # the median of 4 days and 6 hours
        self.assertEqual({k.value: n for k, _i, n in d["kinds"]}, {"feature": 1, "bug": 1})
        self.assertEqual(len(d["weeks"]), 8)
        self.assertEqual(d["weeks"][-1]["n"], 2)

    def test_reports_page_shows_it(self):
        t = self.task("Done thing")
        services.set_done(t, True)
        r = self.client.get(reverse("work:reports"))
        self.assertContains(r, "Cycle time")
        self.assertContains(r, "Finished each week")

    def test_time_logged_before_the_task_was_added_counts_from_when_it_was(self):
        now = timezone.now()
        t = self.task("Logged first")
        TimeEntry.objects.create(owner=self.me, task=t, started_at=now - timedelta(days=3), ended_at=now - timedelta(days=3) + timedelta(hours=1))
        services.set_done(t, True)
        today = timezone.localdate()
        self.assertLess(services.delivery(self.me, today, today)["cycle"], 60)

    def test_span_filter(self):
        from .templatetags.work import span
        self.assertEqual([span(None), span(600), span(5.5 * 3600), span(3 * 86400)], ["—", "10 min", "5.5 h", "3 days"])


class PullRequestTextTests(Base):
    def test_title_notes_link_and_closes(self):
        t = self.task("Fix the login loop", kind=TaskKind.BUG, notes="- [ ] keep the session\n- [ ] add a test", link="https://acme.atlassian.net/browse/PAY-8")
        text = dev.pr_description(t, self.ws)
        self.assertEqual(text.splitlines()[0], f"fix: fix the login loop (T-{t.pk})")
        self.assertIn("- [ ] add a test", text)
        self.assertIn("Ticket: https://acme.atlassian.net/browse/PAY-8", text)
        self.assertTrue(text.endswith(f"Closes T-{t.pk}"))
        t.link = "https://github.com/me/app/pull/9"          # the task's link is this pull request: not repeated
        self.assertNotIn("Ticket:", dev.pr_description(t, self.ws))
        self.assertContains(self.client.get(reverse("work:task", args=[t.pk])), "Copy pull request description")


class RetroTests(Base):
    def setUp(self):
        super().setUp()
        from .models import Sprint
        today = timezone.localdate()
        self.sp = Sprint.objects.create(owner=self.me, name="S1", start_date=today - timedelta(days=13), end_date=today)
        self.next = Sprint.objects.create(owner=self.me, name="S2", start_date=today + timedelta(days=1), end_date=today + timedelta(days=14))
        self.url = reverse("work:sprint", args=[self.sp.pk])

    def test_an_empty_one_starts_from_the_template_and_saves_as_written(self):
        r = self.client.get(self.url)
        self.assertContains(r, "## Went well")
        self.assertTrue(r.context["retro_open"])               # the last day: open
        self.assertEqual(self.client.post(self.url, {"action": "retro", "retro": "## Went well\r\n- deploys"}).json(), {"ok": True})
        self.sp.refresh_from_db()
        self.assertEqual(self.sp.retro, "## Went well\n- deploys")

    def test_action_items_become_tasks_in_the_next_sprint_once(self):
        self.sp.retro = "## Action items\n- [ ] Add a smoke test #ci\n- [x] already done\n- [ ] pair on reviews"
        self.sp.save()
        res = self.client.post(self.url, {"action": "retro_tasks"}).json()
        self.assertEqual((res["count"], res["sprint"]), (2, "S2"))
        made = Task.objects.filter(sprint=self.next).order_by("pk")
        self.assertEqual([t.title for t in made], ["Add a smoke test", "pair on reviews"])
        self.assertEqual(list(made[0].tags.values_list("name", flat=True)), ["ci"])
        self.sp.refresh_from_db()
        self.assertIn(f"](/work/tasks/{made[0].pk}/)", self.sp.retro)
        self.assertEqual(self.client.post(self.url, {"action": "retro_tasks"}).status_code, 400)       # nothing new the second time

    def test_someone_elses_sprint(self):
        other = User.objects.create_superuser("o", "o@example.com", PW)      # can use Productivity, not this sprint
        self.client.force_login(other)
        self.assertEqual(self.client.post(self.url, {"action": "retro", "retro": "x"}).status_code, 404)


class RepoLinkTests(Base):
    def task_in(self, repo, **kw):
        from .models import Project
        p = Project.objects.create(owner=self.me, name=repo or "None", repo_url=repo)
        return self.task("Dark mode", project=p, kind=TaskKind.FEATURE, **kw)

    def test_github_gitlab_bitbucket_and_others(self):
        t = self.task_in("https://github.com/acme/web.git/")
        branch = dev.branch_name(t, self.ws)
        self.assertIn("/", branch)                                   # "feat/T-1-dark-mode": a path on GitHub
        links = dev.repo_links(t, self.ws)
        self.assertEqual(links["branch"], f"https://github.com/acme/web/tree/{branch}")
        self.assertEqual(links["new_pr"], f"https://github.com/acme/web/compare/{branch}?expand=1")
        self.assertIn("/-/merge_requests/new?merge_request%5Bsource_branch%5D=", dev.repo_links(self.task_in("https://gitlab.com/acme/api"), self.ws)["new_pr"])
        self.assertIn("/pull-requests/new?source=", dev.repo_links(self.task_in("https://bitbucket.org/acme/app"), self.ws)["new_pr"])
        self.assertEqual(dev.repo_links(self.task_in("https://git.acme.dev/web"), self.ws), {"repo": "https://git.acme.dev/web"})
        self.assertEqual(dev.repo_links(self.task("No project"), self.ws), {})

    def test_the_task_page_opens_the_branch_and_a_pull_request(self):
        t = self.task_in("https://github.com/acme/web")
        html = self.client.get(reverse("work:task", args=[t.pk])).content.decode()
        self.assertIn("https://github.com/acme/web/compare/", html)
        self.assertIn("data-copy-first=", html)
        t.link = "https://github.com/acme/web/pull/12"          # already has one: that one is opened
        t.save()
        html = self.client.get(reverse("work:task", args=[t.pk])).content.decode()
        self.assertNotIn("/compare/", html)
        self.assertIn(">PR #12</a>", html.replace("\n", "").replace('{% icon "git" %}', ""))

    def test_the_project_form_keeps_it(self):
        r = self.client.post(reverse("work:project_new"), {"name": "Web", "color": "blue", "repo_url": "https://github.com/acme/web"})
        from .models import Project
        self.assertEqual(Project.objects.get(name="Web").repo_url, "https://github.com/acme/web")


class StuckReviewTests(Base):
    def test_today_nudges_about_reviews_waiting_for_days(self):
        old = self.task("Old PR", status=Status.REVIEW, link="https://github.com/a/b/pull/5")
        Task.objects.filter(pk=old.pk).update(updated_at=timezone.now() - timedelta(days=4))
        self.task("Fresh PR", status=Status.REVIEW)
        r = self.client.get(reverse("work:today"))
        self.assertEqual([t.title for t in r.context["stuck_reviews"]], ["Old PR"])
        self.assertContains(r, "Waiting on code review")
