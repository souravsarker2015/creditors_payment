"""What a note pulls in from elsewhere (linked.py): ```tasks lists, ![[embedded
notes]] and unlinked mentions — plus the microphone and slash items that come
with them, and the Tasks page still filtering as before (services.filter_tasks)."""
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from . import linked
from .models import Note, NoteVersion, Priority, Project, Status, Task

PW = "Str0ng-pass-123"


class Base(TestCase):
    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)
        self.today = timezone.localdate()

    def task(self, title, **kw):
        return Task.objects.create(owner=self.me, title=title, **kw)

    def note(self, title, body="", **kw):
        return Note.objects.create(owner=self.me, title=title, body=body, **kw)


class ParseQueryTests(SimpleTestCase):
    def test_a_filter_a_line_or_several_on_one(self):
        found, words, errors = linked.parse_query("project: Payments API\ndue:week #api !high\nlogin bug")
        self.assertEqual(found, {"project": "Payments API", "due": "week", "tag": "api", "priority": "high"})
        self.assertEqual(words, ["login", "bug"])
        self.assertEqual(errors, [])

    def test_unknown_filters_are_named_and_comments_skipped(self):
        found, words, errors = linked.parse_query("// my week\ncolour: red")
        self.assertEqual((found, words), ({}, []))
        self.assertEqual(len(errors), 1)
        self.assertIn("colour", errors[0])


class TaskQueryTests(Base):
    def setUp(self):
        super().setUp()
        self.api = Project.objects.create(owner=self.me, name="Payments API", color="teal")
        self.web = Project.objects.create(owner=self.me, name="Website")
        self.soon = self.task("Fix refunds", project=self.api, due_date=self.today + timedelta(days=2), priority=Priority.HIGH)
        self.late = self.task("Rotate keys", project=self.api, due_date=self.today - timedelta(days=1))
        self.web_task = self.task("New landing page", project=self.web, status=Status.DOING)
        self.done = self.task("Old bug", project=self.api, status=Status.DONE, completed_at=timezone.now())

    def run_query(self, text):
        return linked.run_query(self.me, text, self.today)

    def titles(self, res):
        return [x["title"] for x in res["items"]]

    def test_project_by_name_open_tasks_soonest_first(self):
        res = self.run_query("project: payments api")
        self.assertEqual(self.titles(res), ["Rotate keys", "Fix refunds"])
        self.assertEqual(res["chips"], ["Payments API"])
        self.assertTrue(res["items"][0]["late"])
        self.assertEqual(res["items"][1]["color"], "teal")
        self.assertIn(f"project={self.api.pk}", res["link"])

    def test_shorthand_and_search(self):
        self.assertEqual(self.titles(self.run_query("@Payments-API !high")), ["Fix refunds"])
        self.assertEqual(self.titles(self.run_query("landing")), ["New landing page"])
        self.assertEqual(self.titles(self.run_query("status: in progress")), ["New landing page"])

    def test_done_ones_only_when_asked(self):
        self.assertNotIn("Old bug", self.titles(self.run_query("")))
        self.assertIn("Old bug", self.titles(self.run_query("done: yes")))
        res = self.run_query("status: done")
        self.assertEqual(self.titles(res), ["Old bug"])
        self.assertIn("done=1", res["link"])

    def test_due_and_limit(self):
        res = self.run_query("due: week\nlimit: 1")
        self.assertEqual(res["total"], 1)
        res = self.run_query("limit: 2")
        self.assertEqual((len(res["items"]), res["total"], res["more"]), (2, 3, 1))

    def test_mistakes_are_explained_and_the_rest_still_runs(self):
        res = self.run_query("project: Nope\ndue: someday\npriority: huge")
        self.assertEqual(len(res["errors"]), 3)
        self.assertEqual(res["total"], 3)

    def test_only_my_tasks(self):
        other = User.objects.create_user("other", "o@example.com", PW)
        Task.objects.create(owner=other, title="Their task")
        self.assertNotIn("Their task", self.titles(self.run_query("")))

    def test_the_endpoint(self):
        r = self.client.get(reverse("work:api_task_query"), {"q": "#nothing-here"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["items"], [])
        r = self.client.get(reverse("work:api_task_query"), {"q": "project: Website"})
        self.assertEqual([x["title"] for x in r.json()["items"]], ["New landing page"])

    def test_tasks_page_filters_as_before(self):
        r = self.client.get(reverse("work:tasks"), {"project": self.web.pk})
        self.assertContains(r, "New landing page")
        self.assertNotContains(r, "Fix refunds")
        r = self.client.get(reverse("work:tasks"), {"due": "overdue"})
        self.assertContains(r, "Rotate keys")
        self.assertNotContains(r, "New landing page")


class EmbedTests(Base):
    BODY = "Intro\n\n## Deploy\nRun `make deploy`.\n### Check\nLook at logs.\n```\n# not a heading\n```\n## Rollback\nUndo it."

    def test_a_note_or_one_section(self):
        n = self.note("Runbook", self.BODY)
        data, why = linked.embed(self.me, "runbook")
        self.assertEqual((data["id"], data["body"], why), (n.pk, self.BODY, None))
        data, _ = linked.embed(self.me, "Runbook#deploy")
        self.assertEqual(data["body"], "## Deploy\nRun `make deploy`.\n### Check\nLook at logs.\n```\n# not a heading\n```")
        self.assertEqual(data["heading"], "deploy")
        data, _ = linked.embed(self.me, "Runbook#Rollback")
        self.assertEqual(data["body"], "## Rollback\nUndo it.")

    def test_missing_note_heading_or_itself(self):
        n = self.note("Runbook", self.BODY)
        self.assertIsNone(linked.embed(self.me, "Nope")[0])
        self.assertIn("no heading", linked.embed(self.me, "Runbook#Nope")[1])
        self.assertIn("itself", linked.embed(self.me, "Runbook", current=n.pk)[1])

    def test_a_title_with_a_hash(self):
        self.note("C# notes", "LINQ")
        self.assertEqual(linked.embed(self.me, "C# notes")[0]["body"], "LINQ")

    def test_showing_a_section_counts_as_a_link_here(self):
        from . import services

        n = self.note("Runbook", self.BODY)
        board = self.note("Board", "![[Runbook#Deploy]]")
        self.assertEqual(services.backlinks(n), [board])

    def test_the_endpoint(self):
        self.note("Runbook", self.BODY)
        r = self.client.get(reverse("work:api_note_embed"), {"ref": "Runbook#Rollback"})
        self.assertEqual(r.json()["body"], "## Rollback\nUndo it.")
        r = self.client.get(reverse("work:api_note_embed"), {"ref": "Nope"})
        self.assertFalse(r.json()["ok"])
        other = User.objects.create_user("other", "o@example.com", PW)
        Note.objects.create(owner=other, title="Secret", body="x")
        self.assertFalse(self.client.get(reverse("work:api_note_embed"), {"ref": "Secret"}).json()["ok"])


class MentionTests(Base):
    def test_plain_mentions_found_links_code_and_urls_left_alone(self):
        target = self.note("Redis cache", "")
        plain = self.note("Standup", "Talked about the redis cache today; Redis Cache again.")
        self.note("Linked", "See [[Redis cache]].")
        self.note("Code", "```\nredis cache\n```\n`redis cache` and https://x.dev/redis-cache")
        self.note("Longer", "redis caches are not this note")
        found = linked.unlinked_mentions(target)
        self.assertEqual([m["note"].pk for m in found], [plain.pk])
        self.assertEqual((found[0]["count"], found[0]["match"]), (2, "redis cache"))
        self.assertTrue(found[0]["before"].endswith("the "))

    def test_bangla_words_keep_their_vowel_signs(self):
        target = self.note("কাজ", "")
        self.note("Other", "কাজের তালিকা")         # a longer word, not this note
        self.assertEqual(linked.unlinked_mentions(target), [])

    def test_short_titles_are_not_looked_for(self):
        self.note("Go", "")
        self.note("Other", "go go go")
        self.assertEqual(linked.unlinked_mentions(Note.objects.get(title="Go")), [])

    def test_linking_keeps_the_words_and_the_code(self):
        body, n = linked.link_mentions("Redis cache here, `redis cache` there, [[Redis cache]] and redis cache.", "Redis cache")
        self.assertEqual(body, "[[Redis cache]] here, `redis cache` there, [[Redis cache]] and [[redis cache]].")
        self.assertEqual(n, 2)

    def test_link_one_note_or_all_from_the_page(self):
        target = self.note("Redis cache", "")
        a = self.note("A", "about redis cache")
        b = self.note("B", "Redis cache too")
        url = reverse("work:api_note_action", args=[target.pk])
        res = self.client.post(url, {"action": "link_mentions", "source": a.pk}).json()
        self.assertEqual(res["count"], 1)
        a.refresh_from_db()
        self.assertEqual(a.body, "about [[redis cache]]")
        self.assertTrue(NoteVersion.objects.filter(note=a, body="about redis cache").exists())       # can be taken back
        self.assertIn("Linked from 1 note", res["links"])
        self.assertIn(f'data-link-mention="{b.pk}"', res["links"])
        res = self.client.post(url, {"action": "link_mentions", "source": ""}).json()
        b.refresh_from_db()
        self.assertEqual((res["count"], b.body), (1, "[[Redis cache]] too"))
        self.assertNotIn("data-link-mention", res["links"])

    def test_the_note_page_shows_them(self):
        target = self.note("Redis cache", "")
        self.note("Standup", "the redis cache was slow")
        r = self.client.get(reverse("work:note", args=[target.pk]))
        self.assertContains(r, "Named in 1 note without a link")
        self.assertContains(r, "<mark>redis cache</mark>", html=False)


class FrontEndTests(SimpleTestCase):
    def read(self, path):
        return (Path(settings.BASE_DIR) / path).read_text()

    def test_slash_items_and_dictation(self):
        js = self.read("static/js/writing.js")
        for item in ('id: "tasks"', 'id: "embed"', 'id: "dictate"', "webkitSpeechRecognition", "can-dictate"):
            self.assertIn(item, js)

    def test_the_pages_know_where_to_ask(self):
        from .views import _urls

        urls = _urls()
        self.assertEqual((urls["taskQuery"], urls["noteEmbed"]), (reverse("work:api_task_query"), reverse("work:api_note_embed")))

    def test_previews_pull_in_lists_and_notes(self):
        js = self.read("static/js/work.js")
        self.assertIn("window.Work.enrich", js)
        self.assertIn("language-tasks", js)
        html = self.read("apps/productivity/templates/work/notes.html")
        self.assertEqual(html.count("Work.enrich($el"), 2)
        self.assertEqual(html.count("data-dictate="), 2)
