"""Diagrams: mind maps, system design boards and text (Mermaid) diagrams —
starting one, saving, the list picture, turning a mind map into tasks or a
note, and keeping everything to its owner."""
import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from . import diagrams
from .models import Diagram, DiagramKind, DiagramVersion, Note, Project, Task

PW = "Str0ng-pass-123"
SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10"/></svg>'


class DiagramTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)

    def start(self, kind, template="blank", **extra):
        r = self.client.post(reverse("work:diagram_new"), {"kind": kind, "template": template, **extra})
        self.assertEqual(r.status_code, 302)
        return Diagram.objects.latest("pk")

    def save(self, d, **fields):
        return self.client.post(reverse("work:api_diagram_save", args=[d.pk]), fields).json()

    def test_every_kind_starts_from_every_template(self):
        for kind, items in diagrams.templates().items():
            for key, _title in items:
                d = self.start(kind, key)
                self.assertEqual(d.kind, kind)
                if kind == DiagramKind.MINDMAP:
                    self.assertIn("root", d.data)
                elif kind == DiagramKind.SYSTEM:
                    self.assertIn("nodes", d.data)
                    self.assertTrue(d.notes.startswith("## Requirements"))
                elif kind == DiagramKind.DRAWING:
                    self.assertIsInstance(d.data["nodes"], list)
                else:
                    self.assertEqual(diagrams.kind_of_source(d.source, "x"), kind, f"{kind}/{key}")
                r = self.client.get(reverse("work:diagram", args=[d.pk]))
                self.assertEqual(r.status_code, 200)
        self.assertEqual(Diagram.objects.count(), sum(len(v) for v in diagrams.templates().values()))

    def test_templates_read_well(self):
        title, _s, data, _n = diagrams.start(DiagramKind.SYSTEM, "shortener")
        self.assertEqual(title, "URL shortener")
        ids = {n["id"] for n in data["nodes"]}
        self.assertTrue(all(e["from"] in ids and e["to"] in ids for e in data["edges"]))
        title, _s, data, _n = diagrams.start(DiagramKind.MINDMAP, "sysdesign")
        self.assertEqual(data["root"]["id"], "r")
        self.assertEqual(diagrams.count_nodes(data["root"]), len({n for n in json.dumps(data).split('"id": "')[1:]}))

    def test_list_and_kinds(self):
        self.start(DiagramKind.MINDMAP)
        self.start(DiagramKind.FLOWCHART)
        r = self.client.get(reverse("work:diagrams"))
        self.assertContains(r, "Start something new")
        self.assertEqual(len(r.context["diagrams"]), 2)
        r = self.client.get(reverse("work:diagrams") + "?kind=flowchart")
        self.assertEqual([d.kind for d in r.context["diagrams"]], ["flowchart"])
        r = self.client.get(reverse("work:diagrams") + "?start=system")
        self.assertContains(r, "pick: 'system'")

    def test_saving_a_mind_map(self):
        d = self.start(DiagramKind.MINDMAP)
        data = {"root": {"id": "r", "text": "Trip", "children": [{"id": "a", "text": "Where", "children": []}]}}
        res = self.save(d, title="Holiday", data=json.dumps(data), preview=SVG, notes="Plan it")
        self.assertTrue(res["ok"])
        d.refresh_from_db()
        self.assertEqual((d.title, d.data["root"]["children"][0]["text"], d.notes, d.preview), ("Holiday", "Where", "Plan it", SVG))

    def test_bad_drawings_are_refused(self):
        d = self.start(DiagramKind.MINDMAP)
        self.assertFalse(self.save(d, data="{not json")["ok"])
        self.assertFalse(self.save(d, data=json.dumps({"nodes": []}))["ok"])     # no centre
        self.assertFalse(self.save(d, data="x" * (diagrams.MAX_DATA + 1))["ok"])
        board = self.start(DiagramKind.SYSTEM)
        res = self.save(board, data=json.dumps({"nodes": [{"id": "a", "label": "A"}], "edges": [{"id": "e", "from": "a", "to": "gone"}]}))
        self.assertTrue(res["ok"])
        board.refresh_from_db()
        self.assertEqual(board.data["edges"], [])                                   # a link to a deleted part is dropped

    def test_text_diagram_follows_its_first_line(self):
        d = self.start(DiagramKind.FLOWCHART)
        res = self.save(d, source="%% my notes\nsequenceDiagram\n    A->>B: hi\n")
        self.assertEqual(res["kind"], "sequence")
        d.refresh_from_db()
        self.assertEqual(d.kind, DiagramKind.SEQUENCE)
        self.save(d, data=json.dumps({"root": {}}))                                # shapes are ignored for text diagrams
        d.refresh_from_db()
        self.assertEqual(d.data, {})

    def test_picture_is_only_shown_safely(self):
        d = self.start(DiagramKind.FLOWCHART)
        self.assertEqual(self.client.get(reverse("work:diagram_preview", args=[d.pk])).status_code, 404)
        self.save(d, preview=SVG)
        r = self.client.get(reverse("work:diagram_preview", args=[d.pk]) + "?v=1")
        self.assertEqual(r["Content-Type"], "image/svg+xml; charset=utf-8")
        self.assertIn("sandbox", r["Content-Security-Policy"])
        self.assertIn("immutable", r["Cache-Control"])
        for bad in ('<svg><script>alert(1)</script></svg>', '<svg onload="alert(1)"></svg>', '<svg><a href="javascript:x">x</a></svg>',
                    '<svg><foreignObject><div>x</div></foreignObject></svg>', "<html></html>"):
            self.assertEqual(diagrams.clean_preview(bad), "", bad)
        self.assertEqual(diagrams.clean_preview('<svg><text>online = yes</text></svg>'), '<svg><text>online = yes</text></svg>')
        self.assertContains(self.client.get(reverse("work:diagrams")), reverse("work:diagram_preview", args=[d.pk]))

    def test_mind_map_to_tasks_and_note(self):
        project = Project.objects.create(owner=self.me, name="Launch")
        d = self.start(DiagramKind.MINDMAP, project=project.pk)
        data = {"root": {"id": "r", "text": "Launch", "children": [
            {"id": "a", "text": "Engineering", "children": [{"id": "b", "text": "API", "children": []}, {"id": "c", "text": "Tests", "children": []}]},
            {"id": "d", "text": "Marketing", "children": []}]}}
        self.save(d, data=json.dumps(data))
        url = reverse("work:api_diagram_action", args=[d.pk])
        res = self.client.post(url, {"action": "tasks", "node": "a"}).json()
        self.assertEqual(res["count"], 2)
        self.assertEqual(sorted(Task.objects.filter(project=project).values_list("title", flat=True)), ["API", "Tests"])
        self.client.post(url, {"action": "tasks", "node": "d"})                 # an idea with nothing under it becomes one task
        self.assertTrue(Task.objects.filter(title="Marketing").exists())
        res = self.client.post(url, {"action": "note"}).json()
        note = Note.objects.get()
        self.assertEqual(res["url"], reverse("work:note", args=[note.pk]))
        self.assertEqual(note.body, "# Launch\n\n- Engineering\n  - API\n  - Tests\n- Marketing\n")

    def test_text_diagram_as_a_note(self):
        d = self.start(DiagramKind.SEQUENCE, "payment")
        self.client.post(reverse("work:api_diagram_action", args=[d.pk]), {"action": "note"})
        self.assertIn("```mermaid\nsequenceDiagram", Note.objects.get().body)

    def test_pin_copy_archive_delete(self):
        d = self.start(DiagramKind.SYSTEM, "chat")
        url = reverse("work:api_diagram_action", args=[d.pk])
        self.assertTrue(self.client.post(url, {"action": "pin"}).json()["pinned"])
        copy_url = self.client.post(url, {"action": "duplicate"}).json()["url"]
        copy = Diagram.objects.exclude(pk=d.pk).get()
        self.assertEqual((copy_url, copy.title, copy.data), (reverse("work:diagram", args=[copy.pk]), "Chat app (copy)", d.data))
        self.client.post(url, {"action": "archive"})
        self.assertEqual(len(self.client.get(reverse("work:diagrams")).context["diagrams"]), 1)
        res = self.client.post(url, {"action": "delete"}).json()
        self.assertFalse(Diagram.objects.filter(pk=d.pk).exists())
        self.client.post(res["undo"])                                             # Recently deleted brings it back
        self.assertTrue(Diagram.objects.filter(pk=d.pk).exists())

    def test_found_by_search(self):
        d = self.start(DiagramKind.MINDMAP)
        self.save(d, title="Exam revision")
        res = self.client.get(reverse("work:api_search") + "?q=revision").json()
        self.assertEqual([(x["kind"], x["title"]) for x in res["results"]], [("diagram", "Exam revision")])
        r = self.client.get(reverse("search") + "?q=revision")
        self.assertContains(r, "Exam revision")

    def test_nobody_else_can_see_or_change_it(self):
        d = self.start(DiagramKind.MINDMAP)
        self.save(d, preview=SVG)
        other = User.objects.create_superuser("other", "o@example.com", PW)
        self.client.force_login(other)
        for url in (reverse("work:diagram", args=[d.pk]), reverse("work:diagram_preview", args=[d.pk])):
            self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(reverse("work:api_diagram_save", args=[d.pk]), {"title": "x"}).status_code, 404)
        self.assertEqual(self.client.post(reverse("work:api_diagram_action", args=[d.pk]), {"action": "delete"}).status_code, 404)
        self.assertEqual(self.client.get(reverse("work:diagrams")).context["diagrams"].count(), 0)
        self.assertEqual(self.client.post(reverse("work:diagram_new"), {"kind": "nonsense"}).status_code, 404)

    def test_every_kind_has_a_tile_in_a_group(self):
        r = self.client.get(reverse("work:diagrams"))
        kinds = [t["kind"] for g in r.context["groups"] for t in g["tiles"]]
        self.assertEqual(sorted(kinds), sorted(DiagramKind.values))
        for kind in ("c4", "architecture", "quadrant", "sankey"):
            self.assertContains(r, f'data-kind="{kind}"')

    def test_hand_drawn_look_is_kept_for_kinds_that_have_it(self):
        d = self.start(DiagramKind.FLOWCHART)
        self.save(d, data=json.dumps({"look": "handDrawn"}))
        d.refresh_from_db()
        self.assertEqual(d.data, {"look": "handDrawn"})
        self.assertContains(self.client.get(reverse("work:diagram", args=[d.pk])), "Hand-drawn")
        seq = self.start(DiagramKind.SEQUENCE)
        self.save(seq, data=json.dumps({"look": "handDrawn"}))
        seq.refresh_from_db()
        self.assertEqual(seq.data, {})
        self.assertNotContains(self.client.get(reverse("work:diagram", args=[seq.pk])), "Hand-drawn")

    def test_earlier_versions_are_kept_and_can_come_back(self):
        d = self.start(DiagramKind.FLOWCHART)
        first = d.source
        self.save(d, source="flowchart LR\n    A --> B\n")       # the template's text is kept before the first change
        self.assertEqual(DiagramVersion.objects.get().source, first)
        self.save(d, source="flowchart LR\n    A --> C\n")       # within a few minutes: no second copy
        self.assertEqual(DiagramVersion.objects.count(), 1)
        DiagramVersion.objects.update(created_at=DiagramVersion.objects.get().created_at - diagrams.AUTO_EVERY)
        self.save(d, source="flowchart LR\n    A --> D\n")
        self.assertEqual(DiagramVersion.objects.count(), 2)
        url = reverse("work:api_diagram_action", args=[d.pk])
        v = self.client.post(url, {"action": "version", "name": "Before review"}).json()["version"]
        self.assertEqual(v["name"], "Before review")
        listed = self.client.get(reverse("work:api_diagram_versions", args=[d.pk])).json()["versions"]
        self.assertEqual([x["name"] for x in listed][0], "Before review")
        oldest = DiagramVersion.objects.order_by("created_at").first()
        self.client.post(url, {"action": "restore", "version": oldest.pk})
        d.refresh_from_db()
        self.assertEqual(d.source, first)
        self.assertTrue(DiagramVersion.objects.filter(source="flowchart LR\n    A --> D\n").exists())   # what was there is kept too
        self.client.post(url, {"action": "forget", "version": oldest.pk})
        self.assertFalse(DiagramVersion.objects.filter(pk=oldest.pk).exists())

    def test_version_pictures_are_safe_and_private(self):
        d = self.start(DiagramKind.FLOWCHART)
        self.save(d, preview=SVG)
        d.refresh_from_db()
        v = diagrams.remember(d, name="x", force=True)
        r = self.client.get(reverse("work:diagram_version_preview", args=[d.pk, v.pk]))
        self.assertIn("sandbox", r["Content-Security-Policy"])
        self.assertIn("immutable", r["Cache-Control"])
        other = User.objects.create_superuser("other", "o@example.com", PW)
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("work:diagram_version_preview", args=[d.pk, v.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("work:api_diagram_versions", args=[d.pk])).status_code, 404)

    def test_picture_in_a_note_is_checked_for_changes(self):
        d = self.start(DiagramKind.FLOWCHART)
        self.save(d, preview=SVG)
        url = reverse("work:diagram_preview", args=[d.pk])
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get(url, HTTP_IF_MODIFIED_SINCE=r["Last-Modified"]).status_code, 304)
        items = self.client.get(reverse("work:api_diagram_list")).json()["items"]
        self.assertEqual([(i["id"], i["picture"]) for i in items], [(d.pk, url)])

    def test_ticked_ideas(self):
        data = {"root": {"id": "r", "text": "Trip", "children": [
            {"id": "a", "text": "Pack", "children": [{"id": "b", "text": "Socks", "done": True, "children": []}, {"id": "c", "text": "Charger", "children": []}]}]},
            "layout": "down"}
        d = self.start(DiagramKind.MINDMAP)
        self.save(d, data=json.dumps(data))
        d.refresh_from_db()
        self.assertEqual(d.data["layout"], "down")
        self.assertIn("- [x] Socks", diagrams.outline_text(d.data))
        self.assertEqual(diagrams.branch_titles(d.data, "a"), ["Charger"])     # done ideas don't become tasks


class DrawingTests(TestCase):
    """Drag-and-drop drawings: free drawings, and flowchart/state/class/ER diagrams drawn with shapes."""
    setUp, start, save = DiagramTests.setUp, DiagramTests.start, DiagramTests.save
    SHAPES = {"nodes": [{"id": "a", "shape": "rect", "x": 0, "y": 0, "w": 150, "h": 64, "label": "Login"},
                        {"id": "b", "shape": "diamond", "x": 300, "y": 0, "w": 140, "h": 96, "label": "Valid?" * 1000}],
              "edges": [{"id": "e1", "from": "a", "to": "b", "line": "solid", "label": "go"},
                        {"id": "e2", "from": "a", "to": "gone", "line": "solid"}]}

    def test_a_free_drawing_keeps_its_shapes(self):
        d = self.start(DiagramKind.DRAWING, "process")
        self.assertTrue(d.is_visual)
        self.assertEqual(len(d.data["nodes"]), 5)
        res = self.save(d, data=json.dumps(self.SHAPES), preview=SVG)
        self.assertTrue(res["ok"])
        d.refresh_from_db()
        self.assertEqual([e["id"] for e in d.data["edges"]], ["e1"])          # the link to a deleted shape is dropped
        self.assertLessEqual(len(d.data["nodes"][1]["label"]), diagrams.MAX_TEXT * 4)
        self.assertTrue(self.client.get(reverse("work:diagram", args=[d.pk])).context["diagram"].is_visual)

    def test_text_diagrams_keep_their_drawing_and_their_text(self):
        d = self.start(DiagramKind.FLOWCHART, "blank")
        page = self.client.get(reverse("work:diagram", args=[d.pk]))
        self.assertEqual(page.context["payload"]["mode"], "draw")          # drag and drop first
        self.assertContains(page, "js/drawing.js")
        draw = dict(self.SHAPES, src="flowchart TD\n    a --> b\n", dir="LR", extra=["classDef x fill:#f00"])
        res = self.save(d, source="flowchart TD\n    a --> b\n", data=json.dumps({"mode": "draw", "draw": draw, "look": "handDrawn", "junk": 1}))
        self.assertTrue(res["ok"])
        d.refresh_from_db()
        self.assertEqual(d.kind, DiagramKind.FLOWCHART)
        self.assertEqual(set(d.data), {"mode", "draw", "look"})
        self.assertEqual(d.data["draw"]["dir"], "LR")
        self.assertEqual(d.data["draw"]["src"], d.source)
        self.assertEqual(len(d.data["draw"]["edges"]), 1)
        # switched to text: remembered
        self.save(d, data=json.dumps(dict(d.data, mode="text")))
        d.refresh_from_db()
        self.assertEqual(self.client.get(reverse("work:diagram", args=[d.pk])).context["payload"]["mode"], "text")

    def test_only_some_text_diagrams_have_a_drawing(self):
        d = self.start(DiagramKind.SEQUENCE, "blank")
        self.save(d, data=json.dumps({"mode": "draw", "draw": self.SHAPES}))
        d.refresh_from_db()
        self.assertEqual(d.data, {})
        self.assertNotContains(self.client.get(reverse("work:diagram", args=[d.pk])), "js/drawing.js")

    def test_a_bad_drawing_is_refused(self):
        d = self.start(DiagramKind.DRAWING)
        self.assertFalse(self.save(d, data=json.dumps({"nodes": [{"x": 1}], "edges": []}))["ok"])
        self.assertFalse(self.save(d, data=json.dumps({"nodes": "no", "edges": []}))["ok"])

    def test_a_drawing_as_a_note(self):
        d = self.start(DiagramKind.DRAWING, "team")
        res = self.client.post(reverse("work:api_diagram_action", args=[d.pk]), {"action": "note"}).json()
        self.assertTrue(res["ok"])
        self.assertIn("- Engineering", Note.objects.get().body)
