"""Learning roadmaps: the ready-made ones, the JSON (and outline) people or AI assistants write, the canvas
being saved, progress and what's next, tasks from a topic, and where they show elsewhere — owner only."""
import json

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .. import paths as lp
from ..models import LearningPath, PathNode, PathStatus, Status, Task

PW = "Str0ng-pass-123"


def overlaps(nodes):
    keys = {n["key"]: n for n in nodes}

    def box(n):
        p = keys.get(n["parent"])
        w, h = lp.size(n, 2 if p and p["kind"] == "topic" else 1)
        return n["x"], n["y"], n["x"] + w, n["y"] + h

    out = []
    for i, a in enumerate(nodes):
        for b in nodes[i + 1:]:
            A, B = box(a), box(b)
            if A[0] < B[2] and B[0] < A[2] and A[1] < B[3] and B[1] < A[3]:
                out.append((a["title"], b["title"]))
    return out


class Base(TestCase):
    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)

    def api(self, path, **data):
        return self.client.post(reverse("work:api_path", args=[path.pk]), data)

    def graph(self, path):
        nodes = [lp.node_json(n) for n in path.nodes.all()]
        for n in nodes:
            n.pop("tasks")
        return {"nodes": nodes, "edges": path.edges}


class FormatTests(Base):
    def test_every_ready_made_roadmap_reads_and_is_laid_out_without_overlaps(self):
        self.assertEqual(len(lp.templates()), 14)
        for key in lp.TEMPLATES:
            spec = lp._template(key)[0]
            fields, nodes, edges = lp.build(spec)
            self.assertEqual(overlaps(nodes), [], key)
            self.assertGreaterEqual(len(spec["steps"]), 8, key)
            self.assertTrue(any(n["kind"] == "checkpoint" for n in nodes), key)
            self.assertTrue(all(r["url"].startswith("https://") for n in nodes for r in n["resources"]), key)
            self.assertIn(fields["color"], [c for c, _l in lp.Color.choices], key)

    def test_the_example_and_an_answer_copied_from_a_chat(self):
        answer = "Sure! Here's your roadmap:\n```json\n" + json.dumps(lp.EXAMPLE) + "\n```\nGood luck!"
        fields, nodes, edges = lp.build(lp.read(answer))
        self.assertEqual(fields["title"], "Docker in two weeks")
        self.assertEqual([n["kind"] for n in nodes if not n["parent"]], ["step", "step", "step", "checkpoint"])
        self.assertEqual(len(edges), 3 + 5 + 1)           # the steps in order, each topic to its step, one extra line
        self.assertIn({"from": "images", "to": "multistage", "style": "dashed"}, edges)
        self.assertTrue(next(n for n in nodes if n["key"] == "cache")["optional"])
        self.assertEqual(overlaps(nodes), [])

    def test_the_outline(self):
        spec = lp.read("title: Kubernetes\ncolor: teal\n\n# Pods :: The smallest unit.\n@ Docs | https://kubernetes.io/docs/\n- Labels :: Tags.\n  - Selectors\n"
                       "- ?Init containers\nMore about labels.\n! Checkpoint: deploy an app")
        fields, nodes, _edges = lp.build(spec)
        self.assertEqual((fields["title"], fields["color"]), ("Kubernetes", "teal"))
        by = {n["title"]: n for n in nodes}
        self.assertEqual(by["Pods"]["resources"][0]["url"], "https://kubernetes.io/docs/")
        self.assertEqual(by["Selectors"]["parent"], by["Labels"]["key"])
        self.assertTrue(by["Init containers"]["optional"])
        self.assertEqual(by["Init containers"]["description"], "More about labels.")
        self.assertEqual(by["Checkpoint: deploy an app"]["kind"], "checkpoint")

    def test_problems_say_where_they_are(self):
        cases = [("", "empty"), ("{\"title\": \"x\",}", "line 1"), ('{"steps": [{"title": "a"}]}', "title"), ('{"title": "x", "steps": []}', "steps"),
                 ('{"title": "x", "steps": [{"title": "a"}, {"title": "b", "children": [{"description": "no title"}]}]}', "Step 2 › item 1")]
        for text, says in cases:
            with self.assertRaises(lp.Invalid, msg=text) as cm:
                lp.build(lp.read(text))
            self.assertIn(says, str(cm.exception), text)
        many = {"title": "x", "steps": [{"title": str(i)} for i in range(lp.MAX_NODES + 1)]}
        with self.assertRaises(lp.Invalid):
            lp.build(many)

    def test_odd_values_are_cleaned_not_refused(self):
        spec = {"title": "  Spaced   out ", "color": "chartreuse", "steps": [
            {"id": "A B", "title": "One", "status": "mastered", "resources": ["https://ok.example/x", {"url": "javascript:alert(1)"}, {"url": "ftp://x"}]},
            {"id": "A B", "title": "Two", "x": "left"}]}
        fields, nodes, _e = lp.build(spec)
        self.assertEqual((fields["title"], fields["color"]), ("Spaced out", "blue"))
        self.assertEqual([n["key"] for n in nodes], ["a-b", "a-b-2"])
        self.assertEqual(nodes[0]["status"], "todo")
        self.assertEqual([r["url"] for r in nodes[0]["resources"]], ["https://ok.example/x"])

    def test_download_then_import_gives_the_same_roadmap(self):
        path = lp.from_template(self.me, "go")
        g = self.graph(path)
        g["nodes"][0]["status"], g["nodes"][1]["status"], g["nodes"][2]["x"] = "done", "learning", 999
        g["edges"].append({"from": g["nodes"][3]["key"], "to": g["nodes"][9]["key"], "style": "dashed"})
        lp.save_graph(path, g)
        back = lp.create(self.me, json.loads(json.dumps(lp.export(path))))
        a = {n.key: (n.title, n.kind, n.parent, n.x, n.y, n.status, n.optional, n.resources) for n in path.nodes.all()}
        b = {n.key: (n.title, n.kind, n.parent, n.x, n.y, n.status, n.optional, n.resources) for n in back.nodes.all()}
        self.assertEqual(a, b)
        self.assertEqual(sorted(map(str, path.edges)), sorted(map(str, back.edges)))
        shared = lp.export(path, progress=False)
        self.assertNotIn('"status"', json.dumps(shared))


class CanvasTests(Base):
    def test_saving_adds_changes_and_deletes_boxes(self):
        path = lp.create(self.me, lp.EXAMPLE)
        gone = path.nodes.get(key="run")
        t = Task.objects.create(owner=self.me, title="Run one", path_node=gone)
        g = self.graph(path)
        g["nodes"] = [n for n in g["nodes"] if n["key"] != "run"]
        g["nodes"][0].update(title="Containers 101", status="done", x=40)
        g["nodes"].append({"key": "nnew", "kind": "topic", "title": "Podman", "x": 10, "y": 20, "parent": "basics", "status": "weird", "resources": [{"url": "https://podman.io"}]})
        g["nodes"].append({"key": "nnew", "kind": "topic", "title": "Twice"})                    # the same key again: ignored
        g["edges"] = [{"from": "basics", "to": "nnew"}, {"from": "basics", "to": "run"}, {"from": "basics", "to": "basics"}]
        r = self.api(path, action="save", graph=json.dumps(g))
        self.assertTrue(r.json()["ok"])
        path.refresh_from_db()
        keys = set(path.nodes.values_list("key", flat=True))
        self.assertNotIn("run", keys)
        new = path.nodes.get(key="nnew")
        self.assertEqual((new.title, new.status, new.resources[0]["type"]), ("Podman", "todo", "other"))
        first = path.nodes.get(key="basics")
        self.assertEqual((first.title, first.status, first.x), ("Containers 101", "done", 40))
        self.assertIsNotNone(first.done_at)
        self.assertEqual(path.edges, [{"from": "basics", "to": "nnew", "style": "solid"}])
        t.refresh_from_db()
        self.assertIsNone(t.path_node)                                 # the task stays, unlinked
        self.assertEqual(self.api(path, action="save", graph="not json").status_code, 400)

    def test_tidy_copy_reset_archive_delete(self):
        path = lp.create(self.me, lp.EXAMPLE)
        places = self.api(path, action="tidy").json()["places"]
        self.assertEqual(set(places), set(path.nodes.values_list("key", flat=True)))
        path.nodes.update(status=PathStatus.DONE)
        url = self.api(path, action="duplicate").json()["url"]
        copy = LearningPath.objects.exclude(pk=path.pk).get()
        self.assertEqual(url, reverse("work:path", args=[copy.pk]))
        self.assertFalse(copy.nodes.exclude(status=PathStatus.TODO).exists())
        self.assertEqual(copy.nodes.count(), path.nodes.count())
        self.api(path, action="reset")
        self.assertFalse(path.nodes.exclude(status=PathStatus.TODO).exists())
        self.assertTrue(self.api(path, action="archive").json()["archived"])
        undo = self.api(path, action="delete").json()["undo"]
        self.assertFalse(LearningPath.objects.filter(pk=path.pk).exists())
        self.client.post(undo)
        self.assertEqual(LearningPath.objects.get(pk=path.pk).nodes.count(), copy.nodes.count())

    def test_progress_and_what_is_next(self):
        path = lp.create(self.me, lp.EXAMPLE)
        nodes = list(path.nodes.all())
        self.assertEqual(lp.next_up(nodes)[0].key, "images")           # a step with topics is reached through them
        path.nodes.filter(key__in=["images", "run"]).update(status=PathStatus.DONE)
        path.nodes.filter(key="cache").update(status=PathStatus.SKIPPED)
        path.nodes.filter(key="networks").update(status=PathStatus.LEARNING)
        nodes = list(path.nodes.all())
        p = lp.progress(nodes)
        self.assertEqual((p["total"], p["done"], p["skipped"], p["learning"], p["pct"]), (9, 2, 1, 1, 25))
        self.assertEqual(lp.next_up(nodes)[0].key, "networks")         # what's being learnt comes first


class TaskTests(Base):
    def test_tasks_from_a_topic(self):
        path = lp.create(self.me, lp.EXAMPLE)
        r = self.api(path, action="task_add", node="images", today="1").json()
        t = Task.objects.get(pk=r["task"]["id"])
        self.assertEqual((t.title, t.my_day, t.path_node.key, r["status"]), ("Learn: Images and layers", timezone.localdate(), "images", "learning"))
        self.assertEqual(t.link, "")
        r = self.api(path, action="task_add", node="basics", title="Read the docs").json()
        self.assertEqual(Task.objects.get(pk=r["task"]["id"]).link, "https://docs.docker.com/get-started/")
        detail = self.client.get(reverse("work:api_path", args=[path.pk]) + "?node=images").json()
        self.assertEqual([x["title"] for x in detail["tasks"]], ["Learn: Images and layers"])
        self.api(path, action="task_done", node="images", task=t.pk, done="1")
        t.refresh_from_db()
        self.assertEqual(t.status, Status.DONE)
        Task.objects.create(owner=self.me, title="a", path_node=t.path_node)
        self.assertEqual(self.api(path, action="tasks_close", node="images").json()["count"], 1)
        self.assertEqual(self.api(path, action="task_add", node="nope").status_code, 409)

    def test_plan_the_next_topics(self):
        path = lp.create(self.me, lp.EXAMPLE)
        Task.objects.create(owner=self.me, title="already", path_node=path.nodes.get(key="images"))
        r = self.api(path, action="plan", n="3", today="1").json()
        self.assertEqual(r["count"], 3)
        made = Task.objects.filter(path_node__path=path).exclude(title="already").order_by("pk")
        self.assertEqual([t.path_node.key for t in made], ["run", "multistage", "cache"])
        self.assertTrue(all(t.my_day == timezone.localdate() for t in made))
        self.assertEqual(self.api(path, action="plan", n="20").json()["count"], 2)    # networks, the checkpoint
        self.assertEqual(self.api(path, action="plan").json()["count"], 0)

    def test_a_repeating_task_keeps_its_topic(self):
        from .. import services

        path = lp.create(self.me, lp.EXAMPLE)
        t = Task.objects.create(owner=self.me, title="Practise", path_node=path.nodes.get(key="run"), repeat="daily", due_date=timezone.localdate())
        nxt = services.set_done(t, True)
        self.assertEqual(nxt.path_node, t.path_node)


class PagesTests(Base):
    def test_list_gallery_and_starting_one(self):
        html = self.client.get(reverse("work:paths")).content.decode()
        for title in ("Backend developer", "System design and architecture", "Rust: beginner to senior", "Design patterns"):
            self.assertIn(title, html)
        r = self.client.post(reverse("work:paths"), {"action": "template", "template": "backend"})
        path = LearningPath.objects.get()
        self.assertRedirects(r, reverse("work:path", args=[path.pk]))
        self.assertEqual((path.title, path.template), ("Backend developer", "backend"))
        self.assertIn("started", self.client.get(reverse("work:paths")).content.decode())
        r = self.client.post(reverse("work:paths"), {"action": "blank", "title": "Kubernetes"})
        blank = LearningPath.objects.get(title="Kubernetes")
        self.assertEqual(list(blank.nodes.values_list("title", flat=True)), ["First step"])

    def test_the_canvas_page_and_downloads(self):
        path = lp.create(self.me, lp.EXAMPLE)
        html = self.client.get(reverse("work:path", args=[path.pk])).content.decode()
        data = json.loads(html.split('id="path-data" type="application/json">')[1].split("</script>")[0])
        self.assertEqual(len(data["nodes"]), 9)
        self.assertIn('id="path-text"', html)
        r = self.client.get(reverse("work:path_export", args=[path.pk]))
        self.assertIn("attachment", r["Content-Disposition"])
        self.assertEqual(json.loads(r.content)["title"], "Docker in two weeks")
        self.assertEqual(json.loads(self.client.get(reverse("work:path_example")).content)["format"], "learning-roadmap")
        self.assertEqual(json.loads(self.client.get(reverse("work:path_template", args=["rust"])).content)["title"], "Rust: beginner to senior")
        self.assertEqual(self.client.get(reverse("work:path_template", args=["nope"])).status_code, 404)

    def test_import_checks_then_creates(self):
        url = reverse("work:api_path_import")
        r = self.client.post(url, {"text": json.dumps(lp.EXAMPLE), "check": "1"}).json()
        self.assertEqual((r["info"]["title"], r["info"]["steps"], r["info"]["boxes"]), ("Docker in two weeks", 4, 9))
        self.assertFalse(LearningPath.objects.exists())
        r = self.client.post(url, {"text": '{"title": "x"}'}).json()
        self.assertFalse(r["ok"])
        self.assertIn("steps", r["error"])
        f = SimpleUploadedFile("road.json", json.dumps(lp.EXAMPLE).encode())
        r = self.client.post(url, {"file": f}).json()
        self.assertEqual(r["url"], reverse("work:path", args=[LearningPath.objects.get().pk]))


class ElsewhereTests(Base):
    def test_today_review_search_and_the_task_page(self):
        path = lp.create(self.me, lp.EXAMPLE)
        html = self.client.get(reverse("work:today")).content.decode()
        self.assertIn("Docker in two weeks", html)
        self.assertIn("next: Images and layers", html)
        g = self.graph(path)
        for n in g["nodes"]:
            if n["key"] == "images":
                n["status"] = "done"
        lp.save_graph(path, g)
        html = self.client.get(reverse("work:review") + "?preset=week").content.decode()
        self.assertIn("Topics learnt", html)
        self.assertIn("Images and layers", html)
        self.assertIn("Images and layers (Docker in two weeks)", self.client.get(reverse("work:review") + "?preset=week&export=md").content.decode())
        self.assertContains(self.client.get(reverse("search") + "?q=multi-stage"), "Multi-stage builds")
        t = Task.objects.create(owner=self.me, title="Read", path_node=path.nodes.get(key="run"))
        self.assertContains(self.client.get(reverse("work:task", args=[t.pk])), "?node=run")


class OnlyMineTests(Base):
    def test_someone_else_cant_see_or_change_it(self):
        path = lp.create(self.me, lp.EXAMPLE)
        mine = Task.objects.create(owner=self.me, title="Mine")
        other = User.objects.create_superuser("other", "o@example.com", PW)
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("work:path", args=[path.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("work:path_export", args=[path.pk])).status_code, 404)
        self.assertEqual(self.api(path, action="save", graph=json.dumps({"nodes": []})).status_code, 404)
        self.assertEqual(self.api(path, action="delete").status_code, 404)
        self.assertEqual(PathNode.objects.filter(path=path).count(), 9)
        theirs = lp.create(other, lp.EXAMPLE)
        self.assertEqual(self.api(theirs, action="task_link", node="run", task=mine.pk).status_code, 404)
        self.assertNotContains(self.client.get(reverse("work:paths")), reverse("work:path", args=[path.pk]))
