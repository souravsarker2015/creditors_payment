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
