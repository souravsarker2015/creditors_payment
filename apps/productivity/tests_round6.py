"""For software developers: task types and story points (quick add takes a
conventional-commit start), task keys, branch names and commit messages,
the GitHub / GitLab webhook, release notes, time by type of work, and Jira's
issue types and story points in an import."""
import hashlib
import hmac
import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import dev, importer, services, sprints
from .models import Sprint, Status, Task, TaskActivity, TaskKind, TimeEntry, WorkSettings

PW = "Str0ng-pass-123"
TODAY = timezone.localdate()


class Base(TestCase):
    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)
        self.ws = WorkSettings.for_user(self.me)

    def task(self, title, **kw):
        return Task.objects.create(owner=self.me, title=title, **kw)


class QuickAddTests(Base):
    def test_conventional_commit_start_sets_type_scope_and_points(self):
        t = services.create_from_quick(self.me, "fix(auth): login redirect loop 3pt !high")
        self.assertEqual((t.title, t.kind, t.points, t.priority), ("Login redirect loop", TaskKind.BUG, 3, 3))
        self.assertEqual(list(t.tags.values_list("name", flat=True)), ["auth"])
        self.assertEqual(services.create_from_quick(self.me, "feat: dark mode 5sp").kind, TaskKind.FEATURE)
        self.assertEqual(services.create_from_quick(self.me, "refactor!: drop py3.9").kind, TaskKind.CHORE)
        self.assertEqual(services.create_from_quick(self.me, "docs: README").kind, TaskKind.DOCS)
        plain = services.create_from_quick(self.me, "fixture loading is slow")
        self.assertEqual((plain.title, plain.kind, plain.points), ("fixture loading is slow", TaskKind.TASK, None))


class NamesTests(Base):
    def test_branch_and_commit(self):
        t = self.task("Fix the login redirect loop!", kind=TaskKind.BUG)
        self.assertEqual(dev.branch_name(t, self.ws), f"fix/T-{t.pk}-fix-the-login-redirect-loop")
        self.assertEqual(dev.commit_message(t, self.ws), f"fix: fix the login redirect loop! (T-{t.pk})")
        api = self.task("API rate limits", kind=TaskKind.FEATURE)
        self.assertEqual(dev.commit_message(api, self.ws), f"feat: API rate limits (T-{api.pk})")
        bn = self.task("লগইন ঠিক করা", kind=TaskKind.CHORE)
        self.assertEqual(dev.branch_name(bn, self.ws), f"chore/T-{bn.pk}-task")
        self.ws.branch_format, self.ws.key_prefix = "{id}_{slug}", "FT"
        self.assertEqual(dev.branch_name(t, self.ws), f"{t.pk}_fix-the-login-redirect-loop")
        self.assertEqual(t.key("FT"), f"FT-{t.pk}")

    def test_task_page_offers_them(self):
        t = self.task("Ship it", kind=TaskKind.FEATURE, points=5)
        r = self.client.get(reverse("work:task", args=[t.pk]))
        self.assertContains(r, f'data-copy="feat/T-{t.pk}-ship-it"')
        self.assertContains(r, f"T-{t.pk}")
        self.assertContains(r, "data-bug-template")
        self.assertContains(r, 'data-menu="branch"')
        self.assertEqual(r.context["work_config"]["dev"], {"prefix": "T", "branch": "{type}/{key}-{slug}"})

    def test_settings(self):
        base = {"action": "settings", "s-daily_target_hours": "6", "s-work_day_list": ["0", "1"], "s-week_start": "6", "s-focus_minutes": "25",
                "s-short_break_minutes": "5", "s-long_break_minutes": "15", "s-long_break_every": "4", "s-sound": "chime", "s-volume": "50",
                "s-long_timer_hours": "3", "s-idle_minutes": "15"}
        self.client.post(reverse("work:settings"), {**base, "s-key_prefix": "app", "s-branch_format": "{type}/{key}"})
        self.ws.refresh_from_db()
        self.assertEqual((self.ws.key_prefix, self.ws.branch_format), ("APP", "{type}/{key}"))
        r = self.client.post(reverse("work:settings"), {**base, "s-branch_format": "{type}/{slug}"})
        self.assertEqual(r.status_code, 200)            # it needs {key} or {id}
        self.client.post(reverse("work:settings"), base)  # left out: kept
        self.ws.refresh_from_db()
        self.assertEqual(self.ws.key_prefix, "APP")


class ListAndSearchTests(Base):
    def test_filter_group_and_search_by_key(self):
        bug = self.task("Crash on save", kind=TaskKind.BUG)
        self.task("Dark mode", kind=TaskKind.FEATURE)
        r = self.client.get(reverse("work:tasks"), {"view": "list", "kind": "bug"})
        self.assertEqual([t.title for g in r.context["groups"] for t in g[2]], ["Crash on save"])
        r = self.client.get(reverse("work:tasks"), {"view": "list", "by": "kind"})
        self.assertEqual([k for k, *_ in r.context["groups"]], ["k-feature", "k-bug"])
        self.assertContains(r, 'data-kind="bug"')
        found = self.client.get(reverse("work:api_search"), {"q": f"t-{bug.pk}"}).json()["results"]
        self.assertEqual((found[0]["title"], found[0]["meta"].split(" · ")[0]), ("Crash on save", f"T-{bug.pk}"))

    def test_a_form_without_a_type_keeps_it(self):
        t = self.task("Crash", kind=TaskKind.BUG)
        self.client.post(reverse("work:task", args=[t.pk]), {"title": "Crash on save", "status": "todo", "priority": 0, "repeat": ""})
        t.refresh_from_db()
        self.assertEqual((t.title, t.kind), ("Crash on save", TaskKind.BUG))
        self.client.post(reverse("work:task_new"), {"title": "New one", "status": "todo", "priority": 0, "repeat": ""})
        self.assertEqual(Task.objects.get(title="New one").kind, TaskKind.TASK)

    def test_activity_notes_type_and_points(self):
        t = self.task("X")
        t.kind, t.points = TaskKind.BUG, 3
        t.save()
        from .activity import describe
        words = [describe(a) for a in t.activity.all()]
        self.assertIn("Type: Task → Bug", words)
        self.assertIn("Story points: — → 3", words)


class WebhookTests(Base):
    def setUp(self):
        super().setUp()
        self.token = self.ws.new_git_token()
        self.url = reverse("work:git_hook", args=[self.token])
        self.client.logout()          # GitHub doesn't sign in

    def github(self, event, data, secret=None):
        body = json.dumps(data).encode()
        sig = "sha256=" + hmac.new((secret or self.token).encode(), body, hashlib.sha256).hexdigest()
        return self.client.post(self.url, body, content_type="application/json", HTTP_X_GITHUB_EVENT=event, HTTP_X_HUB_SIGNATURE_256=sig)

    def test_commits_comment_and_fixes_close(self):
        a = self.task("Login loop", kind=TaskKind.BUG)
        b = self.task("Docs")
        other = Task.objects.create(owner=User.objects.create_user("x", "", PW), title="Theirs")
        r = self.github("push", {"ref": "refs/heads/main", "repository": {"full_name": "me/app"}, "commits": [
            {"id": "abc1234def", "message": f"Fixes T-{a.pk}: handle expired session\n\nRefs T-{b.pk}", "url": "https://github.com/me/app/commit/abc1234",
             "author": {"name": "Sourov"}},
            {"id": "fff0000", "message": f"wip T-{other.pk}", "url": ""}]})
        self.assertEqual(r.json(), {"ok": True, "comments": 2, "done": 1, "started": 0, "linked": 0})
        a.refresh_from_db(); b.refresh_from_db(); other.refresh_from_db()
        self.assertEqual((a.status, b.status, other.status), (Status.DONE, Status.TODO, Status.TODO))
        note = TaskActivity.objects.filter(task=a, kind="comment").first()
        self.assertIn("abc1234", note.text)
        self.assertIn("https://github.com/me/app/commit/abc1234", TaskActivity.objects.filter(task=b, kind="comment").get().text)
        self.assertFalse(TaskActivity.objects.filter(task=other, kind="comment").exists())

    def test_a_pushed_branch_starts_its_task(self):
        t = self.task("Dark mode")
        self.github("push", {"ref": f"refs/heads/feat/T-{t.pk}-dark-mode", "commits": []})
        t.refresh_from_db()
        self.assertEqual(t.status, Status.DOING)

    def test_pull_request_links_then_merge_finishes(self):
        t = self.task("Dark mode")
        pr = {"number": 7, "title": "Dark mode", "html_url": "https://github.com/me/app/pull/7", "head": {"ref": f"feat/T-{t.pk}-dark-mode"}, "body": "", "merged": False}
        self.github("pull_request", {"action": "opened", "pull_request": pr})
        t.refresh_from_db()
        self.assertEqual((t.status, t.link, t.link_label), (Status.DOING, pr["html_url"], "PR #7"))
        self.github("pull_request", {"action": "closed", "pull_request": {**pr, "merged": True}})
        t.refresh_from_db()
        self.assertEqual(t.status, Status.DONE)

    def test_a_closed_unmerged_pull_request_leaves_it(self):
        t = self.task("Dark mode", status=Status.DOING)
        self.github("pull_request", {"action": "closed", "pull_request": {"number": 7, "title": f"T-{t.pk}", "html_url": "", "head": {"ref": "x"}, "merged": False}})
        t.refresh_from_db()
        self.assertEqual(t.status, Status.DOING)

    def test_gitlab(self):
        t = self.task("Crash")
        body = {"object_kind": "push", "ref": "refs/heads/main", "project": {"path_with_namespace": "me/app"},
                "commits": [{"id": "123456789", "message": f"closes T-{t.pk}", "url": "https://gitlab.com/me/app/-/commit/1234567"}]}
        r = self.client.post(self.url, json.dumps(body), content_type="application/json", HTTP_X_GITLAB_EVENT="Push Hook", HTTP_X_GITLAB_TOKEN=self.token)
        self.assertEqual(r.json()["done"], 1)
        mr = {"object_attributes": {"action": "merge", "iid": 3, "title": "x", "url": "https://gitlab.com/me/app/-/merge_requests/3",
                                    "source_branch": f"fix/T-{t.pk}", "description": ""}}
        t2 = self.task("Other")
        mr["object_attributes"]["source_branch"] = f"fix/T-{t2.pk}"
        self.client.post(self.url, json.dumps(mr), content_type="application/json", HTTP_X_GITLAB_EVENT="Merge Request Hook", HTTP_X_GITLAB_TOKEN=self.token)
        t2.refresh_from_db()
        self.assertEqual(t2.status, Status.DONE)

    def test_wrong_secret_unknown_address_ping_and_form_payload(self):
        t = self.task("Crash")
        r = self.github("push", {"commits": [{"id": "1", "message": f"fixes T-{t.pk}"}]}, secret="wrong")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.client.post(self.url, "{}", content_type="application/json", HTTP_X_GITHUB_EVENT="push").status_code, 403)
        self.assertEqual(self.client.post(reverse("work:git_hook", args=["x" * 32]), "{}", content_type="application/json").status_code, 404)
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertEqual(self.github("ping", {"zen": "hi"}).json(), {"ok": True, "pong": True})
        from urllib.parse import urlencode
        body = urlencode({"payload": json.dumps({"commits": [{"id": "1", "message": f"fixes T-{t.pk}"}]})}).encode()
        sig = "sha256=" + hmac.new(self.token.encode(), body, hashlib.sha256).hexdigest()
        r = self.client.post(self.url, body, content_type="application/x-www-form-urlencoded", HTTP_X_GITHUB_EVENT="push", HTTP_X_HUB_SIGNATURE_256=sig)
        self.assertEqual(r.json()["done"], 1)
        t.refresh_from_db()
        self.assertEqual(t.status, Status.DONE)
        # turned off: the address stops working
        self.client.force_login(self.me)
        self.client.post(reverse("work:settings"), {"action": "git_off"})
        self.assertEqual(self.github("ping", {}).status_code, 404)

    def test_settings_show_the_address(self):
        self.client.force_login(self.me)
        r = self.client.get(reverse("work:settings"))
        self.assertContains(r, self.url)
        self.assertContains(r, self.token)


class ReleaseNotesTests(Base):
    def test_sprint_release_notes_and_points(self):
        sp = Sprint.objects.create(owner=self.me, name="Sprint 4", start_date=TODAY - timedelta(days=5), end_date=TODAY + timedelta(days=5))
        now = timezone.now()
        f = self.task("Dark mode", kind=TaskKind.FEATURE, sprint=sp, status=Status.DONE, completed_at=now, points=5, link="https://github.com/me/app/pull/9")
        b = self.task("Crash on save", kind=TaskKind.BUG, sprint=sp, status=Status.DONE, completed_at=now, points=2)
        self.task("Not done", sprint=sp, points=3)
        r = self.client.get(reverse("work:sprint", args=[sp.pk]))
        notes = r.context["release_notes"]
        self.assertIn("### Features\n- Dark mode — T-%d (https://github.com/me/app/pull/9)" % f.pk, notes)
        self.assertIn("### Bug fixes\n- Crash on save — T-%d" % b.pk, notes)
        self.assertNotIn("Not done", notes)
        self.assertEqual((r.context["pts_done"], r.context["pts_total"]), (7, 10))
        md = self.client.get(reverse("work:sprint", args=[sp.pk]), {"notes": "md"})
        self.assertEqual(md["Content-Type"], "text/markdown; charset=utf-8")
        self.assertIn("release-notes-sprint-4.md", md["Content-Disposition"])
        sprints.close(sp)
        self.assertEqual(sprints.velocity(self.me), ([(sp, 7, 3)], "points"))
        self.assertContains(self.client.get(reverse("work:sprints")), "story points finished a sprint")


class ReportByKindTests(Base):
    def test_time_by_type_of_work(self):
        now = timezone.now()
        bug = self.task("Crash", kind=TaskKind.BUG)
        feat = self.task("Dark mode", kind=TaskKind.FEATURE)
        TimeEntry.objects.create(owner=self.me, task=bug, started_at=now - timedelta(hours=3), ended_at=now - timedelta(hours=2))
        TimeEntry.objects.create(owner=self.me, task=feat, started_at=now - timedelta(hours=2), ended_at=now)
        TimeEntry.objects.create(owner=self.me, started_at=now - timedelta(hours=4), ended_at=now - timedelta(hours=3, minutes=30))
        r = self.client.get(reverse("work:reports"), {"range": "week"})
        kinds = [(k["k"].value, k["secs"]) for k in r.context["kinds"]]
        self.assertEqual(kinds, [("feature", 7200), ("bug", 3600), ("task", 1800)])
        self.assertContains(r, "wr-kind-bar")


class ImportTests(Base):
    def test_jira_issue_types_and_story_points(self):
        csv = ("Summary,Issue key,Issue Type,Status,Custom field (Story Points)\n"
               "Crash on save,APP-1,Bug,To Do,3\nDark mode,APP-2,Story,In Progress,5.0\nSetup CI,APP-3,Task,Done,\n").encode()
        rows = importer.read(csv).rows
        self.assertEqual([(r["kind"], r["points"]) for r in rows], [("bug", 3), ("feature", 5), ("task", None)])
        importer.save(self.me, rows)
        self.assertEqual(Task.objects.get(title="Crash on save").points, 3)
