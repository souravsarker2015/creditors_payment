"""What a developer's day leans on: the personal API behind `ft`, coming back to work, what Git says about a task,
a sprint weighed in points, and how the time was really spent."""
import hashlib
import hmac
import json
import shutil
import subprocess
from datetime import datetime, time, timedelta
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.business.core.models import Dashboard, UserDashboardAccess

from ..access import CODE
from .. import dev, services, sprints
from ..models import Note, Priority, Snippet, Sprint, Status, Task, TaskActivity, TaskKind, TimeEntry, WorkSettings


def person(name):
    user = get_user_model().objects.create_user(name, password="x")
    UserDashboardAccess.objects.get_or_create(user=user, dashboard=Dashboard.objects.get(code=CODE))
    return user


class Base(TestCase):
    def setUp(self):
        self.me = person("me")
        self.ws = WorkSettings.for_user(self.me)
        self.token = self.ws.new_api_token()
        self.api = Client(HTTP_AUTHORIZATION=f"Bearer {self.token}")

    def post(self, path, data=None, **extra):
        return self.api.post(f"/work/api/v1{path}", json.dumps(data or {}), content_type="application/json", **extra)

    def get(self, path, **extra):
        return self.api.get(f"/work/api/v1{path}", **extra)


class TokenTests(Base):
    def test_only_the_hash_is_kept(self):
        self.ws.refresh_from_db()
        self.assertNotIn(self.token, json.dumps([self.ws.api_token_hash, self.ws.api_token_hint]))
        self.assertEqual(self.ws.api_token_hash, hashlib.sha256(self.token.encode()).hexdigest())

    def test_no_token_or_a_wrong_one_gets_nothing(self):
        self.assertEqual(Client().get("/work/api/v1/me/").status_code, 401)
        self.assertEqual(Client(HTTP_AUTHORIZATION="Bearer nope").get("/work/api/v1/me/").status_code, 401)

    def test_an_empty_token_never_matches_someone_without_one(self):
        person("other")
        self.assertEqual(Client(HTTP_AUTHORIZATION="Bearer ").get("/work/api/v1/me/").status_code, 401)

    def test_a_new_token_ends_the_old_one(self):
        self.ws.new_api_token()
        self.assertEqual(self.get("/me/").status_code, 401)

    def test_turned_off_in_settings(self):
        self.client.force_login(self.me)
        self.client.post(reverse("work:settings"), {"action": "api_off"})
        self.assertEqual(self.get("/me/").status_code, 401)

    def test_a_blocked_person_cant_use_theirs(self):
        self.me.is_active = False
        self.me.save()
        self.assertEqual(self.get("/me/").status_code, 401)

    def test_settings_shows_a_new_token_once(self):
        self.client.force_login(self.me)
        page = self.client.post(reverse("work:settings"), {"action": "api"}, follow=True)
        self.ws.refresh_from_db()
        self.assertContains(page, "ftk_")
        self.assertNotContains(self.client.get(reverse("work:settings")), "ftk_")

    def test_it_reaches_only_its_owners_tasks(self):
        theirs = Task.objects.create(owner=person("other"), title="Secret")
        self.assertEqual(self.get(f"/tasks/T-{theirs.pk}/").status_code, 404)
        self.assertEqual(self.post(f"/tasks/T-{theirs.pk}/", {"status": "done"}).status_code, 404)
        self.assertEqual(self.post("/timer/", {"task": theirs.pk}).status_code, 404)
        self.assertEqual(self.get("/tasks/?status=all").json()["tasks"], [])


class ApiTests(Base):
    def test_adding_is_quick_add(self):
        made = self.post("/tasks/", {"text": "fix(auth): login loop #api p1 ~2h"}).json()["task"]
        self.assertEqual((made["title"], made["kind"], made["priority"]), ("Login loop", TaskKind.BUG, Priority.URGENT))
        self.assertTrue(made["branch"].startswith(f"fix/T-{made['id']}-"))

    def test_listing_and_filtering(self):
        Task.objects.create(owner=self.me, title="Open one")
        Task.objects.create(owner=self.me, title="Finished", status=Status.DONE)
        self.assertEqual([t["title"] for t in self.get("/tasks/").json()["tasks"]], ["Open one"])
        self.assertEqual(len(self.get("/tasks/?status=all").json()["tasks"]), 2)
        self.assertEqual(self.get("/tasks/?status=nonsense").status_code, 400)

    def test_a_terminal_gets_lines(self):
        t = Task.objects.create(owner=self.me, title="Open one")
        r = self.get("/tasks/", HTTP_ACCEPT="text/plain")
        self.assertEqual(r["Content-Type"].split(";")[0], "text/plain")
        self.assertIn(f"T-{t.pk}", r.content.decode())
        self.assertEqual(self.get("/tasks/T-9999/", HTTP_ACCEPT="text/plain").content.decode().strip(), "There's no task T-9999.")

    def test_one_field_for_the_shell(self):
        t = Task.objects.create(owner=self.me, title="Add login", kind=TaskKind.FEATURE)
        self.assertEqual(self.get(f"/tasks/{t.pk}/?field=branch", HTTP_ACCEPT="text/plain").content.decode().strip(), f"feat/T-{t.pk}-add-login")

    def test_moving_and_finishing(self):
        t = Task.objects.create(owner=self.me, title="x")
        self.post(f"/tasks/T-{t.pk}/", {"status": "review"})
        t.refresh_from_db()
        self.assertEqual(t.status, Status.REVIEW)
        self.post(f"/tasks/T-{t.pk}/", {"status": "done"})
        t.refresh_from_db()
        self.assertTrue(t.is_done and t.completed_at)
        self.assertEqual(self.post(f"/tasks/T-{t.pk}/", {"status": "nonsense"}).status_code, 400)

    def test_a_comment(self):
        t = Task.objects.create(owner=self.me, title="x")
        self.post(f"/tasks/{t.pk}/", {"comment": "tried on staging"})
        self.assertTrue(TaskActivity.objects.filter(task=t, text="tried on staging").exists())

    def test_the_timer_and_where_i_left_off(self):
        t = Task.objects.create(owner=self.me, title="x")
        self.post("/timer/", {"task": f"T-{t.pk}"})
        self.assertEqual(self.get("/timer/").json()["running"], "x")
        self.post("/timer/", {"stop": True, "left_off": "next: the retry"})
        t.refresh_from_db()
        self.assertEqual(t.left_off, "next: the retry")
        self.assertIsNone(services.running_entry(self.me))
        self.assertEqual(self.post("/timer/", {"task": t.pk}).json()["left_off"], "next: the retry")

    def test_a_line_goes_in_todays_note(self):
        self.post("/log/", {"text": "pg needs a restart"})
        self.post("/log/", {"text": "second line"})
        note = Note.objects.get(owner=self.me, tags__name="daily")
        self.assertIn("pg needs a restart", note.body)
        self.assertIn("second line", note.body)

    def test_one_snippet_found_is_just_its_code(self):
        Snippet.objects.create(owner=self.me, title="Prune", language="bash", code="docker system prune -af")
        self.assertEqual(self.get("/snippets/?q=prune", HTTP_ACCEPT="text/plain").content.decode().strip(), "docker system prune -af")

    def test_bad_input_is_said(self):
        self.assertEqual(self.post("/tasks/", {}).status_code, 400)
        self.assertEqual(self.api.post("/work/api/v1/tasks/", "not json", content_type="application/json").status_code, 400)
        self.assertEqual(self.api.post("/work/api/v1/tasks/", "[1]", content_type="application/json").status_code, 400)
        self.assertEqual(self.api.delete("/work/api/v1/tasks/").status_code, 405)

    def test_the_standup(self):
        self.assertIn("standup", self.get("/standup/").json())


class CliTests(TestCase):
    def test_the_script_has_this_sites_address_and_no_secret(self):
        r = self.client.get(reverse("work:cli"))
        self.assertEqual(r.status_code, 200)
        text = r.content.decode()
        self.assertTrue(text.startswith("#!/bin/sh\n"))
        self.assertIn('FT_URL="${FT_URL:-http://testserver}"', text)

    @skipUnless(shutil.which("sh"), "no shell")
    def test_it_is_valid_shell(self):
        text = self.client.get(reverse("work:cli")).content.decode()
        self.assertEqual(subprocess.run(["sh", "-n"], input=text, text=True, capture_output=True).returncode, 0)


class LeftOffTests(TestCase):
    def setUp(self):
        self.me = person("me")
        self.client.force_login(self.me)

    def test_it_can_be_written_and_is_shown_on_coming_back(self):
        t = Task.objects.create(owner=self.me, title="x")
        self.client.post(reverse("work:api_task_update", args=[t.pk]), {"left_off": "next: fixtures"})
        self.assertContains(self.client.get(reverse("work:task", args=[t.pk])), "next: fixtures")
        self.assertContains(self.client.get(reverse("work:today")), "next: fixtures")

    def test_finishing_the_task_clears_it(self):
        t = Task.objects.create(owner=self.me, title="x", left_off="next")
        services.set_done(t, True)
        t.refresh_from_db()
        self.assertEqual(t.left_off, "")

    def test_the_timer_brings_it_back(self):
        t = Task.objects.create(owner=self.me, title="x", left_off="next: fixtures")
        r = self.client.post(reverse("work:api_timer_start"), {"task": t.pk}).json()
        self.assertEqual(r["running"]["left_off"], "next: fixtures")


class QuickAddTests(SimpleTestCase):
    def test_p1_is_the_most_urgent(self):
        self.assertEqual(services.parse_quick("Write tests p1").priority, Priority.URGENT)
        self.assertEqual(services.parse_quick("Write tests p4").priority, Priority.LOW)
        self.assertEqual(services.parse_quick("Write tests p2 #api tomorrow").priority, Priority.HIGH)

    def test_in_a_sentence_it_stays_words(self):
        self.assertEqual(services.parse_quick("Fix p1 outage").title, "Fix p1 outage")
        self.assertEqual(services.parse_quick("Fix P1").title, "Fix P1")

    def test_review_and_debt_are_types_of_work(self):
        self.assertEqual(services.parse_quick("review: acme/app#12").kind, TaskKind.REVIEW)
        self.assertEqual(services.parse_quick("review: acme/app#12").title, "acme/app#12")
        self.assertEqual(services.parse_quick("debt: remove the old client").kind, TaskKind.DEBT)


class CommitMessageTests(TestCase):
    def msg(self, title, kind=TaskKind.BUG):
        me = get_user_model().objects.create_user(f"u{Task.objects.count()}", password="x")
        return dev.commit_message(Task.objects.create(owner=me, title=title, kind=kind), WorkSettings.for_user(me))

    def test_the_word_isnt_said_twice(self):
        self.assertTrue(self.msg("Fix the login redirect loop!").startswith("fix: the login redirect loop (T-"))
        self.assertTrue(self.msg("Fixes crash").startswith("fix: crash (T-"))

    def test_a_word_that_only_starts_the_same_stays(self):
        self.assertTrue(self.msg("Fixture loading").startswith("fix: fixture loading (T-"))

    def test_the_subject_keeps_to_72_and_keeps_its_key(self):
        message = self.msg("A very long title " * 10)
        self.assertLessEqual(len(message), 72)
        self.assertRegex(message, r"… \(T-\d+\)$")


class GitTests(Base):
    def setUp(self):
        super().setUp()
        self.ws.new_git_token()
        self.t = Task.objects.create(owner=self.me, title="x", status=Status.REVIEW)
        self.key = self.t.key(self.ws.key_prefix)
        self.pr = {"html_url": "https://x/pull/9", "number": 9, "title": f"fix {self.key}", "body": "", "head": {"ref": f"fix/{self.key}-x"}}

    def hook(self, event, data, secret=None):
        body = json.dumps(data).encode()
        sig = hmac.new(self.ws.git_token.encode(), body, hashlib.sha256).hexdigest()
        r = self.client.post(reverse("work:git_hook", args=[self.ws.git_token]), body, content_type="application/json",
                             HTTP_X_GITHUB_EVENT=event, HTTP_X_HUB_SIGNATURE_256=f"sha256={sig}")
        self.assertEqual(r.status_code, 200)
        self.t.refresh_from_db()

    def said(self):
        return " ".join(TaskActivity.objects.filter(task=self.t).values_list("text", flat=True))

    def test_changes_asked_for_put_it_back_in_progress(self):
        self.hook("pull_request_review", {"action": "submitted", "pull_request": self.pr, "review": {"state": "changes_requested", "user": {"login": "sam"}}})
        self.assertEqual(self.t.status, Status.DOING)
        self.assertIn("sam asked for changes", self.said())

    def test_an_approval_is_noted_and_stays_in_review(self):
        self.hook("pull_request_review", {"action": "submitted", "pull_request": self.pr, "review": {"state": "approved", "user": {"login": "sam"}}})
        self.assertEqual(self.t.status, Status.REVIEW)
        self.assertIn("approved by sam", self.said())

    def test_a_plain_comment_review_changes_nothing(self):
        self.hook("pull_request_review", {"action": "submitted", "pull_request": self.pr, "review": {"state": "commented", "user": {"login": "sam"}}})
        self.assertEqual((self.t.status, self.said()), (Status.REVIEW, ""))

    def test_closed_without_merging_isnt_left_in_review(self):
        self.hook("pull_request", {"action": "closed", "pull_request": {**self.pr, "merged": False}})
        self.assertEqual(self.t.status, Status.DOING)
        self.assertIn("closed without merging", self.said())

    def test_merged_is_still_done(self):
        self.hook("pull_request", {"action": "closed", "pull_request": {**self.pr, "merged": True}})
        self.assertEqual(self.t.status, Status.DONE)

    def test_a_failed_build_on_its_branch(self):
        run = {"conclusion": "failure", "name": "CI", "head_branch": f"fix/{self.key}-x", "html_url": "https://x/ci"}
        self.hook("workflow_run", {"action": "completed", "workflow_run": run})
        self.assertIn("CI failed", self.said())

    def test_a_passing_build_says_nothing(self):
        self.hook("workflow_run", {"action": "completed", "workflow_run": {"conclusion": "success", "head_branch": f"fix/{self.key}-x"}})
        self.assertEqual(self.said(), "")


class SprintTests(TestCase):
    def setUp(self):
        self.me = person("me")
        today = timezone.localdate()
        self.sprint = Sprint.objects.create(owner=self.me, name="S", start_date=today - timedelta(days=2), end_date=today + timedelta(days=5))

    def test_a_big_task_weighs_more_than_a_small_one(self):
        Task.objects.create(owner=self.me, title="big", sprint=self.sprint, points=13)
        Task.objects.create(owner=self.me, title="small", sprint=self.sprint, points=3, status=Status.DONE, completed_at=timezone.now())
        b = sprints.burndown(self.sprint)
        self.assertEqual((b["unit"], b["total"], b["points"][-1][1]), ("points", 16, 13))

    def test_without_points_it_counts_tasks(self):
        Task.objects.create(owner=self.me, title="a", sprint=self.sprint)
        b = sprints.burndown(self.sprint)
        self.assertEqual((b["unit"], b["total"]), ("tasks", 1))

    def test_a_closed_sprint_keeps_its_unit(self):
        Task.objects.create(owner=self.me, title="big", sprint=self.sprint, points=13, status=Status.DONE, completed_at=timezone.now())
        sprints.close(self.sprint)
        self.sprint.refresh_from_db()
        b = sprints.burndown(self.sprint)
        self.assertEqual((b["unit"], b["total"]), ("points", 13))

    def test_more_than_usually_finished_is_said(self):
        today = timezone.localdate()
        old = Sprint.objects.create(owner=self.me, name="Old", start_date=today - timedelta(days=30), end_date=today - timedelta(days=17))
        Task.objects.create(owner=self.me, title="done", sprint=old, points=8, status=Status.DONE, completed_at=timezone.now())
        sprints.close(old)
        Task.objects.create(owner=self.me, title="big", sprint=self.sprint, points=13)
        c = sprints.capacity(self.sprint)
        self.assertEqual((c["planned"], c["usual"], c["unit"], c["over"]), (13, 8, "points", True))
        self.client.force_login(self.me)
        self.assertContains(self.client.get(reverse("work:sprint", args=[self.sprint.pk])), "You usually finish about 8")

    def test_no_history_no_warning(self):
        self.assertIsNone(sprints.capacity(self.sprint))


class FocusTests(TestCase):
    def setUp(self):
        self.me = person("me")
        self.day = timezone.localdate() - timedelta(days=1)

    def entry(self, hour, minute, length, **what):
        at = timezone.make_aware(datetime.combine(self.day, time(hour, minute)))
        return TimeEntry.objects.create(owner=self.me, started_at=at, ended_at=at + timedelta(minutes=length), **what)

    def test_a_short_break_doesnt_end_a_block(self):
        self.entry(10, 0, 30, description="a")
        self.entry(10, 33, 30, description="a")
        f = services.focus_pattern(self.me, self.day, self.day)
        self.assertEqual((f["blocks"], f["deep"]), (1, 1))

    def test_changing_what_you_work_on_counts(self):
        self.entry(10, 0, 20, description="a")
        self.entry(10, 20, 20, description="b")
        self.entry(10, 40, 20, description="a")
        f = services.focus_pattern(self.me, self.day, self.day)
        self.assertEqual((f["blocks"], f["deep"], f["switches"]), (3, 0, 2.0))

    def test_when_the_deep_work_happens(self):
        self.entry(10, 0, 90, description="a")
        f = services.focus_pattern(self.me, self.day, self.day)
        self.assertEqual(f["best_from"].hour, 10)

    def test_nothing_tracked(self):
        self.assertIsNone(services.focus_pattern(self.me, self.day, self.day))

    def test_it_shows_on_reports(self):
        self.entry(10, 0, 90, description="a")
        self.client.force_login(self.me)
        self.assertContains(self.client.get(reverse("work:reports"), {"range": "30"}), "How you focus")


class BackupKeysTests(TestCase):
    def test_a_tracker_backup_carries_no_keys_and_keeps_where_i_left_off(self):
        me = person("me")
        ws = WorkSettings.for_user(me)
        ws.new_api_token()
        ws.new_git_token()
        Task.objects.create(owner=me, title="x", left_off="next: fixtures")
        rows, _files = services.backup_rows(me)
        text = json.dumps(rows)
        self.assertIn("next: fixtures", text)
        for key in (ws.api_token_hash, ws.git_token):
            self.assertNotIn(key, text)


JS = (Path(settings.BASE_DIR) / "static/js/devtools.js")
NODE = r"""
global.window = {}; global.document = { addEventListener() {}, documentElement: { lang: "en" } };
if (!global.crypto) global.crypto = require("crypto").webcrypto;
require(process.argv[1]);
const D = window.FTDevTools, out = {};
const attempt = (f) => { try { return f(); } catch (e) { return "THROWS"; } };
out.big = D.fmtJson('{"id":12345678901234567890,"p":1.10,"e":1e3,"s":"12345678901234567890","n":5}', 0);
out.invalid = attempt(() => D.fmtJson('{"a":01}', 0));
out.jwt = D.readJwt(btoa('{"alg":"HS256"}') + "." + btoa('{"uid":12345678901234567890}') + ".x").payload;
out.cron = [D.cronWords("*/15 9-17 * * 1-5", {}), D.cronWords("0 9 * * 1-5", {}), D.cronWords("@daily", {}), D.cronWords("1 2 3 4 5", {})];
out.uuid = D.uuid7();
out.sql = D.fmtSql("select a, b from t where x = 'select from' and y = 1 order by a");
out.bases = D.bases("0xFF").map((x) => x[1]);
out.big64 = D.bases("18446744073709551615")[0][1];
out.notNumber = attempt(() => D.bases("12ab"));
out.chmod = [D.chmod("755").symbolic, D.chmod("rw-r--r--").octal, D.chmod("-rwxr-xr-x").octal];
out.badMode = attempt(() => D.chmod("999"));
out.lines = [D.lines("b\na\nb", "unique").join(","), D.lines("10\n9", "sort").join(",")];
console.log(JSON.stringify(out));
"""


@skipUnless(shutil.which("node"), "Node isn't installed")
class DevToolsTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        run = subprocess.run(["node", "-e", NODE, str(JS)], capture_output=True, text=True, timeout=30)
        assert run.returncode == 0, run.stderr
        cls.r = json.loads(run.stdout)

    def test_numbers_come_back_exactly_as_written(self):
        self.assertEqual(self.r["big"], '{"id":12345678901234567890,"p":1.10,"e":1e3,"s":"12345678901234567890","n":5}')
        self.assertIn("12345678901234567890", self.r["jwt"])

    def test_invalid_json_is_still_invalid(self):
        self.assertEqual(self.r["invalid"], "THROWS")

    def test_cron_in_words_or_not_at_all(self):
        self.assertEqual(self.r["cron"], ["every 15 minutes, 09:00–17:59, Monday to Friday", "at 09:00, Monday to Friday", "at 00:00, every day", ""])

    def test_a_v7_uuid(self):
        self.assertRegex(self.r["uuid"], r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")

    def test_sql_leaves_strings_alone(self):
        self.assertIn("WHERE x = 'select from'", self.r["sql"])
        self.assertIn("\n  AND y = 1", self.r["sql"])
        self.assertIn("\nORDER BY a", self.r["sql"])

    def test_bases_stay_exact(self):
        self.assertEqual(self.r["bases"], ["255", "0xff", "0o377", "0b11111111"])
        self.assertEqual(self.r["big64"], "18446744073709551615")
        self.assertEqual(self.r["notNumber"], "THROWS")

    def test_chmod_both_ways(self):
        self.assertEqual(self.r["chmod"], ["rwxr-xr-x", "644", "755"])
        self.assertEqual(self.r["badMode"], "THROWS")

    def test_lines(self):
        self.assertEqual(self.r["lines"], ["b,a", "9,10"])


class PersonalBackupKeysTests(TestCase):
    def test_keys_stay_out_of_the_file_and_out_of_another_account(self):
        import io
        import zipfile

        from apps.core import personal_backup as pb

        me = person("me")
        ws = WorkSettings.for_user(me)
        ws.new_api_token()
        ws.new_git_token()
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as z:
            pb.add_to_zip(z, me)
            text = b"".join(z.read(n) for n in z.namelist()).decode("utf-8", "ignore")
        self.assertNotIn(ws.api_token_hash, text)
        self.assertNotIn(ws.git_token, text)
